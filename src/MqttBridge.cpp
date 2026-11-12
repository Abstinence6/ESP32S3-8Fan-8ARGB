#include "MqttBridge.h"
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(ARDUINO_ARCH_ESP32)
#include <WiFi.h>
#include <PubSubClient.h>
#endif

namespace {
bool validTopicPrefix(const char* prefix) {
    if (!prefix || !*prefix || strlen(prefix) >= 48) return false;
    for (const char* p = prefix; *p; ++p)
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
              (*p >= '0' && *p <= '9') || *p == '_' || *p == '-' || *p == '/')) return false;
    return prefix[0] != '/' && prefix[strlen(prefix) - 1] != '/';
}
bool validHost(const char* host) {
    if (!host || !*host || strlen(host) >= 64) return false;
    for (const char* p = host; *p; ++p)
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
              (*p >= '0' && *p <= '9') || *p == '-' || *p == '.')) return false;
    return true;
}
}

uint32_t MqttBridge::checksum(const Config& config) {
    uint32_t hash = 2166136261UL;
    const uint8_t* data = reinterpret_cast<const uint8_t*>(&config);
    for (size_t i = 0; i < offsetof(Config, crc); ++i) {
        hash ^= data[i]; hash *= 16777619UL;
    }
    return hash;
}

bool MqttBridge::begin(FanController& fans, CoolingController& cooling, ArgbController& argb) {
    fans_ = &fans;
    cooling_ = &cooling;
    argb_ = &argb;
#if defined(ARDUINO_ARCH_ESP32)
    if (!storage_.begin("mqtt-v1", false)) return false;
    Config previous = {};
    if (storage_.getBytesLength("settings") == sizeof(previous) &&
        storage_.getBytes("settings", &previous, sizeof(previous)) == sizeof(previous) &&
        previous.magic == config_.magic && previous.version == config_.version &&
        previous.crc == checksum(previous) && previous.port && previous.enabled <= 1 &&
        memchr(previous.host, 0, sizeof(previous.host)) &&
        memchr(previous.user, 0, sizeof(previous.user)) &&
        memchr(previous.password, 0, sizeof(previous.password)) &&
        memchr(previous.prefix, 0, sizeof(previous.prefix)) &&
        validTopicPrefix(previous.prefix) &&
        (!previous.host[0] || validHost(previous.host))) config_ = previous;
    configLock_ = xSemaphoreCreateMutex();
    commands_ = xQueueCreate(12, sizeof(Command));
    snapshots_ = xQueueCreate(1, sizeof(Snapshot));
    if (!configLock_ || !commands_ || !snapshots_) return false;
    if (xTaskCreatePinnedToCore(taskEntrypoint, "MQTT", 8192, this, 1, &task_, 0) != pdPASS)
        return false;
#endif
    return true;
}

bool MqttBridge::save(const Config& value) {
#if defined(ARDUINO_ARCH_ESP32)
    Config copy = value;
    copy.crc = checksum(copy);
    return storage_.putBytes("settings", &copy, sizeof(copy)) == sizeof(copy);
#else
    (void)value; return true;
#endif
}
bool MqttBridge::setConfig(const Config& value) {
    if (!save(value)) return false;
#if defined(ARDUINO_ARCH_ESP32)
    if (xSemaphoreTake(configLock_, pdMS_TO_TICKS(100)) != pdTRUE) return false;
#endif
    config_ = value;
#if defined(ARDUINO_ARCH_ESP32)
    ++configRevision_;
    xSemaphoreGive(configLock_);
#endif
    return true;
}
bool MqttBridge::setHost(const char* host, uint16_t port) {
    if (!validHost(host) || !port) return false;
    Config value = config_;
    memset(value.host, 0, sizeof(value.host));
    strcpy(value.host, host);
    value.port = port;
    return setConfig(value);
}
bool MqttBridge::setAuth(const char* user, const char* password) {
    if (!user || !password || strlen(user) >= sizeof(config_.user) ||
        strlen(password) >= sizeof(config_.password)) return false;
    Config value = config_;
    memset(value.user, 0, sizeof(value.user));
    memset(value.password, 0, sizeof(value.password));
    strcpy(value.user, user);
    strcpy(value.password, password);
    return setConfig(value);
}
bool MqttBridge::setPrefix(const char* prefix) {
    if (!validTopicPrefix(prefix)) return false;
    Config value = config_;
    memset(value.prefix, 0, sizeof(value.prefix));
    strcpy(value.prefix, prefix);
    return setConfig(value);
}
bool MqttBridge::setEnabled(bool enabled) {
    if (enabled && !config_.host[0]) return false;
    Config value = config_;
    value.enabled = enabled ? 1 : 0;
    return setConfig(value);
}
void MqttBridge::printStatus(Stream& out) const {
    out.print(F("MQTT ENABLED=")); out.print(config_.enabled ? 1 : 0);
    out.print(F(" CONNECTED="));
#if defined(ARDUINO_ARCH_ESP32)
    out.print(connected_ ? 1 : 0);
#else
    out.print(0);
#endif
    out.print(F(" HOST=")); out.print(config_.host[0] ? config_.host : "unset");
    out.print(F(" PORT=")); out.print(config_.port);
    out.print(F(" PREFIX=")); out.println(config_.prefix);
}
void MqttBridge::update(uint32_t nowMs) {
    if (!fans_ || !cooling_ || !argb_) return;
#if defined(ARDUINO_ARCH_ESP32)
    Command command = {};
    for (unsigned i = 0; i < 8 && xQueueReceive(commands_, &command, 0) == pdTRUE; ++i) {
        bool ok = false;
        const uint8_t ch = command.channel;
        if (ch >= board::kChannelCount) continue;
        switch (command.kind) {
        case Command::FanDuty: ok = cooling_->setManual(ch, static_cast<uint8_t>(command.value)); break;
        case Command::FanAuto: ok = cooling_->setAuto(ch); break;
        case Command::Temperature:
            cooling_->setTemperature(ch, command.value, nowMs); ok = true; break;
        case Command::ArgbColor:
            ok = argb_->setSolid(ch, command.red, command.green, command.blue); break;
        case Command::ArgbOff: ok = argb_->setOff(ch); break;
        case Command::ArgbRainbow: ok = argb_->setRainbow(ch); break;
        case Command::Brightness: ok = argb_->setBrightness(ch, static_cast<uint8_t>(command.value)); break;
        }
        rejected_[ch] = ok ? 0 : 1;
    }
    if (nowMs - lastSnapshotMs_ < 1000U) return;
    lastSnapshotMs_ = nowMs;
    Snapshot snapshot = {};
    snapshot.dcReady = fans_->dcHardwareAvailable() ? 1 : 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        snapshot.pwm[ch] = fans_->getPercent(ch);
        snapshot.rpm[ch] = static_cast<uint16_t>(fans_->getRpm(ch) > 65535U ? 65535U : fans_->getRpm(ch));
        snapshot.temp[ch] = cooling_->temperature(ch);
        snapshot.tempFresh[ch] = cooling_->temperatureFresh(ch, nowMs) ? 1 : 0;
        snapshot.fault[ch] = cooling_->faulted(ch) ? 1 : 0;
        snapshot.tach[ch] = fans_->tachValid(ch) ? 1 : 0;
        snapshot.type[ch] = static_cast<uint8_t>(fans_->configuredType(ch));
        snapshot.mode[ch] = static_cast<uint8_t>(cooling_->mode(ch));
        snapshot.rgbMode[ch] = static_cast<uint8_t>(argb_->getMode(ch));
        snapshot.rejected[ch] = rejected_[ch];
    }
    xQueueOverwrite(snapshots_, &snapshot);
#else
    (void)nowMs;
#endif
}

#if defined(ARDUINO_ARCH_ESP32)
MqttBridge* MqttBridge::callbackInstance_ = nullptr;
void MqttBridge::taskEntrypoint(void* arg) {
    static_cast<MqttBridge*>(arg)->networkLoop();
    vTaskDelete(nullptr);
}

void MqttBridge::receive(char* topic, uint8_t* payload, unsigned int length) {
    if (!topic || length == 0 || length > 48 || !commands_) return;
    char text[49] = {};
    memcpy(text, payload, length);
    Config c = {};
    if (xSemaphoreTake(configLock_, pdMS_TO_TICKS(10)) != pdTRUE) return;
    c = config_;
    xSemaphoreGive(configLock_);
    const size_t prefixLen = strlen(c.prefix);
    if (strncmp(topic, c.prefix, prefixLen) || topic[prefixLen] != '/') return;
    const char* suffix = topic + prefixLen + 1;
    unsigned channel = 0;
    char action[24] = {};
    if (sscanf(suffix, "fan/%u/%23s", &channel, action) != 2 &&
        sscanf(suffix, "argb/%u/%23s", &channel, action) != 2) return;
    if (channel < 1 || channel > board::kChannelCount) return;
    const bool isFan = strncmp(suffix, "fan/", 4) == 0;
    Command cmd = {};
    cmd.channel = static_cast<uint8_t>(channel - 1);
    char* end = nullptr;
    if (isFan && strcmp(action, "set") == 0 && strcmp(text, "AUTO") == 0)
        cmd.kind = Command::FanAuto;
    else if (isFan && strcmp(action, "set") == 0) {
        const long value = strtol(text, &end, 10);
        if (*end || end == text || value < 0 || value > 100) return;
        cmd.kind = Command::FanDuty; cmd.value = static_cast<uint16_t>(value);
    } else if (isFan && strcmp(action, "power/set") == 0) {
        if (strcmp(text, "ON") == 0) { cmd.kind = Command::FanDuty; cmd.value = 100; }
        else if (strcmp(text, "OFF") == 0) { cmd.kind = Command::FanDuty; cmd.value = 0; }
        else return;
    } else if (!isFan && strcmp(action, "set") == 0) {
        if (strcmp(text, "OFF") == 0) cmd.kind = Command::ArgbOff;
        else if (strcmp(text, "RAINBOW") == 0) cmd.kind = Command::ArgbRainbow;
        else if (strlen(text) == 7 && text[0] == '#') {
            unsigned r, g, b; char tail;
            if (sscanf(text + 1, "%02x%02x%02x%c", &r, &g, &b, &tail) != 3) return;
            cmd.kind = Command::ArgbColor;
            cmd.red = static_cast<uint8_t>(r);
            cmd.green = static_cast<uint8_t>(g);
            cmd.blue = static_cast<uint8_t>(b);
        } else return;
    } else if (!isFan && strcmp(action, "brightness/set") == 0) {
        const long value = strtol(text, &end, 10);
        if (*end || end == text || value < 0 || value > 255) return;
        cmd.kind = Command::Brightness; cmd.value = static_cast<uint16_t>(value);
    } else return;
    xQueueSend(commands_, &cmd, 0); // Overflow: drop safely, never block cooling.
}

void MqttBridge::networkLoop() {
    WiFiClient connection;
    PubSubClient client(connection);
    client.setBufferSize(1024);
    client.setKeepAlive(30);
    client.setSocketTimeout(1);
    callbackInstance_ = this;
    client.setCallback([](char* topic, uint8_t* bytes, unsigned int length) {
        if (callbackInstance_) callbackInstance_->receive(topic, bytes, length);
    });
    uint32_t lastAttempt = 0;
    uint32_t activeRevision = 0xFFFFFFFFUL;
    bool announce = false;
    char deviceId[40] = {};
    const uint64_t chip = ESP.getEfuseMac();
    snprintf(deviceId, sizeof(deviceId), "esp32s3_fanargb_%012llx",
             static_cast<unsigned long long>(chip & 0xFFFFFFFFFFFFULL));
    for (;;) {
        Config cfg = {};
        if (xSemaphoreTake(configLock_, pdMS_TO_TICKS(100)) == pdTRUE) {
            cfg = config_;
            const uint32_t revision = configRevision_;
            xSemaphoreGive(configLock_);
            if (revision != activeRevision) {
                activeRevision = revision;
                client.disconnect();
                connected_ = false;
                announce = false;
            }
        }
        if (!cfg.enabled || !cfg.host[0] || WiFi.status() != WL_CONNECTED) {
            if (client.connected()) client.disconnect();
            connected_ = false;
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }
        if (!client.connected()) {
            connected_ = false;
            if (static_cast<uint32_t>(millis() - lastAttempt) >= 5000U) {
                lastAttempt = millis();
                client.setServer(cfg.host, cfg.port);
                char availability[110] = {};
                snprintf(availability, sizeof(availability), "%s/status", cfg.prefix);
                const bool ok = cfg.user[0]
                    ? client.connect(deviceId, cfg.user, cfg.password, availability, 1, true, "offline")
                    : client.connect(deviceId, availability, 1, true, "offline");
                if (ok) {
                    connected_ = true;
                    client.publish(availability, "online", true);
                    char topic[100] = {};
                    snprintf(topic, sizeof(topic), "%s/fan/+/set", cfg.prefix);
                    client.subscribe(topic);
                    snprintf(topic, sizeof(topic), "%s/fan/+/power/set", cfg.prefix);
                    client.subscribe(topic);
                    snprintf(topic, sizeof(topic), "%s/argb/+/set", cfg.prefix);
                    client.subscribe(topic);
                    snprintf(topic, sizeof(topic), "%s/argb/+/brightness/set", cfg.prefix);
                    client.subscribe(topic);
                    announce = true;
                }
            }
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        client.loop();
        // Home Assistant MQTT discovery, retained. Reannounce after reconnect.
        if (announce) {
            announce = false;
            const String base = String(cfg.prefix);
            const String availability = base + "/status";
            const String device = String("\"device\":{\"identifiers\":[\"") + deviceId +
                "\"],\"name\":\"ESP32-S3 8 Fan 8 ARGB\",\"manufacturer\":\"DIY\"}";
            for (unsigned ch = 1; ch <= board::kChannelCount; ++ch) {
                const String id = String(deviceId) + "_fan" + ch;
                const String fan = base + "/fan/" + ch;
                const String discovery = String("homeassistant/fan/") + id + "/config";
                const String config = String("{\"name\":\"Fan ") + ch +
                    "\",\"unique_id\":\"" + id + "\",\"availability_topic\":\"" + availability +
                    "\",\"state_topic\":\"" + fan + "/state\",\"command_topic\":\"" + fan +
                    "/power/set\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"percentage_state_topic\":\"" + fan +
                    "/pwm\",\"percentage_command_topic\":\"" + fan + "/set\"," + device + "}";
                client.publish(discovery.c_str(), config.c_str(), true);
                const String rpmTopic = String("homeassistant/sensor/") + id + "_rpm/config";
                const String rpm = String("{\"name\":\"Fan ") + ch + " RPM\",\"unique_id\":\"" + id +
                    "_rpm\",\"state_topic\":\"" + fan + "/rpm\",\"unit_of_measurement\":\"rpm\",\"availability_topic\":\"" +
                    availability + "\"," + device + "}";
                client.publish(rpmTopic.c_str(), rpm.c_str(), true);
                const String tempTopic = String("homeassistant/sensor/") + id + "_temp/config";
                const String temp = String("{\"name\":\"Fan ") + ch + " Temperature\",\"unique_id\":\"" + id +
                    "_temp\",\"state_topic\":\"" + fan + "/temperature\",\"device_class\":\"temperature\",\"unit_of_measurement\":\"°C\",\"availability_topic\":\"" +
                    availability + "\"," + device + "}";
                client.publish(tempTopic.c_str(), temp.c_str(), true);
                const String faultTopic = String("homeassistant/binary_sensor/") + id + "_fault/config";
                const String fault = String("{\"name\":\"Fan ") + ch + " Fault\",\"unique_id\":\"" + id +
                    "_fault\",\"state_topic\":\"" + fan + "/fault\",\"payload_on\":\"1\",\"payload_off\":\"0\"," +
                    "\"availability_topic\":\"" + availability + "\"," + device + "}";
                client.publish(faultTopic.c_str(), fault.c_str(), true);
                client.loop();
                vTaskDelay(pdMS_TO_TICKS(8));
                if (!client.connected()) break;
            }
        }
        Snapshot snapshot = {};
        if (xQueueReceive(snapshots_, &snapshot, 0) == pdTRUE) {
            for (uint8_t i = 0; i < board::kChannelCount && client.connected(); ++i) {
                const unsigned ch = i + 1;
                char topic[110] = {};
                char number[20] = {};
                auto publishNum = [&](const char* field, unsigned value) {
                    snprintf(topic, sizeof(topic), "%s/fan/%u/%s", cfg.prefix, ch, field);
                    snprintf(number, sizeof(number), "%u", value);
                    client.publish(topic, number, true);
                };
                publishNum("pwm", snapshot.pwm[i]);
                publishNum("rpm", snapshot.rpm[i]);
                snprintf(topic, sizeof(topic), "%s/fan/%u/temperature", cfg.prefix, ch);
                char temperature[24] = {};
                snprintf(temperature, sizeof(temperature), "%u.%u",
                         snapshot.temp[i] / 10U, snapshot.temp[i] % 10U);
                client.publish(topic, snapshot.tempFresh[i] ? temperature : "unknown", true);
                publishNum("type", snapshot.type[i]);
                snprintf(topic, sizeof(topic), "%s/fan/%u/fault", cfg.prefix, ch);
                client.publish(topic, snapshot.fault[i] ? "1" :
                               snapshot.type[i] == 2 ? "unknown" : "0", true);
                publishNum("tach_valid", snapshot.tach[i]);
                publishNum("rejected", snapshot.rejected[i]);
                snprintf(topic, sizeof(topic), "%s/fan/%u/state", cfg.prefix, ch);
                client.publish(topic, snapshot.pwm[i] ? "ON" : "OFF", true);
                snprintf(topic, sizeof(topic), "%s/fan/%u/mode", cfg.prefix, ch);
                const char* mode = snapshot.mode[i] == 1 ? "manual" :
                    snapshot.mode[i] == 2 ? "calibration" :
                    snapshot.mode[i] == 3 ? "rpm" : "auto";
                client.publish(topic, mode, true);
                snprintf(topic, sizeof(topic), "%s/argb/%u/state", cfg.prefix, ch);
                const char* rgbMode = snapshot.rgbMode[i] == 0 ? "off" :
                    snapshot.rgbMode[i] == 1 ? "solid" :
                    snapshot.rgbMode[i] == 2 ? "rainbow" : "external";
                client.publish(topic, rgbMode, true);
            }
            char topic[110] = {};
            snprintf(topic, sizeof(topic), "%s/dc_pwm_validated", cfg.prefix);
            client.publish(topic, snapshot.dcReady ? "1" : "0", true);
        }
        vTaskDelay(pdMS_TO_TICKS(30));
    }
}
#endif

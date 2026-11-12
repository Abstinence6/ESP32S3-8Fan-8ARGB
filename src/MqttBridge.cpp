#include "MqttBridge.h"
#include <ctype.h>
#include <initializer_list>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace {
constexpr uint32_t kMagic = 0x4D515435UL; // MQT5
bool parseUInt(const char* s, unsigned max, unsigned& value) {
    if (!s || !*s) return false;
    unsigned n = 0;
    for (; *s; ++s) {
        if (*s < '0' || *s > '9') return false;
        n = n * 10U + static_cast<unsigned>(*s - '0');
        if (n > max) return false;
    }
    value = n;
    return true;
}
}

MqttBridge::MqttBridge(CoolingController& cooling, FanController& fans,
                       ArgbController& leds, NetworkRgbBridge& network)
    : cooling_(cooling), fans_(fans), leds_(leds), network_(network)
#if defined(ARDUINO_ARCH_ESP32)
    , mqtt_(tcp_)
#endif
{}

bool MqttBridge::begin() {
    if (!storage_.begin("fanmqtt", false)) return false;
    Settings old = {};
    if (storage_.getBytesLength("config") == sizeof(old) &&
        storage_.getBytes("config", &old, sizeof(old)) == sizeof(old) &&
        old.magic == kMagic && old.enabled <= 1 && old.port > 0 &&
        memchr(old.host, 0, sizeof(old.host)) &&
        memchr(old.user, 0, sizeof(old.user)) &&
        memchr(old.password, 0, sizeof(old.password))) {
        settings_ = old;
    } else {
        settings_ = {};
        settings_.magic = kMagic;
        settings_.port = 1883;
    }
#if defined(ARDUINO_ARCH_ESP32)
    snprintf(baseTopic_, sizeof(baseTopic_), "esp32fan/%08lx",
             static_cast<unsigned long>(ESP.getEfuseMac() & 0xFFFFFFFFULL));
    mqtt_.setBufferSize(1024);
    mqtt_.setKeepAlive(15);
    mqtt_.setSocketTimeout(1); // never leave cooling unserved for a long broker stall
    mqtt_.setCallback([this](char* t, uint8_t* p, unsigned n) { receive(t, p, n); });
#endif
    return true;
}

bool MqttBridge::persist() {
    return storage_.putBytes("config", &settings_, sizeof(settings_)) == sizeof(settings_);
}
bool MqttBridge::setBroker(const char* host, uint16_t port) {
    if (!host || !*host || strlen(host) >= sizeof(settings_.host) || !port) return false;
    const Settings before = settings_;
    memset(settings_.host, 0, sizeof(settings_.host));
    memcpy(settings_.host, host, strlen(host));
    settings_.port = port;
    settings_.enabled = 1;
    if (!persist()) { settings_ = before; return false; }
#if defined(ARDUINO_ARCH_ESP32)
    mqtt_.disconnect();
#endif
    return true;
}
bool MqttBridge::setCredentials(const char* user, const char* password) {
    if (!user || !password || strlen(user) >= sizeof(settings_.user) ||
        strlen(password) >= sizeof(settings_.password)) return false;
    const Settings before = settings_;
    memset(settings_.user, 0, sizeof(settings_.user));
    memset(settings_.password, 0, sizeof(settings_.password));
    memcpy(settings_.user, user, strlen(user));
    memcpy(settings_.password, password, strlen(password));
    if (!persist()) { settings_ = before; return false; }
#if defined(ARDUINO_ARCH_ESP32)
    mqtt_.disconnect();
#endif
    return true;
}
bool MqttBridge::setEnabled(bool enabled) {
    if (enabled && !settings_.host[0]) return false;
    const uint8_t old = settings_.enabled;
    settings_.enabled = enabled ? 1 : 0;
    if (!persist()) { settings_.enabled = old; return false; }
#if defined(ARDUINO_ARCH_ESP32)
    if (!enabled) mqtt_.disconnect();
#endif
    return true;
}
bool MqttBridge::connected() const {
#if defined(ARDUINO_ARCH_ESP32)
    return settings_.enabled && network_.connected() && mqtt_.connected();
#else
    return false;
#endif
}
void MqttBridge::printStatus(Stream& serial) const {
    serial.print(F("MQTT ENABLED=")); serial.print(settings_.enabled);
    serial.print(F(" HOST=")); serial.print(settings_.host);
    serial.print(F(" PORT=")); serial.print(settings_.port);
    serial.print(F(" AUTH=")); serial.print(settings_.user[0] ? 1 : 0);
    serial.print(F(" CONNECTED=")); serial.print(connected() ? 1 : 0);
    serial.print(F(" TOPIC=")); serial.println(baseTopic_);
}

bool MqttBridge::applyCommand(const char* topic, const char* payload, uint32_t nowMs) {
    if (!topic || !payload) return false;
    const size_t prefix = strlen(baseTopic_);
    if (strncmp(topic, baseTopic_, prefix) || topic[prefix] != '/') return false;
    const char* p = topic + prefix + 1;
    unsigned number = 0;
    const char* suffix = nullptr;
    if (!strncmp(p, "fan/", 4)) {
        p += 4;
        if (*p < '1' || *p > '8' || p[1] != '/') return false;
        number = static_cast<unsigned>(*p - '1');
        suffix = p + 2;
        unsigned value = 0;
        if (!strcmp(suffix, "set") && parseUInt(payload, 100, value))
            return cooling_.setManual(number, static_cast<uint8_t>(value));
        if (!strcmp(suffix, "power/set")) {
            if (!strcmp(payload, "ON")) return cooling_.setManual(number, 100);
            if (!strcmp(payload, "OFF")) return cooling_.setManual(number, 0);
        }
        if (!strcmp(suffix, "mode/set") && !strcmp(payload, "auto"))
            return cooling_.setAuto(number);
        if ((!strcmp(suffix, "temp/set") || !strcmp(suffix, "temp2/set")) &&
            parseUInt(payload, 1250, value)) {
            cooling_.setTemperature(number, static_cast<uint16_t>(value), nowMs,
                                    !strcmp(suffix, "temp2/set"));
            return true;
        }
        return false;
    }
    if (!strncmp(p, "light/", 6)) {
        p += 6;
        if (*p < '1' || *p > '8' || p[1] != '/') return false;
        number = static_cast<unsigned>(*p - '1');
        suffix = p + 2;
        if (!strcmp(suffix, "set")) {
            if (!strcmp(payload, "OFF")) return leds_.setOff(number);
            if (!strcmp(payload, "RAINBOW") || !strcmp(payload, "ON"))
                return leds_.setRainbow(number);
            return false;
        }
        if (!strcmp(suffix, "rgb/set")) {
            unsigned r = 0, g = 0, b = 0; char tail = 0;
            if (sscanf(payload, "%u,%u,%u%c", &r, &g, &b, &tail) != 3 ||
                r > 255 || g > 255 || b > 255) return false;
            return leds_.setSolid(number, r, g, b);
        }
    }
    return false;
}

void MqttBridge::receive(char* topic, uint8_t* bytes, unsigned len) {
    if (!topic || !bytes || !len || len >= 48U) return;
    char payload[48] = {};
    memcpy(payload, bytes, len);
    applyCommand(topic, payload, millis());
}

void MqttBridge::publishStatus(uint8_t ch) {
#if defined(ARDUINO_ARCH_ESP32)
    if (!connected()) return;
    char topic[96], payload[36];
    const unsigned idx = static_cast<unsigned>(ch + 1);
    snprintf(topic, sizeof(topic), "%s/fan/%u/pct", baseTopic_, idx);
    snprintf(payload, sizeof(payload), "%u", fans_.getPercent(ch));
    mqtt_.publish(topic, payload, true);
    snprintf(topic, sizeof(topic), "%s/fan/%u/state", baseTopic_, idx);
    mqtt_.publish(topic, fans_.getPercent(ch) ? "ON" : "OFF", true);
    snprintf(topic, sizeof(topic), "%s/fan/%u/rpm", baseTopic_, idx);
    snprintf(payload, sizeof(payload), "%lu", static_cast<unsigned long>(fans_.getRpm(ch)));
    mqtt_.publish(topic, payload, true);
    snprintf(topic, sizeof(topic), "%s/fan/%u/mode", baseTopic_, idx);
    mqtt_.publish(topic, cooling_.mode(ch) == CoolingController::Mode::Auto ? "auto" : "manual", true);
    snprintf(topic, sizeof(topic), "%s/fan/%u/fault", baseTopic_, idx);
    mqtt_.publish(topic, cooling_.faulted(ch) ? "ON" : "OFF", true);
    snprintf(topic, sizeof(topic), "%s/fan/%u/temp", baseTopic_, idx);
    snprintf(payload, sizeof(payload), "%.1f", cooling_.temperature(ch) / 10.0f);
    mqtt_.publish(topic, payload, true);
#else
    (void)ch;
#endif
}

void MqttBridge::publishDiscovery() {
#if defined(ARDUINO_ARCH_ESP32)
    char topic[120], payload[900];
    const char* id = strchr(baseTopic_, '/');
    id = id ? id + 1 : "esp32s3";
    if (discoveryStep_ >= board::kChannelCount) return;
    const unsigned i = ++discoveryStep_;
    {
        snprintf(topic, sizeof(topic), "homeassistant/fan/%s_f%u/config", id, i);
        snprintf(payload, sizeof(payload),
            "{\"name\":\"Fan %u\",\"unique_id\":\"%s_f%u\","
            "\"command_topic\":\"%s/fan/%u/power/set\","
            "\"state_topic\":\"%s/fan/%u/state\","
            "\"percentage_command_topic\":\"%s/fan/%u/set\","
            "\"percentage_state_topic\":\"%s/fan/%u/pct\","
            "\"availability_topic\":\"%s/availability\","
            "\"device\":{\"identifiers\":[\"%s\"],\"name\":\"ESP32-S3 Fan/ARGB %s\",\"manufacturer\":\"DIY\"}}",
            i, id, i, baseTopic_, i, baseTopic_, i,
            baseTopic_, i, baseTopic_, i, baseTopic_, baseTopic_, id);
        mqtt_.publish(topic, payload, true);
        snprintf(topic, sizeof(topic), "homeassistant/sensor/%s_f%u_rpm/config", id, i);
        snprintf(payload, sizeof(payload),
            "{\"name\":\"Fan %u RPM\",\"unique_id\":\"%s_f%u_rpm\","
            "\"state_topic\":\"%s/fan/%u/rpm\",\"unit_of_measurement\":\"rpm\","
            "\"availability_topic\":\"%s/availability\","
            "\"device\":{\"identifiers\":[\"%s\"],\"name\":\"ESP32-S3 Fan/ARGB %s\"}}",
            i, id, i, baseTopic_, i, baseTopic_, baseTopic_, id);
        mqtt_.publish(topic, payload, true);
        snprintf(topic, sizeof(topic), "homeassistant/light/%s_l%u/config", id, i);
        snprintf(payload, sizeof(payload),
            "{\"name\":\"ARGB %u\",\"unique_id\":\"%s_l%u\","
            "\"command_topic\":\"%s/light/%u/set\","
            "\"rgb_command_topic\":\"%s/light/%u/rgb/set\","
            "\"availability_topic\":\"%s/availability\","
            "\"device\":{\"identifiers\":[\"%s\"],\"name\":\"ESP32-S3 Fan/ARGB %s\"}}",
            i, id, i, baseTopic_, i, baseTopic_, i, baseTopic_, baseTopic_, id);
        mqtt_.publish(topic, payload, true);
    }
#endif
}

void MqttBridge::update(uint32_t nowMs) {
#if defined(ARDUINO_ARCH_ESP32)
    if (!settings_.enabled || !settings_.host[0] || !network_.connected()) {
        if (mqtt_.connected()) mqtt_.disconnect();
        return;
    }
    if (!mqtt_.connected()) {
        if (retryAtMs_ && nowMs - retryAtMs_ < 10000U) return;
        retryAtMs_ = nowMs;
        mqtt_.setServer(settings_.host, settings_.port);
        char will[70]; snprintf(will, sizeof(will), "%s/availability", baseTopic_);
        const bool ok = settings_.user[0] ?
            mqtt_.connect(baseTopic_, settings_.user, settings_.password,
                          will, 0, true, "offline") :
            mqtt_.connect(baseTopic_, will, 0, true, "offline");
        if (!ok) return;
        mqtt_.publish(will, "online", true);
        char topic[96];
        for (const char* wildcard : {"fan/+/set", "fan/+/power/set", "fan/+/mode/set",
                                     "fan/+/temp/set", "fan/+/temp2/set", "light/+/set",
                                     "light/+/rgb/set"}) {
            snprintf(topic, sizeof(topic), "%s/%s", baseTopic_, wildcard);
            mqtt_.subscribe(topic);
        }
        discoveryStep_ = 0;
        lastDiscoveryMs_ = nowMs;
        lastPublishMs_ = nowMs - 2000U;
    }
    mqtt_.loop();
    // Limit HA discovery traffic: three retained configs per 300 ms visit.
    if (discoveryStep_ < board::kChannelCount &&
        nowMs - lastDiscoveryMs_ >= 300U) {
        lastDiscoveryMs_ = nowMs;
        publishDiscovery();
    }
    if (nowMs - lastPublishMs_ >= 250U) {
        lastPublishMs_ = nowMs;
        publishStatus(nextChannel_);
        nextChannel_ = (nextChannel_ + 1U) % board::kChannelCount;
    }
#else
    (void)nowMs;
#endif
}

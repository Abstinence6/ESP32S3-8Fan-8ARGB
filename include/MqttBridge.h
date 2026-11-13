#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "CoolingController.h"
#include "ArgbController.h"
#include "NetworkRgbBridge.h"
#include "PcPowerController.h"

#if defined(ARDUINO_ARCH_ESP32)
#include <WiFi.h>
#include <PubSubClient.h>
#endif

// Optional *local broker* MQTT interface. All fan changes go through the same
// CoolingController guards as Serial; no remote command can bypass DC interlock.
class MqttBridge {
public:
    MqttBridge(CoolingController& cooling, FanController& fans,
               ArgbController& leds, NetworkRgbBridge& network, PcPowerController* pc = nullptr);
    bool begin();
    void update(uint32_t nowMs);
    bool setBroker(const char* host, uint16_t port, bool enable = true);
    bool setCredentials(const char* username, const char* password);
    bool setEnabled(bool enabled);
    bool setDiscovery(bool enabled);
    bool setExternalTemperatures(bool enabled);
    bool externalTemperaturesEnabled() const { return externalTemperaturesEnabled_; }
    bool resetSettings();
    void printStatus(Stream& serial);
    void printConfig(Stream& serial);
    bool connected();
    const char* baseTopic() const { return baseTopic_; }
    // Pure (hardware-independent) MQTT command routing for native safety tests.
    bool applyCommand(const char* topic, const char* payload, uint32_t nowMs);
private:
    struct Settings {
        uint32_t magic;
        uint8_t enabled;
        uint16_t port;
        char host[64];
        char user[32];
        char password[64];
    };
    bool persist();
    void publishStatus(uint8_t ch);
    void publishDiscovery();
    void removeDiscovery(uint8_t channel);
    void receive(char* topic, uint8_t* payload, unsigned length);
    CoolingController& cooling_;
    FanController& fans_;
    ArgbController& leds_;
    NetworkRgbBridge& network_;
    PcPowerController* pc_;
    Preferences storage_;
    Settings settings_ = {};
    char baseTopic_[40] = "esp32fan/esp32s3";
    uint32_t retryAtMs_ = 0;
    uint32_t lastPublishMs_ = 0;
    uint32_t lastPcPublishMs_ = 0;
    uint8_t nextChannel_ = 0;
    uint8_t discoveryStep_ = 0;
    uint32_t lastDiscoveryMs_ = 0;
    bool discoveryEnabled_ = true;
    bool externalTemperaturesEnabled_ = false;
    // 0..8: pending retained-entity deletion, 255: complete.
    uint8_t discoveryCleanupStep_ = 255;
#if defined(ARDUINO_ARCH_ESP32)
    WiFiClient tcp_;
    PubSubClient mqtt_;
#endif
};

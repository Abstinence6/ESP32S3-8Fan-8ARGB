#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "ArgbController.h"

#if defined(ARDUINO_ARCH_ESP32)
#include <WiFi.h>
#include <WiFiUdp.h>
#endif

// Optional Wi-Fi receiver. Direct E1.31/sACN (UDP 5568) or DDP (UDP 4048)
// without the desktop USB RGB bridge. PC temperature telemetry remains USB-only.
class NetworkRgbBridge {
public:
    explicit NetworkRgbBridge(ArgbController& outputs) : outputs_(outputs) {}
    bool begin();
    void update(uint32_t nowMs);
    bool configure(const char* ssid, const char* password);
    // Keep existing PSK only for the same SSID. Never expose stored PSK.
    bool reconnectExisting(const char* ssid);
    bool disable();
    void printConfig(Stream& out) const;
    bool configured() const { return enabled_; }
    bool connected() const;
    void printStatus(Stream& out) const;
    static bool sacnFrame(const uint8_t* packet, size_t bytes, uint8_t& channel,
                          const uint8_t*& rgb, uint16_t& pixels);
    static bool ddpFrame(const uint8_t* packet, size_t bytes, uint8_t& channel,
                         const uint8_t*& rgb, uint16_t& pixels);
private:
    void connect();
    ArgbController& outputs_;
    Preferences config_;
    bool enabled_ = false;
    bool listening_ = false;
    char ssid_[33] = {};
    char password_[65] = {};
    uint32_t retryAtMs_ = 0;
#if defined(ARDUINO_ARCH_ESP32)
    WiFiUDP sacn_;
    WiFiUDP ddp_;
#endif
    uint8_t buffer_[640] = {};
};

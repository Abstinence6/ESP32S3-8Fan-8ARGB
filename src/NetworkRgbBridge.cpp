#include "NetworkRgbBridge.h"
#include <string.h>
#include <initializer_list>

namespace {
constexpr size_t kSettingsSize = 33 + 65;
uint16_t be16(const uint8_t* b) {
    return static_cast<uint16_t>(static_cast<uint16_t>(b[0]) << 8U | b[1]);
}
}

bool NetworkRgbBridge::sacnFrame(const uint8_t* packet, size_t bytes, uint8_t& ch,
                                  const uint8_t*& rgb, uint16_t& pixels) {
    if (!packet || bytes < 129 || bytes > 638 ||
        packet[0] != 0 || packet[1] != 16 ||
        memcmp(packet + 4, "ASC-E1.17\0\0\0", 12) != 0 ||
        packet[18] != 0 || packet[19] != 0 || packet[20] != 0 || packet[21] != 4 ||
        packet[40] != 0 || packet[41] != 0 || packet[42] != 0 || packet[43] != 2 ||
        packet[117] != 2 || packet[118] != 0xA1 ||
        packet[119] != 0 || packet[120] != 0 || packet[121] != 0 || packet[122] != 1 ||
        (packet[112] & 0xC0) != 0 || packet[125] != 0) return false;
    for (const size_t pos : {16U, 38U, 115U}) {
        if (be16(packet + pos) != static_cast<uint16_t>(0x7000U | (bytes - pos))) return false;
    }
    const uint16_t u = be16(packet + 113);
    const uint16_t slots = be16(packet + 123);
    if (u < 1 || u > board::kChannelCount || slots < 4 || slots > 513 ||
        125U + slots != bytes) return false;
    ch = static_cast<uint8_t>(u);
    rgb = packet + 126;
    pixels = static_cast<uint16_t>((bytes - 126) / 3U);
    return pixels > 0 && pixels <= board::kMaxArgbPixelsPerFrame;
}

bool NetworkRgbBridge::ddpFrame(const uint8_t* packet, size_t bytes, uint8_t& ch,
                                 const uint8_t*& rgb, uint16_t& pixels) {
    if (!packet || bytes < 13 || bytes > 522 || (packet[0] & 0xC0) != 0x40 ||
        packet[2] != 1 || packet[3] < 1 || packet[3] > board::kChannelCount ||
        packet[4] || packet[5] || packet[6] || packet[7]) return false;
    const uint16_t length = be16(packet + 8);
    if (length < 3 || length > board::kMaxArgbPixelsPerFrame * 3U ||
        length % 3U || length + 10U != bytes) return false;
    ch = packet[3];
    rgb = packet + 10;
    pixels = length / 3;
    return true;
}

bool NetworkRgbBridge::begin() {
#if defined(ARDUINO_ARCH_ESP32)
    if (!config_.begin("rgbwifi", false)) return false;
    uint8_t credentials[kSettingsSize] = {};
    if (config_.getBytesLength("network") == sizeof(credentials) &&
        config_.getBytes("network", credentials, sizeof(credentials)) == sizeof(credentials) &&
        credentials[0] != 0) {
        memcpy(ssid_, credentials, sizeof(ssid_));
        memcpy(password_, credentials + sizeof(ssid_), sizeof(password_));
        if (!memchr(ssid_, 0, sizeof(ssid_)) || !memchr(password_, 0, sizeof(password_))) return false;
        enabled_ = true;
        connect();
    }
#endif
    return true;
}
void NetworkRgbBridge::connect() {
#if defined(ARDUINO_ARCH_ESP32)
    if (enabled_) {
        WiFi.mode(WIFI_STA);
        WiFi.begin(ssid_, password_); // asynchronous, no long blocking wait
    }
#endif
}
bool NetworkRgbBridge::configure(const char* ssid, const char* password) {
    if (!ssid || !password || !ssid[0] || strlen(ssid) > 32 || strlen(password) > 64) return false;
#if defined(ARDUINO_ARCH_ESP32)
    uint8_t credentials[kSettingsSize] = {};
    memcpy(credentials, ssid, strlen(ssid));
    memcpy(credentials + sizeof(ssid_), password, strlen(password));
    if (config_.putBytes("network", credentials, sizeof(credentials)) != sizeof(credentials)) return false;
    strncpy(ssid_, ssid, sizeof(ssid_) - 1);
    strncpy(password_, password, sizeof(password_) - 1);
    enabled_ = true;
    if (listening_) { sacn_.stop(); ddp_.stop(); listening_ = false; }
    WiFi.disconnect();
    connect();
    return true;
#else
    (void)ssid; (void)password; return false;
#endif
}
bool NetworkRgbBridge::disable() {
#if defined(ARDUINO_ARCH_ESP32)
    const uint8_t empty[kSettingsSize] = {};
    if (config_.putBytes("network", empty, sizeof(empty)) != sizeof(empty)) return false;
    if (listening_) { sacn_.stop(); ddp_.stop(); listening_ = false; }
    WiFi.disconnect(true);
    enabled_ = false;
    memset(ssid_, 0, sizeof(ssid_));
    memset(password_, 0, sizeof(password_));
    return true;
#else
    return false;
#endif
}
bool NetworkRgbBridge::connected() const {
#if defined(ARDUINO_ARCH_ESP32)
    return enabled_ && WiFi.status() == WL_CONNECTED;
#else
    return false;
#endif
}
void NetworkRgbBridge::printStatus(Stream& out) const {
    out.print(F("WIFI "));
    if (!enabled_) { out.println(F("disabled")); return; }
    out.print(connected() ? F("connected ") : F("disconnected "));
    out.print(ssid_);
#if defined(ARDUINO_ARCH_ESP32)
    if (connected()) { out.print(F(" ")); out.print(WiFi.localIP().toString().c_str()); }
#endif
    out.println("");
}
void NetworkRgbBridge::update(uint32_t nowMs) {
#if defined(ARDUINO_ARCH_ESP32)
    if (!enabled_) return;
    if (WiFi.status() != WL_CONNECTED) {
        if (listening_) { sacn_.stop(); ddp_.stop(); listening_ = false; }
        if (nowMs - retryAtMs_ > 15000U) {
            retryAtMs_ = nowMs;
            connect();
        }
        return;
    }
    if (!listening_) {
        if (!sacn_.begin(5568) || !ddp_.begin(4048)) return;
        listening_ = true;
    }
    for (uint8_t port = 0; port < 2; ++port) {
        WiFiUDP& udp = port == 0 ? sacn_ : ddp_;
        for (uint8_t frame = 0; frame < 4; ++frame) {
            const int bytes = udp.parsePacket();
            if (bytes <= 0) break;
            if (bytes > static_cast<int>(sizeof(buffer_))) { udp.flush(); continue; }
            if (udp.read(buffer_, bytes) != bytes) continue;
            uint8_t ch = 0; const uint8_t* rgb = nullptr; uint16_t pixels = 0;
            const bool ok = port == 0 ? sacnFrame(buffer_, bytes, ch, rgb, pixels)
                                      : ddpFrame(buffer_, bytes, ch, rgb, pixels);
            if (ok) {
                const uint16_t count = outputs_.pixelCount(ch - 1);
                if (pixels > count) pixels = count;
                if (pixels) outputs_.setPixels(ch - 1, rgb, pixels);
            }
        }
    }
#else
    (void)nowMs;
#endif
}

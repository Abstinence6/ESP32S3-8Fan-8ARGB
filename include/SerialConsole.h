#pragma once

#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
class MqttBridge;
#include "NetworkRgbBridge.h"
#include "PcPowerController.h"
#include "HardwareTemperature.h"

class SerialConsole {
public:
    SerialConsole(Stream& serial, FanController& fans, ArgbController& leds, CoolingController& cooling, NetworkRgbBridge* wifi = nullptr, MqttBridge* mqtt = nullptr, PcPowerController* pc = nullptr, HardwareTemperature* hw = nullptr);
    void begin();
    void poll();

private:
    enum class RxState : uint8_t { Text, Sync, Channel, CountLo, CountHi, Pixels, CrcLo, CrcHi, Discard };
    void handleLine(char* line);
    void handleByte(uint8_t value);
    void resetBinary();
    static uint16_t crcByte(uint16_t crc, uint8_t value);
    void printStatus();
    void printHealth(uint8_t channel);
    void startSelfTest(uint32_t nowMs);
    void finishSelfTest();
    void printHelp();
    static bool parseByte(const char* token, uint8_t maximum, uint8_t& out);
    static bool parseU16(const char* token, uint16_t maximum, uint16_t& out);

    Stream& serial_;
    FanController& fans_;
    ArgbController& leds_;
    CoolingController& cooling_;
    NetworkRgbBridge* wifi_;
    MqttBridge* mqtt_;
    PcPowerController* pc_;
    HardwareTemperature* hw_;
    bool selfTestActive_ = false;
    uint32_t selfTestStartMs_ = 0;
    uint32_t selfTestBasePulses_[board::kChannelCount] = {};
    uint8_t selfTestBasePwm_[board::kChannelCount] = {};
    FanController::Type selfTestBaseType_[board::kChannelCount] = {};
    char line_[240] = {}; // bounded hex-encoded SSID/PSK + MQTT auth tokens
    uint8_t size_ = 0;
    bool discardingLongLine_ = false;
    RxState rx_ = RxState::Text;
    uint8_t rgbChannel_ = 0;
    uint16_t rgbCount_ = 0;
    uint16_t rgbOffset_ = 0;
    uint16_t rgbCrc_ = 0xFFFF;
    uint16_t rgbReceivedCrc_ = 0;
    uint32_t rgbLastByteMs_ = 0;
    uint8_t rgbBuffer_[board::kMaxArgbPixelsPerFrame * 3] = {};
};

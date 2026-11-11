#pragma once

#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "NetworkRgbBridge.h"

class SerialConsole {
public:
    SerialConsole(Stream& serial, FanController& fans, ArgbController& leds, CoolingController& cooling, NetworkRgbBridge* wifi = nullptr);
    void begin();
    void poll();

private:
    enum class RxState : uint8_t { Text, Sync, Channel, CountLo, CountHi, Pixels, CrcLo, CrcHi, Discard };
    void handleLine(char* line);
    void handleByte(uint8_t value);
    void resetBinary();
    static uint16_t crcByte(uint16_t crc, uint8_t value);
    void printStatus();
    void printHelp();
    static bool parseByte(const char* token, uint8_t maximum, uint8_t& out);
    static bool parseU16(const char* token, uint16_t maximum, uint16_t& out);

    Stream& serial_;
    FanController& fans_;
    ArgbController& leds_;
    CoolingController& cooling_;
    NetworkRgbBridge* wifi_;
    char line_[96] = {};
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

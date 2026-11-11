#pragma once

#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"

class SerialConsole {
public:
    SerialConsole(Stream& serial, FanController& fans, ArgbController& leds, CoolingController& cooling);
    void begin();
    void poll();

private:
    void handleLine(char* line);
    void printStatus();
    void printHelp();
    static bool parseByte(const char* token, uint8_t maximum, uint8_t& out);
    static bool parseU16(const char* token, uint16_t maximum, uint16_t& out);

    Stream& serial_;
    FanController& fans_;
    ArgbController& leds_;
    CoolingController& cooling_;
    char line_[96] = {};
    uint8_t size_ = 0;
    bool discardingLongLine_ = false;
};

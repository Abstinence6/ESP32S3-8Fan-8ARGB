#pragma once

#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"

class SerialConsole {
public:
    SerialConsole(Stream& serial, FanController& fans, ArgbController& leds);
    void begin();
    void poll();

private:
    void handleLine(char* line);
    void printStatus();
    void printHelp();
    static bool parseByte(const char* token, uint8_t maximum, uint8_t& out);

    Stream& serial_;
    FanController& fans_;
    ArgbController& leds_;
    char line_[96] = {};
    uint8_t size_ = 0;
    bool discardingLongLine_ = false;
};

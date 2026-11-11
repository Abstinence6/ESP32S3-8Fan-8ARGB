#include "SerialConsole.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

SerialConsole::SerialConsole(Stream& serial, FanController& fans, ArgbController& leds)
    : serial_(serial), fans_(fans), leds_(leds) {}

void SerialConsole::begin() {
    serial_.println(F("8Fan/8ARGB ready | type HELP"));
}

void SerialConsole::poll() {
    while (serial_.available() > 0) {
        const char c = static_cast<char>(serial_.read());
        if (c == '\r') continue;
        if (c == '\n') {
            if (!discardingLongLine_ && size_ > 0) {
                line_[size_] = '\0';
                handleLine(line_);
            }
            size_ = 0;
            discardingLongLine_ = false;
            continue;
        }
        if (discardingLongLine_) continue;
        if (size_ >= sizeof(line_) - 1) {
            discardingLongLine_ = true;
            serial_.println(F("ERR line too long"));
            continue;
        }
        line_[size_++] = c;
    }
}

bool SerialConsole::parseByte(const char* token, uint8_t maximum, uint8_t& out) {
    if (!token || *token == '\0' || *token == '-') return false;
    char* end = nullptr;
    const unsigned long value = strtoul(token, &end, 10);
    if (*end != '\0' || value > maximum) return false;
    out = static_cast<uint8_t>(value);
    return true;
}

void SerialConsole::handleLine(char* line) {
    char* save = nullptr;
    char* command = strtok_r(line, " \t", &save);
    if (!command) return;
    for (char* c = command; *c; ++c) *c = static_cast<char>(toupper(static_cast<unsigned char>(*c)));

    auto next = [&save]() -> char* { return strtok_r(nullptr, " \t", &save); };
    auto noMore = [&next]() -> bool { return next() == nullptr; };
    auto error = [this]() { serial_.println(F("ERR arguments | type HELP")); };

    if (strcmp(command, "HELP") == 0) {
        if (!noMore()) return error();
        printHelp();
        return;
    }
    if (strcmp(command, "STATUS") == 0) {
        if (!noMore()) return error();
        printStatus();
        return;
    }
    if (strcmp(command, "FAN") == 0 || strcmp(command, "ALLFAN") == 0) {
        const bool all = (strcmp(command, "ALLFAN") == 0);
        uint8_t channel = 0, percent = 0;
        if ((!all && !parseByte(next(), board::kChannelCount, channel)) ||
            !parseByte(next(), 100, percent) || !noMore() || (!all && channel == 0)) {
            return error();
        }
        if (all) {
            for (uint8_t i = 0; i < board::kChannelCount; ++i) fans_.setPercent(i, percent);
        } else {
            fans_.setPercent(channel - 1, percent);
        }
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "LED") == 0 || strcmp(command, "ALLLED") == 0) {
        const bool all = (strcmp(command, "ALLLED") == 0);
        uint8_t channel = 0, r = 0, g = 0, b = 0;
        if ((!all && !parseByte(next(), board::kChannelCount, channel)) ||
            !parseByte(next(), 255, r) || !parseByte(next(), 255, g) ||
            !parseByte(next(), 255, b) || !noMore() || (!all && channel == 0)) {
            return error();
        }
        if (all) {
            for (uint8_t i = 0; i < board::kChannelCount; ++i) leds_.setSolid(i, r, g, b);
        } else {
            leds_.setSolid(channel - 1, r, g, b);
        }
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "OFF") == 0 || strcmp(command, "RAINBOW") == 0 ||
        strcmp(command, "BRIGHT") == 0) {
        uint8_t channel = 0, value = 0;
        if (!parseByte(next(), board::kChannelCount, channel) || channel == 0) return error();
        if (strcmp(command, "BRIGHT") == 0) {
            if (!parseByte(next(), 255, value) || !noMore()) return error();
            leds_.setBrightness(channel - 1, value);
        } else {
            if (!noMore()) return error();
            if (strcmp(command, "OFF") == 0) leds_.setOff(channel - 1);
            else leds_.setRainbow(channel - 1);
        }
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "ALLOFF") == 0) {
        if (!noMore()) return error();
        for (uint8_t i = 0; i < board::kChannelCount; ++i) leds_.setOff(i);
        serial_.println(F("OK"));
        return;
    }
    serial_.println(F("ERR unknown command | type HELP"));
}

void SerialConsole::printHelp() {
    serial_.println(F("Channels are numbered 1..8"));
    serial_.println(F("FAN <ch> <0..100>   | ALLFAN <0..100>"));
    serial_.println(F("LED <ch> <R> <G> <B> | ALLLED <R> <G> <B>"));
    serial_.println(F("OFF <ch> | ALLOFF | RAINBOW <ch>"));
    serial_.println(F("BRIGHT <ch> <0..255>"));
    serial_.println(F("STATUS | HELP"));
}

void SerialConsole::printStatus() {
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        const char* mode = "off";
        if (leds_.getMode(i) == ArgbController::Mode::Solid) mode = "solid";
        if (leds_.getMode(i) == ArgbController::Mode::Rainbow) mode = "rainbow";
        serial_.print(F("CH ")); serial_.print(i + 1);
        serial_.print(F(" FAN=")); serial_.print(fans_.getPercent(i));
        serial_.print(F("% RPM=")); serial_.print(fans_.getRpm(i));
        serial_.print(F(" LED=")); serial_.print(mode);
        serial_.print(F(" BRIGHT=")); serial_.println(leds_.getBrightness(i));
    }
}

#include "SerialConsole.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

SerialConsole::SerialConsole(Stream& serial, FanController& fans, ArgbController& leds,
                             CoolingController& cooling)
    : serial_(serial), fans_(fans), leds_(leds), cooling_(cooling) {}

void SerialConsole::begin() {
    serial_.println(F("8Fan/8ARGB ready | protocol v2 | type HELP"));
}

void SerialConsole::poll() {
    // Corrupt/partial packets cannot lock out normal fan and temperature commands.
    if (rx_ != RxState::Text && millis() - rgbLastByteMs_ > 300U) resetBinary();
    while (serial_.available() > 0) {
        handleByte(static_cast<uint8_t>(serial_.read()));
    }
}

uint16_t SerialConsole::crcByte(uint16_t crc, uint8_t value) {
    crc ^= static_cast<uint16_t>(value) << 8U;
    for (uint8_t i = 0; i < 8; ++i) {
        crc = (crc & 0x8000U) ? static_cast<uint16_t>((crc << 1U) ^ 0x1021U)
                               : static_cast<uint16_t>(crc << 1U);
    }
    return crc;
}

void SerialConsole::resetBinary() {
    rx_ = RxState::Text;
    rgbCount_ = rgbOffset_ = rgbReceivedCrc_ = 0;
    rgbCrc_ = 0xFFFFU;
}

void SerialConsole::handleByte(uint8_t byte) {
    if (rx_ != RxState::Text) {
        rgbLastByteMs_ = millis();
        switch (rx_) {
        case RxState::Sync:
            if (byte == 0x5AU) rx_ = RxState::Channel;
            else if (byte != 0xA5U) resetBinary();
            break;
        case RxState::Channel:
            if (byte < 1 || byte > board::kChannelCount) { rx_ = RxState::Discard; break; }
            rgbChannel_ = byte;
            rgbCrc_ = crcByte(rgbCrc_, byte);
            rx_ = RxState::CountLo;
            break;
        case RxState::CountLo:
            rgbCount_ = byte;
            rgbCrc_ = crcByte(rgbCrc_, byte);
            rx_ = RxState::CountHi;
            break;
        case RxState::CountHi:
            rgbCount_ |= static_cast<uint16_t>(byte) << 8U;
            rgbCrc_ = crcByte(rgbCrc_, byte);
            if (rgbCount_ == 0 || rgbCount_ > board::kMaxArgbPixelsPerFrame ||
                rgbCount_ > leds_.pixelCount(rgbChannel_ - 1)) { rx_ = RxState::Discard; break; }
            rgbOffset_ = 0;
            rx_ = RxState::Pixels;
            break;
        case RxState::Pixels:
            rgbBuffer_[rgbOffset_++] = byte;
            rgbCrc_ = crcByte(rgbCrc_, byte);
            if (rgbOffset_ == rgbCount_ * 3U) rx_ = RxState::CrcLo;
            break;
        case RxState::CrcLo:
            rgbReceivedCrc_ = byte;
            rx_ = RxState::CrcHi;
            break;
        case RxState::CrcHi:
            rgbReceivedCrc_ |= static_cast<uint16_t>(byte) << 8U;
            if (rgbReceivedCrc_ == rgbCrc_)
                leds_.setPixels(rgbChannel_ - 1, rgbBuffer_, rgbCount_);
            // CRC mismatch: reject frame completely; never display partial data.
            resetBinary();
            break;
        case RxState::Discard:
            // Reject invalid binary headers without accidentally interpreting
            // arbitrary RGB payload as fan control text. Wait for idle gap.
            break;
        case RxState::Text: break;
        }
        return;
    }

    // Binary frames only begin between complete text commands.
    if (byte == 0xA5U && size_ == 0 && !discardingLongLine_) {
        rx_ = RxState::Sync;
        rgbCrc_ = 0xFFFFU;
        rgbLastByteMs_ = millis();
        return;
    }
    if (byte == '\r') return;
    if (byte == '\n') {
        if (!discardingLongLine_ && size_ > 0) {
            line_[size_] = '\0';
            handleLine(line_);
        }
        size_ = 0;
        discardingLongLine_ = false;
        return;
    }
    if (discardingLongLine_) return;
    if (size_ >= sizeof(line_) - 1) {
        discardingLongLine_ = true;
        serial_.println(F("ERR line too long"));
        return;
    }
    line_[size_++] = static_cast<char>(byte);
}

bool SerialConsole::parseU16(const char* token, uint16_t maximum, uint16_t& out) {
    if (!token || *token == '\0' || *token == '-') return false;
    char* end = nullptr;
    const unsigned long value = strtoul(token, &end, 10);
    if (*end != '\0' || value > maximum) return false;
    out = static_cast<uint16_t>(value);
    return true;
}

bool SerialConsole::parseByte(const char* token, uint8_t maximum, uint8_t& out) {
    uint16_t result = 0;
    if (!parseU16(token, maximum, result)) return false;
    out = static_cast<uint8_t>(result);
    return true;
}

void SerialConsole::handleLine(char* line) {
    char* save = nullptr;
    char* command = strtok_r(line, " \t", &save);
    if (!command) return;
    for (char* c = command; *c; ++c)
        *c = static_cast<char>(toupper(static_cast<unsigned char>(*c)));

    auto next = [&save]() -> char* { return strtok_r(nullptr, " \t", &save); };
    auto noMore = [&next]() -> bool { return next() == nullptr; };
    auto error = [this]() { serial_.println(F("ERR arguments | type HELP")); };

    if (strcmp(command, "PING") == 0) {
        if (!noMore()) return error();
        serial_.println(F("PONG 2"));
        return;
    }
    if (strcmp(command, "HELP") == 0) {
        if (!noMore()) return error();
        printHelp();
        return;
    }
    if (strcmp(command, "LEDS") == 0) {
        if (!noMore()) return error();
        serial_.print(F("LEDCOUNTS"));
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            serial_.print(F(" "));
            serial_.print(leds_.pixelCount(ch));
        }
        serial_.println("");
        return;
    }
    if (strcmp(command, "STATUS") == 0) {
        if (!noMore()) return error();
        printStatus();
        return;
    }
    if (strcmp(command, "TEMP") == 0) {
        uint8_t ch = 0;
        uint16_t deciC = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 ||
            !parseU16(next(), 1250, deciC) || !noMore()) return error();
        cooling_.setTemperature(ch-1, deciC, millis());
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "CURVE") == 0 || strcmp(command, "CURVE?") == 0) {
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0) return error();
        if (strcmp(command, "CURVE?") == 0) {
            if (!noMore()) return error();
            const auto* curve = cooling_.curve(ch-1);
            serial_.print(F("CURVE ")); serial_.print(ch);
            for (uint8_t i = 0; i < CoolingController::kCurvePoints; ++i) {
                serial_.print(F(" ")); serial_.print(curve[i].tempC);
                serial_.print(F(" ")); serial_.print(curve[i].pwm);
            }
            serial_.println("");
            return;
        }
        CoolingController::CurvePoint points[CoolingController::kCurvePoints];
        for (uint8_t i = 0; i < CoolingController::kCurvePoints; ++i) {
            if (!parseByte(next(), 125, points[i].tempC) ||
                !parseByte(next(), 100, points[i].pwm)) return error();
        }
        if (!noMore() || !CoolingController::validCurve(points)) return error();
        if (!cooling_.setCurve(ch-1, points)) {
            serial_.println(F("ERR NVS write")); return;
        }
        serial_.println(F("OK CURVE_SAVED"));
        return;
    }
    if (strcmp(command, "CAL") == 0) {
        char* op = next();
        if (!op) return error();
        for (char* c = op; *c; ++c) *c = static_cast<char>(toupper(static_cast<unsigned char>(*c)));
        if (strcmp(op, "CANCEL") == 0) {
            if (!noMore() || !cooling_.cancelCalibration()) return error();
            serial_.println(F("OK"));
            return;
        }
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 || !noMore()) return error();
        if (strcmp(op, "START") == 0) {
            if (!cooling_.startCalibration(ch-1, millis())) {
                serial_.println(F("ERR calibration busy")); return;
            }
            serial_.println(F("OK"));
            return;
        }
        if (strcmp(op, "GET") == 0) {
            if (!cooling_.hasCalibration(ch-1)) {
                serial_.println(F("ERR calibration missing")); return;
            }
            for (uint8_t i = 0; i < CoolingController::kCalibrationPoints; ++i) {
                serial_.print(F("CAL_RESULT ")); serial_.print(ch);
                serial_.print(F(" ")); serial_.print(i * 5);
                serial_.print(F(" ")); serial_.println(cooling_.rpmAt(ch-1, i));
            }
            serial_.print(F("CAL_END ")); serial_.println(ch);
            return;
        }
        return error();
    }
    if (strcmp(command, "AUTO") == 0 || strcmp(command, "ALLAUTO") == 0) {
        if (strcmp(command, "ALLAUTO") == 0) {
            if (!noMore()) return error();
            for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) cooling_.setAuto(ch);
            serial_.println(F("OK")); return;
        }
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 || !noMore()) return error();
        if (!cooling_.setAuto(ch-1)) { serial_.println(F("ERR calibration busy")); return; }
        serial_.println(F("OK")); return;
    }
    if (strcmp(command, "FAN") == 0 || strcmp(command, "ALLFAN") == 0) {
        const bool all = (strcmp(command, "ALLFAN") == 0);
        uint8_t ch = 0, percent = 0;
        if ((!all && !parseByte(next(), board::kChannelCount, ch)) ||
            !parseByte(next(), 100, percent) || !noMore() || (!all && ch == 0)) return error();
        if (all) {
            if (cooling_.calibrationActive()) { serial_.println(F("ERR calibration busy")); return; }
            for (uint8_t i = 0; i < board::kChannelCount; ++i) cooling_.setManual(i, percent);
        } else if (!cooling_.setManual(ch - 1, percent)) {
            serial_.println(F("ERR calibration busy")); return;
        }
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "LED") == 0 || strcmp(command, "ALLLED") == 0) {
        const bool all = (strcmp(command, "ALLLED") == 0);
        uint8_t ch = 0, r = 0, g = 0, b = 0;
        if ((!all && !parseByte(next(), board::kChannelCount, ch)) ||
            !parseByte(next(), 255, r) || !parseByte(next(), 255, g) ||
            !parseByte(next(), 255, b) || !noMore() || (!all && ch == 0)) return error();
        if (all) {
            for (uint8_t i = 0; i < board::kChannelCount; ++i) leds_.setSolid(i, r, g, b);
        } else {
            leds_.setSolid(ch - 1, r, g, b);
        }
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "OFF") == 0 || strcmp(command, "RAINBOW") == 0 ||
        strcmp(command, "BRIGHT") == 0) {
        uint8_t ch = 0, value = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0) return error();
        if (strcmp(command, "BRIGHT") == 0) {
            if (!parseByte(next(), 255, value) || !noMore()) return error();
            leds_.setBrightness(ch - 1, value);
        } else {
            if (!noMore()) return error();
            if (strcmp(command, "OFF") == 0) leds_.setOff(ch - 1);
            else leds_.setRainbow(ch - 1);
        }
        serial_.println(F("OK")); return;
    }
    if (strcmp(command, "ALLOFF") == 0) {
        if (!noMore()) return error();
        for (uint8_t i = 0; i < board::kChannelCount; ++i) leds_.setOff(i);
        serial_.println(F("OK")); return;
    }
    serial_.println(F("ERR unknown command | type HELP"));
}

void SerialConsole::printHelp() {
    serial_.println(F("Channels: 1..8, temperatures: deci-Celsius, e.g. 455 = 45.5 C"));
    serial_.println(F("PING | STATUS | HELP | LEDS"));
    serial_.println(F("TEMP <ch> <0..1250> | AUTO <ch> | ALLAUTO"));
    serial_.println(F("FAN <ch> <0..100> | ALLFAN <0..100> (manual override)"));
    serial_.println(F("CURVE? <ch> | CURVE <ch> <T1> <PWM1> ... <T5> <PWM5>"));
    serial_.println(F("CAL START <ch> | CAL GET <ch> | CAL CANCEL"));
    serial_.println(F("LED <ch> <R> <G> <B> | ALLLED <R> <G> <B>"));
    serial_.println(F("OFF <ch> | ALLOFF | RAINBOW <ch> | BRIGHT <ch> <0..255>"));
    serial_.println(F("Binary ARGB: A5 5A ch countLE16 RGB... crc16LE (CCITT-FALSE)"));
}

void SerialConsole::printStatus() {
    const uint32_t now = millis();
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        const char* mode = "auto";
        if (cooling_.mode(i) == CoolingController::Mode::Manual) mode = "manual";
        if (cooling_.mode(i) == CoolingController::Mode::Calibration) mode = "cal";
        const char* sensor = !cooling_.temperatureFresh(i, now) ? "stale" : "ok";
        serial_.print(F("CH ")); serial_.print(i + 1);
        serial_.print(F(" FAN=")); serial_.print(fans_.getPercent(i));
        serial_.print(F("% RPM=")); serial_.print(fans_.getRpm(i));
        serial_.print(F(" TEMP=")); serial_.print(cooling_.temperature(i));
        serial_.print(F(" MODE=")); serial_.print(mode);
        serial_.print(F(" SENSOR=")); serial_.println(sensor);
    }
}

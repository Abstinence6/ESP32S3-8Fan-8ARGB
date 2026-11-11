#include "SerialConsole.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

SerialConsole::SerialConsole(Stream& serial, FanController& fans, ArgbController& leds,
                             CoolingController& cooling, NetworkRgbBridge* wifi)
    : serial_(serial), fans_(fans), leds_(leds), cooling_(cooling), wifi_(wifi) {}

void SerialConsole::begin() {
    serial_.println(F("8Fan/8ARGB ready | protocol v4 | type HELP"));
}

void SerialConsole::poll() {
    // Corrupt/partial packets cannot lock out normal fan and temperature commands.
    if (rx_ != RxState::Text && millis() - rgbLastByteMs_ > 300U) resetBinary();
    while (serial_.available() > 0) {
        handleByte(static_cast<uint8_t>(serial_.read()));
    }
    // Read-only 5-second tachometer check. No change to fan duty or modes.
    if (selfTestActive_ && static_cast<uint32_t>(millis() - selfTestStartMs_) >= 5000U)
        finishSelfTest();
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
        serial_.println(F("PONG 4"));
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
    if (strcmp(command, "SELFTEST") == 0) {
        char* action = next();
        if (action) {
            for (char* c = action; *c; ++c)
                *c = static_cast<char>(toupper(static_cast<unsigned char>(*c)));
            if (strcmp(action, "CANCEL") != 0 || !noMore()) return error();
            if (!selfTestActive_) { serial_.println(F("ERR selftest not running")); return; }
            selfTestActive_ = false;
            serial_.println(F("SELFTEST_CANCELLED"));
            return;
        }
        if (selfTestActive_ || cooling_.calibrationActive()) {
            serial_.println(F("ERR selftest busy")); return;
        }
        startSelfTest(millis());
        serial_.println(F("SELFTEST_STARTED 5000"));
        return;
    }
    if (strcmp(command, "HEALTH") == 0) {
        char* requested = next();
        if (requested) {
            uint8_t ch = 0;
            if (!parseByte(requested, board::kChannelCount, ch) || ch == 0 || !noMore()) return error();
            printHealth(ch - 1);
        } else {
            for (uint8_t i = 0; i < board::kChannelCount; ++i) printHealth(i);
        }
        serial_.println(F("HEALTH_END"));
        return;
    }
    if (strcmp(command, "TEMP") == 0 || strcmp(command, "TEMP2") == 0) {
        const bool secondary = strcmp(command, "TEMP2") == 0;
        uint8_t ch = 0;
        uint16_t deciC = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 ||
            !parseU16(next(), 1250, deciC) || !noMore()) return error();
        cooling_.setTemperature(ch-1, deciC, millis(), secondary);
        serial_.println(F("OK"));
        return;
    }
    if (strcmp(command, "CURVE") == 0 || strcmp(command, "CURVE?") == 0 ||
        strcmp(command, "CURVE2") == 0 || strcmp(command, "CURVE2?") == 0) {
        const bool secondary = strncmp(command, "CURVE2", 6) == 0;
        const bool query = strchr(command, '?') != nullptr;
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0) return error();
        if (query) {
            if (!noMore()) return error();
            const auto* curve = cooling_.curve(ch-1, secondary);
            serial_.print(secondary ? F("CURVE2 ") : F("CURVE ")); serial_.print(ch);
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
        if (!cooling_.setCurve(ch-1, points, secondary)) {
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
        if (strcmp(op, "START") == 0 || strcmp(op, "SMART") == 0) {
            if (!cooling_.startCalibration(ch-1, millis(), strcmp(op, "SMART") == 0)) {
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
            if (cooling_.calibrationActive()) { serial_.println(F("ERR calibration busy")); return; }
            for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) cooling_.setAuto(ch);
            serial_.println(F("OK")); return;
        }
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 || !noMore()) return error();
        if (!cooling_.setAuto(ch-1)) { serial_.println(F("ERR calibration busy")); return; }
        serial_.println(F("OK")); return;
    }
    if (strcmp(command, "WIFI") == 0) {
        if (!wifi_) { serial_.println(F("ERR wifi not available")); return; }
        char* op = next();
        if (!op) return error();
        for (char* c=op; *c; ++c) *c=static_cast<char>(toupper(static_cast<unsigned char>(*c)));
        if (!strcmp(op,"STATUS")) {
            if (!noMore()) return error();
            wifi_->printStatus(serial_); return;
        }
        if (!strcmp(op,"OFF")) {
            if (!noMore() || !wifi_->disable()) { serial_.println(F("ERR WIFI storage")); return; }
            serial_.println(F("OK WIFI_OFF")); return;
        }
        if (!strcmp(op,"SET")) {
            char* ssid = next(); char* password = next();
            if (!ssid || !password || !noMore() || !wifi_->configure(ssid, password)) {
                serial_.println(F("ERR WIFI config")); return;
            }
            serial_.println(F("OK WIFI_SET")); return;
        }
        return error();
    }
    if (!strcmp(command, "STRIP") || !strcmp(command,"REVERSE")) {
        uint8_t ch = 0; uint16_t val = 0;
        if (!parseByte(next(),board::kChannelCount,ch) || !ch ||
            !parseU16(next(),board::kMaxArgbPixelsPerFrame,val) || !noMore()) return error();
        bool ok = false;
        if (!strcmp(command,"STRIP") && val > 0)
            ok = leds_.configureStrip(ch-1,val,leds_.isReversed(ch-1));
        else if (!strcmp(command,"REVERSE") && val <= 1)
            ok = leds_.configureStrip(ch-1,leds_.pixelCount(ch-1),val != 0);
        if (!ok) { serial_.println(F("ERR STRIP config")); return; }
        serial_.println(F("OK STRIP_SAVED")); return;
    }
    if (!strcmp(command, "RGBBUDGET")) {
        uint16_t milliamps = 0;
        if (!parseU16(next(),20000,milliamps) || !noMore() ||
            !leds_.setPowerBudget(milliamps)) return error();
        serial_.println(F("OK BUDGET_SAVED")); return;
    }
    if (!strcmp(command,"ARGBSTATUS")) {
        if (!noMore()) return error();
        serial_.print(F("ARGBSTATUS LIMIT_MA=")); serial_.print(leds_.powerBudget());
        serial_.print(F(" REQUESTED_MA=")); serial_.println(leds_.estimatedFullCurrent());
        return;
    }
    if (strcmp(command, "TYPE") == 0 || strcmp(command, "TYPE?") == 0) {
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0) return error();
        if (strcmp(command, "TYPE?") == 0) {
            if (!noMore()) return error();
            serial_.print(F("TYPE ")); serial_.print(ch);
            serial_.print(F(" SET=")); serial_.print(static_cast<unsigned>(cooling_.fanType(ch-1)));
            serial_.print(F(" DETECTED=")); serial_.print(static_cast<unsigned>(cooling_.detectedFanType(ch-1)));
            serial_.print(F(" RPM_OK=")); serial_.print(fans_.hasRpmFeedback(ch-1) ? 1 : 0);
            serial_.print(F(" DC_HW=")); serial_.println(fans_.dcHardwareAvailable() ? 1 : 0);
            return;
        }
        char* value = next();
        if (!value || !noMore()) return error();
        for (char* c = value; *c; ++c) *c = static_cast<char>(toupper(static_cast<unsigned char>(*c)));
        FanController::Type type = FanController::Type::Unknown;
        if (!strcmp(value, "AUTO") || !strcmp(value, "0")) type = FanController::Type::Auto;
        if (!strcmp(value, "2")) type = FanController::Type::TwoPin;
        if (!strcmp(value, "3")) type = FanController::Type::ThreePin;
        if (!strcmp(value, "4")) type = FanController::Type::FourPin;
        if (!cooling_.setFanType(ch-1, type)) {
            serial_.println(F("ERR AUTO unavailable without pin4 detection or invalid TYPE")); return;
        }
        serial_.println(F("OK TYPE_SAVED")); return;
    }
    if (strcmp(command, "RPM") == 0) {
        uint8_t ch = 0; uint16_t rpm = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 ||
            !parseU16(next(), 20000, rpm) || !noMore()) return error();
        if (!cooling_.setFixedRpm(ch-1, rpm)) {
            serial_.println(F("ERR RPM needs calibration")); return;
        }
        serial_.println(F("OK RPM")); return;
    }
    if (strcmp(command, "PID") == 0 || strcmp(command, "DUAL") == 0 ||
        strcmp(command, "PPR") == 0 || strcmp(command, "CRIT") == 0 ||
        strcmp(command, "STALL") == 0) {
        uint8_t ch = 0; uint16_t value = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 ||
            !parseU16(next(), 3000, value) || !noMore()) return error();
        bool ok = false;
        if (strcmp(command, "PID") == 0 && value <= 1) ok = cooling_.setClosedLoop(ch-1, value != 0);
        else if (strcmp(command, "DUAL") == 0 && value <= 1) ok = cooling_.setDualSensor(ch-1, value != 0);
        else if (strcmp(command, "PPR") == 0 && value <= 12) ok = cooling_.setPulsesPerRevolution(ch-1, value);
        else if (strcmp(command, "CRIT") == 0 && value <= 120) ok = cooling_.setCriticalTemperature(ch-1, value);
        else if (strcmp(command, "STALL") == 0) ok = cooling_.setStallThreshold(ch-1, value);
        if (!ok) { serial_.println(F("ERR config unavailable or invalid")); return; }
        serial_.println(F("OK CONFIG")); return;
    }
    if (strcmp(command, "CONFIG") == 0) {
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 || !noMore()) return error();
        --ch;
        serial_.print(F("CONFIG ")); serial_.print(ch+1);
        serial_.print(F(" PPR=")); serial_.print(cooling_.pulsesPerRevolution(ch));
        serial_.print(F(" CRIT=")); serial_.print(cooling_.criticalTemperature(ch));
        serial_.print(F(" STALL=")); serial_.print(cooling_.stallThreshold(ch));
        serial_.print(F(" PID=")); serial_.print(cooling_.closedLoop(ch) ? 1 : 0);
        serial_.print(F(" DUAL=")); serial_.print(cooling_.dualSensor(ch) ? 1 : 0);
        serial_.print(F(" START=")); serial_.print(cooling_.minStartPwm(ch));
        serial_.print(F(" RUN=")); serial_.print(cooling_.minRunPwm(ch));
        serial_.print(F(" TYPE=")); serial_.print(static_cast<unsigned>(cooling_.fanType(ch)));
        serial_.print(F(" DETECTED=")); serial_.println(static_cast<unsigned>(cooling_.detectedFanType(ch)));
        return;
    }
    if (strcmp(command, "FAULTS") == 0) {
        if (!noMore()) return error();
        for (uint8_t i=0; i<cooling_.faultCount(); ++i) {
            const auto f = cooling_.faultAt(i);
            serial_.print(F("EVENT ")); serial_.print(f.channel);
            serial_.print(F(" ")); serial_.print(f.code);
            serial_.print(F(" ")); serial_.println(f.uptimeSeconds);
        }
        serial_.println(F("EVENT_END")); return;
    }
    if (strcmp(command, "CLEARFAULT") == 0) {
        uint8_t ch = 0;
        if (!parseByte(next(), board::kChannelCount, ch) || ch == 0 || !noMore()) return error();
        if (!cooling_.clearFault(ch-1)) return error();
        serial_.println(F("OK")); return;
    }
    if (strcmp(command, "CLEARHISTORY") == 0) {
        if (!noMore() || !cooling_.clearHistory()) return error();
        serial_.println(F("OK")); return;
    }
    if (strcmp(command, "FAN") == 0 || strcmp(command, "ALLFAN") == 0) {
        const bool all = (strcmp(command, "ALLFAN") == 0);
        uint8_t ch = 0, percent = 0;
        if ((!all && !parseByte(next(), board::kChannelCount, ch)) ||
            !parseByte(next(), 100, percent) || !noMore() || (!all && ch == 0)) return error();
        if (all) {
            if (cooling_.calibrationActive()) { serial_.println(F("ERR calibration busy")); return; }
            // Preflight every channel before changing any: ALLFAN is atomic.
            for (uint8_t i = 0; i < board::kChannelCount; ++i) {
                if (!cooling_.canSetManual(i, percent)) {
                    serial_.println(F("ERR fan control blocked")); return;
                }
            }
            for (uint8_t i = 0; i < board::kChannelCount; ++i) cooling_.setManual(i, percent);
        } else if (!cooling_.setManual(ch - 1, percent)) {
            serial_.println(F("ERR fan control blocked")); return;
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
    serial_.println(F("PING | STATUS | HEALTH [ch] | SELFTEST [CANCEL] | HELP | LEDS"));
    serial_.println(F("TEMP <ch> <0..1250> | AUTO <ch> | ALLAUTO"));
    serial_.println(F("FAN <ch> <0..100> | ALLFAN <0..100> (manual override)"));
    serial_.println(F("CURVE? <ch> | CURVE <ch> <T1> <PWM1> ... <T5> <PWM5>"));
    serial_.println(F("CAL START <ch> | CAL SMART <ch> | CAL GET <ch> | CAL CANCEL"));
    serial_.println(F("TEMP2 / CURVE2 / CURVE2? for second thermal source; DUAL <ch> 0|1"));
    serial_.println(F("PID <ch> 0|1 | RPM <ch> <rpm> (requires calibration)"));
    serial_.println(F("PPR <ch> 1..12 | CRIT <ch> 40..120 | STALL <ch> 0..3000"));
    serial_.println(F("TYPE? <ch> | TYPE <ch> 2|3|4 (matches physical jumper; no auto)"));
    serial_.println(F("CONFIG <ch> | FAULTS | CLEARFAULT <ch> | CLEARHISTORY"));
    serial_.println(F("LED <ch> <R> <G> <B> | ALLLED <R> <G> <B>"));
    serial_.println(F("OFF <ch> | ALLOFF | RAINBOW <ch> | BRIGHT <ch> <0..255>"));
    serial_.println(F("WIFI SET <ssid> <pass> | WIFI STATUS | WIFI OFF (no spaces in SSID/pass)"));
    serial_.println(F("STRIP <ch> 1..170 | REVERSE <ch> 0|1 | RGBBUDGET <100..20000> | ARGBSTATUS"));
    serial_.println(F("Binary ARGB: A5 5A ch countLE16 RGB... crc16LE (CCITT-FALSE)"));
}

void SerialConsole::startSelfTest(uint32_t nowMs) {
    selfTestStartMs_ = nowMs;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        selfTestBasePulses_[ch] = fans_.tachPulseCount(ch);
        selfTestBasePwm_[ch] = fans_.getPercent(ch);
        selfTestBaseType_[ch] = fans_.configuredType(ch);
    }
    selfTestActive_ = true;
}

void SerialConsole::finishSelfTest() {
    selfTestActive_ = false;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint32_t count = fans_.tachPulseCount(ch) - selfTestBasePulses_[ch];
        const uint8_t pwm = fans_.getPercent(ch);
        const auto type = fans_.configuredType(ch);
        const char* result = "NO_TACH";
        if (!fans_.hasRpmFeedback(ch)) result = "NA";
        else if (type != selfTestBaseType_[ch] || pwm != selfTestBasePwm_[ch])
            result = "INCONCLUSIVE";
        else if (count >= 3U) result = "OK";
        serial_.print(F("SELFTEST ")); serial_.print(ch + 1);
        serial_.print(F(" RESULT=")); serial_.print(result);
        serial_.print(F(" PULSES=")); serial_.print(count);
        serial_.print(F(" PWM=")); serial_.println(pwm);
    }
    serial_.println(F("SELFTEST_END"));
}

void SerialConsole::printHealth(uint8_t ch) {
    const uint32_t now = millis();
    const auto mode = cooling_.mode(ch);
    const char* modeLabel = mode == CoolingController::Mode::Manual ? "manual" :
                            mode == CoolingController::Mode::Calibration ? "cal" :
                            mode == CoolingController::Mode::FixedRpm ? "rpm" : "auto";
    const char* tachLabel = !fans_.hasRpmFeedback(ch) ? "na" :
                            fans_.tachObserved(ch) ? "seen" : "unseen";
    const bool sensorFresh = cooling_.temperatureFresh(ch, now) &&
        (!cooling_.dualSensor(ch) || cooling_.temperatureFresh(ch, now, true));
    serial_.print(F("HEALTH ")); serial_.print(ch + 1);
    serial_.print(F(" TYPE=")); serial_.print(static_cast<unsigned>(cooling_.fanType(ch)));
    serial_.print(F(" DETECTED=255")); // no pin-4 sense; no physical autodetection
    serial_.print(F(" PWM=")); serial_.print(fans_.getPercent(ch));
    serial_.print(F(" RPM=")); serial_.print(fans_.getRpm(ch));
    serial_.print(F(" TACH=")); serial_.print(tachLabel);
    serial_.print(F(" SENSOR=")); serial_.print(sensorFresh ? F("ok") : F("stale"));
    serial_.print(F(" FAULT=")); serial_.print(cooling_.faulted(ch) ? 1 : 0);
    serial_.print(F(" DC_READY=")); serial_.print(fans_.dcHardwareAvailable() ? 1 : 0);
    serial_.print(F(" MODE=")); serial_.println(modeLabel);
}

void SerialConsole::printStatus() {
    const uint32_t now = millis();
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        const char* mode = "auto";
        if (cooling_.mode(i) == CoolingController::Mode::Manual) mode = "manual";
        if (cooling_.mode(i) == CoolingController::Mode::Calibration) mode = "cal";
        if (cooling_.mode(i) == CoolingController::Mode::FixedRpm) mode = "rpm";
        const char* sensor = !cooling_.temperatureFresh(i, now) ? "stale" : "ok";
        serial_.print(F("CH ")); serial_.print(i + 1);
        serial_.print(F(" FAN=")); serial_.print(fans_.getPercent(i));
        serial_.print(F("% RPM=")); serial_.print(fans_.getRpm(i));
        serial_.print(F(" TEMP=")); serial_.print(cooling_.temperature(i));
        serial_.print(F(" MODE=")); serial_.print(mode);
        serial_.print(F(" SENSOR=")); serial_.print(sensor);
        serial_.print(F(" TARGET=")); serial_.print(cooling_.rpmTarget(i));
        serial_.print(F(" FAULT=")); serial_.print(cooling_.faulted(i) ? 1 : 0);
        serial_.print(F(" TYPE=")); serial_.print(static_cast<unsigned>(cooling_.fanType(i)));
        serial_.print(F(" RPM_OK=")); serial_.print(fans_.hasRpmFeedback(i) ? 1 : 0);
        serial_.println("");
    }
}

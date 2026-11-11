#include "CoolingController.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

namespace {
constexpr uint32_t kMagic = 0x46414E53UL; // "FANS"
constexpr uint8_t kVersion = 1;
constexpr uint32_t kControlIntervalMs = 250;
constexpr uint32_t kCalWarmupMs = 1200;
constexpr uint32_t kCalPointMs = 3500;

void fanKey(uint8_t ch, char* key, size_t size) {
    snprintf(key, size, "fan%u", static_cast<unsigned>(ch + 1));
}
}

CoolingController::CoolingController(FanController& fans, Stream& events)
    : fans_(fans), events_(events) {}

uint32_t CoolingController::calculateChecksum(const StoredFan& fan) {
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&fan);
    const size_t count = offsetof(StoredFan, checksum);
    uint32_t hash = 2166136261UL;
    for (size_t i = 0; i < count; ++i) {
        hash ^= bytes[i];
        hash *= 16777619UL;
    }
    return hash;
}

void CoolingController::makeDefault(StoredFan& fan) {
    memset(&fan, 0, sizeof(fan));
    fan.magic = kMagic;
    fan.version = kVersion;
    const CurvePoint defaults[kCurvePoints] = {
        {25, 25}, {35, 35}, {50, 55}, {65, 80}, {80, 100}
    };
    memcpy(fan.curve, defaults, sizeof(defaults));
    fan.checksum = calculateChecksum(fan);
}

bool CoolingController::readFan(uint8_t ch, StoredFan& fan) {
    char key[8];
    fanKey(ch, key, sizeof(key));
    if (storage_.getBytesLength(key) != sizeof(fan)) return false;
    if (storage_.getBytes(key, &fan, sizeof(fan)) != sizeof(fan)) return false;
    return fan.magic == kMagic && fan.version == kVersion &&
           fan.checksum == calculateChecksum(fan) && validCurve(fan.curve) &&
           fan.calibrated <= 1;
}

bool CoolingController::writeFan(uint8_t ch, StoredFan& newValue) {
    if (ch >= board::kChannelCount) return false;
    newValue.magic = kMagic;
    newValue.version = kVersion;
    newValue.checksum = calculateChecksum(newValue);
    char key[8];
    fanKey(ch, key, sizeof(key));
    if (storage_.putBytes(key, &newValue, sizeof(newValue)) != sizeof(newValue)) return false;
    saved_[ch] = newValue;
    return true;
}

bool CoolingController::begin() {
    if (!storage_.begin("cooling-v1", false)) return false;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        if (!readFan(ch, saved_[ch])) makeDefault(saved_[ch]);
        fanMode_[ch] = Mode::Auto;
        fans_.setPercent(ch, 100); // on boot, no PC temperatures: full speed
    }
    lastControlMs_ = millis();
    return true;
}

bool CoolingController::validCurve(const CurvePoint* points) {
    if (!points) return false;
    for (uint8_t i = 0; i < kCurvePoints; ++i) {
        if (points[i].tempC > 125 || points[i].pwm > 100) return false;
        if (i > 0 && (points[i].tempC <= points[i-1].tempC ||
                      points[i].pwm < points[i-1].pwm)) return false;
    }
    return true;
}

uint8_t CoolingController::interpolate(const CurvePoint* points, uint16_t tempDeciC) {
    if (tempDeciC <= static_cast<uint16_t>(points[0].tempC) * 10U) return points[0].pwm;
    for (uint8_t i = 1; i < kCurvePoints; ++i) {
        const uint16_t rightTemp = static_cast<uint16_t>(points[i].tempC) * 10U;
        if (tempDeciC > rightTemp) continue;
        const uint16_t leftTemp = static_cast<uint16_t>(points[i-1].tempC) * 10U;
        const uint16_t deltaTemp = rightTemp - leftTemp;
        const uint16_t deltaPwm = points[i].pwm - points[i-1].pwm;
        return static_cast<uint8_t>(points[i-1].pwm +
            (static_cast<uint32_t>(tempDeciC - leftTemp) * deltaPwm + deltaTemp / 2U) / deltaTemp);
    }
    return points[kCurvePoints-1].pwm;
}

bool CoolingController::setCurve(uint8_t ch, const CurvePoint* points) {
    if (ch >= board::kChannelCount || !validCurve(points)) return false;
    StoredFan candidate = saved_[ch];
    memcpy(candidate.curve, points, sizeof(candidate.curve));
    return writeFan(ch, candidate);
}

const CoolingController::CurvePoint* CoolingController::curve(uint8_t ch) const {
    return ch < board::kChannelCount ? saved_[ch].curve : nullptr;
}

bool CoolingController::setManual(uint8_t ch, uint8_t pwm) {
    if (ch >= board::kChannelCount || pwm > 100 || activeCalibration_ == ch) return false;
    fanMode_[ch] = Mode::Manual;
    manualPwm_[ch] = pwm;
    fans_.setPercent(ch, pwm);
    return true;
}

bool CoolingController::setAuto(uint8_t ch) {
    if (ch >= board::kChannelCount || activeCalibration_ == ch) return false;
    fanMode_[ch] = Mode::Auto;
    // Re-enable full-speed fail-safe immediately if the PC isn't connected.
    if (!temperatureFresh(ch, millis())) fans_.setPercent(ch, 100);
    return true;
}

void CoolingController::setTemperature(uint8_t ch, uint16_t deciC, uint32_t nowMs) {
    if (ch >= board::kChannelCount || deciC > 1250) return;
    lastTemp_[ch] = deciC;
    lastTempMs_[ch] = nowMs;
    gotTemp_[ch] = true;
}

bool CoolingController::temperatureFresh(uint8_t ch, uint32_t nowMs) const {
    return ch < board::kChannelCount && gotTemp_[ch] &&
           (nowMs - lastTempMs_[ch] <= kSensorTimeoutMs);
}

bool CoolingController::startCalibration(uint8_t ch, uint32_t nowMs) {
    if (ch >= board::kChannelCount || calibrationActive()) return false;
    previousCalibrationMode_ = fanMode_[ch];
    activeCalibration_ = static_cast<int8_t>(ch);
    calibrationStep_ = 0;
    warmup_ = true;
    memset(workingRpm_, 0, sizeof(workingRpm_));
    stepStartMs_ = nowMs;
    fans_.setPercent(ch, 100); // spin up before sweeping from 0 to 100
    events_.print(F("CAL_STARTED ")); events_.println(ch + 1);
    return true;
}

bool CoolingController::cancelCalibration() {
    if (!calibrationActive()) return false;
    endCalibration(true, false);
    return true;
}

void CoolingController::reportPoint(uint8_t ch, uint8_t step, uint16_t rpm) {
    events_.print(F("CAL_POINT ")); events_.print(ch + 1);
    events_.print(F(" ")); events_.print(step * 5);
    events_.print(F(" ")); events_.println(rpm);
}

void CoolingController::endCalibration(bool cancelled, bool validRpm) {
    const uint8_t ch = static_cast<uint8_t>(activeCalibration_);
    activeCalibration_ = -1;
    fans_.setPercent(ch, 100); // safe before automatic regulation resumes
    fanMode_[ch] = previousCalibrationMode_;
    if (fanMode_[ch] == Mode::Manual) fans_.setPercent(ch, manualPwm_[ch]);
    if (cancelled) {
        events_.print(F("CAL_CANCELLED ")); events_.println(ch + 1);
        return;
    }
    if (!validRpm) {
        events_.print(F("CAL_ERROR ")); events_.print(ch + 1);
        events_.println(F(" NO_TACH"));
        return;
    }
    StoredFan candidate = saved_[ch];
    memcpy(candidate.rpm, workingRpm_, sizeof(workingRpm_));
    candidate.calibrated = 1;
    if (writeFan(ch, candidate)) {
        events_.print(F("CAL_SAVED ")); events_.println(ch + 1);
    } else {
        events_.print(F("CAL_ERROR ")); events_.print(ch + 1);
        events_.println(F(" STORAGE"));
    }
}

void CoolingController::update(uint32_t nowMs) {
    if (activeCalibration_ >= 0) {
        const uint8_t ch = static_cast<uint8_t>(activeCalibration_);
        const uint32_t elapsed = nowMs - stepStartMs_;
        if (warmup_) {
            if (elapsed >= kCalWarmupMs) {
                warmup_ = false;
                stepStartMs_ = nowMs;
                fans_.setPercent(ch, 0);
            }
        } else if (elapsed >= kCalPointMs) {
            uint32_t rpm = fans_.getRpm(ch);
            if (rpm > 65535) rpm = 65535;
            workingRpm_[calibrationStep_] = static_cast<uint16_t>(rpm);
            reportPoint(ch, calibrationStep_, workingRpm_[calibrationStep_]);
            if (++calibrationStep_ >= kCalibrationPoints) {
                bool tachWorking = false;
                for (uint8_t i = 0; i < kCalibrationPoints; ++i) {
                    if (workingRpm_[i] > 0) tachWorking = true;
                }
                endCalibration(false, tachWorking);
            } else {
                fans_.setPercent(ch, calibrationStep_ * 5);
                stepStartMs_ = nowMs;
            }
        }
    }

    if (nowMs - lastControlMs_ < kControlIntervalMs) return;
    lastControlMs_ = nowMs;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        if (activeCalibration_ == ch) continue;
        if (fanMode_[ch] == Mode::Manual) continue;
        if (!temperatureFresh(ch, nowMs)) {
            // Connection loss, absent temperature or PC crash => full speed immediately.
            fans_.setPercent(ch, 100);
            continue;
        }
        const uint8_t target = interpolate(saved_[ch].curve, lastTemp_[ch]);
        const uint8_t current = fans_.getPercent(ch);
        if (target > current) {
            const uint8_t step = static_cast<uint8_t>(target - current);
            fans_.setPercent(ch, static_cast<uint8_t>(current + (step > 20 ? 20 : step)));
        } else if (target < current) {
            const uint8_t step = static_cast<uint8_t>(current - target);
            fans_.setPercent(ch, static_cast<uint8_t>(current - (step > 2 ? 2 : step)));
        }
    }
}

bool CoolingController::hasCalibration(uint8_t ch) const {
    return ch < board::kChannelCount && saved_[ch].calibrated != 0;
}
uint16_t CoolingController::rpmAt(uint8_t ch, uint8_t step) const {
    if (ch >= board::kChannelCount || step >= kCalibrationPoints) return 0;
    return saved_[ch].rpm[step];
}
uint8_t CoolingController::appliedPwm(uint8_t ch) const { return fans_.getPercent(ch); }
uint16_t CoolingController::temperature(uint8_t ch) const { return ch < board::kChannelCount ? lastTemp_[ch] : 0; }
CoolingController::Mode CoolingController::mode(uint8_t ch) const {
    if (activeCalibration_ == ch) return Mode::Calibration;
    return ch < board::kChannelCount ? fanMode_[ch] : Mode::Auto;
}

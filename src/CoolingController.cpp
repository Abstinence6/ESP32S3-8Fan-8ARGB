#include "CoolingController.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

namespace {
constexpr uint32_t kMagic = 0x46414E53UL; // "FANS"
constexpr uint32_t kFaultMagic = 0x45564E54UL; // "EVNT"
constexpr uint8_t kVersion = 4;
constexpr uint32_t kControlIntervalMs = 250;
constexpr uint32_t kCalWarmupMs = 1200;
constexpr uint32_t kCalPointMs = 3500;
constexpr uint32_t kStallDelayMs = 4000;
constexpr uint32_t kRestartDurationMs = 2200;

void fanKey(uint8_t ch, char* key, size_t size) {
    snprintf(key, size, "fan%u", static_cast<unsigned>(ch + 1));
}
uint8_t clampPercent(int32_t value) {
    return static_cast<uint8_t>(value < 0 ? 0 : value > 100 ? 100 : value);
}
}

CoolingController::CoolingController(FanController& fans, Stream& events)
    : fans_(fans), events_(events) {}

uint32_t CoolingController::checksum(const void* ptr, size_t count) {
    const uint8_t* bytes = static_cast<const uint8_t*>(ptr);
    uint32_t hash = 2166136261UL;
    for (size_t i = 0; i < count; ++i) {
        hash ^= bytes[i];
        hash *= 16777619UL;
    }
    return hash;
}
uint32_t CoolingController::calculateChecksum(const StoredFan& fan) {
    return checksum(&fan, offsetof(StoredFan, checksum));
}

void CoolingController::makeDefault(StoredFan& fan) {
    memset(&fan, 0, sizeof(fan));
    fan.magic = kMagic;
    fan.version = kVersion;
    const CurvePoint defaults[kCurvePoints] = {
        {25, 25}, {35, 35}, {50, 55}, {65, 80}, {80, 100}
    };
    memcpy(fan.curve, defaults, sizeof(defaults));
    memcpy(fan.secondCurve, defaults, sizeof(defaults));
    fan.minStart = 30;
    fan.minRun = 20;
    fan.ppr = board::kTachPulsesPerRevolution;
    fan.criticalC = 85;
    fan.stallRpm = 120;
    fan.fanType = board::kDefaultFanType; // new profiles default to 3-pin

    fan.checksum = calculateChecksum(fan);
}

bool CoolingController::readFan(uint8_t ch, StoredFan& fan) {
    char key[8];
    fanKey(ch, key, sizeof(key));
    const size_t size = storage_.getBytesLength(key);
    if (size == sizeof(StoredFan)) {
        if (storage_.getBytes(key, &fan, sizeof(fan)) != sizeof(fan)) return false;
        if (fan.magic != kMagic || (fan.version != 3 && fan.version != kVersion) ||
            fan.checksum != calculateChecksum(fan) || !validCurve(fan.curve) ||
            !validCurve(fan.secondCurve) || fan.calibrated > 1 ||
            fan.ppr < 1 || fan.ppr > 12 || fan.criticalC < 40 || fan.criticalC > 120 ||
            fan.minStart > 100 || fan.minRun > 100 || fan.stallRpm > 3000 ||
            fan.pidEnabled > 1 || fan.dualEnabled > 1 ||
            (fan.fanType != 0 && fan.fanType != 2 && fan.fanType != 3 && fan.fanType != 4))
            return false;
        if (fan.version == kVersion) return fan.fanType == 2 || fan.fanType == 3;
        // v3 -> v4: physical drive topology changed; old PWM-to-RPM samples
        // cannot be reused even if the stored connector type was 3-pin.
        const uint8_t target = fan.fanType == 2 ? 2 : 3;
        fan.fanType = target;
    } else if (size == sizeof(StoredFanV2)) {
        StoredFanV2 old = {};
        if (storage_.getBytes(key, &old, sizeof(old)) != sizeof(old) ||
            old.magic != kMagic || old.version != 2 ||
            old.checksum != checksum(&old, offsetof(StoredFanV2, checksum)) ||
            !validCurve(old.curve) || !validCurve(old.secondCurve) ||
            old.calibrated > 1 || old.ppr < 1 || old.ppr > 12) return false;
        makeDefault(fan);
        memcpy(fan.curve, old.curve, sizeof(fan.curve));
        memcpy(fan.secondCurve, old.secondCurve, sizeof(fan.secondCurve));
        fan.ppr = old.ppr;
        fan.criticalC = old.criticalC >= 40 && old.criticalC <= 120 ? old.criticalC : 85;
        fan.stallRpm = old.stallRpm <= 3000 ? old.stallRpm : 120;
        fan.dualEnabled = old.dualEnabled <= 1 ? old.dualEnabled : 0;
    } else if (size == sizeof(LegacyFan)) {
        LegacyFan old = {};
        if (storage_.getBytes(key, &old, sizeof(old)) != sizeof(old) ||
            old.magic != kMagic || old.version != 1 || old.calibrated > 1 ||
            old.checksum != checksum(&old, offsetof(LegacyFan, checksum)) ||
            !validCurve(old.curve)) return false;
        makeDefault(fan);
        memcpy(fan.curve, old.curve, sizeof(old.curve));
    } else {
        return false;
    }
    fan.calibrated = 0;
    fan.pidEnabled = 0;
    fan.minStart = 30;
    fan.minRun = 20;
    memset(fan.rpm, 0, sizeof(fan.rpm));
    // Durable migration; never activate an obsolete calibrated profile on a
    // new power stage if storage fails. In-memory state remains safe.
    if (!writeFan(ch, fan)) return false;
    return true;
}

bool CoolingController::writeFan(uint8_t ch, StoredFan& value) {
    if (ch >= board::kChannelCount) return false;
    value.magic = kMagic;
    value.version = kVersion;
    value.checksum = calculateChecksum(value);
    char key[8];
    fanKey(ch, key, sizeof(key));
    if (storage_.putBytes(key, &value, sizeof(value)) != sizeof(value)) return false;
    saved_[ch] = value;
    return true;
}

bool CoolingController::begin() {
    if (!storage_.begin("cooling-v1", false)) return false;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        if (!readFan(ch, saved_[ch])) makeDefault(saved_[ch]);
        fans_.setPulsesPerRevolution(ch, saved_[ch].ppr);
        // Physical jumper selection cannot be changed by software. Persisted
        // type represents the user's confirmed PCB wiring only.
        if (!fans_.setType(ch, static_cast<FanController::Type>(saved_[ch].fanType)))
            fans_.setType(ch, FanController::Type::ThreePin);
        fanMode_[ch] = Mode::Auto;
        fans_.setPercent(ch, 100); // Safe until real PC temperature telemetry arrives.
        spinupUntilMs_[ch] = millis() + 4000U;
    }
    FaultStore savedHistory = {};
    if (storage_.getBytesLength("faults") == sizeof(savedHistory) &&
        storage_.getBytes("faults", &savedHistory, sizeof(savedHistory)) == sizeof(savedHistory) &&
        savedHistory.magic == kFaultMagic && savedHistory.size <= kFaultCapacity &&
        savedHistory.checksum == checksum(&savedHistory, offsetof(FaultStore, checksum))) {
        faultCount_ = savedHistory.size;
        memcpy(faultHistory_, savedHistory.entries, sizeof(faultHistory_));
    }
    lastControlMs_ = millis();
    return true;
}

bool CoolingController::validCurve(const CurvePoint* points) {
    if (!points) return false;
    for (uint8_t i = 0; i < kCurvePoints; ++i) {
        if (points[i].tempC > 125 || points[i].pwm > 100) return false;
        if (i && (points[i].tempC <= points[i-1].tempC ||
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

bool CoolingController::setCurve(uint8_t ch, const CurvePoint* points, bool secondary) {
    if (ch >= board::kChannelCount || !validCurve(points)) return false;
    StoredFan value = saved_[ch];
    memcpy(secondary ? value.secondCurve : value.curve, points, sizeof(value.curve));
    return writeFan(ch, value);
}
const CoolingController::CurvePoint* CoolingController::curve(uint8_t ch, bool secondary) const {
    if (ch >= board::kChannelCount) return nullptr;
    return secondary ? saved_[ch].secondCurve : saved_[ch].curve;
}

bool CoolingController::setFanType(uint8_t ch, FanController::Type type) {
    if (ch >= board::kChannelCount || activeCalibration_ == ch) return false;
    if (type != FanController::Type::TwoPin && type != FanController::Type::ThreePin) return false;
    const auto oldType = fans_.configuredType(ch);
    if (!fans_.setType(ch, type)) return false;
    StoredFan candidate = saved_[ch];
    if (candidate.fanType != static_cast<uint8_t>(type)) {
        // Calibrations are motor/driver specific, never reuse across fan types.
        candidate.calibrated = 0;
        candidate.pidEnabled = 0;
        candidate.minStart = 30;
        candidate.minRun = 20;
        memset(candidate.rpm, 0, sizeof(candidate.rpm));
    }
    candidate.fanType = static_cast<uint8_t>(type);
    if (!writeFan(ch, candidate)) {
        fans_.setType(ch, oldType);
        return false;
    }
    fanMode_[ch] = Mode::Auto;
    fixedRpm_[ch] = 0;
    integral_[ch] = 0;
    restartAttempts_[ch] = 0;
    return true;
}
FanController::Type CoolingController::fanType(uint8_t ch) const {
    return fans_.configuredType(ch);
}
FanController::Type CoolingController::detectedFanType(uint8_t ch) const {
    return fans_.detectedType(ch);
}

bool CoolingController::canSetManual(uint8_t ch, uint8_t pwm) const {
    return ch < board::kChannelCount && pwm <= 100 && activeCalibration_ != ch &&
           fans_.canControl(ch, pwm);
}

bool CoolingController::setManual(uint8_t ch, uint8_t pwm) {
    if (!canSetManual(ch, pwm)) return false;
    fanMode_[ch] = Mode::Manual;
    manualPwm_[ch] = pwm;
    integral_[ch] = 0;
    fans_.setPercent(ch, pwm);
    return true;
}
bool CoolingController::setFixedRpm(uint8_t ch, uint16_t rpm) {
    if (ch >= board::kChannelCount || activeCalibration_ == ch ||
        !saved_[ch].calibrated || !fans_.tachReliable(ch) ||
        !fans_.canControl(ch, 50) || rpm > 20000) return false;
    fanMode_[ch] = Mode::FixedRpm;
    fixedRpm_[ch] = rpm;
    integral_[ch] = 0;
    return true;
}
bool CoolingController::setAuto(uint8_t ch) {
    if (ch >= board::kChannelCount || activeCalibration_ == ch) return false;
    fanMode_[ch] = Mode::Auto;
    integral_[ch] = 0;
    if (!freshPair(ch, millis())) fans_.setPercent(ch, 100);
    return true;
}

void CoolingController::setTemperature(uint8_t ch, uint16_t deciC, uint32_t nowMs, bool secondary) {
    if (ch >= board::kChannelCount || deciC > 1250) return;
    uint16_t& raw = secondary ? lastTemp2_[ch] : lastTemp_[ch];
    uint16_t& filtered = secondary ? filteredTemp2_[ch] : filteredTemp_[ch];
    uint32_t& stamp = secondary ? lastTemp2Ms_[ch] : lastTempMs_[ch];
    bool& valid = secondary ? gotTemp2_[ch] : gotTemp_[ch];
    // EMA, alpha=0.25, with immediate emergency checks on the unfiltered value.
    filtered = valid ? static_cast<uint16_t>((3U * filtered + deciC + 2U) / 4U) : deciC;
    raw = deciC;
    stamp = nowMs;
    valid = true;
    timeoutRecorded_[ch] = false;
}
bool CoolingController::temperatureFresh(uint8_t ch, uint32_t nowMs, bool secondary) const {
    if (ch >= board::kChannelCount) return false;
    const bool valid = secondary ? gotTemp2_[ch] : gotTemp_[ch];
    const uint32_t stamp = secondary ? lastTemp2Ms_[ch] : lastTempMs_[ch];
    return valid && nowMs - stamp <= kSensorTimeoutMs;
}
bool CoolingController::freshPair(uint8_t ch, uint32_t nowMs) const {
    return temperatureFresh(ch, nowMs) &&
        (!saved_[ch].dualEnabled || temperatureFresh(ch, nowMs, true));
}
bool CoolingController::overTemperature(uint8_t ch) const {
    return gotTemp_[ch] && (lastTemp_[ch] >= saved_[ch].criticalC * 10U ||
        (saved_[ch].dualEnabled && gotTemp2_[ch] && lastTemp2_[ch] >= saved_[ch].criticalC * 10U));
}

bool CoolingController::startCalibration(uint8_t ch, uint32_t nowMs, bool smart) {
    if (ch >= board::kChannelCount || calibrationActive() || faultLatched_[ch] ||
        !fans_.tachReliable(ch) || !fans_.canControl(ch, 50) ||
        !freshPair(ch, nowMs) || overTemperature(ch)) return false;
    previousCalibrationMode_ = fanMode_[ch];
    activeCalibration_ = static_cast<int8_t>(ch);
    calibrationStep_ = 0;
    smartCalibration_ = smart;
    downward_ = false;
    calRetry_ = 0;
    calBadSamples_ = 0;
    warmup_ = true;
    memset(workingRpm_, 0, sizeof(workingRpm_));
    memset(downRpm_, 0, sizeof(downRpm_));
    stepStartMs_ = nowMs;
    fans_.setPercent(ch, 100);
    spinupUntilMs_[ch] = nowMs + kCalWarmupMs;
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
    fanMode_[ch] = previousCalibrationMode_;
    integral_[ch] = 0;
    fans_.setPercent(ch, 100);
    spinupUntilMs_[ch] = millis() + 3000U;
    if (cancelled) {
        events_.print(F("CAL_CANCELLED ")); events_.println(ch + 1);
        return;
    }
    if (!validRpm) {
        events_.print(F("CAL_ERROR ")); events_.print(ch + 1);
        events_.println(F(" UNRELIABLE_TACH"));
        return;
    }
    StoredFan candidate = saved_[ch];
    if (smartCalibration_) {
        // Average ascending/descending measurements to reduce hysteresis noise.
        uint8_t start = 100, run = 100;
        for (uint8_t i = 0; i < kCalibrationPoints; ++i) {
            if (workingRpm_[i] >= 300 && start == 100) start = i * 5;
            if (downRpm_[i] >= 300 && run == 100) run = i * 5;
            workingRpm_[i] = static_cast<uint16_t>(
                (static_cast<uint32_t>(workingRpm_[i]) + downRpm_[i] + 1) / 2U);
        }
        candidate.minStart = start;
        candidate.minRun = run;
    }
    memcpy(candidate.rpm, workingRpm_, sizeof(workingRpm_));
    candidate.calibrated = 1;
    if (writeFan(ch, candidate)) {
        events_.print(F("CAL_SAVED ")); events_.println(ch + 1);
        events_.print(F("CAL_MIN ")); events_.print(ch + 1);
        events_.print(F(" ")); events_.print(candidate.minStart);
        events_.print(F(" ")); events_.println(candidate.minRun);
    } else {
        events_.print(F("CAL_ERROR ")); events_.print(ch + 1);
        events_.println(F(" STORAGE"));
    }
}

uint16_t CoolingController::targetRpmFromPwm(uint8_t ch, uint8_t pwm) const {
    if (ch >= board::kChannelCount || !saved_[ch].calibrated) return 0;
    const uint8_t left = pwm / 5;
    const uint8_t right = left >= 20 ? 20 : left + 1;
    const int32_t a = saved_[ch].rpm[left];
    const int32_t b = saved_[ch].rpm[right];
    const int32_t target = a + (b - a) * (pwm % 5) / 5;
    return static_cast<uint16_t>(target < 0 ? 0 : target);
}
uint8_t CoolingController::pwmFromRpm(uint8_t ch, uint16_t rpm) const {
    if (rpm == 0) return 0;
    for (uint8_t i = 1; i < kCalibrationPoints; ++i) {
        if (saved_[ch].rpm[i] >= rpm && saved_[ch].rpm[i] > saved_[ch].rpm[i-1]) {
            const uint32_t below = saved_[ch].rpm[i-1];
            const uint32_t span = saved_[ch].rpm[i] - below;
            const uint32_t increment = rpm > below ? (rpm - below) * 5U / span : 0;
            return static_cast<uint8_t>((i - 1) * 5 + (increment > 5 ? 5 : increment));
        }
    }
    return 100;
}
uint8_t CoolingController::controlPwm(uint8_t ch, uint8_t feedforward, uint16_t targetRpm, uint32_t nowMs) {
    if (targetRpm == 0 || !saved_[ch].calibrated) return feedforward;
    if (!fans_.tachReliable(ch)) {
        // No fresh measurement: avoid integrating a fabricated zero-RPM error.
        integral_[ch] = 0;
        lastError_[ch] = 0;
        return feedforward;
    }
    const uint32_t elapsed = nowMs - lastPidMs_[ch];
    if (elapsed < 1000U) return fans_.getPercent(ch);
    lastPidMs_[ch] = nowMs;
    const int32_t error = static_cast<int32_t>(targetRpm) - static_cast<int32_t>(fans_.getRpm(ch));
    const float seconds = static_cast<float>(elapsed) / 1000.0f;
    integral_[ch] += static_cast<float>(error) * 0.003f * seconds;
    if (integral_[ch] > 30) integral_[ch] = 30;
    if (integral_[ch] < -30) integral_[ch] = -30;
    const float derivative = static_cast<float>(error - lastError_[ch]) / seconds;
    lastError_[ch] = error;
    const int32_t correction = static_cast<int32_t>(0.030f * error + integral_[ch] + 0.004f * derivative);
    const int32_t bound = correction > 35 ? 35 : correction < -35 ? -35 : correction;
    const uint8_t requested = clampPercent(static_cast<int32_t>(feedforward) + bound);
    return requested && requested < saved_[ch].minRun ? saved_[ch].minRun : requested;
}

void CoolingController::recordFault(uint8_t ch, Fault code, uint32_t nowMs) {
    const FaultRecord entry = {nowMs / 1000U, static_cast<uint8_t>(ch + 1), static_cast<uint8_t>(code)};
    if (faultCount_ < kFaultCapacity) faultHistory_[faultCount_++] = entry;
    else {
        memmove(faultHistory_, faultHistory_ + 1, sizeof(FaultRecord) * (kFaultCapacity - 1));
        faultHistory_[kFaultCapacity - 1] = entry;
    }
    events_.print(F("FAULT ")); events_.print(ch + 1);
    events_.print(F(" ")); events_.print(entry.code);
    events_.print(F(" ")); events_.println(entry.uptimeSeconds);
    FaultStore store = {};
    store.magic = kFaultMagic;
    store.size = faultCount_;
    memcpy(store.entries, faultHistory_, sizeof(faultHistory_));
    store.checksum = checksum(&store, offsetof(FaultStore, checksum));
    storage_.putBytes("faults", &store, sizeof(store)); // only when new event occurs
}
void CoolingController::updateStall(uint8_t ch, uint32_t nowMs) {
    // Stall monitoring continues even when PC telemetry is absent: in this
    // case the fan is commanded to 100%, but a missing tach is still serious.
    // Do NOT fault an unconfirmed TACH input: no edges can equally mean an
    // unplugged fan, a broken TACH line, or a 3-pin power-gated output.
    if (fanMode_[ch] == Mode::Calibration || !fans_.hasRpmFeedback(ch) ||
        !fans_.tachObserved(ch) || fans_.getPercent(ch) < saved_[ch].minRun ||
        saved_[ch].stallRpm == 0) {
        stallSinceMs_[ch] = 0;
        return;
    }
    if (faultLatched_[ch]) { fans_.setPercent(ch, 100); return; }
    if (spinupUntilMs_[ch] && static_cast<int32_t>(spinupUntilMs_[ch] - nowMs) > 0) {
        fans_.setPercent(ch, 100);
        return;
    }
    spinupUntilMs_[ch] = 0;
    if (fans_.getRpm(ch) >= saved_[ch].stallRpm) {
        stallSinceMs_[ch] = 0;
        restartAttempts_[ch] = 0;
        return;
    }
    if (!stallSinceMs_[ch]) stallSinceMs_[ch] = nowMs;
    if (nowMs - stallSinceMs_[ch] < kStallDelayMs) return;
    stallSinceMs_[ch] = 0;
    ++restartAttempts_[ch];
    fans_.setPercent(ch, 100);
    if (restartAttempts_[ch] >= 3) {
        faultLatched_[ch] = true;
        recordFault(ch, Fault::Stall, nowMs);
    } else {
        spinupUntilMs_[ch] = nowMs + kRestartDurationMs;
    }
}

void CoolingController::update(uint32_t nowMs) {
    if (activeCalibration_ >= 0) {
        const uint8_t ch = static_cast<uint8_t>(activeCalibration_);
        if (!freshPair(ch, nowMs) || overTemperature(ch)) {
            recordFault(ch, Fault::CalibrationAborted, nowMs);
            endCalibration(true, false);
        } else {
            const uint32_t elapsed = nowMs - stepStartMs_;
            if (warmup_) {
                if (elapsed >= kCalWarmupMs) {
                    warmup_ = false;
                    stepStartMs_ = nowMs;
                    fans_.setPercent(ch, 0);
                }
            } else if (elapsed >= kCalPointMs) {
                uint32_t rpm = fans_.getRpm(ch);
                if (calibrationStep_ >= 16 && !fans_.tachReliable(ch)) {
                    // Above 80% power, missing/implausible TACH is not a useful
                    // calibration sample. One extra settling window then abort.
                    if (calRetry_++ == 0) { stepStartMs_ = nowMs; return; }
                    ++calBadSamples_;
                    events_.print(F("CAL_WARNING ")); events_.println(ch + 1);
                }
                calRetry_ = 0;
                if (rpm > 65535U) rpm = 65535U;
                if (downward_) downRpm_[calibrationStep_] = static_cast<uint16_t>(rpm);
                else workingRpm_[calibrationStep_] = static_cast<uint16_t>(rpm);
                reportPoint(ch, calibrationStep_, static_cast<uint16_t>(rpm));
                if (calBadSamples_ > 0) {
                    endCalibration(false, false);
                    return;
                }
                if (!downward_ && ++calibrationStep_ >= kCalibrationPoints) {
                    if (smartCalibration_) {
                        downward_ = true;
                        calibrationStep_ = kCalibrationPoints - 1;
                        fans_.setPercent(ch, 100);
                        stepStartMs_ = nowMs;
                    } else {
                        bool valid = false;
                        for (uint8_t i = 0; i < kCalibrationPoints; ++i)
                            valid |= workingRpm_[i] > 0;
                        endCalibration(false, valid);
                    }
                } else if (downward_ && calibrationStep_ == 0) {
                    bool valid = false;
                    for (uint8_t i = 0; i < kCalibrationPoints; ++i)
                        valid |= workingRpm_[i] >= 300 || downRpm_[i] >= 300;
                    endCalibration(false, valid);
                } else {
                    if (downward_) --calibrationStep_;
                    fans_.setPercent(ch, calibrationStep_ * 5);
                    stepStartMs_ = nowMs;
                }
            }
        }
    }

    if (nowMs - lastControlMs_ < kControlIntervalMs) return;
    lastControlMs_ = nowMs;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        if (activeCalibration_ == ch) continue;
        if (!freshPair(ch, nowMs)) {
            fans_.setPercent(ch, 100); // enforce in EVERY mode including manual/fixed RPM
            if (gotTemp_[ch] && !timeoutRecorded_[ch]) {
                recordFault(ch, Fault::SensorTimeout, nowMs);
                timeoutRecorded_[ch] = true;
            }
            updateStall(ch, nowMs);
            continue;
        }
        if (overTemperature(ch)) {
            fans_.setPercent(ch, 100);
            if (!overheatRecorded_[ch]) {
                recordFault(ch, Fault::Overheat, nowMs);
                overheatRecorded_[ch] = true;
            }
            updateStall(ch, nowMs);
            continue;
        }
        overheatRecorded_[ch] = false;
        if (faultLatched_[ch]) { fans_.setPercent(ch, 100); continue; }
        if (spinupUntilMs_[ch] && static_cast<int32_t>(spinupUntilMs_[ch] - nowMs) > 0) {
            fans_.setPercent(ch, 100);
            continue;
        }
        uint8_t targetPwm = 100;
        bool regulate = false;
        if (fanMode_[ch] == Mode::Manual) {
            targetPwm = manualPwm_[ch];
        } else if (fanMode_[ch] == Mode::FixedRpm) {
            targetPwm = pwmFromRpm(ch, fixedRpm_[ch]);
            desiredRpm_[ch] = fixedRpm_[ch];
            regulate = true;
        } else {
            targetPwm = interpolate(saved_[ch].curve, filteredTemp_[ch]);
            if (saved_[ch].dualEnabled) {
                const uint8_t second = interpolate(saved_[ch].secondCurve, filteredTemp2_[ch]);
                if (second > targetPwm) targetPwm = second;
            }
            desiredRpm_[ch] = targetRpmFromPwm(ch, targetPwm);
            regulate = saved_[ch].pidEnabled && saved_[ch].calibrated;
        }
        if (regulate) targetPwm = controlPwm(ch, targetPwm, desiredRpm_[ch], nowMs);
        const uint8_t current = fans_.getPercent(ch);
        // Ramp-up fast, ramp-down slowly (avoids hunting and acoustic oscillation).
        if (targetPwm > current) {
            const uint8_t diff = targetPwm - current;
            fans_.setPercent(ch, static_cast<uint8_t>(current + (diff > 20 ? 20 : diff)));
        } else if (targetPwm < current) {
            const uint8_t diff = current - targetPwm;
            fans_.setPercent(ch, static_cast<uint8_t>(current - (diff > 2 ? 2 : diff)));
        }
        updateStall(ch, nowMs);
    }
}

bool CoolingController::hasCalibration(uint8_t ch) const { return ch < board::kChannelCount && saved_[ch].calibrated; }
uint16_t CoolingController::rpmAt(uint8_t ch, uint8_t step) const {
    return ch < board::kChannelCount && step < kCalibrationPoints ? saved_[ch].rpm[step] : 0;
}
uint8_t CoolingController::minStartPwm(uint8_t ch) const { return ch < board::kChannelCount ? saved_[ch].minStart : 0; }
uint8_t CoolingController::minRunPwm(uint8_t ch) const { return ch < board::kChannelCount ? saved_[ch].minRun : 0; }
uint8_t CoolingController::appliedPwm(uint8_t ch) const { return fans_.getPercent(ch); }
uint16_t CoolingController::temperature(uint8_t ch, bool secondary) const {
    if (ch >= board::kChannelCount) return 0;
    return secondary ? lastTemp2_[ch] : lastTemp_[ch];
}
CoolingController::Mode CoolingController::mode(uint8_t ch) const {
    if (activeCalibration_ == ch) return Mode::Calibration;
    return ch < board::kChannelCount ? fanMode_[ch] : Mode::Auto;
}
bool CoolingController::closedLoop(uint8_t ch) const { return ch < board::kChannelCount && saved_[ch].pidEnabled; }
bool CoolingController::setClosedLoop(uint8_t ch, bool enabled) {
    if (ch >= board::kChannelCount || (enabled && (!saved_[ch].calibrated ||
        !fans_.hasRpmFeedback(ch) || !fans_.canControl(ch, 50)))) return false;
    StoredFan value = saved_[ch]; value.pidEnabled = enabled; integral_[ch] = 0;
    return writeFan(ch, value);
}
bool CoolingController::setDualSensor(uint8_t ch, bool enabled) {
    if (ch >= board::kChannelCount) return false;
    StoredFan value = saved_[ch]; value.dualEnabled = enabled;
    return writeFan(ch, value);
}
bool CoolingController::dualSensor(uint8_t ch) const { return ch < board::kChannelCount && saved_[ch].dualEnabled; }
bool CoolingController::setPulsesPerRevolution(uint8_t ch, uint8_t ppr) {
    if (ch >= board::kChannelCount || ppr == 0 || ppr > 12) return false;
    StoredFan value = saved_[ch]; value.ppr = ppr;
    if (!writeFan(ch, value)) return false;
    fans_.setPulsesPerRevolution(ch, ppr);
    return true;
}
uint8_t CoolingController::pulsesPerRevolution(uint8_t ch) const { return ch < board::kChannelCount ? saved_[ch].ppr : 0; }
bool CoolingController::setCriticalTemperature(uint8_t ch, uint8_t t) {
    if (ch >= board::kChannelCount || t < 40 || t > 120) return false;
    StoredFan value = saved_[ch]; value.criticalC = t; return writeFan(ch, value);
}
uint8_t CoolingController::criticalTemperature(uint8_t ch) const { return ch < board::kChannelCount ? saved_[ch].criticalC : 0; }
bool CoolingController::setFanThresholds(uint8_t ch, uint8_t ppr,
                                          uint8_t criticalC, uint16_t stallRpm) {
    if (ch >= board::kChannelCount || ppr < 1 || ppr > 12 ||
        criticalC < 40 || criticalC > 120 || stallRpm > 3000) return false;
    if (saved_[ch].ppr == ppr && saved_[ch].criticalC == criticalC &&
        saved_[ch].stallRpm == stallRpm) return true;
    StoredFan value = saved_[ch];
    value.ppr = ppr;
    value.criticalC = criticalC;
    value.stallRpm = stallRpm;
    if (!writeFan(ch, value)) return false;
    fans_.setPulsesPerRevolution(ch, ppr);
    return true;
}
bool CoolingController::setStallThreshold(uint8_t ch, uint16_t rpm) {
    if (ch >= board::kChannelCount || rpm > 3000) return false;
    StoredFan value = saved_[ch]; value.stallRpm = rpm; return writeFan(ch, value);
}
uint16_t CoolingController::stallThreshold(uint8_t ch) const { return ch < board::kChannelCount ? saved_[ch].stallRpm : 0; }
bool CoolingController::faulted(uint8_t ch) const { return ch < board::kChannelCount && faultLatched_[ch]; }
bool CoolingController::clearFault(uint8_t ch) {
    if (ch >= board::kChannelCount) return false;
    faultLatched_[ch] = false;
    restartAttempts_[ch] = 0;
    stallSinceMs_[ch] = 0;
    spinupUntilMs_[ch] = millis() + 3000U;
    fans_.setPercent(ch, 100);
    return true;
}
CoolingController::FaultRecord CoolingController::faultAt(uint8_t i) const {
    return i < faultCount_ ? faultHistory_[i] : FaultRecord{};
}
bool CoolingController::clearHistory() {
    faultCount_ = 0;
    memset(faultHistory_, 0, sizeof(faultHistory_));
    FaultStore store = {};
    store.magic = kFaultMagic;
    store.size = 0;
    store.checksum = checksum(&store, offsetof(FaultStore, checksum));
    return storage_.putBytes("faults", &store, sizeof(store)) == sizeof(store);
}
uint16_t CoolingController::rpmTarget(uint8_t ch) const { return ch < board::kChannelCount ? desiredRpm_[ch] : 0; }

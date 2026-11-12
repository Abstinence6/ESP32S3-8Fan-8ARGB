#include "PcPowerController.h"
#include "BoardConfig.h"

const char* PcPowerController::stateText() const {
    if (!enabled_) return "disabled";
    if (state_ == State::Unknown) return "unknown";
    return state_ == State::On ? "on" : "off";
}

void PcPowerController::release() {
#if PC_POWER_ENABLED
    digitalWrite(board::kPcPowerPin, HIGH); // open drain: HIGH == high impedance
#endif
}

bool PcPowerController::begin() {
#if PC_POWER_ENABLED
    // Write HIGH before enabling the open-drain output: never pulse on boot.
    release();
    pinMode(board::kPcPowerPin, OUTPUT_OPEN_DRAIN);
    release();
    pinMode(board::kPcSensePin, INPUT);
    enabled_ = true;
    candidateKnown_ = false;
    state_ = State::Unknown;
    update(millis());
#endif
    return true;
}

void PcPowerController::update(uint32_t nowMs) {
#if PC_POWER_ENABLED
    if (!enabled_) return;
    const bool high = digitalRead(board::kPcSensePin) == HIGH;
    if (!candidateKnown_ || high != candidateHigh_) {
        candidateHigh_ = high;
        candidateSince_ = nowMs;
        candidateKnown_ = true;
    }
    // Match the ESPHome source's delayed_on=100ms, delayed_off=2s.
    if (nowMs - candidateSince_ >= (high ? 100U : 2000U))
        state_ = high ? State::On : State::Off;
    if (pressing_ && nowMs - pressStarted_ >= pressDuration_) {
        release();
        pressing_ = false;
        lastRelease_ = nowMs;
        hadRelease_ = true;
    }
#else
    (void)nowMs;
#endif
}

bool PcPowerController::request(Action action, uint32_t nowMs) {
#if PC_POWER_ENABLED
    update(nowMs);
    if (!enabled_ || pressing_ || state_ == State::Unknown ||
        (hadRelease_ && nowMs - lastRelease_ < 1000U)) return false;
    if (action == Action::On && state_ != State::Off) return false;
    if (action != Action::On && state_ != State::On) return false;
    pressDuration_ = action == Action::ForceOff ? 6000U : 300U;
    pressStarted_ = nowMs;
    pressing_ = true;
    digitalWrite(board::kPcPowerPin, LOW); // open drain sinks PWR_SW only
    return true;
#else
    (void)action; (void)nowMs;
    return false;
#endif
}

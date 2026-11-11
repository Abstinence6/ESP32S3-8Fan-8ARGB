#include "FanController.h"
#include <stdint.h>

volatile uint32_t FanController::tachPulses_[board::kChannelCount] = {};
portMUX_TYPE FanController::tachMux_ = portMUX_INITIALIZER_UNLOCKED;

void IRAM_ATTR FanController::tachInterrupt(void* arg) {
    const uint8_t channel = static_cast<uint8_t>(reinterpret_cast<uintptr_t>(arg));
    if (channel >= board::kChannelCount) return;
    portENTER_CRITICAL_ISR(&tachMux_);
    ++tachPulses_[channel];
    portEXIT_CRITICAL_ISR(&tachMux_);
}

bool FanController::begin() {
    // Ensure smart power switches are bypassed (steady 12V) first.
    if (hardware_ && !hardware_->begin()) return false;
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        if (hardware_ && !hardware_->setSupplyBypass(i, true)) return false;
        configured_[i] = Type::FourPin; // backward-compatible safe default
        detected_[i] = Type::FourPin;
        if (ledcSetup(i, board::kFanPwmFrequencyHz, board::kFanPwmResolutionBits) <= 0.0) return false;
        ledcAttachPin(board::kFanPwmPins[i], i);
        if (!setPercent(i, board::kInitialFanPercent)) return false;
    }
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        pinMode(board::kFanTachPins[i], INPUT_PULLUP);
        attachInterruptArg(digitalPinToInterrupt(board::kFanTachPins[i]), tachInterrupt,
                           reinterpret_cast<void*>(static_cast<uintptr_t>(i)), FALLING);
    }
    previousSampleMs_ = millis();
    return true;
}

bool FanController::dcHardwareAvailable() const {
    return hardware_ && hardware_->canModulateSupply();
}

bool FanController::setType(uint8_t channel, Type requested) {
    if (channel >= board::kChannelCount ||
        (requested != Type::Auto && requested != Type::TwoPin &&
         requested != Type::ThreePin && requested != Type::FourPin)) return false;
    if (requested != Type::FourPin && !dcHardwareAvailable())
        return false;
    // First request full PWM, then switch the static supply-bypass control.
    setPercent(channel, 100);
    const bool bypass = requested != Type::TwoPin && requested != Type::ThreePin;
    if (hardware_ && !hardware_->setSupplyBypass(channel, bypass)) return false;
    configured_[channel] = requested;
    detected_[channel] = requested == Type::Auto ? Type::Unknown : requested;
    candidate_[channel] = Type::Unknown;
    confidence_[channel] = 0;
    // Remain at 100% while AUTO is unresolved. 2-wire never has reliable RPM.
    return setPercent(channel, 100);
}

FanController::Type FanController::configuredType(uint8_t channel) const {
    return channel < board::kChannelCount ? configured_[channel] : Type::Unknown;
}
FanController::Type FanController::detectedType(uint8_t channel) const {
    return channel < board::kChannelCount ? detected_[channel] : Type::Unknown;
}
bool FanController::hasRpmFeedback(uint8_t channel) const {
    return channel < board::kChannelCount &&
        (detected_[channel] == Type::ThreePin || detected_[channel] == Type::FourPin);
}

bool FanController::setPercent(uint8_t channel, uint8_t percent) {
    if (channel >= board::kChannelCount || percent > 100) return false;
    // Never chop supply of an unidentified load.
    if (configured_[channel] == Type::Auto && detected_[channel] == Type::Unknown)
        percent = 100;
    percent_[channel] = percent;
    const uint32_t duty = (static_cast<uint32_t>(percent) * 255U + 50U) / 100U;
    const uint32_t gpioDuty = board::kPwmDriverInverts ? 255U - duty : duty;
    // The external DC-key gate MUST invert the NPN-drive GPIO path to recover
    // logical PWM duty, then OR with the bypass signal (see docs/FAN_MODES.md).
    ledcWrite(channel, gpioDuty);
    return true;
}

uint8_t FanController::getPercent(uint8_t channel) const {
    return channel < board::kChannelCount ? percent_[channel] : 0;
}
uint32_t FanController::getRpm(uint8_t channel) const {
    return channel < board::kChannelCount && hasRpmFeedback(channel) ? rpm_[channel] : 0;
}

bool FanController::setPulsesPerRevolution(uint8_t channel, uint8_t ppr) {
    if (channel >= board::kChannelCount || ppr == 0 || ppr > 12) return false;
    ppr_[channel] = ppr;
    return true;
}
uint8_t FanController::getPulsesPerRevolution(uint8_t channel) const {
    return channel < board::kChannelCount ? ppr_[channel] : 0;
}

void FanController::detectType(uint8_t channel) {
    if (configured_[channel] != Type::Auto || detected_[channel] != Type::Unknown ||
        !dcHardwareAvailable()) return;
    const int8_t present = hardware_->pwmInputPresent(channel);
    Type next = Type::Unknown;
    if (present == 1) next = Type::FourPin; // pin-4 internal pull-up
    else if (present == 0 && rpm_[channel] >= 150) next = Type::ThreePin;
    if (next == Type::Unknown) { candidate_[channel] = Type::Unknown; confidence_[channel] = 0; return; }
    if (candidate_[channel] != next) {
        candidate_[channel] = next;
        confidence_[channel] = 1;
    } else if (confidence_[channel] < 3) {
        ++confidence_[channel];
    }
    // Require 3 successive 1s readings before changing supply mode.
    if (confidence_[channel] < 3) return;
    if (!hardware_->setSupplyBypass(channel, next == Type::FourPin)) return;
    detected_[channel] = next;
}

void FanController::update(uint32_t nowMs) {
    const uint32_t elapsedMs = nowMs - previousSampleMs_;
    if (elapsedMs < board::kRpmUpdateMs) return;
    uint32_t currentPulses[board::kChannelCount];
    portENTER_CRITICAL(&tachMux_);
    for (uint8_t i = 0; i < board::kChannelCount; ++i) currentPulses[i] = tachPulses_[i];
    portEXIT_CRITICAL(&tachMux_);
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        const uint32_t delta = currentPulses[i] - previousPulses_[i];
        previousPulses_[i] = currentPulses[i];
        rpm_[i] = static_cast<uint32_t>(
            (static_cast<uint64_t>(delta) * 60000ULL) / (static_cast<uint64_t>(elapsedMs) * ppr_[i]));
        detectType(i);
    }
    previousSampleMs_ = nowMs;
}

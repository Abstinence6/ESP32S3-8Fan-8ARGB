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
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        configured_[i] = static_cast<Type>(board::kDefaultFanType);
        if (ledcSetup(i, board::kFanPwmFrequencyHz, board::kFanPwmResolutionBits) <= 0.0)
            return false;
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
    return board::kDcSupplyPwmValidated;
}

bool FanController::canControl(uint8_t channel, uint8_t percent) const {
    if (channel >= board::kChannelCount || percent > 100) return false;
    const Type type = configured_[channel];
    if (type != Type::TwoPin && type != Type::ThreePin && type != Type::FourPin)
        return false;
    // Open-collector 4-pin PWM is always supported. Modulating DC supply is
    // blocked until the intelligent key is explicitly certified by the builder.
    return type == Type::FourPin || percent == 100 || dcHardwareAvailable();
}

bool FanController::setType(uint8_t channel, Type requested) {
    if (channel >= board::kChannelCount ||
        (requested != Type::TwoPin && requested != Type::ThreePin &&
         requested != Type::FourPin)) return false;
    // No bypass/select GPIO exists! The user must set a matching jumper and
    // then confirm the software type. Changing type cannot rewire the PCB.
    const Type old = configured_[channel];
    if (old != requested) {
        setPercent(channel, 100); // safe before accepting a different type
        configured_[channel] = requested;
    }
    return setPercent(channel, 100);
}

FanController::Type FanController::configuredType(uint8_t channel) const {
    return channel < board::kChannelCount ? configured_[channel] : Type::Unknown;
}
FanController::Type FanController::detectedType(uint8_t) const {
    // TACH presence cannot distinguish 3- vs 4-wire or missing/disconnected 2-wire.
    return Type::Unknown;
}

bool FanController::hasRpmFeedback(uint8_t channel) const {
    return channel < board::kChannelCount &&
        (configured_[channel] == Type::ThreePin || configured_[channel] == Type::FourPin);
}

bool FanController::setPercent(uint8_t channel, uint8_t percent) {
    if (channel >= board::kChannelCount || percent > 100) return false;
    const bool permitted = canControl(channel, percent);
    // Fail safe: never apply a partial duty in DC mode without rated hardware.
    const uint8_t applied = permitted ? percent : 100;
    percent_[channel] = applied;
    const uint32_t duty = (static_cast<uint32_t>(applied) * 255U + 50U) / 100U;
    const uint32_t gpioDuty = board::kPwmDriverInverts ? 255U - duty : duty;
    ledcWrite(channel, gpioDuty);
    return permitted;
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

void FanController::update(uint32_t nowMs) {
    const uint32_t elapsedMs = nowMs - previousSampleMs_;
    if (elapsedMs < board::kRpmUpdateMs) return;
    uint32_t currentPulses[board::kChannelCount];
    portENTER_CRITICAL(&tachMux_);
    for (uint8_t i = 0; i < board::kChannelCount; ++i)
        currentPulses[i] = tachPulses_[i];
    portEXIT_CRITICAL(&tachMux_);
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        const uint32_t delta = currentPulses[i] - previousPulses_[i];
        previousPulses_[i] = currentPulses[i];
        rpm_[i] = static_cast<uint32_t>(
            (static_cast<uint64_t>(delta) * 60000ULL) /
            (static_cast<uint64_t>(elapsedMs) * ppr_[i]));
    }
    previousSampleMs_ = nowMs;
}

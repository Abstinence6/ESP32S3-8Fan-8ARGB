#pragma once

#include <Arduino.h>
#include "BoardConfig.h"

// Fan connector wiring selection is PHYSICAL (jumper/solder bridge).
// Stored type affects feedback/PID permissions only, never switches supply.
class FanController {
public:
    enum class Type : uint8_t { TwoPin = 2, ThreePin = 3, Unknown = 255 };

    bool begin();
    bool setPercent(uint8_t channel, uint8_t percent);
    bool canControl(uint8_t channel, uint8_t percent) const;
    uint8_t getPercent(uint8_t channel) const;
    uint32_t getRpm(uint8_t channel) const;
    bool setPulsesPerRevolution(uint8_t channel, uint8_t ppr);
    uint8_t getPulsesPerRevolution(uint8_t channel) const;
    bool setType(uint8_t channel, Type requested);
    Type configuredType(uint8_t channel) const;
    // Without a sense pin, the physical connector type cannot be detected.
    Type detectedType(uint8_t channel) const;
    bool hasRpmFeedback(uint8_t channel) const;
    // True only after real TACH edges were observed since boot/type change.
    // Capability alone (3-pin/4-pin) does not prove a fan is connected.
    bool tachObserved(uint8_t channel) const;
    // Valid RPM is derived from the most recent complete measurement window.
    // No TACH / implausible pulse rate -> false; no closed-loop decisions.
    bool tachReliable(uint8_t channel) const;
    uint32_t tachPulseCount(uint8_t channel) const;
    // True only after user explicitly validates the DC power switch in firmware.
    bool dcHardwareAvailable() const;
    void update(uint32_t nowMs);

private:
    static void IRAM_ATTR tachInterrupt(void* arg);
    static volatile uint32_t tachPulses_[board::kChannelCount];
    static portMUX_TYPE tachMux_;
    Type configured_[board::kChannelCount] = {};
    uint8_t ppr_[board::kChannelCount] = {2,2,2,2,2,2,2,2};
    uint32_t previousPulses_[board::kChannelCount] = {};
    uint32_t rpm_[board::kChannelCount] = {};
    bool tachObserved_[board::kChannelCount] = {};
    bool tachReliable_[board::kChannelCount] = {};
    uint8_t percent_[board::kChannelCount] = {};
    uint32_t previousSampleMs_ = 0;
};

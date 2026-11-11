#pragma once

#include <Arduino.h>
#include "BoardConfig.h"
#include "FanPowerHardware.h"

class FanController {
public:
    enum class Type : uint8_t { Auto = 0, TwoPin = 2, ThreePin = 3, FourPin = 4, Unknown = 255 };

    void attachPowerHardware(FanPowerHardware& hardware) { hardware_ = &hardware; }
    bool begin();
    bool setPercent(uint8_t channel, uint8_t percent);
    uint8_t getPercent(uint8_t channel) const;
    uint32_t getRpm(uint8_t channel) const;
    bool setPulsesPerRevolution(uint8_t channel, uint8_t ppr);
    uint8_t getPulsesPerRevolution(uint8_t channel) const;
    bool setType(uint8_t channel, Type requested);
    Type configuredType(uint8_t channel) const;
    Type detectedType(uint8_t channel) const;
    bool hasRpmFeedback(uint8_t channel) const;
    bool dcHardwareAvailable() const;
    void update(uint32_t nowMs);

private:
    static void IRAM_ATTR tachInterrupt(void* arg);
    static volatile uint32_t tachPulses_[board::kChannelCount];
    static portMUX_TYPE tachMux_;
    void detectType(uint8_t channel);

    FanPowerHardware* hardware_ = nullptr;
    Type configured_[board::kChannelCount] = {};
    Type detected_[board::kChannelCount] = {};
    Type candidate_[board::kChannelCount] = {};
    uint8_t confidence_[board::kChannelCount] = {};
    uint8_t ppr_[board::kChannelCount] = {2,2,2,2,2,2,2,2};
    uint32_t previousPulses_[board::kChannelCount] = {};
    uint32_t rpm_[board::kChannelCount] = {};
    uint8_t percent_[board::kChannelCount] = {};
    uint32_t previousSampleMs_ = 0;
};

#pragma once

#include <Arduino.h>
#include "BoardConfig.h"

class FanController {
public:
    bool begin();
    bool setPercent(uint8_t channel, uint8_t percent);
    uint8_t getPercent(uint8_t channel) const;
    uint32_t getRpm(uint8_t channel) const;
    void update(uint32_t nowMs);

private:
    static void IRAM_ATTR tachInterrupt(void* arg);
    static volatile uint32_t tachPulses_[board::kChannelCount];
    static portMUX_TYPE tachMux_;

    uint32_t previousPulses_[board::kChannelCount] = {};
    uint32_t rpm_[board::kChannelCount] = {};
    uint8_t percent_[board::kChannelCount] = {};
    uint32_t previousSampleMs_ = 0;
};

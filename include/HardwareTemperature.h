#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include "BoardConfig.h"
#include "CoolingController.h"
#if HARDWARE_TEMP_ENABLED
#include <OneWire.h>
#include <DallasTemperature.h>
#endif

// Optional external DS18B20 on a verified spare GPIO.  No temperature is
// invented, and loss of the physical sensor never bypasses CoolingController
// stale-temperature protection.
class HardwareTemperature {
public:
    enum class Mode : uint8_t { PcOnly = 0, Local = 1, Backup = 2 };
    bool begin();
    void update(uint32_t nowMs, CoolingController& cooling);
    bool setMode(uint8_t channel, Mode mode);
    Mode mode(uint8_t channel) const;
    bool acceptsPc(uint8_t channel) const;
    void notePc(uint8_t channel, uint32_t nowMs);
    bool enabled() const { return HARDWARE_TEMP_ENABLED != 0; }
    bool fresh(uint32_t nowMs) const;
    uint16_t deciC() const { return valueDeciC_; }
    uint32_t age(uint32_t nowMs) const { return fresh(nowMs) ? nowMs - sampleMs_ : 0; }
    static const char* modeName(Mode mode);
private:
#if HARDWARE_TEMP_ENABLED
    OneWire oneWire_{board::kHardwareTempPin};
    DallasTemperature sensor_{&oneWire_};
    bool conversionPending_ = false;
    uint32_t conversionMs_ = 0;
    uint32_t lastRequestMs_ = 0;
#endif
    Preferences preferences_;
    Mode modes_[board::kChannelCount] = {};
    bool valid_ = false;
    uint16_t valueDeciC_ = 0;
    uint32_t sampleMs_ = 0;
    uint32_t lastInjectMs_[board::kChannelCount] = {};
    uint32_t pcReceivedMs_[board::kChannelCount] = {};
    bool pcSeen_[board::kChannelCount] = {};
};

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
    uint16_t deciC() const { return count_ ? probes_[0].deciC : 0; }
    uint32_t age(uint32_t nowMs) const { return fresh(nowMs) ? nowMs - probes_[0].sampleMs : 0; }
    static const char* modeName(Mode mode);

    // Stable 64-bit ROM identification avoids index changes across reboots.
    static constexpr uint8_t kMaxProbes = 8;
    uint8_t sensorCount() const { return count_; }
    bool sensorInfo(uint8_t index, char rom[17], uint16_t& deciC,
                    bool& valid, uint32_t& ageMs, uint32_t nowMs) const;
    bool mappedAddress(uint8_t channel, char rom[17]) const;
    bool setAddress(uint8_t channel, const char* romOrAuto);
    bool rescan(); // explicit, never automatic during fan-control loop
    static bool parseRom(const char* hex, uint8_t (&rom)[8]);
    static void formatRom(const uint8_t (&rom)[8], char (&hex)[17]);
private:
#if HARDWARE_TEMP_ENABLED
    OneWire oneWire_{board::kHardwareTempPin};
    DallasTemperature sensor_{&oneWire_};
    bool conversionPending_ = false;
    uint32_t conversionMs_ = 0;
    uint32_t lastRequestMs_ = 0;
#endif
    struct Probe {
        uint8_t rom[8] = {};
        uint16_t deciC = 0;
        uint32_t sampleMs = 0;
        bool valid = false;
    };
    Preferences preferences_;
    Probe probes_[kMaxProbes] = {};
    uint8_t count_ = 0;
    Mode modes_[board::kChannelCount] = {};
    bool mapped_[board::kChannelCount] = {};
    uint8_t assignedRom_[board::kChannelCount][8] = {};
    uint32_t lastInjectMs_[board::kChannelCount] = {};
    uint32_t pcReceivedMs_[board::kChannelCount] = {};
    bool pcSeen_[board::kChannelCount] = {};
    int8_t resolve(uint8_t channel) const;
};

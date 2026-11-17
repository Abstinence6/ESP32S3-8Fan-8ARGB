#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "BoardConfig.h"

// Separate from cooling-v1 calibration/NVS: PID gains can be upgraded without
// invalidating existing calibrated fan curves. Milli-coefficients are bounded.
class PidGainsSettings {
public:
    struct Gains {
        uint16_t kpMilli = 30;
        uint16_t kiMilli = 3;
        uint16_t kdMilli = 4;
    };
    static Gains defaults() { return Gains{}; }
    static bool valid(const Gains& gains) {
        return gains.kpMilli >= 5 && gains.kpMilli <= 80 &&
            gains.kiMilli <= 15 && gains.kdMilli <= 20;
    }
    bool begin() {
        if (!storage_.begin("pid-gains", false)) return false;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            gains_[ch] = defaults();
            Record record = {};
            char key[8];
            snprintf(key, sizeof(key), "fan%u", ch + 1);
            if (storage_.getBytesLength(key) == sizeof(record) &&
                storage_.getBytes(key, &record, sizeof(record)) == sizeof(record) &&
                record.magic == kMagic && record.version == 1 &&
                record.crc == checksum(record) && valid(record.gains))
                gains_[ch] = record.gains;
        }
        return true;
    }
    const Gains& get(uint8_t ch) const {
        return gains_[ch < board::kChannelCount ? ch : 0];
    }
    bool set(uint8_t ch, const Gains& value) {
        if (ch >= board::kChannelCount || !valid(value)) return false;
        if (gains_[ch].kpMilli == value.kpMilli &&
            gains_[ch].kiMilli == value.kiMilli &&
            gains_[ch].kdMilli == value.kdMilli) return true;
        Record record = {};
        record.magic = kMagic;
        record.version = 1;
        record.gains = value;
        record.crc = checksum(record);
        char key[8];
        snprintf(key, sizeof(key), "fan%u", ch + 1);
        if (storage_.putBytes(key, &record, sizeof(record)) != sizeof(record))
            return false;
        gains_[ch] = value;
        return true;
    }
private:
    static constexpr uint32_t kMagic = 0x50494431UL; // PID1
    struct Record {
        uint32_t magic = 0;
        uint32_t version = 0;
        Gains gains = {};
        uint32_t crc = 0;
    };
    static uint32_t checksum(const Record& record) {
        uint32_t hash = 2166136261UL;
        const auto* data = reinterpret_cast<const uint8_t*>(&record);
        for (size_t i = 0; i < offsetof(Record, crc); ++i)
            hash = (hash ^ data[i]) * 16777619UL;
        return hash;
    }
    Preferences storage_;
    Gains gains_[board::kChannelCount] = {};
};

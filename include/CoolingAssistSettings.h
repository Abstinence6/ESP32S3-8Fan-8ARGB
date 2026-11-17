#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "BoardConfig.h"

// User-configured power forecasting and airflow grouping. These are BOOSTS
// only: no assist command may lower the normal temperature demand, bypass
// the thermal fail-safe, or enable unqualified DC PWM hardware.
class CoolingAssistSettings {
public:
    struct Config {
        uint8_t enabled = 0;
        uint16_t cpuStartW = 65;
        uint16_t cpuFullW = 160;
        uint16_t gpuStartW = 100;
        uint16_t gpuFullW = 300;
        uint8_t maxPowerBoost = 15;
        uint8_t intakeBias = 5;
        uint8_t role[board::kChannelCount] = {};      // 0=none, 1=intake, 2=exhaust
        uint8_t source[board::kChannelCount] = {};    // 0=off, 1=CPU, 2=GPU, 3=MAX
    };
    static Config defaults() {
        Config v = {};
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
            v.source[ch] = 3;
        return v;
    }
    static bool valid(const Config& c) {
        if (c.enabled > 1 || c.cpuStartW < 10 || c.cpuFullW <= c.cpuStartW ||
            c.cpuFullW > 3000 || c.gpuStartW < 10 || c.gpuFullW <= c.gpuStartW ||
            c.gpuFullW > 3000 || c.maxPowerBoost > 25 || c.intakeBias > 15)
            return false;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
            if (c.role[ch] > 2 || c.source[ch] > 3) return false;
        return true;
    }
    bool begin() {
        config_ = defaults();
        if (!storage_.begin("cool-assist", false)) return false;
        Record saved = {};
        if (storage_.getBytesLength("config") == sizeof(saved) &&
            storage_.getBytes("config", &saved, sizeof(saved)) == sizeof(saved) &&
            saved.magic == kMagic && saved.version == 1 &&
            saved.crc == checksum(saved) && valid(saved.config))
            config_ = saved.config;
        return true;
    }
    const Config& get() const { return config_; }
    bool set(const Config& next) {
        if (!valid(next)) return false;
        // Pack into known, zero-initialized form to avoid padding surprises.
        Config clean = {};
        clean.enabled = next.enabled;
        clean.cpuStartW = next.cpuStartW; clean.cpuFullW = next.cpuFullW;
        clean.gpuStartW = next.gpuStartW; clean.gpuFullW = next.gpuFullW;
        clean.maxPowerBoost = next.maxPowerBoost; clean.intakeBias = next.intakeBias;
        for (uint8_t i = 0; i < board::kChannelCount; ++i) {
            clean.role[i] = next.role[i];
            clean.source[i] = next.source[i];
        }
        if (memcmp(&clean, &config_, sizeof(Config)) == 0) return true;
        Record record = {};
        record.magic = kMagic;
        record.version = 1;
        record.config = clean;
        record.crc = checksum(record);
        if (storage_.putBytes("config", &record, sizeof(record)) != sizeof(record))
            return false;
        config_ = clean;
        return true;
    }
    static uint8_t boost(const Config& c, uint8_t channel, uint16_t cpuW,
                         uint16_t gpuW, uint32_t powerAgeMs) {
        if (channel >= board::kChannelCount || !c.enabled) return 0;
        const uint8_t bias = c.role[channel] == 1 ? c.intakeBias : 0;
        if (powerAgeMs > 6000U || c.source[channel] == 0)
            return bias;  // missing PC metrics cannot invent power
        uint16_t level = 0;
        if ((c.source[channel] & 1) && cpuW != UINT16_MAX) {
            const uint16_t span = c.cpuFullW - c.cpuStartW;
            const uint16_t fraction = cpuW <= c.cpuStartW ? 0 :
                cpuW >= c.cpuFullW ? 100 :
                static_cast<uint16_t>((cpuW - c.cpuStartW) * 100UL / span);
            if (fraction > level) level = fraction;
        }
        if ((c.source[channel] & 2) && gpuW != UINT16_MAX) {
            const uint16_t span = c.gpuFullW - c.gpuStartW;
            const uint16_t fraction = gpuW <= c.gpuStartW ? 0 :
                gpuW >= c.gpuFullW ? 100 :
                static_cast<uint16_t>((gpuW - c.gpuStartW) * 100UL / span);
            if (fraction > level) level = fraction;
        }
        return static_cast<uint8_t>(bias + (level * c.maxPowerBoost + 50) / 100U);
    }
private:
    static constexpr uint32_t kMagic = 0x43415331UL; // CAS1
    struct Record {
        uint32_t magic = 0;
        uint32_t version = 0;
        Config config = {};
        uint32_t crc = 0;
    };
    static uint32_t checksum(const Record& record) {
        uint32_t hash = 2166136261UL;
        const uint8_t* data = reinterpret_cast<const uint8_t*>(&record);
        for (size_t i = 0; i < offsetof(Record, crc); ++i) {
            hash = (hash ^ data[i]) * 16777619UL;
        }
        return hash;
    }
    Preferences storage_;
    Config config_ = defaults();
};

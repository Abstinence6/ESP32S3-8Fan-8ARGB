#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "BoardConfig.h"

// The ESP32 is the source of truth for temperature ARGB assignments. A PC
// supplies live NWinfo values, but zone-to-sensor mapping survives PC reinstall
// and MCU restart. Single-zone transactions commit one CRC-checked NVS blob.
class TemperatureArgbSettings {
public:
    static constexpr uint8_t kMaxGroup = 8;
    static constexpr size_t kIdCapacity = 96; // 95 bytes UTF-8 + terminator

    struct Zone {
        char source[kIdCapacity] = {};
        char groups[kMaxGroup][kIdCapacity] = {};
        uint8_t groupCount = 0;
        uint8_t lowC = 30;
        uint8_t highC = 85;
        uint8_t brightness = 64;
    };

    bool begin() {
        if (!storage_.begin("temp-argb", false)) return false;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            Zone fallback = {};
            memcpy(fallback.source, "__OFF__", 8);
            zones_[ch] = fallback;
            Record record = {};
            char key[6];
            snprintf(key, sizeof(key), "z%u", ch + 1);
            if (storage_.getBytesLength(key) != sizeof(record) ||
                storage_.getBytes(key, &record, sizeof(record)) != sizeof(record) ||
                record.magic != kMagic || record.version != 1 ||
                record.crc != crc(record) || !valid(record.zone))
                continue;
            zones_[ch] = record.zone;
        }
        return true;
    }

    const Zone& zone(uint8_t ch) const { return zones_[ch < board::kChannelCount ? ch : 0]; }

    bool start(uint8_t ch, uint32_t nowMs) {
        if (ch >= board::kChannelCount || transaction_) return false;
        staging_ = Zone{};
        memcpy(staging_.source, "__OFF__", 8);
        stagedChannel_ = ch;
        startedMs_ = nowMs;
        transaction_ = true;
        return true;
    }
    bool setSource(const char* source, uint32_t nowMs) {
        if (!active(nowMs) || !setText(staging_.source, source)) return false;
        return true;
    }
    bool addMember(const char* source, uint32_t nowMs) {
        if (!active(nowMs) || staging_.groupCount >= kMaxGroup || !source) return false;
        for (uint8_t i = 0; i < staging_.groupCount; ++i)
            if (!strcmp(staging_.groups[i], source)) return false;
        if (!setText(staging_.groups[staging_.groupCount], source)) return false;
        ++staging_.groupCount;
        return true;
    }
    bool setRange(uint8_t low, uint8_t high, uint8_t brightness, uint32_t nowMs) {
        if (!active(nowMs) || low >= high || high > 125 || brightness > 128)
            return false;
        staging_.lowC = low;
        staging_.highC = high;
        staging_.brightness = brightness;
        return true;
    }
    bool commit(uint32_t nowMs) {
        if (!active(nowMs) || !valid(staging_)) return false;
        const uint8_t ch = stagedChannel_;
        const Zone next = staging_;
        if (memcmp(&zones_[ch], &next, sizeof(Zone)) != 0) {
            Record record = {};
            record.magic = kMagic;
            record.version = 1;
            record.zone = next;
            record.crc = crc(record);
            char key[6];
            snprintf(key, sizeof(key), "z%u", ch + 1);
            if (storage_.putBytes(key, &record, sizeof(record)) != sizeof(record))
                return false;
            zones_[ch] = next;
        }
        cancel();
        return true;
    }
    void cancel() { transaction_ = false; }
    bool transactionActive() const { return transaction_; }

private:
    static constexpr uint32_t kMagic = 0x54415247UL; // TARG
    struct Record {
        uint32_t magic = 0;
        uint32_t version = 0;
        Zone zone = {};
        uint32_t crc = 0;
    };
    static uint32_t crc(const Record& value) {
        uint32_t hash = 2166136261UL;
        const auto* bytes = reinterpret_cast<const uint8_t*>(&value);
        for (size_t i = 0; i < offsetof(Record, crc); ++i) {
            hash ^= bytes[i];
            hash *= 16777619UL;
        }
        return hash;
    }
    static bool terminated(const char* str) {
        return memchr(str, 0, kIdCapacity) != nullptr && str[0] != 0;
    }
    static bool valid(const Zone& zone) {
        if (!terminated(zone.source) || zone.lowC >= zone.highC ||
            zone.highC > 125 || zone.brightness > 128 ||
            zone.groupCount > kMaxGroup) return false;
        for (uint8_t i = 0; i < zone.groupCount; ++i) {
            if (!terminated(zone.groups[i])) return false;
            for (uint8_t j = 0; j < i; ++j)
                if (!strcmp(zone.groups[j], zone.groups[i])) return false;
        }
        // A group without sensors cannot be considered a valid configuration.
        if ((!strcmp(zone.source, "__GROUP_AVG__") ||
             !strcmp(zone.source, "__GROUP_MAX__") ||
             !strcmp(zone.source, "__GROUP_WEIGHTED__")) && !zone.groupCount)
            return false;
        return true;
    }
    static bool setText(char (&dest)[kIdCapacity], const char* source) {
        if (!source) return false;
        const size_t size = strlen(source);
        if (!size || size >= kIdCapacity) return false;
        memcpy(dest, source, size + 1);
        return true;
    }
    bool active(uint32_t nowMs) {
        if (transaction_ && nowMs - startedMs_ > 30000U) transaction_ = false;
        return transaction_;
    }
    Preferences storage_;
    Zone zones_[board::kChannelCount] = {};
    Zone staging_ = {};
    uint8_t stagedChannel_ = 0;
    bool transaction_ = false;
    uint32_t startedMs_ = 0;
};

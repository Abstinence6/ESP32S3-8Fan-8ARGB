#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "BoardConfig.h"

// Independent from existing TARGB v1 NVS layout: installed zone assignments
// survive firmware upgrades. Each palette is an atomic versioned CRC record.
class TemperaturePaletteSettings {
public:
    static constexpr uint8_t kMinPoints = 4;
    static constexpr uint8_t kMaxPoints = 8;
    struct Point {
        uint8_t tempC, r, g, b;
        Point(uint8_t t = 0, uint8_t red = 0, uint8_t green = 0, uint8_t blue = 0)
            : tempC(t), r(red), g(green), b(blue) {}
    };
    struct Palette {
        uint8_t count = 0;
        Point points[kMaxPoints] = {};
    };

    static Palette defaults() {
        Palette value = {};
        value.count = 4;
        value.points[0] = Point(30, 0, 100, 255);
        value.points[1] = Point(49, 0, 220, 65);
        value.points[2] = Point(69, 255, 190, 0);
        value.points[3] = Point(85, 255, 0, 0);
        return value;
    }
    static bool valid(const Palette& v) {
        if (v.count < kMinPoints || v.count > kMaxPoints) return false;
        for (uint8_t i = 0; i < v.count; ++i) {
            if (v.points[i].tempC > 125 ||
                (i && v.points[i].tempC <= v.points[i-1].tempC)) return false;
        }
        return true;
    }
    bool begin() {
        if (!storage_.begin("temp-pal", false)) return false;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            palettes_[ch] = defaults();
            Record rec = {};
            char key[6];
            snprintf(key, sizeof(key), "p%u", ch + 1);
            if (storage_.getBytesLength(key) != sizeof(rec) ||
                storage_.getBytes(key, &rec, sizeof(rec)) != sizeof(rec) ||
                rec.magic != kMagic || rec.version != 1 ||
                rec.checksum != checksum(rec) || !valid(rec.palette))
                continue;
            palettes_[ch] = rec.palette;
        }
        return true;
    }
    const Palette& get(uint8_t ch) const {
        return palettes_[ch < board::kChannelCount ? ch : 0];
    }
    bool set(uint8_t ch, const Palette& next) {
        if (ch >= board::kChannelCount || !valid(next)) return false;
        Palette clean = {};
        clean.count = next.count;
        for (uint8_t i = 0; i < next.count; ++i)
            clean.points[i] = next.points[i];
        if (memcmp(&palettes_[ch], &clean, sizeof(Palette)) == 0)
            return true;  // protect flash endurance
        Record record = {};
        record.magic = kMagic;
        record.version = 1;
        record.palette = clean;
        record.checksum = checksum(record);
        char key[6];
        snprintf(key, sizeof(key), "p%u", ch + 1);
        if (storage_.putBytes(key, &record, sizeof(record)) != sizeof(record))
            return false;
        palettes_[ch] = clean;
        return true;
    }
private:
    static constexpr uint32_t kMagic = 0x54504C31UL; // TPL1
    struct Record {
        uint32_t magic = 0;
        uint32_t version = 0;
        Palette palette = {};
        uint32_t checksum = 0;
    };
    static uint32_t checksum(const Record& v) {
        uint32_t hash = 2166136261UL;
        const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&v);
        for (size_t i = 0; i < offsetof(Record, checksum); ++i) {
            hash = (hash ^ bytes[i]) * 16777619UL;
        }
        return hash;
    }
    Preferences storage_;
    Palette palettes_[board::kChannelCount] = {};
};

#pragma once
#include <stdint.h>
#include "ArgbEffects.h"

// Autonomous, bounded RGB24 effects. All values are in tenths of their
// source's physical unit (e.g. 63.5% -> 635, 55.2 C -> 552).
// Input IDs: 1..8=TACH RPM, 9..16=fan control temperature,
// 17..24=local DS18B20 probes, 25..32=USB/MQTT metric slots,
// 33..40=actual fan PWM. Source 0 is never a valid primary source.
namespace argbreaction {
constexpr uint8_t kMaxSource = 40;
constexpr uint32_t kMaxValue = 10000000U;
constexpr uint32_t kFreshMs = 7000U;
enum class Style : uint8_t { Color=1, Bar=2, Brightness=3, Speed=4 };

struct Config {
    uint8_t source = 1;
    uint8_t fallback = 0;
    uint8_t style = static_cast<uint8_t>(Style::Color);
    uint32_t low = 0;
    uint32_t high = 1000; // default: 0..100% or 0..100 C
    argbeffects::Scene scene = {};
};
inline Config defaults() { return Config{}; }
inline bool localSource(uint8_t source) {
    return (source >= 1 && source <= 24) || (source >= 33 && source <= 40);
}
inline bool valid(const Config& cfg) {
    return cfg.source >= 1 && cfg.source <= kMaxSource &&
        (cfg.fallback == 0 || localSource(cfg.fallback)) &&
        cfg.style >= 1 && cfg.style <= 4 &&
        cfg.low < cfg.high && cfg.high <= kMaxValue &&
        argbeffects::valid(cfg.scene);
}
inline uint8_t level(const Config& cfg, uint32_t value) {
    if (value <= cfg.low) return 0;
    if (value >= cfg.high) return 255;
    return static_cast<uint8_t>((static_cast<uint64_t>(value - cfg.low) * 255U) /
        static_cast<uint64_t>(cfg.high - cfg.low));
}
inline void render(const Config& cfg, uint16_t count, uint32_t nowMs,
                   uint32_t reading, bool present, uint8_t* dest) {
    if (!valid(cfg) || !dest || !count || count > 170) return;
    // Missing data must not be misrepresented as a healthy/low reading.
    if (!present) {
        const uint8_t pulse = (nowMs / 500U) % 2U ? 40 : 110;
        for (uint16_t pixel=0; pixel<count; ++pixel) {
            dest[pixel*3U] = pulse; dest[pixel*3U+1] = pulse/4U;
            dest[pixel*3U+2] = 0;
        }
        return;
    }
    const uint8_t amount = level(cfg, reading);
    const Style style = static_cast<Style>(cfg.style);
    if (style == Style::Color || style == Style::Bar) {
        // The bar length, not the fan power, is controlled by the sensor.
        const uint16_t filled = static_cast<uint16_t>(
            (static_cast<uint32_t>(amount)*count + 254U) / 255U);
        for (uint16_t pixel=0; pixel<count; ++pixel) {
            const uint8_t blendAt = (style == Style::Color) ? amount :
                static_cast<uint8_t>(static_cast<uint32_t>(pixel) * 255U /
                    (count > 1 ? count-1 : 1));
            for (uint8_t component=0; component<3; ++component) {
                dest[pixel*3U+component] =
                    (style == Style::Bar && pixel >= filled) ? 0 :
                    argbeffects::blend(cfg.scene.primary[component],
                                       cfg.scene.secondary[component], blendAt);
            }
        }
        return;
    }
    uint32_t animationTime = nowMs;
    if (style == Style::Speed)
        animationTime = static_cast<uint32_t>(
            (static_cast<uint64_t>(nowMs) * (1U + static_cast<uint32_t>(amount)*7U/255U)) / 2U);
    argbeffects::render(cfg.scene,count,animationTime,dest);
    if (style == Style::Brightness) {
        for (uint16_t i=0; i<count*3U; ++i)
            dest[i] = static_cast<uint8_t>(static_cast<uint16_t>(dest[i])*amount/255U);
    }
}
} // namespace argbreaction

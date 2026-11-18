#pragma once
#include <stdint.h>

// Heap-free RGB24 effects. No GPIO access, flash writes or blocking delays.
namespace argbeffects {
enum class Pattern : uint8_t { Gradient=1, Wave=2, Breathe=3, Chase=4 };
struct Scene {
    uint8_t pattern = 1;
    uint8_t primary[3] = {20, 160, 255};
    uint8_t secondary[3] = {255, 50, 140};
    uint8_t speed = 3;       // 1..10
    uint8_t brightness = 64; // 0..255
    uint8_t direction = 0;   // 0 forward, 1 reverse
};
inline Scene defaults() { return Scene{}; }
inline bool valid(const Scene& s) {
    return s.pattern >= 1 && s.pattern <= 4 &&
           s.speed >= 1 && s.speed <= 10 && s.direction <= 1;
}
inline uint8_t blend(uint8_t a, uint8_t b, uint8_t weight) {
    return static_cast<uint8_t>((static_cast<uint16_t>(a) * (255U - weight) +
        static_cast<uint16_t>(b) * weight + 127U) / 255U);
}
inline uint8_t triangle(uint8_t phase) {
    return phase < 128U ? static_cast<uint8_t>(phase * 2U) :
        static_cast<uint8_t>((255U - phase) * 2U);
}
inline void render(const Scene& s, uint16_t count, uint32_t nowMs, uint8_t* dest) {
    if (!valid(s) || !dest || count == 0 || count > 170) return;
    const uint32_t tick = (nowMs / 40U) * s.speed;
    const uint16_t head = static_cast<uint16_t>((tick / 3U) % count);
    const uint16_t width = count < 6 ? 1 : count / 6;
    for (uint16_t i = 0; i < count; ++i) {
        const uint16_t pos = s.direction ? count - i - 1 : i;
        uint8_t mix = static_cast<uint8_t>(pos * 255U / (count > 1 ? count - 1 : 1));
        uint8_t intensity = 255;
        if (s.pattern == static_cast<uint8_t>(Pattern::Wave)) {
            mix = triangle(static_cast<uint8_t>((tick + pos * 256UL / count) & 255UL));
        } else if (s.pattern == static_cast<uint8_t>(Pattern::Breathe)) {
            intensity = static_cast<uint8_t>(24U +
                static_cast<uint16_t>(triangle(static_cast<uint8_t>(tick & 255U))) * 231U / 255U);
        } else if (s.pattern == static_cast<uint8_t>(Pattern::Chase)) {
            mix = 0;
            const uint16_t dist = pos > head ? pos - head : head - pos;
            const uint16_t wrapped = dist < count - dist ? dist : count - dist;
            intensity = wrapped >= width ? 0 : static_cast<uint8_t>(255U - wrapped * 255U / width);
        }
        for (uint8_t k = 0; k < 3; ++k) {
            const uint8_t color = blend(s.primary[k], s.secondary[k], mix);
            dest[static_cast<uint16_t>(i * 3U + k)] =
                static_cast<uint8_t>(static_cast<uint16_t>(color) * intensity / 255U);
        }
    }
}
} // namespace argbeffects

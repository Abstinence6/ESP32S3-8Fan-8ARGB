#pragma once
#include <stdint.h>

// Device-local audio envelopes, computed from four bounded numeric frequency
// bands. Audio capture (PC loopback / external MQTT sender) is always separate.
// Rendering is bounded, heap-free and never touches fan control or flash.
namespace argbaudio {
constexpr uint32_t kFreshMs = 1200U;
enum class Style : uint8_t { Vu=1, Spectrum=2, BassPulse=3, Wave=4 };
struct Config {
    uint8_t style=1;
    uint8_t gain=100;       // 1..200 percent
    uint8_t brightness=64; // 0..255 (also obeys global power limiter)
    uint8_t primary[3]={0,150,255};
    uint8_t secondary[3]={255,40,100};
};
struct Levels { uint8_t bass=0, mid=0, treble=0, peak=0; };
inline Config defaults() { return Config{}; }
inline bool valid(const Config& c) {
    return c.style>=1 && c.style<=4 && c.gain>=1 && c.gain<=200;
}
inline uint8_t scaled(uint8_t value,uint8_t gain) {
    const uint16_t product=static_cast<uint16_t>(value)*gain/100U;
    return static_cast<uint8_t>(product>255U ? 255U : product);
}
inline uint8_t blend(uint8_t first,uint8_t second,uint8_t amount) {
    return static_cast<uint8_t>((static_cast<uint16_t>(first)*(255U-amount)+
        static_cast<uint16_t>(second)*amount+127U)/255U);
}
inline uint8_t triangle(uint8_t phase) {
    return phase<128 ? static_cast<uint8_t>(phase*2U) :
        static_cast<uint8_t>((255U-phase)*2U);
}
inline void render(const Config& cfg, const Levels& levels, bool fresh,
                   uint16_t count,uint32_t nowMs,uint8_t* dest) {
    if (!dest || !count || count>170 || !valid(cfg)) return;
    const uint8_t values[4] = {
        scaled(levels.bass,cfg.gain), scaled(levels.mid,cfg.gain),
        scaled(levels.treble,cfg.gain), scaled(levels.peak,cfg.gain)
    };
    const uint8_t envelope=values[3]>values[0] ? values[3] : values[0];
    const uint16_t active=static_cast<uint16_t>((static_cast<uint32_t>(envelope)*count+254U)/255U);
    for (uint16_t i=0; i<count; ++i) {
        const uint8_t position=static_cast<uint8_t>(static_cast<uint32_t>(i)*255U/
            (count>1? count-1 : 1));
        uint8_t amount=0;
        if (fresh) switch (static_cast<Style>(cfg.style)) {
            case Style::Vu: amount=i<active ? 255 : 0; break;
            case Style::Spectrum: amount=values[static_cast<uint32_t>(i)*4U/count]; break;
            case Style::BassPulse: {
                const uint8_t flicker=triangle(static_cast<uint8_t>(nowMs/6U));
                amount=static_cast<uint8_t>(
                    (static_cast<uint16_t>(envelope)*flicker)/255U);
                break;
            }
            case Style::Wave: {
                const uint8_t wave=triangle(static_cast<uint8_t>(position + nowMs/10U));
                const uint8_t band=values[static_cast<uint32_t>(i)*3U/count];
                amount=static_cast<uint8_t>((static_cast<uint16_t>(wave)*band)/255U);
                break;
            }
        }
        for (uint8_t k=0; k<3; ++k) {
            const uint8_t color=blend(cfg.primary[k],cfg.secondary[k],position);
            dest[i*3U+k]=static_cast<uint8_t>(
                static_cast<uint16_t>(color)*amount/255U);
        }
    }
}
}

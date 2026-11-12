#include "ArgbController.h"

#include <stddef.h>
#include <string.h>

namespace {
constexpr uint32_t kArgbMagic = 0x41524734UL; // ARG4
constexpr uint32_t kExternalTimeoutMs = 3000;
}

uint32_t ArgbController::checksum(const Config& config) {
    uint32_t hash = 2166136261UL;
    const uint8_t* data = reinterpret_cast<const uint8_t*>(&config);
    for (size_t i = 0; i < offsetof(Config, crc); ++i) {
        hash ^= data[i];
        hash *= 16777619UL;
    }
    return hash;
}
bool ArgbController::persist() {
    Config config = {};
    config.magic = kArgbMagic;
    config.budgetMa = powerLimitMa_;
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        config.counts[i] = strips_[i].numPixels();
        config.reversed[i] = reversed_[i];
    }
    config.crc = checksum(config);
    return storage_.putBytes("config", &config, sizeof(config)) == sizeof(config);
}

bool ArgbController::begin() {
    if (!storage_.begin("argb-v4", false)) return false;
    Config config = {};
    bool valid = storage_.getBytesLength("config") == sizeof(config) &&
        storage_.getBytes("config", &config, sizeof(config)) == sizeof(config) &&
        config.magic == kArgbMagic && config.crc == checksum(config) &&
        config.budgetMa >= 100 && config.budgetMa <= 20000;
    if (valid) for (uint8_t i = 0; i < board::kChannelCount; ++i)
        if (config.counts[i] == 0 || config.counts[i] > board::kMaxArgbPixelsPerFrame || config.reversed[i] > 1)
            valid = false;
    powerLimitMa_ = valid ? config.budgetMa : 2000;
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        strips_[i].updateType(NEO_GRB + NEO_KHZ800);
        strips_[i].updateLength(valid ? config.counts[i] : board::kArgbLedCounts[i]);
        strips_[i].setPin(board::kArgbDataPins[i]);
        strips_[i].begin();
        strips_[i].setBrightness(255);
        brightness_[i] = board::kInitialArgbBrightness;
        modes_[i] = Mode::Off;
        reversed_[i] = valid && config.reversed[i] != 0;
        strips_[i].clear();
        strips_[i].show();
    }
    previousFrameMs_ = millis();
    return true;
}
void ArgbController::markDirty(uint8_t ch) { dirty_[ch] = true; }

uint32_t ArgbController::estimatedFullCurrent() const {
    uint32_t total = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        total += count; // ~1 mA idle per pixel (estimate, depends on LED model)
        for (uint16_t i = 0; i < count * 3U; ++i)
            total += static_cast<uint32_t>(frame_[ch][i]) * brightness_[ch] * 20U / (255U * 255U);
    }
    return total;
}
void ArgbController::render() {
    uint32_t baseline = 0, requestedColor = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        baseline += count;
        for (uint16_t i = 0; i < count * 3U; ++i)
            requestedColor += static_cast<uint32_t>(frame_[ch][i]) * brightness_[ch] * 20U;
    }
    const uint32_t allowance = powerLimitMa_ > baseline ? powerLimitMa_ - baseline : 0;
    // RequestedColor is in units of mA * 255 * 255 (RGB channels assume 20 mA max).
    const uint64_t desired = static_cast<uint64_t>(requestedColor);
    const uint64_t maxColor = static_cast<uint64_t>(allowance) * 255U * 255U;
    const uint16_t scale = desired > maxColor && desired
        ? static_cast<uint16_t>(maxColor * 255U / desired) : 255;
    if (lastScale_ != scale) {
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) markDirty(ch);
        lastScale_ = scale;
    }
    for (uint8_t scan = 0; scan < board::kChannelCount; ++scan) {
        const uint8_t ch = static_cast<uint8_t>((nextStrip_ + scan) % board::kChannelCount);
        if (!dirty_[ch]) continue;
        dirty_[ch] = false;
        const uint16_t count = strips_[ch].numPixels();
        for (uint16_t i = 0; i < count; ++i) {
            const uint16_t n = 3U * i;
            const uint32_t multiplier = static_cast<uint32_t>(brightness_[ch]) * scale;
            const uint8_t r = static_cast<uint8_t>(static_cast<uint32_t>(frame_[ch][n]) * multiplier / (255U * 255U));
            const uint8_t g = static_cast<uint8_t>(static_cast<uint32_t>(frame_[ch][n+1]) * multiplier / (255U * 255U));
            const uint8_t b = static_cast<uint8_t>(static_cast<uint32_t>(frame_[ch][n+2]) * multiplier / (255U * 255U));
            const uint16_t idx = reversed_[ch] ? count - i - 1 : i;
            strips_[ch].setPixelColor(idx, strips_[ch].Color(r,g,b));
        }
        strips_[ch].show();
        nextStrip_ = static_cast<uint8_t>((ch + 1) % board::kChannelCount);
        break; // Never block for multiple RMT transfers in one cooling cycle.
    }
}

void ArgbController::drawSolid(uint8_t ch) {
    for (uint16_t i = 0; i < strips_[ch].numPixels(); ++i) {
        const uint16_t n = i * 3U;
        frame_[ch][n] = colors_[ch].r;
        frame_[ch][n+1] = colors_[ch].g;
        frame_[ch][n+2] = colors_[ch].b;
    }
    markDirty(ch);
}
bool ArgbController::setSolid(uint8_t ch, uint8_t r, uint8_t g, uint8_t b) {
    if (ch >= board::kChannelCount) return false;
    modes_[ch] = Mode::Solid;
    colors_[ch].r = r; colors_[ch].g = g; colors_[ch].b = b;
    drawSolid(ch);
    return true;
}
bool ArgbController::setOff(uint8_t ch) {
    if (ch >= board::kChannelCount) return false;
    modes_[ch] = Mode::Off;
    memset(frame_[ch], 0, sizeof(frame_[ch]));
    markDirty(ch);
    return true;
}
bool ArgbController::setRainbow(uint8_t ch) {
    if (ch >= board::kChannelCount) return false;
    modes_[ch] = Mode::Rainbow;
    return true;
}
bool ArgbController::setPixels(uint8_t ch, const uint8_t* rgb, uint16_t count) {
    if (ch >= board::kChannelCount || !rgb || !count ||
        count > board::kMaxArgbPixelsPerFrame || count > strips_[ch].numPixels()) return false;
    if (modes_[ch] != Mode::External) brightness_[ch] = 255;
    modes_[ch] = Mode::External;
    lastExternalFrameMs_[ch] = millis();
    memcpy(frame_[ch], rgb, count * 3U);
    memset(frame_[ch] + count * 3U, 0, (strips_[ch].numPixels() - count) * 3U);
    markDirty(ch);
    return true;
}
bool ArgbController::configureStrip(uint8_t ch, uint16_t count, bool reversed) {
    if (ch >= board::kChannelCount || count == 0 || count > board::kMaxArgbPixelsPerFrame) return false;
    const uint16_t oldCount = strips_[ch].numPixels();
    const bool oldReverse = reversed_[ch];
    strips_[ch].updateLength(count);
    reversed_[ch] = reversed;
    memset(frame_[ch], 0, sizeof(frame_[ch]));
    modes_[ch] = Mode::Off;
    markDirty(ch);
    if (persist()) return true;
    strips_[ch].updateLength(oldCount);
    reversed_[ch] = oldReverse;
    return false;
}
bool ArgbController::setPowerBudget(uint16_t ma) {
    if (ma < 100 || ma > 20000) return false;
    const uint16_t previous = powerLimitMa_;
    powerLimitMa_ = ma;
    if (!persist()) { powerLimitMa_ = previous; return false; }
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) markDirty(ch);
    return true;
}
bool ArgbController::isReversed(uint8_t ch) const { return ch < board::kChannelCount && reversed_[ch]; }
uint16_t ArgbController::pixelCount(uint8_t ch) const { return ch < board::kChannelCount ? strips_[ch].numPixels() : 0; }
bool ArgbController::setBrightness(uint8_t ch, uint8_t value) {
    if (ch >= board::kChannelCount) return false;
    brightness_[ch] = value;
    markDirty(ch);
    return true;
}
ArgbController::Mode ArgbController::getMode(uint8_t ch) const { return ch < board::kChannelCount ? modes_[ch] : Mode::Off; }
uint8_t ArgbController::getBrightness(uint8_t ch) const { return ch < board::kChannelCount ? brightness_[ch] : 0; }
void ArgbController::update(uint32_t nowMs) {
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
        if (modes_[ch] == Mode::External && nowMs - lastExternalFrameMs_[ch] > kExternalTimeoutMs)
            setOff(ch);
    if (nowMs - previousFrameMs_ >= board::kArgbFrameMs) {
        previousFrameMs_ = nowMs;
        bool changed = false;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            if (modes_[ch] != Mode::Rainbow) continue;
            const uint16_t count = strips_[ch].numPixels();
            for (uint16_t pixel = 0; pixel < count; ++pixel) {
                const uint16_t hue = static_cast<uint16_t>(rainbowHue_ + (static_cast<uint32_t>(pixel) * 65536UL) / count);
                const uint32_t color = Adafruit_NeoPixel::gamma32(Adafruit_NeoPixel::ColorHSV(hue));
                const uint16_t n = pixel * 3U;
                frame_[ch][n] = static_cast<uint8_t>(color >> 16U);
                frame_[ch][n+1] = static_cast<uint8_t>(color >> 8U);
                frame_[ch][n+2] = static_cast<uint8_t>(color);
            }
            markDirty(ch);
            changed = true;
        }
        if (changed) rainbowHue_ += 192;
    }
    // 170 WS2812 pixels cost ~5.1 ms on the wire; budget one strip per tick.
    if (nowMs - lastShowMs_ >= 6U) {
        lastShowMs_ = nowMs;
        render();
    }
}

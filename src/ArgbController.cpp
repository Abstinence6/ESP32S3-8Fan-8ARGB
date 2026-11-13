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
uint32_t ArgbController::estimatedLimitedCurrent() const {
    // Estimate only; this is not a measurement or a substitute for a fuse.
    uint32_t baseline = 0;
    uint64_t weightedColor = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        baseline += count;
        for (uint16_t i = 0; i < count * 3U; ++i)
            weightedColor += static_cast<uint64_t>(frame_[ch][i]) * brightness_[ch] * 20U;
    }
    return baseline + static_cast<uint32_t>(weightedColor * lastScale_ /
        (255ULL * 255ULL * 255ULL));
}
void ArgbController::render() {
    uint32_t baseline = 0;
    uint64_t requestedColor = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        baseline += count;
        for (uint16_t i = 0; i < count * 3U; ++i)
            requestedColor += static_cast<uint64_t>(frame_[ch][i]) * brightness_[ch] * 20U;
    }
    const uint32_t allowance = powerLimitMa_ > baseline ? powerLimitMa_ - baseline : 0;
    // RequestedColor is in units of mA * 255 * 255 (RGB channels assume 20 mA max).
    const uint64_t desired = requestedColor;
    const uint64_t maxColor = static_cast<uint64_t>(allowance) * 255U * 255U;
    const uint16_t scale = desired > maxColor && desired
        ? static_cast<uint16_t>(maxColor * 255U / desired) : 255;
    if (lastScale_ != scale) {
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) markDirty(ch);
        lastScale_ = scale;
    }
    for (uint8_t n = 0; n < board::kChannelCount; ++n) {
        const uint8_t ch = (renderCursor_ + n) % board::kChannelCount;
        if (!dirty_[ch]) continue;
        dirty_[ch] = false;
        renderCursor_ = (ch + 1) % board::kChannelCount;
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
        break; // Give the control loop a chance to run between strip transfers.
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
    // LED output deferred to update() so fan control/serial input get priority.
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
    // LED output deferred to update() so fan control/serial input get priority.
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
    // LED output deferred to update() so fan control/serial input get priority.
    return true;
}
bool ArgbController::configureStrip(uint8_t ch, uint16_t count, bool reversed) {
    if (ch >= board::kChannelCount) return false;
    return configureStripAndBudget(ch, count, reversed, powerLimitMa_);
}
bool ArgbController::configureStripAndBudget(uint8_t ch, uint16_t count,
                                             bool reversed, uint16_t budgetMa) {
    if (ch >= board::kChannelCount || count == 0 ||
        count > board::kMaxArgbPixelsPerFrame ||
        budgetMa < 100 || budgetMa > 20000) return false;

    const bool geometryChanged = strips_[ch].numPixels() != count ||
                                 reversed_[ch] != reversed;
    const bool budgetChanged = powerLimitMa_ != budgetMa;
    if (!geometryChanged && !budgetChanged) return true; // preserve scene; no flash wear

    Config config = {};
    config.magic = kArgbMagic;
    config.budgetMa = budgetMa;
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        config.counts[i] = (i == ch) ? count : strips_[i].numPixels();
        config.reversed[i] = (i == ch) ? reversed : reversed_[i];
    }
    config.crc = checksum(config);
    if (storage_.putBytes("config", &config, sizeof(config)) != sizeof(config))
        return false; // never alter RAM settings on a failed NVS commit

    if (geometryChanged) {
        strips_[ch].updateLength(count);
        reversed_[ch] = reversed;
        memset(frame_[ch], 0, sizeof(frame_[ch]));
        modes_[ch] = Mode::Off;
        markDirty(ch);
    }
    if (budgetChanged) {
        powerLimitMa_ = budgetMa;
        for (uint8_t i = 0; i < board::kChannelCount; ++i) markDirty(i);
    }
    return true;
}
bool ArgbController::setPowerBudget(uint16_t ma) {
    return configureStripAndBudget(0, strips_[0].numPixels(), reversed_[0], ma);
}
bool ArgbController::isReversed(uint8_t ch) const { return ch < board::kChannelCount && reversed_[ch]; }
uint16_t ArgbController::pixelCount(uint8_t ch) const { return ch < board::kChannelCount ? strips_[ch].numPixels() : 0; }
bool ArgbController::setBrightness(uint8_t ch, uint8_t value) {
    if (ch >= board::kChannelCount) return false;
    brightness_[ch] = value;
    markDirty(ch);
    // LED output deferred to update() so fan control/serial input get priority.
    return true;
}
ArgbController::Mode ArgbController::getMode(uint8_t ch) const { return ch < board::kChannelCount ? modes_[ch] : Mode::Off; }
uint8_t ArgbController::getBrightness(uint8_t ch) const { return ch < board::kChannelCount ? brightness_[ch] : 0; }
void ArgbController::update(uint32_t nowMs) {
    // External frames and Serial commands only mark dirty; no LED show() inside
    // those handlers can monopolize the USB/TACH control loop.
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
        if (modes_[ch] == Mode::External && nowMs - lastExternalFrameMs_[ch] > kExternalTimeoutMs)
            setOff(ch);
    if (nowMs - previousFrameMs_ >= board::kArgbFrameMs) {
        previousFrameMs_ = nowMs;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            if (modes_[ch] != Mode::Rainbow) continue;
            const uint16_t count = strips_[ch].numPixels();
            for (uint16_t pixel = 0; pixel < count; ++pixel) {
                const uint16_t hue = static_cast<uint16_t>(
                    rainbowHue_ + (static_cast<uint32_t>(pixel) * 65536UL) / count);
                const uint32_t color = Adafruit_NeoPixel::gamma32(Adafruit_NeoPixel::ColorHSV(hue));
                const uint16_t n = pixel * 3U;
                frame_[ch][n] = static_cast<uint8_t>(color >> 16U);
                frame_[ch][n+1] = static_cast<uint8_t>(color >> 8U);
                frame_[ch][n+2] = static_cast<uint8_t>(color);
            }
            markDirty(ch);
        }
        rainbowHue_ += 192;
    }
    // Max one strip per ~6 ms visit, while rainbow animation keeps its
    // previous 40 ms cadence. The ESP controls cooling before reaching here.
    if (nowMs - previousRenderMs_ >= 6U) {
        previousRenderMs_ = nowMs;
        render();
    }
}

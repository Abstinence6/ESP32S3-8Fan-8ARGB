#pragma once

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Preferences.h>
#include "BoardConfig.h"

// Eight RGB24 addressable outputs. Internal raw pixel buffers allow a single
// *global* approximate power budget to be applied to every output, including
// OpenRGB USB and Wi-Fi frames (there is no bypass of this limit).
class ArgbController {
public:
    enum class Mode : uint8_t { Off, Solid, Rainbow, External };
    bool begin();
    bool setSolid(uint8_t channel, uint8_t red, uint8_t green, uint8_t blue);
    bool setOff(uint8_t channel);
    bool setRainbow(uint8_t channel);
    bool setPixels(uint8_t channel, const uint8_t* rgb, uint16_t count);
    bool configureStrip(uint8_t channel, uint16_t pixels, bool reversed);
    // Update count/reversal and global power budget in one NVS record.
    bool configureStripAndBudget(uint8_t channel, uint16_t pixels, bool reversed, uint16_t budgetMa);
    bool isReversed(uint8_t channel) const;
    uint16_t pixelCount(uint8_t channel) const;
    bool setBrightness(uint8_t channel, uint8_t brightness);
    bool setPowerBudget(uint16_t milliamps);
    uint16_t powerBudget() const { return powerLimitMa_; }
    uint32_t estimatedFullCurrent() const;
    uint32_t estimatedLimitedCurrent() const;
    Mode getMode(uint8_t channel) const;
    uint8_t getBrightness(uint8_t channel) const;
    void update(uint32_t nowMs);

private:
    struct Rgb { uint8_t r = 0, g = 0, b = 0; };
    struct Config {
        uint32_t magic;
        uint16_t counts[board::kChannelCount];
        uint8_t reversed[board::kChannelCount];
        uint16_t budgetMa;
        uint32_t crc;
    };
    static uint32_t checksum(const Config& config);
    void render();
    void drawSolid(uint8_t channel);
    void markDirty(uint8_t channel);

    Adafruit_NeoPixel strips_[board::kChannelCount];
    Preferences storage_;
    Mode modes_[board::kChannelCount] = {};
    Rgb colors_[board::kChannelCount] = {};
    uint8_t brightness_[board::kChannelCount] = {};
    bool reversed_[board::kChannelCount] = {};
    bool dirty_[board::kChannelCount] = {};
    uint8_t frame_[board::kChannelCount][board::kMaxArgbPixelsPerFrame * 3] = {};
    uint16_t powerLimitMa_ = 2000;
    uint16_t lastScale_ = 255;
    uint32_t previousFrameMs_ = 0;
    uint8_t renderCursor_ = 0;
    uint32_t previousRenderMs_ = 0;
    uint32_t lastExternalFrameMs_[board::kChannelCount] = {};
    uint16_t rainbowHue_ = 0;
};

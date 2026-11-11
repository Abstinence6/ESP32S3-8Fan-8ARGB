#pragma once

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include "BoardConfig.h"

class ArgbController {
public:
    enum class Mode : uint8_t { Off, Solid, Rainbow };

    bool begin();
    bool setSolid(uint8_t channel, uint8_t red, uint8_t green, uint8_t blue);
    bool setOff(uint8_t channel);
    bool setRainbow(uint8_t channel);
    bool setBrightness(uint8_t channel, uint8_t brightness);
    Mode getMode(uint8_t channel) const;
    uint8_t getBrightness(uint8_t channel) const;
    void update(uint32_t nowMs);

private:
    struct Rgb { uint8_t r = 0, g = 0, b = 0; };

    void drawSolid(uint8_t channel);
    Adafruit_NeoPixel strips_[board::kChannelCount];
    Mode modes_[board::kChannelCount] = {};
    Rgb colors_[board::kChannelCount] = {};
    uint8_t brightness_[board::kChannelCount] = {};
    uint32_t previousFrameMs_ = 0;
    uint16_t rainbowHue_ = 0;
};

#include "ArgbController.h"

bool ArgbController::begin() {
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        strips_[i].updateType(NEO_GRB + NEO_KHZ800);
        strips_[i].updateLength(board::kArgbLedCounts[i]);
        strips_[i].setPin(board::kArgbDataPins[i]);
        strips_[i].begin();
        strips_[i].setBrightness(board::kInitialArgbBrightness);
        brightness_[i] = board::kInitialArgbBrightness;
        modes_[i] = Mode::Off;
        strips_[i].clear();
        strips_[i].show();
    }
    previousFrameMs_ = millis();
    return true;
}

void ArgbController::drawSolid(uint8_t channel) {
    const Rgb& color = colors_[channel];
    strips_[channel].fill(strips_[channel].Color(color.r, color.g, color.b));
    strips_[channel].show();
}

bool ArgbController::setSolid(uint8_t channel, uint8_t red, uint8_t green, uint8_t blue) {
    if (channel >= board::kChannelCount) return false;
    modes_[channel] = Mode::Solid;
    colors_[channel].r = red;
    colors_[channel].g = green;
    colors_[channel].b = blue;
    drawSolid(channel);
    return true;
}

bool ArgbController::setOff(uint8_t channel) {
    if (channel >= board::kChannelCount) return false;
    modes_[channel] = Mode::Off;
    strips_[channel].clear();
    strips_[channel].show();
    return true;
}

bool ArgbController::setRainbow(uint8_t channel) {
    if (channel >= board::kChannelCount) return false;
    modes_[channel] = Mode::Rainbow;
    // First frame will be drawn by update().
    return true;
}

bool ArgbController::setPixels(uint8_t channel, const uint8_t* rgb, uint16_t count) {
    if (channel >= board::kChannelCount || !rgb || count == 0 ||
        count > board::kMaxArgbPixelsPerFrame || count > strips_[channel].numPixels()) return false;
    if (modes_[channel] != Mode::External) {
        // In streaming mode external software supplies actual brightness in RGB values.
        strips_[channel].setBrightness(255);
        brightness_[channel] = 255;
    }
    modes_[channel] = Mode::External;
    for (uint16_t i = 0; i < count; ++i) {
        const uint16_t n = i * 3;
        strips_[channel].setPixelColor(i, strips_[channel].Color(rgb[n], rgb[n+1], rgb[n+2]));
    }
    for (uint16_t i = count; i < strips_[channel].numPixels(); ++i)
        strips_[channel].setPixelColor(i, 0);
    strips_[channel].show();
    return true;
}

uint16_t ArgbController::pixelCount(uint8_t channel) const {
    return channel < board::kChannelCount ? strips_[channel].numPixels() : 0;
}

bool ArgbController::setBrightness(uint8_t channel, uint8_t brightness) {
    if (channel >= board::kChannelCount) return false;
    brightness_[channel] = brightness;
    strips_[channel].setBrightness(brightness);
    if (modes_[channel] == Mode::Solid) drawSolid(channel);
    else if (modes_[channel] == Mode::Off || modes_[channel] == Mode::External) strips_[channel].show();
    // Rainbow data will be regenerated on next frame.
    return true;
}

ArgbController::Mode ArgbController::getMode(uint8_t channel) const {
    return channel < board::kChannelCount ? modes_[channel] : Mode::Off;
}

uint8_t ArgbController::getBrightness(uint8_t channel) const {
    return channel < board::kChannelCount ? brightness_[channel] : 0;
}

void ArgbController::update(uint32_t nowMs) {
    if (nowMs - previousFrameMs_ < board::kArgbFrameMs) return;
    previousFrameMs_ = nowMs;

    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        if (modes_[ch] != Mode::Rainbow) continue;

        const uint16_t count = strips_[ch].numPixels();
        for (uint16_t pixel = 0; pixel < count; ++pixel) {
            const uint16_t hue = static_cast<uint16_t>(
                rainbowHue_ + (static_cast<uint32_t>(pixel) * 65536UL) / count);
            const uint32_t color = Adafruit_NeoPixel::gamma32(Adafruit_NeoPixel::ColorHSV(hue));
            strips_[ch].setPixelColor(pixel, color);
        }
        // Each show() is blocking; one temporary RMT TX channel is reused.
        // 8 outputs work even though the S3 has only 4 simultaneous RMT TX channels.
        strips_[ch].show();
    }
    rainbowHue_ += 192;
}

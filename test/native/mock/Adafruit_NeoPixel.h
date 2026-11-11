#pragma once
#include <cstdint>
#include <vector>

typedef uint16_t neoPixelType;
static constexpr neoPixelType NEO_GRB = 1;
static constexpr neoPixelType NEO_KHZ800 = 2;

class Adafruit_NeoPixel {
public:
    Adafruit_NeoPixel() = default;
    void updateType(neoPixelType) {}
    void updateLength(uint16_t count) { data_.resize(count, 0); }
    void setPin(uint16_t pin) { pin_ = pin; }
    bool begin() { return true; }
    void setBrightness(uint8_t brightness) { brightness_ = brightness; }
    void clear() { for (auto& pixel : data_) pixel = 0; }
    void show() { ++shows_; }
    void fill(uint32_t color) { for (auto& pixel : data_) pixel = color; }
    uint16_t numPixels() const { return static_cast<uint16_t>(data_.size()); }
    void setPixelColor(uint16_t pos, uint32_t color) { if (pos < data_.size()) data_[pos] = color; }
    static uint32_t Color(uint8_t red, uint8_t green, uint8_t blue) {
        return (uint32_t(red) << 16) | (uint32_t(green) << 8) | blue;
    }
    static uint32_t ColorHSV(uint16_t hue) { return Color(hue >> 8, 255, 10); }
    static uint32_t gamma32(uint32_t color) { return color; }
private:
    uint16_t pin_ = 0;
    uint8_t brightness_ = 0;
    unsigned shows_ = 0;
    std::vector<uint32_t> data_;
};

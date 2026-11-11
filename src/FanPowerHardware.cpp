#include "FanPowerHardware.h"
#include "BoardConfig.h"

#if defined(ARDUINO_ARCH_ESP32)
#include <Wire.h>
#endif

bool Mcp23017FanPowerHardware::begin() {
    online_ = false;
    bypassMask_ = 0xFF;
    if (!board::kEnableFanModeExpander) return true;
#if defined(ARDUINO_ARCH_ESP32)
    Wire.begin(board::kFanI2cSda, board::kFanI2cScl);
    // MCP23017 BANK=0, default after reset. Assert full-power bypass before
    // changing GPA direction; GPA requires external pull-ups for reset safety.
    if (!writeRegister(0x14, 0xFF) ||
        !writeRegister(0x01, 0xFF) || // GPB all inputs
        !writeRegister(0x00, 0x00)) return false; // GPA all outputs
    online_ = true;
    return true;
#else
    return false;
#endif
}

bool Mcp23017FanPowerHardware::canModulateSupply() const {
    return board::kEnableFanModeExpander && online_;
}

bool Mcp23017FanPowerHardware::setSupplyBypass(uint8_t channel, bool fullPower) {
    if (channel >= board::kChannelCount) return false;
    if (!canModulateSupply()) return fullPower; // legacy fan-only PCB
    const uint8_t mask = static_cast<uint8_t>(1U << channel);
    const uint8_t next = fullPower ? static_cast<uint8_t>(bypassMask_ | mask)
                                   : static_cast<uint8_t>(bypassMask_ & ~mask);
    if (!writeRegister(0x14, next)) return false;
    bypassMask_ = next;
    return true;
}

int8_t Mcp23017FanPowerHardware::pwmInputPresent(uint8_t channel) {
    if (channel >= board::kChannelCount || !canModulateSupply()) return -1;
    const int port = readRegister(0x13);
    if (port < 0) return -1;
    return (port & (1U << channel)) ? 1 : 0;
}

bool Mcp23017FanPowerHardware::writeRegister(uint8_t reg, uint8_t data) {
#if defined(ARDUINO_ARCH_ESP32)
    Wire.beginTransmission(board::kFanExpanderI2cAddress);
    Wire.write(reg);
    Wire.write(data);
    return Wire.endTransmission() == 0;
#else
    (void)reg; (void)data;
    return false;
#endif
}

int Mcp23017FanPowerHardware::readRegister(uint8_t reg) {
#if defined(ARDUINO_ARCH_ESP32)
    Wire.beginTransmission(board::kFanExpanderI2cAddress);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return -1;
    if (Wire.requestFrom(static_cast<uint8_t>(board::kFanExpanderI2cAddress), static_cast<uint8_t>(1)) != 1) return -1;
    return Wire.read();
#else
    (void)reg;
    return -1;
#endif
}

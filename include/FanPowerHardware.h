#pragma once

#include <stdint.h>

// One logical PWM stream per fan. A hardware bypass gate forces 12V power ON
// for 4-wire fans; for 2/3-wire DC mode the smart high-side switch follows the
// buffered/inverted logical PWM. This interface never switches motor current.
class FanPowerHardware {
public:
    virtual ~FanPowerHardware() = default;
    virtual bool begin() = 0;
    virtual bool canModulateSupply() const = 0;
    virtual bool setSupplyBypass(uint8_t channel, bool fullPower) = 0;
    // 1 = pin-4 pullup sensed, 0 = definitely absent, -1 = unsupported/unknown.
    virtual int8_t pwmInputPresent(uint8_t channel) = 0;
};

// Optional MCP23017 at 0x20: GPA0-7 = supply bypass outputs (HIGH means ON),
// GPB0-7 = protected digital pin-4 presence sense inputs (external divider).
// In unconfigured/legacy builds it accepts only full-power 4-wire operation.
class Mcp23017FanPowerHardware final : public FanPowerHardware {
public:
    bool begin() override;
    bool canModulateSupply() const override;
    bool setSupplyBypass(uint8_t channel, bool fullPower) override;
    int8_t pwmInputPresent(uint8_t channel) override;
private:
    bool writeRegister(uint8_t reg, uint8_t data);
    int readRegister(uint8_t reg);
    bool online_ = false;
    uint8_t bypassMask_ = 0xFF;
};

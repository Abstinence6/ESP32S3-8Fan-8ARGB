#pragma once

#include <stdint.h>

// Reference pin assignment: ESP32-S3-DevKitC-1.
// IMPORTANT: Verify every GPIO against the exact module, board and schematic.
// Not using USB GPIO19/20, flash GPIO26-32, octal-PSRAM GPIO35-37,
// boot straps GPIO0/3/45/46, or UART0 GPIO43/44.
namespace board {

static constexpr uint8_t kChannelCount = 8;
// Two native ESP32-S3 GPIO per fan: one PWM and one tachometer input.
// For 2/3-pin, a qualified high-side switch controls +12 V.
// No 4-pin PWM input, physical DC/PWM jumper, automatic detection, or GPIO expander.
static constexpr uint8_t kDefaultFanType = 3;
// SAFETY INTERLOCK: enable only after bench validation of the actual power stage,
// including switching frequency, 12 V transient handling, inrush, TACH, and power-ON at reset.
// While false, 2/3-pin channels are held at 100% and reject lower duty.
#ifndef FAN_DC_PWM_VALIDATED
#define FAN_DC_PWM_VALIDATED 0
#endif
static constexpr bool kDcSupplyPwmValidated = (FAN_DC_PWM_VALIDATED != 0);
static constexpr uint8_t kFanPwmPins[kChannelCount] = {4, 5, 6, 7, 15, 16, 17, 18};
static constexpr uint8_t kFanTachPins[kChannelCount] = {8, 9, 10, 11, 12, 13, 14, 21};
static constexpr uint8_t kArgbDataPins[kChannelCount] = {1, 2, 38, 39, 40, 41, 42, 47};
static constexpr uint16_t kArgbLedCounts[kChannelCount] = {30, 30, 30, 30, 30, 30, 30, 30};
// sACN: one universe per channel, up to 170 RGB pixels (510 DMX slots).
static constexpr uint16_t kMaxArgbPixelsPerFrame = 170;
static constexpr uint32_t kSerialBaud = 921600;

// Supply PWM for 2/3-wire fans is not the 25 kHz control signal for 4-wire fans.
// 250 Hz is a starting test setting, NOT yet verified for a particular motor.
static constexpr uint32_t kFanPwmFrequencyHz = 250;
static constexpr uint32_t kMaxValidRpm = 25000;
static constexpr uint8_t kFanPwmResolutionBits = 8;
static constexpr uint8_t kTachPulsesPerRevolution = 2;
static constexpr uint32_t kRpmUpdateMs = 1000;

// MUST match the final tested high-side gate-drive circuit! An ULN2803
// pulling a P-MOSFET gate low is active HIGH at the ESP GPIO.
// No firmware polarity setting can guarantee 12 V during reset; hardware must.
static constexpr bool kPwmDriverInverts = false;
static constexpr uint8_t kInitialFanPercent = 100; // fail-safe full speed

static constexpr uint8_t kInitialArgbBrightness = 64; // 0..255
static constexpr uint32_t kArgbFrameMs = 40; // up to 25 FPS, updates strips sequentially


// Optional motherboard PWR_SW + 3.3 V power-indicator interface.
// Deliberately NO pin default: GPIO1 is already ARGB1; many ESP32-S3
// variants reserve other pins for flash/PSRAM, USB or bootstrapping.
#ifndef PC_POWER_ENABLED
#define PC_POWER_ENABLED 0
#endif
#ifndef PC_POWER_GPIO
#define PC_POWER_GPIO -1
#endif
#ifndef PC_SENSE_GPIO
#define PC_SENSE_GPIO -1
#endif
static constexpr int kPcPowerPin = PC_POWER_GPIO;
static constexpr int kPcSensePin = PC_SENSE_GPIO;
#if PC_POWER_ENABLED
static_assert(kPcPowerPin >= 0 && kPcPowerPin <= 48 &&
              kPcSensePin >= 0 && kPcSensePin <= 48 &&
              kPcPowerPin != kPcSensePin, "PC power requires two distinct assigned ESP32-S3 GPIOs");
constexpr bool reservedPcGpio(int pin) {
    // Conservative: boot strapping, USB, UART0 and flash/PSRAM-related pins.
    if (pin == 0 || pin == 3 || pin == 19 || pin == 20 ||
        pin == 43 || pin == 44 || pin == 45 || pin == 46 ||
        (pin >= 26 && pin <= 32) || (pin >= 35 && pin <= 37)) return true;
    for (uint8_t i = 0; i < kChannelCount; ++i) {
        if (pin == kFanPwmPins[i] || pin == kFanTachPins[i] || pin == kArgbDataPins[i])
            return true;
    }
    return false;
}
static_assert(!reservedPcGpio(kPcPowerPin) && !reservedPcGpio(kPcSensePin),
              "PC power pins conflict with reserved GPIOs or fan/ARGB outputs");
#endif

} // namespace board

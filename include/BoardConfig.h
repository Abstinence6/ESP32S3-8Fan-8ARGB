#pragma once

#include <stdint.h>

// Reference pin assignment: ESP32-S3-DevKitC-1.
// IMPORTANT: Verify every GPIO against the exact module, board and schematic.
// Not using USB GPIO19/20, flash GPIO26-32, octal-PSRAM GPIO35-37,
// boot straps GPIO0/3/45/46, or UART0 GPIO43/44.
namespace board {

static constexpr uint8_t kChannelCount = 8;
// Two native ESP32-S3 GPIO per fan: one PWM and one tachometer input.
// For 2/3-pin, a selected smart high-side key modulates +12V; for 4-pin,
// a physical jumper holds +12V ON and routes PWM to fan pin 4.
// No GPIO expander, I2C, automatic connector detection or software bypass.
static constexpr uint8_t kDefaultFanType = 3;
// SAFETY INTERLOCK: set true only after verifying the selected smart switch
// supports 25 kHz PWM of a motor load, inrush, heat and an ON-at-reset circuit.
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

static constexpr uint32_t kFanPwmFrequencyHz = 25000;
static constexpr uint8_t kFanPwmResolutionBits = 8;
static constexpr uint8_t kTachPulsesPerRevolution = 2;
static constexpr uint32_t kRpmUpdateMs = 1000;

// true: GPIO -> base/gate of NPN/NMOS open-collector/open-drain stage -> fan PWM pin.
// The stage inverts the logic level. PWM high on the *fan connector* means full speed.
static constexpr bool kPwmDriverInverts = true;
static constexpr uint8_t kInitialFanPercent = 100; // fail-safe full speed

static constexpr uint8_t kInitialArgbBrightness = 64; // 0..255
static constexpr uint32_t kArgbFrameMs = 40; // up to 25 FPS, updates strips sequentially

} // namespace board

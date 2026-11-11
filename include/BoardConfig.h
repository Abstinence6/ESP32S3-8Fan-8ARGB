#pragma once

#include <stdint.h>

// Reference pin assignment: ESP32-S3-DevKitC-1.
// IMPORTANT: Verify every GPIO against the exact module, board and schematic.
// Not using USB GPIO19/20, flash GPIO26-32, octal-PSRAM GPIO35-37,
// boot straps GPIO0/3/45/46, or UART0 GPIO43/44.
namespace board {

static constexpr uint8_t kChannelCount = 8;
// On the universal fan PCB, MCP23017 GPA0..7 controls 12V-power bypass and
// GPB0..7 senses pin-4 presence via a 3.3V protected sense circuit.
// NEVER enable this until the expander and its fail-safe external pull-ups
// are mounted. 4-pin-only legacy boards keep the adapter disabled.
static constexpr bool kEnableFanModeExpander = false;
static constexpr uint8_t kFanI2cSda = 33;
static constexpr uint8_t kFanI2cScl = 34;
static constexpr uint8_t kFanExpanderI2cAddress = 0x20;
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

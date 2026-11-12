#pragma once

#include <stdint.h>

// Reference pin assignment: ESP32-S3-DevKitC-1.
// IMPORTANT: Verify every GPIO against the exact module, board and schematic.
// Not using USB GPIO19/20, flash GPIO26-32, octal-PSRAM GPIO35-37,
// boot straps GPIO0/3/45/46, or UART0 GPIO43/44.
namespace board {

static constexpr uint8_t kChannelCount = 8;
// 2-pin and 3-pin DC fans ONLY. Keep GND common and switch the +12 V rail
// with a properly designed high-side driver. 3-pin has TACH; 2-pin does not.
// No pin-4 PWM stage, connector jumper, I2C expander or type detection.
static constexpr uint8_t kDefaultFanType = 3;
// SAFETY INTERLOCK: BOTH the high-side driver and fan must be tested under
// real load, including startup/inrush and safe behaviour during MCU reset.
// OFF by default; power-PWM requests below 100% are rejected until validated.
#ifndef FAN_DC_PWM_VALIDATED
#define FAN_DC_PWM_VALIDATED 0
#endif
static constexpr bool kDcSupplyPwmValidated = (FAN_DC_PWM_VALIDATED != 0);
// With chopped 12 V the TACH output can be unreliable. Never use fractional
// supply-duty RPM feedback for calibration/PID/stall until scope-validated.
#ifndef FAN_DC_TACH_VALIDATED
#define FAN_DC_TACH_VALIDATED 0
#endif
static constexpr bool kDcTachValidated = (FAN_DC_TACH_VALIDATED != 0);
#ifndef FAN_DC_PWM_HZ
#define FAN_DC_PWM_HZ 250
#endif
static_assert(FAN_DC_PWM_HZ >= 80 && FAN_DC_PWM_HZ <= 1000,
              "Power-PWM frequency must be 80..1000 Hz, validated for your switch and fans");
#ifndef FAN_OUTPUT_INVERTED
#define FAN_OUTPUT_INVERTED 1
#endif
static_assert(FAN_OUTPUT_INVERTED == 0 || FAN_OUTPUT_INVERTED == 1,
              "FAN_OUTPUT_INVERTED must be 0 or 1");
static constexpr uint8_t kFanPwmPins[kChannelCount] = {4, 5, 6, 7, 15, 16, 17, 18};
static constexpr uint8_t kFanTachPins[kChannelCount] = {8, 9, 10, 11, 12, 13, 14, 21};
static constexpr uint8_t kArgbDataPins[kChannelCount] = {1, 2, 38, 39, 40, 41, 42, 47};
static constexpr uint16_t kArgbLedCounts[kChannelCount] = {30, 30, 30, 30, 30, 30, 30, 30};
// sACN: one universe per channel, up to 170 RGB pixels (510 DMX slots).
static constexpr uint16_t kMaxArgbPixelsPerFrame = 170;
static constexpr uint32_t kSerialBaud = 921600;

static constexpr uint32_t kFanPwmFrequencyHz = FAN_DC_PWM_HZ;
static constexpr uint32_t kTachMinEdgeUs = 300; // Reject electrical glitches, not normal fan pulses.
static constexpr uint32_t kTachMaxRpm = 15000;  // Reject impossible RPM samples.
static constexpr uint8_t kFanPwmResolutionBits = 8;
static constexpr uint8_t kTachPulsesPerRevolution = 2;
static constexpr uint32_t kRpmUpdateMs = 1000;

// Electrical output polarity depends on the SELECTED high-side gate driver.
// Default matches the old inverted prototype; confirm with oscilloscope before
// setting FAN_DC_PWM_VALIDATED=1. This cannot guarantee power ON during reset.
static constexpr bool kPwmDriverInverts = (FAN_OUTPUT_INVERTED != 0);
static constexpr uint8_t kInitialFanPercent = 100; // fail-safe full speed

static constexpr uint8_t kInitialArgbBrightness = 64; // 0..255
static constexpr uint32_t kArgbFrameMs = 40; // up to 25 FPS, updates strips sequentially

} // namespace board

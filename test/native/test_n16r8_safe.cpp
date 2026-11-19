#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "PinMapSettings.h"

int main() {
    static_assert(board::kN16R8Safe, "Run with -DFANARGB_N16R8_SAFE=1");
    static_assert(board::enabledChannelMask() == 0xFD, "FAN2/ARGB2 must be disabled");
    static_assert(!board::channelEnabled(1) && board::channelEnabled(0) &&
                  board::channelEnabled(2), "Expected seven active channels");
    assert(pinmap::settings().begin());
    assert(pinmap::validate(pinmap::settings().applied()));
    // Reserved PSRAM pins may exist in legacy defaults only as inactive
    // placeholders; never as new output assignments for other channels.
    assert(pinmap::allowed(35, 1));
    assert(pinmap::allowed(36, 9));
    assert(pinmap::allowed(37, 17));
    assert(!pinmap::allowed(35, 0));
    assert(!pinmap::allowed(34, 0));
    assert(!pinmap::allowed(37, 16));

    FanController fans;
    assert(fans.begin());
    assert(mock::pin[0] == board::kFanPwmPins[0]);
    assert(mock::pin[1] == 0);                 // ledcAttachPin never called
    assert(mock::handlers[36] == nullptr);    // no TACH interrupt on GPIO36
    assert(fans.getPercent(1) == 0);
    assert(!fans.canControl(1, 100));         // even 100% is not controllable
    assert(!fans.setPercent(1, 100));
    assert(!fans.hasRpmFeedback(1));
    assert(fans.getPercent(0) == 100);

    ArgbController leds;
    assert(leds.begin());
    assert(leds.pixelCount(1) == 0);          // no pin, no NeoPixel::show
    assert(leds.pixelCount(0) != 0);
    assert(!leds.setSolid(1, 255, 0, 0));
    assert(!leds.setOff(1));
    assert(!leds.setRainbow(1));
    assert(!leds.setBrightness(1, 100));
    assert(!leds.setEffectBoot(1, true));
    assert(!leds.configureStrip(1, 30, false));
    assert(leds.setSolid(0, 7, 20, 70));
    leds.update(100);
    // Saving global ARGB budget must never store an invalid 0-pixel count
    // for the inactive physical strip (would break NVS on next boot).
    assert(leds.setPowerBudget(2200));
    ArgbController restartedLeds;
    assert(restartedLeds.begin());
    assert(restartedLeds.pixelCount(0) == board::kArgbLedCounts[0]);
    assert(restartedLeds.pixelCount(1) == 0);

    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    assert(!cooling.canSetManual(1, 100));
    assert(!cooling.setManualMask(0x02, 100));
    assert(!cooling.setAutoMask(0x02));
    assert(cooling.setAutoMask(0xFD));
    assert(cooling.setManualMask(0xFD, 100));
    // No data yet: 10-second temperature watchdog still forces 100%.
    mock::currentMs = 15000;
    cooling.update(mock::currentMs);
    assert(fans.getPercent(0) == 100);
    assert(fans.getPercent(1) == 0);
    assert(mock::duty[1] == 0);
    std::cout << "PASS: N16R8 safe 7-channel GPIO isolation and thermal guard\n";
}

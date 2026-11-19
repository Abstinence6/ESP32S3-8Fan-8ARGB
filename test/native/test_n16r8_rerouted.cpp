#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "PinMapSettings.h"

int main() {
    static_assert(board::kN16R8Safe, "Require N16R8 PSRAM safety");
    static_assert(board::kN16R8Fan2Rerouted, "Use the opt-in rerouted build");
    static_assert(board::enabledChannelMask() == 0xFF, "8 channels after physical reroute");
    static_assert(board::kFanPwmPins[1] == 8 && board::kFanTachPins[1] == 11 &&
                  board::kArgbDataPins[1] == 17, "Unexpected replacement GPIO");

    pinmap::Settings pins;
    assert(pins.begin());
    assert(pinmap::validate(pins.applied()));
    assert(pins.applied().pwm[1] == 8);
    assert(pins.applied().tach[1] == 11);
    assert(pins.applied().argb[1] == 17);
    // A saved legacy map must never be accepted for the active output.
    assert(!pinmap::allowed(35, 1));
    assert(!pinmap::allowed(36, 9));
    assert(!pinmap::allowed(37, 17));
    assert(!pinmap::allowed(33, 1));
    assert(!pinmap::allowed(34, 9));
    assert(!pinmap::allowed(19, 1));
    assert(!pinmap::allowed(20, 9));

    FanController fans;
    assert(fans.begin());
    assert(mock::pin[1] == 8);             // LEDC for channel 2
    assert(mock::handlers[11] != nullptr); // FAN2 TACH interrupt
    assert(mock::handlers[36] == nullptr); // Never attach PSRAM interrupt
    assert(fans.setPercent(1, 100));
    assert(fans.getPercent(1) == 100);
    assert(fans.canControl(1, 55) == board::kDcSupplyPwmValidated);

    ArgbController rgb;
    assert(rgb.begin());
    assert(rgb.pixelCount(1) > 0);
    assert(rgb.setSolid(1, 15, 25, 35));
    rgb.update(100);

    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    assert(cooling.setAutoMask(0xFF));     // all eight logical channels available
    // With no temperature feedback, the safe output must stay at 100%.
    mock::currentMs = 15000;
    cooling.update(mock::currentMs);
    assert(fans.getPercent(1) == 100);
    assert(!cooling.faulted(1));
    if (board::kDcSupplyPwmValidated) {
        cooling.setTemperature(1, 410, mock::currentMs);
        assert(cooling.setManual(1, 55));
        assert(fans.getPercent(1) == 55);
        mock::currentMs += CoolingController::kSensorTimeoutMs + 1U;
        assert(cooling.setManual(1, 0));
        assert(fans.getPercent(1) == 100);
    } else {
        assert(!fans.setPercent(1, 55));
        assert(fans.getPercent(1) == 100);
    }
    std::cout << "PASS: N16R8 opt-in FAN2 reroute on GPIO8/11/17; "
              << "DC_READY=" << board::kDcSupplyPwmValidated << "\n";
}

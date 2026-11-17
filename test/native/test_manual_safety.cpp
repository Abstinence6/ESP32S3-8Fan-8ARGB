#include <cassert>
#include <iostream>

#include "Arduino.h"
#include "FanController.h"
#include "CoolingController.h"

int main() {
    // This test simulates a BENCH-VALIDATED DC driver and does not enable
    // partial-speed PWM in production builds.
    FanController fans;
    assert(fans.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());

    // No fresh temperature: accepting a manual preference may not drop power.
    assert(cooling.setManual(0, 25));
    assert(cooling.mode(0) == CoolingController::Mode::Manual);
    assert(fans.getPercent(0) == 100);

    // After startup and with fresh temperatures, manual speed may apply.
    mock::currentMs = 5000;
    cooling.setTemperature(0, 430, mock::currentMs);
    assert(cooling.setManual(0, 55));
    assert(fans.getPercent(0) == 55);

    // A previously safe manual output must immediately return to full PWM
    // when a stale sensor is followed by another manual command.
    mock::currentMs += CoolingController::kSensorTimeoutMs + 1U;
    assert(cooling.setManual(0, 30));
    assert(fans.getPercent(0) == 100);

    // Fresh but overcritical temperature must not be bypassed.
    cooling.setTemperature(0, 950, mock::currentMs);
    assert(cooling.setManual(0, 30));
    assert(fans.getPercent(0) == 100);

    // Hardware interlock and raw-temperature safety are separate safeguards.
    // A subsequent fresh safe reading enables the manual request again.
    cooling.setTemperature(0, 430, mock::currentMs + 100U);
    mock::currentMs += 100;
    assert(cooling.setManual(0, 40));
    assert(fans.getPercent(0) == 40);

    std::cout << "PASS: manual commands cannot bypass sensor, thermal or startup safety\n";
}

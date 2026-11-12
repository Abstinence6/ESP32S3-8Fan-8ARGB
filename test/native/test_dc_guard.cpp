#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "FanController.h"

int main() {
    FanController fans;
    assert(fans.begin());
    assert(fans.configuredType(0) == FanController::Type::ThreePin);
    assert(!fans.dcHardwareAvailable());
    assert(!fans.canControl(0, 50));
    assert(!fans.setPercent(0, 50));
    assert(fans.getPercent(0) == 100); // failed DC request cannot reduce fan power
    assert(mock::duty[0] == 0);        // inverted open-drain driver: high fan duty
    assert(fans.setPercent(0, 100));
    assert(fans.setType(0, FanController::Type::TwoPin));
    assert(!fans.hasRpmFeedback(0));
    assert(!fans.setPercent(0, 0));
    assert(fans.getPercent(0) == 100);
    assert(!fans.setType(0, static_cast<FanController::Type>(4)));
    assert(!fans.canControl(0, 50));
    assert(!fans.setPercent(0, 50));
    assert(fans.getPercent(0) == 100);
    assert(fans.detectedType(0) == FanController::Type::Unknown);
    assert(!fans.setType(0, FanController::Type::Auto));
    std::cout << "PASS: nonvalidated smart key is hard-gated to full fan power\n";
}

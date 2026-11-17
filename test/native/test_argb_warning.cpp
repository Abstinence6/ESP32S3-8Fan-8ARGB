#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "ArgbController.h"

int main() {
    ArgbController rgb;
    assert(rgb.begin());
    assert(rgb.setSolid(0, 0, 20, 160));
    rgb.update(700);
    const uint32_t normal = rgb.estimatedFullCurrent();
    rgb.setSafetyWarning(0, 2);
    rgb.update(1000);  // visible red phase
    assert(rgb.safetyWarning(0) == 2);
    assert(rgb.estimatedFullCurrent() > normal);
    rgb.update(1500);  // invisible phase
    assert(rgb.estimatedFullCurrent() == normal);
    rgb.setSafetyWarning(0, 1);
    rgb.update(2000);
    assert(rgb.estimatedFullCurrent() > normal);
    rgb.setSafetyWarning(0, 0);
    assert(rgb.estimatedFullCurrent() == normal);
    assert(rgb.getMode(0) == ArgbController::Mode::Solid);

    assert(rgb.setOff(1));
    rgb.setSafetyWarning(1, 3);
    rgb.update(2000);
    assert(rgb.estimatedFullCurrent() > normal);
    const uint8_t one[3] = {255, 255, 255};
    assert(rgb.setPixels(1, one, 1)); // OpenRGB cannot hide a safety warning
    assert(rgb.safetyWarning(1) == 3);
    assert(rgb.estimatedLimitedCurrent() <= rgb.powerBudget());
    rgb.setSafetyWarning(1, 0);
    rgb.update(2600);
    std::cout << "PASS: priority safety indication preserves scenes and current budget\n";
}

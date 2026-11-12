#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "BoardConfig.h"
#include "FanController.h"
int main() {
    FanController fans;
    assert(fans.begin());
    const uint8_t pin = board::kFanTachPins[0];
    mock::pulse(pin, 12);
    const uint32_t accepted = fans.tachPulseCount(0);
    mock::glitch(pin);
    assert(fans.tachPulseCount(0) == accepted); // 20us rejected
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    assert(fans.tachValid(0));
    assert(fans.getRpm(0) == 360);
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    assert(!fans.tachValid(0) && fans.getRpm(0) == 0);
    assert(fans.tachObserved(0)); // historical observation used for stall detection
    assert(fans.setType(0, FanController::Type::TwoPin));
    assert(!fans.tachTrustworthy(0) && !fans.tachValid(0));
    assert(fans.getRpm(0) == 0);
    std::cout << "PASS: TACH glitch rejection, fresh/stale, 2-pin untrusted\n";
}

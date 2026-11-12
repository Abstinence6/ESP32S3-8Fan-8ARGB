#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "BoardConfig.h"
#include "PcPowerController.h"

int main() {
    static_assert(board::kPcPowerPin == 33 && board::kPcSensePin == 34, "test pins");
    mock::currentMs = 0;
    mock::digitalLevels[34] = LOW; // PC initially off
    PcPowerController power;
    assert(power.begin());
    assert(mock::digitalLevels[33] == HIGH); // boot RELEASED
    assert(!power.request(PcPowerController::Action::On, 0)); // status unknown
    mock::currentMs = 1999; power.update(mock::currentMs);
    assert(power.state() == PcPowerController::State::Unknown);
    mock::currentMs = 2000; power.update(mock::currentMs);
    assert(power.state() == PcPowerController::State::Off);
    assert(!power.request(PcPowerController::Action::Off, 2000));
    assert(power.request(PcPowerController::Action::On, 2000));
    assert(mock::digitalLevels[33] == LOW && power.busy());
    assert(!power.request(PcPowerController::Action::On, 2100));
    power.update(2299);
    assert(mock::digitalLevels[33] == LOW);
    power.update(2300);
    assert(mock::digitalLevels[33] == HIGH && !power.busy());
    mock::digitalLevels[34] = HIGH;
    power.update(2400);
    assert(power.state() == PcPowerController::State::Off);
    power.update(2500);
    assert(power.state() == PcPowerController::State::On);
    assert(!power.request(PcPowerController::Action::ForceOff, 2500)); // cooldown
    assert(power.request(PcPowerController::Action::ForceOff, 3300));
    power.update(9299);
    assert(power.busy() && mock::digitalLevels[33] == LOW);
    power.update(9300);
    assert(!power.busy() && mock::digitalLevels[33] == HIGH);
    std::cout << "PASS: PC PWR_SW safe boot, state gating, pulses and force-off\n";
}

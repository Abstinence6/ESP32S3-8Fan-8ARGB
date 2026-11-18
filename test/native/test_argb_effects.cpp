#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "ArgbController.h"

int main() {
    ArgbController leds;
    assert(leds.begin());
    assert(leds.getMode(0) == ArgbController::Mode::Off);
    const size_t before = Preferences::writeCount();
    auto scene = argbeffects::defaults();
    scene.pattern = static_cast<uint8_t>(argbeffects::Pattern::Wave);
    scene.speed = 7;
    assert(leds.setEffect(0, scene));
    assert(leds.getMode(0) == ArgbController::Mode::Effect);
    for (uint32_t t = 40; t <= 500; t += 40) leds.update(t);
    assert(Preferences::writeCount() == before);
    assert(leds.estimatedLimitedCurrent() <= leds.powerBudget());
    leds.setSafetyWarning(0, 2);
    leds.update(1000);
    assert(leds.safetyWarning(0) == 2);
    assert(leds.estimatedLimitedCurrent() <= leds.powerBudget());
    assert(leds.setEffectBoot(0, false));
    assert(leds.saveEffects());
    assert(Preferences::writeCount() == before + 1);
    assert(leds.saveEffects());
    assert(Preferences::writeCount() == before + 1);
    ArgbController restarted;
    assert(restarted.begin());
    assert(restarted.getMode(0) == ArgbController::Mode::Off);
    assert(restarted.effect(0).pattern == scene.pattern);
    assert(restarted.startEffect(0));
    assert(restarted.getMode(0) == ArgbController::Mode::Effect);
    assert(restarted.setEffectBoot(0, true));
    assert(restarted.saveEffects());
    ArgbController optIn;
    assert(optIn.begin());
    assert(optIn.getMode(0) == ArgbController::Mode::Effect);
    assert(optIn.getMode(1) == ArgbController::Mode::Off);
    const uint8_t pixel[3] = {255,0,0};
    assert(optIn.setPixels(0, pixel, 1));
    assert(optIn.getMode(0) == ArgbController::Mode::External);
    optIn.update(5000);
    assert(optIn.getMode(0) == ArgbController::Mode::Off);
    Preferences prefs;
    assert(prefs.begin("argb-v4", false));
    const char corrupt[3] = {'b','a','d'};
    assert(prefs.putBytes("effects", corrupt, sizeof(corrupt)) == sizeof(corrupt));
    ArgbController fallback;
    assert(fallback.begin());
    assert(fallback.getMode(0) == ArgbController::Mode::Off);
    std::cout << "PASS: native ARGB effects, NVS opt-in and safety overlay\n";
}

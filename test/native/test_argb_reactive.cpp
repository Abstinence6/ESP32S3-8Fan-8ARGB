#include <cassert>
#include <cstring>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "ArgbController.h"

int main() {
    argbreaction::Config cfg = argbreaction::defaults();
    cfg.source = 26; // USB or MQTT slot 2
    cfg.fallback = 1; // local FAN 1 tach
    cfg.low = 100; cfg.high = 1000;
    cfg.style = static_cast<uint8_t>(argbreaction::Style::Bar);
    cfg.scene.brightness = 88;
    assert(argbreaction::valid(cfg));
    uint8_t pixels[30*3] = {};
    argbreaction::render(cfg, 30, 1000, 550, true, pixels);
    assert(pixels[0] != 0 || pixels[1] != 0 || pixels[2] != 0);
    assert(pixels[29*3] == 0 && pixels[29*3+1] == 0);
    argbreaction::render(cfg, 30, 2000, 0, false, pixels);
    assert(pixels[0] > pixels[2]); // Missing is amber, not blue/healthy.
    cfg.fallback = 25; // external slots are not valid autonomous fallbacks
    assert(!argbreaction::valid(cfg));
    cfg.fallback = 1;
    cfg.low = 1000; cfg.high = 100;
    assert(!argbreaction::valid(cfg));
    cfg.low = 100; cfg.high = 1000;

    ArgbController leds;
    assert(leds.begin());
    const size_t startWrites = Preferences::writeCount();
    assert(leds.setReactive(1, cfg));
    assert(leds.getMode(1) == ArgbController::Mode::Reactive);
    assert(Preferences::writeCount() == startWrites);
    assert(leds.setReactiveInput(26, 550, 1000));
    uint32_t actual = 0;
    assert(leds.reactiveInput(26, 1001, actual) && actual == 550);
    assert(!leds.reactiveInput(26, 9000, actual)); // stale external metric
    assert(leds.setReactiveInput(1, 15000, 9000)); // local fallback
    assert(leds.reactiveInput(1, 9000, actual));
    leds.update(9000);
    assert(leds.estimatedLimitedCurrent() <= leds.powerBudget());
    leds.setSafetyWarning(1, 2);
    leds.update(10000);
    assert(leds.safetyWarning(1) == 2);
    assert(leds.estimatedLimitedCurrent() <= leds.powerBudget());
    assert(leds.setReactiveBoot(1, false));
    assert(leds.saveReactive());
    assert(Preferences::writeCount() == startWrites + 1);
    assert(leds.saveReactive());
    assert(Preferences::writeCount() == startWrites + 1);
    ArgbController rebooted;
    assert(rebooted.begin());
    assert(rebooted.getMode(1) == ArgbController::Mode::Off);
    assert(rebooted.reactive(1).source == 26);
    assert(rebooted.setReactiveBoot(1, true));
    assert(rebooted.saveReactive());
    ArgbController optin;
    assert(optin.begin());
    assert(optin.getMode(1) == ArgbController::Mode::Reactive);
    assert(optin.getMode(0) == ArgbController::Mode::Off);
    const uint8_t rgb[3] = {255,0,0};
    assert(optin.setPixels(1, rgb, 1)); // OpenRGB overrides a reactive zone
    assert(optin.getMode(1) == ArgbController::Mode::External);
    optin.update(10000);
    assert(optin.getMode(1) == ArgbController::Mode::Off);
    Preferences storage;
    assert(storage.begin("argb-v4", false));
    const uint8_t corrupt[] = {1,2,3};
    assert(storage.putBytes("reactive",corrupt,sizeof(corrupt)) == sizeof(corrupt));
    ArgbController safe;
    assert(safe.begin());
    assert(safe.getMode(1) == ArgbController::Mode::Off);
    std::cout << "PASS: reactive RGB local fallback, remote TTL, boot opt-in and current safety\n";
}

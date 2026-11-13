#include <array>
#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "SerialConsole.h"

int main() {
    FanController fans;
    ArgbController lights;
    assert(fans.begin());
    assert(lights.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    std::array<uint8_t, 510> allWhite = {};
    allWhite.fill(255);
    for (uint8_t ch = 0; ch < 8; ++ch) {
        assert(lights.configureStripAndBudget(ch, 170, false, 2000));
        assert(lights.setPixels(ch, allWhite.data(), 170));
    }
    mock::currentMs = 1000;
    lights.update(mock::currentMs);
    assert(lights.estimatedFullCurrent() > 80000U);
    assert(lights.estimatedLimitedCurrent() <= lights.powerBudget());
    assert(lights.getMode(0) == ArgbController::Mode::External);
    // A budget-only edit and a no-op geometry edit must not clear live LEDs.
    assert(lights.configureStripAndBudget(0, 170, false, 1800));
    assert(lights.getMode(0) == ArgbController::Mode::External);
    assert(lights.configureStrip(0, 170, false));
    assert(lights.getMode(0) == ArgbController::Mode::External);
    assert(!lights.configureStripAndBudget(0, 170, false, 99));
    assert(lights.powerBudget() == 1800);

    SerialConsole console(Serial, fans, lights, cooling);
    console.begin();
    Serial.out.clear();
    Serial.send("VERSION?\nARGBCFG 1 170 0 1900 128\nFANCFG 1 3 88 250\nSTRIPCFG? 1\nCONFIG 1\nARGBSTATUS\n");
    console.poll();
    assert(Serial.out.find("SERIAL=7") != std::string::npos);
    assert(Serial.out.find("OK ARGBCFG_SAVED") != std::string::npos);
    assert(Serial.out.find("OK FANCFG_SAVED") != std::string::npos);
    assert(Serial.out.find("BRIGHT=128") != std::string::npos);
    assert(Serial.out.find("PPR=3 CRIT=88 STALL=250") != std::string::npos);
    assert(Serial.out.find("LIMITED_MA=") != std::string::npos);
    assert(lights.getMode(0) == ArgbController::Mode::External);
    Serial.out.clear();
    Serial.send("FANCFG 1 0 88 250\nARGBCFG 1 171 0 1900 128\n");
    console.poll();
    assert(Serial.out.find("ERR arguments") != std::string::npos);
    assert(cooling.pulsesPerRevolution(0) == 3);
    assert(lights.pixelCount(0) == 170);
    std::cout << "PASS: 64-bit RGB budget + atomic settings protocol\n";
}

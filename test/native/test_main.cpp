#include <cassert>
#include <iostream>

#include "Arduino.h"
#include "BoardConfig.h"
#include "FanController.h"
#include "ArgbController.h"
#include "SerialConsole.h"

int main() {
    FanController fans;
    ArgbController leds;
    assert(fans.begin());
    assert(leds.begin());
    for (unsigned ch = 0; ch < 8; ++ch) {
        assert(mock::duty[ch] == 0); // fan initially at full speed via inverted driver
        assert(fans.getPercent(ch) == 100);
    }

    assert(fans.setPercent(1, 0));
    assert(mock::duty[1] == 255);
    assert(fans.setPercent(0, 50));
    assert(mock::duty[0] == 127);
    assert(!fans.setPercent(8, 50));
    assert(!fans.setPercent(0, 101));

    mock::pulse(board::kFanTachPins[0], 40);
    mock::currentMs = 1000;
    fans.update(mock::currentMs);
    assert(fans.getRpm(0) == 1200);
    assert(fans.getRpm(1) == 0);
    mock::currentMs = 2000;
    fans.update(mock::currentMs);
    assert(fans.getRpm(0) == 0);

    SerialConsole console(Serial, fans, leds);
    console.begin();
    Serial.send("FAN 1 45\nLED 3 255 0 0\nBRIGHT 3 80\nRAINBOW 2\nSTATUS\n");
    console.poll();
    assert(fans.getPercent(0) == 45);
    assert(leds.getMode(2) == ArgbController::Mode::Solid);
    assert(leds.getBrightness(2) == 80);
    assert(leds.getMode(1) == ArgbController::Mode::Rainbow);
    assert(Serial.out.find("CH 1 FAN=45% RPM=0") != std::string::npos);

    Serial.out.clear();
    Serial.send("FAN 9 80\nFAN 1 101\nALLFAN 70\nALLOFF\n");
    console.poll();
    assert(Serial.out.find("ERR arguments") != std::string::npos);
    for (unsigned ch = 0; ch < 8; ++ch) {
        assert(fans.getPercent(ch) == 70);
        assert(leds.getMode(ch) == ArgbController::Mode::Off);
    }
    Serial.out.clear();
    Serial.send(std::string(120, 'A') + "\nFAN 2 60\n");
    console.poll();
    assert(Serial.out.find("ERR line too long") != std::string::npos);
    assert(fans.getPercent(1) == 60);

    leds.setRainbow(0);
    mock::currentMs = 2040;
    leds.update(mock::currentMs);
    std::cout << "PASS: 8 PWM, RPM, ARGB modes, serial commands, malformed inputs\n";
}

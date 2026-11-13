#include <cassert>
#include <iostream>

#include "Arduino.h"
#include "BoardConfig.h"
#include "FanController.h"
#include "ArgbController.h"
#include "SerialConsole.h"
#include "CoolingController.h"

int main() {
    FanController fans;
    ArgbController leds;
    assert(fans.begin());
    assert(leds.begin());
    for (unsigned ch = 0; ch < 8; ++ch) {
        assert(mock::duty[ch] == 255); // active-high 12V power enable
        assert(fans.getPercent(ch) == 100);
    }

    assert(fans.setPercent(1, 0));
    assert(mock::duty[1] == 0);
    assert(fans.setPercent(0, 50));
    assert(mock::duty[0] == 128);
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

    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    SerialConsole console(Serial, fans, leds, cooling);
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
    Serial.send(std::string(300, 'A') + "\nFAN 2 60\n");
    console.poll();
    assert(Serial.out.find("ERR line too long") != std::string::npos);
    assert(fans.getPercent(1) == 60);

    // USB binary pixel stream (sACN bridge) must coexist with text fan control.
    // Fixed Python reference: encode_rgb_frame(3, bytes.fromhex("ff000000ff00"))
    // == a55a030200ff000000ff00d0ed (CRC16-CCITT-FALSE).
    leds.setOff(2);
    const uint8_t pixelBytes[] = {0xA5, 0x5A, 0x03, 0x02, 0x00,
                                  0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00,
                                  0xD0, 0xED};
    std::string pixelPacket(reinterpret_cast<const char*>(pixelBytes), sizeof(pixelBytes));
    Serial.send(pixelPacket.substr(0, 7));
    console.poll();
    assert(leds.getMode(2) == ArgbController::Mode::Off);
    Serial.send(pixelPacket.substr(7) + "LEDS\nFAN 3 65\n");
    console.poll();
    assert(leds.getMode(2) == ArgbController::Mode::External);
    assert(leds.getBrightness(2) == 255);
    assert(fans.getPercent(2) == 65);
    assert(Serial.out.find("LEDCOUNTS 30 30 30 30 30 30 30 30") != std::string::npos);

    // Malformed CRC and partial frame timeout must be discarded without modifying pixels.
    leds.setOff(3);
    std::string badCrc = pixelPacket;
    badCrc[2] = 4;  // channel changed but checksum stays from channel 3
    Serial.send(badCrc);
    console.poll();
    assert(leds.getMode(3) == ArgbController::Mode::Off);
    Serial.send(pixelPacket.substr(0, 5));
    console.poll();
    mock::currentMs += 500;
    console.poll();  // discard truncated packet
    Serial.send("FAN 4 77\n");
    console.poll();
    assert(fans.getPercent(3) == 77);

    // Invalid RGB header: any following bytes must not execute fan commands.
    const uint8_t invalidLength[] = {0xA5, 0x5A, 0x02, 0xFF, 0x7F};
    Serial.send(std::string(reinterpret_cast<const char*>(invalidLength), 5) + "FAN 4 0\n");
    console.poll();
    assert(fans.getPercent(3) == 77);
    mock::currentMs += 500;
    console.poll();
    Serial.send("FAN 4 45\n");
    console.poll();
    assert(fans.getPercent(3) == 45);

    leds.setRainbow(0);
    mock::currentMs = 2040;
    leds.update(mock::currentMs);
    // Default curves start at 25% and reach full fan PWM at 80 C.
    assert(CoolingController::interpolate(cooling.curve(0), 250) == 25);
    assert(CoolingController::interpolate(cooling.curve(0), 800) == 100);
    assert(CoolingController::interpolate(cooling.curve(0), 425) == 45);
    CoolingController::CurvePoint bad[5] = {{25, 20}, {30, 40}, {20, 50}, {70, 80}, {80, 100}};
    assert(!cooling.setCurve(0, bad));
    CoolingController::CurvePoint custom[5] = {{20, 30}, {30, 40}, {45, 60}, {60, 80}, {75, 100}};
    assert(cooling.setCurve(0, custom));
    assert(cooling.curve(0)[0].pwm == 30);

    // Automatic control follows temperature, but falls back to 100% on link loss.
    assert(cooling.setAuto(0));
    assert(cooling.setStallThreshold(0, 0)); // no simulated tach for channel 1
    cooling.setTemperature(0, 450, mock::currentMs);
    for (int i = 0; i < 65; ++i) { mock::currentMs += 250; if (i % 8 == 0) cooling.setTemperature(0, 450, mock::currentMs); cooling.update(mock::currentMs); }
    assert(fans.getPercent(0) == 60);
    mock::currentMs += CoolingController::kSensorTimeoutMs + 500;
    cooling.update(mock::currentMs);
    assert(fans.getPercent(0) == 100);

    // Serial command persists a new five-point temperature curve.
    Serial.out.clear();
    Serial.send("CURVE 1 20 30 30 40 45 60 60 80 75 100\nCURVE? 1\nTEMP 1 425\nAUTO 1\nPING\n");
    console.poll();
    assert(Serial.out.find("OK CURVE_SAVED") != std::string::npos);
    assert(Serial.out.find("CURVE 1 20 30 30 40 45 60 60 80 75 100") != std::string::npos);
    assert(Serial.out.find("PONG 4") != std::string::npos);

    // A calibration sweep logs 21 PWM/RPM samples, then saves them to NVS.
    Serial.out.clear();
    cooling.setTemperature(2, 450, mock::currentMs);
    mock::pulse(board::kFanTachPins[2], 40);
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    mock::pulse(board::kFanTachPins[2], 40);
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    cooling.setTemperature(2, 450, mock::currentMs);
    assert(cooling.startCalibration(2, mock::currentMs));
    assert(!cooling.startCalibration(1, mock::currentMs));
    for (int step = 0; step < 21; ++step) {
        mock::currentMs += (step == 0 ? 1200 : 0);
        cooling.update(mock::currentMs);
        // Synthesize TACH pulses every 500 ms for a fan with RPM growing with PWM.
        for (int quarter = 0; quarter < 8; ++quarter) {
            mock::pulse(board::kFanTachPins[2], static_cast<unsigned>(step + 3));
            mock::currentMs += 500;
            cooling.setTemperature(2, 450, mock::currentMs);
            fans.update(mock::currentMs);
            cooling.update(mock::currentMs);
        }
    }
    assert(!cooling.calibrationActive());
    assert(cooling.hasCalibration(2));
    assert(cooling.rpmAt(2, 20) > 0);
    assert(Serial.out.find("CAL_POINT 3 100 ") != std::string::npos);
    assert(Serial.out.find("CAL_SAVED 3") != std::string::npos);

    // Simulate reboot: NVS state must survive object reconstruction.
    CoolingController afterReboot(fans, Serial);
    assert(afterReboot.begin());
    assert(afterReboot.hasCalibration(2));
    assert(afterReboot.rpmAt(2, 20) == cooling.rpmAt(2, 20));
    assert(afterReboot.curve(0)[0].pwm == 30);
    afterReboot.setTemperature(3, 450, mock::currentMs);
    mock::pulse(board::kFanTachPins[3], 40);
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    mock::pulse(board::kFanTachPins[3], 40);
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    afterReboot.setTemperature(3, 450, mock::currentMs);
    assert(afterReboot.startCalibration(3, mock::currentMs));
    assert(afterReboot.cancelCalibration());
    assert(!afterReboot.hasCalibration(3));

    // 3-pin is the first-boot default: two native GPIO per channel.
    FanController multi;
    assert(multi.begin());
    assert(multi.configuredType(0) == FanController::Type::ThreePin);
    assert(multi.dcHardwareAvailable()); // host simulation was compiled with PWM validated
    assert(multi.setPercent(0, 35));
    assert(multi.getPercent(0) == 35);
    assert(multi.setType(1, FanController::Type::TwoPin));
    assert(multi.setPercent(1, 40));
    assert(!multi.hasRpmFeedback(1));
    assert(multi.getRpm(1) == 0);
    assert(multi.setType(1, FanController::Type::ThreePin));
    assert(multi.hasRpmFeedback(1));
    assert(!multi.setType(2, static_cast<FanController::Type>(4)));
    assert(multi.configuredType(2) == FanController::Type::ThreePin);
    // No presence-sense line, so a physical fan type is never detected.
    assert(multi.detectedType(0) == FanController::Type::Unknown);
    assert(multi.detectedType(2) == FanController::Type::Unknown);
    assert(!multi.setType(0, static_cast<FanController::Type>(0)));
    Serial.out.clear();
    Serial.send("TYPE? 1\nTYPE 1 AUTO\nTYPE 1 3\nSTATUS\n");
    console.poll();
    assert(Serial.out.find("TYPE 1 SET=3 DETECTED=255 RPM_OK=1 DC_HW=1") != std::string::npos);
    assert(Serial.out.find("ERR TYPE must be 2 or 3") != std::string::npos);
    assert(Serial.out.find("OK TYPE_SAVED") != std::string::npos);
    assert(Serial.out.find("TYPE=3 RPM_OK=1") != std::string::npos);

    std::cout << "PASS: PWM, RPM, ARGB, serial, curves, NVS, calibration, fan types\n";
}

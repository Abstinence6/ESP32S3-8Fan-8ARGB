#include <cassert>
#include <iostream>
#include <string>

#include "Arduino.h"
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "SerialConsole.h"

int main() {
    FanController fans;
    ArgbController leds;
    assert(fans.begin());
    assert(leds.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    SerialConsole console(Serial, fans, leds, cooling);
    console.begin();

    // An unvalidated smart DC key must not acknowledge an ALLFAN request.
    Serial.out.clear();
    Serial.send("ALLFAN 35\n");
    console.poll();
    assert(Serial.out.find("ERR fan control blocked") != std::string::npos);
    for (int i=0; i<8; ++i) {
        assert(fans.getPercent(i) == 100);
        assert(cooling.mode(i) == CoolingController::Mode::Auto);
    }

    // No tach data yet: non-invasive health report must not claim detection.
    Serial.out.clear();
    Serial.send("HEALTH\n");
    console.poll();
    assert(Serial.out.find("HEALTH 1 TYPE=3") != std::string::npos);
    assert(Serial.out.find("DC_READY=0") != std::string::npos);
    assert(Serial.out.find("TACH=unseen") != std::string::npos);
    assert(Serial.out.find("HEALTH_END") != std::string::npos);

    // A disconnected/unconfirmed 3-pin TACH does not trigger a false stall alarm.
    for (int sec = 1; sec < 10; ++sec) {
        mock::currentMs = static_cast<uint32_t>(sec) * 1000U;
        fans.update(mock::currentMs);
        cooling.update(mock::currentMs);
    }
    assert(!cooling.faulted(1));
    Serial.out.clear();
    Serial.send("HEALTH 2\n");
    console.poll();
    assert(Serial.out.find("HEALTH 2 TYPE=3") != std::string::npos);
    assert(Serial.out.find("TACH=unseen") != std::string::npos);

    // 4-pin cannot bypass the unvalidated high-side power interlock.
    Serial.out.clear();
    Serial.send("TYPE 1 4\nFAN 1 50\nALLFAN 70\n");
    console.poll();
    assert(fans.getPercent(0) == 100);
    assert(fans.getPercent(1) == 100);
    assert(Serial.out.find("ERR TYPE must be 2 or 3") != std::string::npos);
    assert(Serial.out.find("ERR fan control blocked") != std::string::npos);

    // Tachometer was confirmed once; a subsequent stall must remain detectable
    // even while no PC temperatures are available and full speed is enforced.
    mock::pulse(board::kFanTachPins[0], 40);
    mock::currentMs += 1000;
    fans.update(mock::currentMs);
    cooling.update(mock::currentMs);
    assert(fans.getRpm(0) >= 1200);
    assert(!cooling.faulted(0));
    for (int sec = 2; sec < 35; ++sec) {
        mock::currentMs += 1000U;
        fans.update(mock::currentMs);
        cooling.update(mock::currentMs);
    }
    assert(cooling.faulted(0));
    assert(fans.getPercent(0) == 100);
    Serial.out.clear();
    Serial.send("HEALTH\n");
    console.poll();
    assert(Serial.out.find("HEALTH 1 TYPE=3") != std::string::npos);
    assert(Serial.out.find("TACH=seen") != std::string::npos);
    assert(Serial.out.find("FAULT=1") != std::string::npos);
    // All-fan 100% is permitted without a DC key, but guarded partial speed
    // must never transition a single channel to Manual.
    Serial.out.clear();
    Serial.send("ALLFAN 100\nALLAUTO\n");
    console.poll();
    assert(Serial.out.find("ERR") == std::string::npos);
    for (unsigned i = 0; i < 8; ++i) {
        assert(cooling.mode(i) == CoolingController::Mode::Auto);
        assert(fans.getPercent(i) == 100);
    }
    Serial.out.clear();
    Serial.send("HEALTH 0\nHEALTH 9\nHEALTH 1 extra\n");
    console.poll();
    assert(Serial.out.find("ERR arguments") != std::string::npos);
    // v4.2 SELFTEST is observational: no GPIO or mode changes.
    Serial.out.clear();
    Serial.send("SELFTEST\nSELFTEST\n");
    console.poll();
    assert(Serial.out.find("SELFTEST_STARTED 5000") != std::string::npos);
    assert(Serial.out.find("ERR selftest busy") != std::string::npos);
    mock::pulse(board::kFanTachPins[0], 20);
    mock::currentMs += 5000U;
    fans.update(mock::currentMs);
    console.poll();
    assert(Serial.out.find("SELFTEST 1 RESULT=OK PULSES=20") != std::string::npos);
    assert(Serial.out.find("SELFTEST 2 RESULT=NO_TACH") != std::string::npos);
    assert(Serial.out.find("SELFTEST_END") != std::string::npos);
    assert(fans.getPercent(0) == 100);
    assert(cooling.mode(0) == CoolingController::Mode::Auto);
    // Source tracing: local and USB readings preempt remote MQTT telemetry.
    cooling.setTemperature(3, 440, mock::currentMs);
    assert(std::string(cooling.temperatureSourceName(3)) == "usb");
    assert(!cooling.setMqttTemperature(3, 250, mock::currentMs + 1000U));
    cooling.setHardwareTemperature(3, 490, mock::currentMs + 2000U);
    assert(std::string(cooling.temperatureSourceName(3)) == "ds18b20");
    assert(cooling.temperatureAgeMs(3, mock::currentMs + 2500U) == 500U);
    assert(!cooling.setMqttTemperature(3, 350, mock::currentMs + 2500U));
    assert(cooling.setMqttTemperature(3, 350, mock::currentMs + 14000U));
    assert(std::string(cooling.temperatureSourceName(3)) == "mqtt");
    mock::currentMs += 14000U;
    Serial.out.clear();
    Serial.send("HEALTH 4\n");
    console.poll();
    assert(Serial.out.find("SOURCE=mqtt AGE_MS=0 FAILSAFE=dc_lock") != std::string::npos);
    mock::currentMs += CoolingController::kSensorTimeoutMs + 1U;
    assert(std::string(cooling.failSafeReason(3, mock::currentMs)) == "sensor");
    Serial.out.clear();
    Serial.send("HEALTH 4\n");
    console.poll();
    assert(Serial.out.find("SENSOR=stale SOURCE=mqtt") != std::string::npos);

    std::cout << "PASS: 2/3-pin guard, offline stall, health, SELFTEST\n";
}

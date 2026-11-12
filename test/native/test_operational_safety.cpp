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

    // 4-pin and partial duty must both be rejected without changing any fan.
    Serial.out.clear();
    Serial.send("TYPE 1 4\nFAN 1 50\nALLFAN 70\n");
    console.poll();
    assert(Serial.out.find("ERR only 2-pin or 3-pin") != std::string::npos);
    assert(fans.getPercent(0) == 100);
    assert(fans.getPercent(1) == 100);
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
    assert(Serial.out.find("TACH=stale") != std::string::npos);
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
    const uint8_t oldPwm = fans.getPercent(0);
    const auto oldMode = cooling.mode(0);
    Serial.out.clear();
    Serial.send("SELFTEST\nSELFTEST\n");
    console.poll();
    assert(Serial.out.find("SELFTEST_STARTED 5000") != std::string::npos);
    assert(Serial.out.find("ERR selftest busy") != std::string::npos);
    assert(fans.getPercent(0) == oldPwm);
    mock::pulse(board::kFanTachPins[0], 20);
    mock::currentMs += 5000U;
    fans.update(mock::currentMs);
    console.poll();
    assert(Serial.out.find("SELFTEST 1 RESULT=OK PULSES=20") != std::string::npos);
    assert(Serial.out.find("SELFTEST_END") != std::string::npos);
    assert(fans.getPercent(0) == oldPwm && cooling.mode(0) == oldMode);
    Serial.out.clear();
    Serial.send("TYPE 2 2\nSELFTEST\nSELFTEST CANCEL\n");
    console.poll();
    assert(Serial.out.find("SELFTEST_CANCELLED") != std::string::npos);
    std::cout << "PASS: atomic ALLFAN, offline stall, non-invasive health and TACH self-test\n";
}

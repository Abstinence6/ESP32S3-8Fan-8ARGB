#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "CoolingAssistSettings.h"
#include "FanController.h"
#include "CoolingController.h"

int main() {
    CoolingAssistSettings settings;
    assert(settings.begin());
    const auto before = settings.get();
    assert(before.enabled == 0);
    auto candidate = before;
    candidate.enabled = 1;
    candidate.role[0] = 1;   // intake
    candidate.source[0] = 3; // CPU/GPU peak
    candidate.role[1] = 2;   // exhaust
    candidate.source[1] = 1;
    candidate.maxPowerBoost = 20;
    candidate.intakeBias = 7;
    assert(CoolingAssistSettings::valid(candidate));
    assert(CoolingAssistSettings::boost(candidate, 0, 200, 300, 0) == 27);
    assert(CoolingAssistSettings::boost(candidate, 1, 200, 300, 0) == 20);
    assert(CoolingAssistSettings::boost(candidate, 0, UINT16_MAX, UINT16_MAX, 0) == 7);
    assert(CoolingAssistSettings::boost(candidate, 0, 200, 300, 7000) == 7);
    candidate.cpuFullW = candidate.cpuStartW;
    assert(!settings.set(candidate));
    candidate.cpuFullW = 160;
    Preferences::failNextWrite();
    assert(!settings.set(candidate));
    assert(settings.get().enabled == 0);
    assert(settings.set(candidate));
    const size_t writes = Preferences::writeCount();
    assert(settings.set(candidate));
    assert(Preferences::writeCount() == writes);
    CoolingAssistSettings restarted;
    assert(restarted.begin());
    assert(restarted.get().role[0] == 1);

    // Real cooling controller must apply only positive assists while fresh
    // temperature still gates every output. Unqualified power stages remain
    // at 100% regardless of the assistance settings.
    FanController fans;
    assert(fans.begin());
    CoolingController cooling(fans, Serial, &restarted);
    assert(cooling.begin());
    mock::currentMs = 5000;
    cooling.setPowerTelemetry(200, 300, mock::currentMs);
    cooling.update(mock::currentMs);
    assert(fans.getPercent(0) == 100); // no fresh temperature: full failsafe
    cooling.setTemperature(0, 440, mock::currentMs);
    cooling.update(mock::currentMs + 300);
    assert(fans.getPercent(0) == 100); // reset and DC interlock still win

    std::cout << "PASS: CPU/GPU predictive cooling, intake bias, NVS and fail-safe guard\n";
}

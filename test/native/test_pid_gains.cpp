#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "PidGainsSettings.h"
#include "FanController.h"
#include "CoolingController.h"

int main() {
    PidGainsSettings settings;
    assert(settings.begin());
    assert(settings.get(0).kpMilli == 30);
    assert(settings.get(0).kiMilli == 3);
    assert(settings.get(0).kdMilli == 4);
    auto candidate = settings.get(0);
    candidate.kpMilli = 25;
    candidate.kiMilli = 2;
    candidate.kdMilli = 0;
    assert(PidGainsSettings::valid(candidate));
    Preferences::failNextWrite();
    assert(!settings.set(0, candidate));
    assert(settings.get(0).kpMilli == 30);
    assert(settings.set(0, candidate));
    const size_t oldWrites = Preferences::writeCount();
    assert(settings.set(0, candidate));
    assert(Preferences::writeCount() == oldWrites);
    PidGainsSettings afterReset;
    assert(afterReset.begin());
    assert(afterReset.get(0).kpMilli == 25);
    assert(afterReset.get(1).kpMilli == 30);
    candidate.kpMilli = 200;
    assert(!settings.set(0, candidate));
    assert(settings.get(0).kpMilli == 25);
    Preferences bad;
    assert(bad.begin("pid-gains", false));
    const char invalid[] = "wrong";
    assert(bad.putBytes("fan1", invalid, sizeof(invalid)) == sizeof(invalid));
    PidGainsSettings fallback;
    assert(fallback.begin());
    assert(fallback.get(0).kpMilli == 30);

    FanController fans;
    assert(fans.begin());
    CoolingController cooling(fans, Serial, nullptr, &fallback);
    assert(cooling.begin());
    assert(!cooling.setPidGains(0, PidGainsSettings::defaults()));
    // No calibration or fresh TACH: must not accept a PID retune.
    std::cout << "PASS: PID gains independent CRC NVS and hardware interlock\n";
}

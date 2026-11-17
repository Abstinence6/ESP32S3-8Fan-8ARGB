#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "TemperaturePaletteSettings.h"

int main() {
    TemperaturePaletteSettings value;
    assert(value.begin());
    assert(value.get(0).count == 4);
    auto next = value.get(0);
    next.count = 5;
    next.points[4] = {105, 220, 10, 0};
    assert(value.set(0, next));
    const size_t writes = Preferences::writeCount();
    assert(value.set(0, next));
    assert(Preferences::writeCount() == writes);
    TemperaturePaletteSettings second;
    assert(second.begin());
    assert(second.get(0).count == 5);
    next.points[4].tempC = 45; // unsorted
    assert(!second.set(0, next));
    assert(second.get(0).count == 5);
    next.points[4].tempC = 115;
    Preferences::failNextWrite();
    assert(!second.set(0, next));
    assert(second.get(0).points[4].tempC == 105);
    assert(second.set(0, next));
    TemperaturePaletteSettings restarted;
    assert(restarted.begin());
    assert(restarted.get(0).points[4].tempC == 115);
    Preferences mem;
    assert(mem.begin("temp-pal", false));
    const char invalid[] = "broken";
    assert(mem.putBytes("p1", invalid, sizeof(invalid)) == sizeof(invalid));
    TemperaturePaletteSettings safe;
    assert(safe.begin());
    assert(safe.get(0).count == 4); // damaged NVS restores defaults
    std::cout << "PASS: temperature palette NVS atomicity, constraints, restoration\n";
}

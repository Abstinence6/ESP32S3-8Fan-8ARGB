#include <cassert>
#include <cstring>
#include <iostream>

#include "Arduino.h"
#include "Preferences.h"
#include "ArgbController.h"

int main() {
    ArgbController first;
    assert(first.begin());
    assert(first.getStoredBrightness(0) == board::kInitialArgbBrightness);
    const size_t startWrites = Preferences::writeCount();
    assert(first.setBrightness(2, 83));
    assert(first.getBrightness(2) == 83);
    assert(first.getStoredBrightness(2) == 83);
    assert(Preferences::writeCount() == startWrites + 1);
    assert(first.setBrightness(2, 83));
    assert(Preferences::writeCount() == startWrites + 1); // no NVS wear
    Preferences::failNextWrite();
    assert(!first.setBrightness(2, 84));
    assert(first.getStoredBrightness(2) == 83);
    assert(first.getBrightness(2) == 83);
    // External frames must never persist the temporary 255 brightness.
    const uint8_t pixel[] = {255, 30, 0};
    assert(first.setPixels(2, pixel, 1));
    assert(first.getBrightness(2) == 255);
    assert(first.getStoredBrightness(2) == 83);
    assert(Preferences::writeCount() == startWrites + 1);
    assert(first.setOff(2));
    assert(first.getBrightness(2) == 83);
    ArgbController restarted;
    assert(restarted.begin());
    assert(restarted.getBrightness(2) == 83);
    assert(restarted.getBrightness(1) == board::kInitialArgbBrightness);

    // NVS corruption must use safe factory brightness, not arbitrary bytes.
    Preferences store;
    assert(store.begin("argb-v4", false));
    const char bytes[] = "garbage";
    assert(store.putBytes("brightness", bytes, sizeof(bytes)) == sizeof(bytes));
    ArgbController fallback;
    assert(fallback.begin());
    assert(fallback.getBrightness(2) == board::kInitialArgbBrightness);
    std::cout << "PASS: ARGB brightness NVS persists without frame write wear\n";
}

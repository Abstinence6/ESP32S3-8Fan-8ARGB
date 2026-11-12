#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include "Arduino.h"
#include "CoolingController.h"

struct LegacyProfileV3 {
    uint32_t magic;
    uint8_t version;
    CoolingController::CurvePoint curve[5];
    CoolingController::CurvePoint secondCurve[5];
    uint16_t rpm[21];
    uint8_t calibrated;
    uint8_t minStart;
    uint8_t minRun;
    uint8_t ppr;
    uint8_t criticalC;
    uint16_t stallRpm;
    uint8_t pidEnabled;
    uint8_t dualEnabled;
    uint8_t fanType;
    uint32_t checksum;
};

static uint32_t checksum(const void* bytes, size_t size) {
    uint32_t h = 2166136261UL;
    auto data = static_cast<const uint8_t*>(bytes);
    for (size_t i=0; i<size; ++i) {
        h ^= data[i];
        h *= 16777619UL;
    }
    return h;
}

int main() {
    Preferences pref;
    assert(pref.begin("cooling-v1", false));
    LegacyProfileV3 v3 = {};
    v3.magic = 0x46414E53UL;
    v3.version = 3;
    v3.calibrated = 1;
    v3.pidEnabled = 1;
    v3.minStart = 15;
    v3.minRun = 12;
    v3.criticalC = 85;
    v3.stallRpm = 120;
    v3.ppr = 2;
    v3.fanType = 4; // must not survive 2/3-pin migration
    v3.rpm[20] = 1200;
    const CoolingController::CurvePoint curve[5] = {{25,30},{35,45},{50,60},{65,85},{80,100}};
    memcpy(v3.curve, curve, sizeof(curve));
    memcpy(v3.secondCurve, curve, sizeof(curve));
    v3.checksum = checksum(&v3, offsetof(LegacyProfileV3, checksum));
    assert(pref.putBytes("fan1", &v3, sizeof(v3)) == sizeof(v3));

    FanController fans;
    assert(fans.begin());
    CoolingController controller(fans, Serial);
    assert(controller.begin());
    assert(controller.fanType(0) == FanController::Type::ThreePin);
    assert(controller.curve(0)[0].pwm == 30);
    assert(!controller.hasCalibration(0));
    assert(!controller.closedLoop(0));
    assert(controller.rpmAt(0, 20) == 0);
    LegacyProfileV3 migrated = {};
    assert(pref.getBytes("fan1", &migrated, sizeof(migrated)) == sizeof(migrated));
    assert(migrated.version == 4 && migrated.fanType == 3 && migrated.calibrated == 0);
    assert(migrated.checksum == checksum(&migrated, offsetof(LegacyProfileV3, checksum)));

    // A corrupted saved profile must never reactivate old calibration.
    migrated.version = 3;
    migrated.calibrated = 1;
    migrated.fanType = 4;
    migrated.checksum ^= 3;
    pref.putBytes("fan2", &migrated, sizeof(migrated));
    CoolingController fresh(fans, Serial);
    assert(fresh.begin());
    assert(fresh.fanType(1) == FanController::Type::ThreePin);
    assert(!fresh.hasCalibration(1));
    assert(fresh.curve(1)[0].pwm == 25);
    std::cout << "PASS: v3 -> v4 NVS migration, curve retention and CRC guard\n";
}

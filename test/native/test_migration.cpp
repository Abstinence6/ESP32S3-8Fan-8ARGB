#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include "Arduino.h"
#include "BoardConfig.h"
#include "CoolingController.h"
#include "Preferences.h"

struct OldV3 {
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
uint32_t fnv(const void* data, size_t size) {
    const auto* bytes = static_cast<const uint8_t*>(data);
    uint32_t value = 2166136261UL;
    for (size_t i=0; i<size; ++i) { value ^= bytes[i]; value *= 16777619UL; }
    return value;
}
int main() {
    Preferences storage;
    assert(storage.begin("cooling-v1", false));
    OldV3 old = {};
    old.magic = 0x46414E53UL;
    old.version = 3;
    const CoolingController::CurvePoint points[5] = {{25, 25}, {35, 38}, {50, 65}, {65, 85}, {80, 100}};
    memcpy(old.curve, points, sizeof(points));
    memcpy(old.secondCurve, points, sizeof(points));
    old.calibrated = 1;
    old.minStart = 5;
    old.minRun = 5;
    old.rpm[20] = 2100;
    old.ppr = 2;
    old.criticalC = 90;
    old.stallRpm = 120;
    old.pidEnabled = 1;
    old.fanType = 4; // old hardware mode no longer exists
    old.checksum = fnv(&old, offsetof(OldV3, checksum));
    assert(storage.putBytes("fan1", &old, sizeof(old)) == sizeof(old));
    OldV3 corrupt = old;
    corrupt.curve[0].pwm = 99; // invalid CRC and monotonicity
    assert(storage.putBytes("fan2", &corrupt, sizeof(corrupt)) == sizeof(corrupt));
    FanController fans;
    assert(fans.begin());
    CoolingController controller(fans, Serial);
    assert(controller.begin());
    assert(controller.fanType(0) == FanController::Type::ThreePin);
    assert(controller.curve(0)[1].pwm == 38);
    assert(!controller.hasCalibration(0));
    assert(!controller.closedLoop(0));
    assert(controller.minStartPwm(0) == 30);
    assert(controller.minRunPwm(0) == 20);
    assert(controller.curve(1)[0].pwm == 25);
    OldV3 migrated = {};
    assert(storage.getBytes("fan1", &migrated, sizeof(migrated)) == sizeof(migrated));
    assert(migrated.version == 4 && migrated.fanType == 3 && migrated.calibrated == 0);
    assert(migrated.checksum == fnv(&migrated, offsetof(OldV3, checksum)));
    assert(!controller.setFanType(0, static_cast<FanController::Type>(4)));
    std::cout << "PASS: old v3 NVS migrated, curves retained, unsafe calibration reset\n";
}

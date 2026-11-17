#include <cassert>
#include <cstring>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "TemperatureArgbSettings.h"
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "SerialConsole.h"

int main() {
    TemperatureArgbSettings cfg;
    assert(cfg.begin());
    assert(std::strcmp(cfg.zone(0).source, "__OFF__") == 0);
    assert(!cfg.commit(0));
    assert(cfg.start(0, 100));
    assert(cfg.setSource("nwinfo/cpu/package", 100));
    assert(cfg.addMember("nwinfo/cpu/package", 100));
    assert(!cfg.addMember("nwinfo/cpu/package", 100)); // no duplicates
    assert(cfg.setRange(35, 85, 70, 100));
    assert(!cfg.setRange(90, 40, 70, 100));
    assert(!cfg.start(1, 100)); // one writer
    Preferences::failNextWrite();
    assert(!cfg.commit(100)); // NVS failure leaves old record intact
    assert(std::strcmp(cfg.zone(0).source, "__OFF__") == 0);
    assert(cfg.commit(100));
    assert(std::strcmp(cfg.zone(0).source, "nwinfo/cpu/package") == 0);
    assert(cfg.zone(0).brightness == 70);
    TemperatureArgbSettings recovered;
    assert(recovered.begin());
    assert(recovered.zone(0).groupCount == 1);
    assert(std::strcmp(recovered.zone(0).groups[0], "nwinfo/cpu/package") == 0);
    assert(recovered.zone(0).lowC == 35);
    const auto writes = Preferences::writeCount();
    assert(recovered.start(0, 200));
    assert(recovered.setSource("nwinfo/cpu/package", 200));
    assert(recovered.addMember("nwinfo/cpu/package", 200));
    assert(recovered.setRange(35, 85, 70, 200));
    assert(recovered.commit(200));
    assert(Preferences::writeCount() == writes); // NVS wear prevention
    assert(recovered.start(1, 0));
    assert(!recovered.setSource("invalid", 30001)); // expired transaction
    assert(!recovered.commit(30001));

    FanController fans;
    ArgbController leds;
    assert(fans.begin() && leds.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    SerialConsole serial(Serial, fans, leds, cooling, nullptr, nullptr, nullptr, nullptr, &recovered);
    serial.begin();
    Serial.out.clear();
    Serial.send(
        "TARGB BEGIN 2\n"
        "TARGB SOURCE 5F5F47524F55505F4D41585F5F\n" // __GROUP_MAX__
        "TARGB GROUP 6E77696E666F2F6370752F7061636B616765\n"
        "TARGB GROUP 6E77696E666F2F6770752F686F7473706F74\n"
        "TARGB RANGE 30 95 100\nTARGB COMMIT\nTARGB? 2\n"
    );
    serial.poll();
    assert(Serial.out.find("ERR") == std::string::npos);
    assert(Serial.out.find("OK TARGB_SAVED") != std::string::npos);
    assert(Serial.out.find("SOURCE_HEX=5F5F47524F55505F4D41585F5F") != std::string::npos);
    assert(Serial.out.find("TARGB_GROUP CH=2 ID_HEX=") != std::string::npos);
    assert(Serial.out.find("TARGB_END CH=2") != std::string::npos);
    TemperatureArgbSettings postReboot;
    assert(postReboot.begin());
    assert(std::strcmp(postReboot.zone(1).source, "__GROUP_MAX__") == 0);
    assert(postReboot.zone(1).groupCount == 2);

    // A corrupted record must not be used to drive an ARGB source.
    Preferences storage;
    assert(storage.begin("temp-argb", false));
    const uint8_t corruption[] = {0, 1, 2, 3};
    assert(storage.putBytes("z2", corruption, sizeof(corruption)) == sizeof(corruption));
    TemperatureArgbSettings fallback;
    assert(fallback.begin());
    assert(std::strcmp(fallback.zone(1).source, "__OFF__") == 0);
    std::cout << "PASS: ARGB temperature settings persisted and CRC-validated\n";
}

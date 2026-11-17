#include <cassert>
#include <cstring>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "PinMapSettings.h"

int main() {
    pinmap::Settings cfg;
    assert(cfg.begin());
    assert(pinmap::validate(cfg.saved()));
    assert(cfg.applied().pwm[0] == board::kFanPwmPins[0]);
    assert(cfg.applied().argb[6] == board::kArgbDataPins[6]);
    // ESP32-S3 GPIO22-25 do not exist; flash, USB, strapping and
    // octal-PSRAM/flash pins are excluded from NEW assignments.
    assert(!pinmap::allowed(22, 0));
    assert(!pinmap::allowed(28, 0));
    assert(!pinmap::allowed(20, 0));
    assert(!pinmap::allowed(0, 0));
    assert(!pinmap::allowed(35, 0));
    assert(!pinmap::allowed(46, 0));
    assert(pinmap::allowed(board::kFanPwmPins[1], 1));

    assert(cfg.start(100));
    assert(!cfg.start(100));
    assert(cfg.set(0, 0, cfg.saved().tach[0], 100)); // duplicate GPIO
    assert(!cfg.commit(100)); // staged invalid config cannot alter flash
    assert(!cfg.rebootNeeded());
    cfg.cancel();

    // Move FAN1 PWM to a verified free pin, keeping the current wiring
    // untouched until next reboot.
    assert(cfg.start(200));
    assert(cfg.set(0, 0, 18, 200));
    assert(pinmap::validate(cfg.applied()));
    Preferences::failNextWrite();
    assert(!cfg.commit(200));
    assert(cfg.saved().pwm[0] == board::kFanPwmPins[0]);
    assert(cfg.commit(200));
    assert(cfg.saved().pwm[0] == 18);
    assert(cfg.applied().pwm[0] == board::kFanPwmPins[0]);
    assert(cfg.rebootNeeded());

    pinmap::Settings rebooted;
    assert(rebooted.begin());
    assert(rebooted.applied().pwm[0] == 18);
    assert(!rebooted.rebootNeeded());
    assert(rebooted.factory(300));
    assert(rebooted.saved().pwm[0] == board::kFanPwmPins[0]);
    assert(rebooted.applied().pwm[0] == 18);
    assert(rebooted.rebootNeeded());
    pinmap::Settings restored;
    assert(restored.begin());
    assert(restored.applied().pwm[0] == board::kFanPwmPins[0]);

    // CRC/size failure is not allowed to select an unverified power GPIO.
    Preferences storage;
    assert(storage.begin("pinmap-v1", false));
    const uint8_t invalid[] = {1, 2, 3, 4};
    assert(storage.putBytes("pins", invalid, sizeof(invalid)) == sizeof(invalid));
    pinmap::Settings corrupted;
    assert(corrupted.begin());
    assert(pinmap::validate(corrupted.applied()));
    assert(corrupted.applied().pwm[0] == board::kFanPwmPins[0]);
    std::cout << "PASS: GPIO NVS validation, rollback and reboot-only apply\n";
}

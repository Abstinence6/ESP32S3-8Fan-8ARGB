#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "SerialConsole.h"

FanController fans;
ArgbController leds;
SerialConsole console(Serial, fans, leds);

void setup() {
    Serial.begin(115200);
    // No 'while (!Serial)' here: fan control must start without a PC attached.
    if (!fans.begin()) {
        Serial.println(F("FATAL: unable to configure 8 PWM channels"));
        // Leave the fan PWM outputs in their last state; do NOT start RGB.
        // For a guaranteed electrical fail-safe, the external driver must
        // release PWM input HIGH whenever the MCU is off or reset.
        while (true) delay(1000);
    }
    if (!leds.begin()) {
        Serial.println(F("FATAL: unable to initialize ARGB strips"));
        while (true) delay(1000);
    }
    console.begin();
}

void loop() {
    console.poll();
    const uint32_t now = millis();
    fans.update(now);
    leds.update(now);
    delay(1);
}

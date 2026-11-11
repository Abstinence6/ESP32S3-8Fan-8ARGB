#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "SerialConsole.h"
#include "CoolingController.h"
#include "NetworkRgbBridge.h"

FanController fans;
ArgbController leds;
CoolingController cooling(fans, Serial);
NetworkRgbBridge wifiRgb(leds);
SerialConsole console(Serial, fans, leds, cooling, &wifiRgb);

void setup() {
#if !ARDUINO_USB_CDC_ON_BOOT
    // 921600 baud plus blocking NeoPixel::show() needs a large UART RX ring.
    Serial.setRxBufferSize(4096);
#endif
    Serial.begin(board::kSerialBaud);
    // No 'while (!Serial)' here: fan control must start without a PC attached.
    if (!fans.begin()) {
        Serial.println(F("FATAL: unable to configure 8 PWM channels"));
        // Leave the fan PWM outputs in their last state; do NOT start RGB.
        // For a guaranteed electrical fail-safe, the external driver must
        // release PWM input HIGH whenever the MCU is off or reset.
        while (true) delay(1000);
    }
    if (!cooling.begin()) {
        Serial.println(F("FATAL: NVS initialization failed"));
        while (true) delay(1000);
    }
    if (!leds.begin()) {
        Serial.println(F("FATAL: unable to initialize ARGB strips"));
        while (true) delay(1000);
    }
    wifiRgb.begin();
    console.begin();
}

void loop() {
    console.poll();
    const uint32_t now = millis();
    fans.update(now);
    cooling.update(now);
    wifiRgb.update(now);
    leds.update(now);
    delay(1);
}

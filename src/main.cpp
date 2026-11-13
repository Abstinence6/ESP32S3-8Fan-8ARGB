#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "SerialConsole.h"
#include "CoolingController.h"
#include "NetworkRgbBridge.h"
#include "MqttBridge.h"
#include "PcPowerController.h"
#include "HardwareTemperature.h"

#if defined(ARDUINO_ARCH_ESP32)
#include <esp_task_wdt.h>
#include <esp_err.h>
namespace { bool watchdogArmed = false; }
#endif

FanController fans;
ArgbController leds;
CoolingController cooling(fans, Serial);
NetworkRgbBridge wifiRgb(leds);
PcPowerController pcPower;
HardwareTemperature hardwareTemp;
MqttBridge mqtt(cooling, fans, leds, wifiRgb, &pcPower);
SerialConsole console(Serial, fans, leds, cooling, &wifiRgb, &mqtt, &pcPower, &hardwareTemp);

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
    pcPower.begin();
    if (!hardwareTemp.begin()) Serial.println(F("WARN: hardware DS18B20 NVS unavailable"));
    wifiRgb.begin();
    if (!mqtt.begin()) Serial.println(F("WARN: MQTT NVS unavailable"));
    console.begin();
#if defined(ARDUINO_ARCH_ESP32)
    // Software recovery from a stalled Arduino loop. Electrical full-speed
    // during MCU reset still requires a physically qualified fail-ON driver.
    const esp_err_t init = esp_task_wdt_init(8, true);
    if (init == ESP_OK || init == ESP_ERR_INVALID_STATE) {
        const esp_err_t add = esp_task_wdt_add(nullptr);
        watchdogArmed = add == ESP_OK || esp_task_wdt_status(nullptr) == ESP_OK;
    }
    if (!watchdogArmed) Serial.println(F("WARN: loop task watchdog not armed"));
#endif
}

void loop() {
    console.poll();
    const uint32_t now = millis();
    fans.update(now);
    hardwareTemp.update(now, cooling);
    cooling.update(now);
    pcPower.update(now);
    wifiRgb.update(now);
    mqtt.update(now);
    leds.update(now);
#if defined(ARDUINO_ARCH_ESP32)
    // Never feed before the temperature/fan safety logic and communication tasks.
    if (watchdogArmed) esp_task_wdt_reset();
#endif
    delay(1);
}

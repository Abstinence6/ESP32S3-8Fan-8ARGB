#include <Arduino.h>
#include "FanController.h"
#include "ArgbController.h"
#include "SerialConsole.h"
#include "CoolingController.h"
#include "NetworkRgbBridge.h"
#include "MqttBridge.h"
#include "PcPowerController.h"
#include "HardwareTemperature.h"
#include "PinMapSettings.h"
#include "CoolingAssistSettings.h"
#include "PidGainsSettings.h"
#include "TemperatureArgbSettings.h"
#include "TemperaturePaletteSettings.h"
#include "OfflineProfiles.h"
#include "AirflowAssistant.h"
#include <string.h>

#if defined(ARDUINO_ARCH_ESP32)
#include <esp_task_wdt.h>
#include <esp_err.h>
namespace { bool watchdogArmed = false; }
#endif

FanController fans;
ArgbController leds;
CoolingAssistSettings coolingAssist;
PidGainsSettings pidGainsSettings;
CoolingController cooling(fans, Serial, &coolingAssist, &pidGainsSettings);
OfflineProfiles offlineProfiles(cooling, leds);
AirflowAssistant airflowAssistant(fans);
NetworkRgbBridge wifiRgb(leds);
PcPowerController pcPower;
HardwareTemperature hardwareTemp;
TemperatureArgbSettings temperatureArgbSettings;
TemperaturePaletteSettings temperaturePaletteSettings;
MqttBridge mqtt(cooling, fans, leds, wifiRgb, &pcPower);
SerialConsole console(Serial, fans, leds, cooling, &wifiRgb, &mqtt, &pcPower, &hardwareTemp, &temperatureArgbSettings, &temperaturePaletteSettings, &offlineProfiles, &airflowAssistant);

void setup() {
#if !ARDUINO_USB_CDC_ON_BOOT
    // 921600 baud plus blocking NeoPixel::show() needs a large UART RX ring.
    Serial.setRxBufferSize(4096);
#endif
    Serial.begin(board::kSerialBaud);
    // No 'while (!Serial)' here: fan control must start without a PC attached.
    if (!pinmap::settings().begin()) {
        Serial.println(F("FATAL: GPIO map NVS invalid; outputs NOT initialized"));
        Serial.println(F("Recover with PC powered off; hardware fan fail-ON required"));
        while (true) delay(1000);
    }
    if (!fans.begin()) {
        Serial.println(F("FATAL: unable to configure 8 PWM channels"));
        // Leave the fan PWM outputs in their last state; do NOT start RGB.
        // For a guaranteed electrical fail-safe, the external driver must
        // release PWM input HIGH whenever the MCU is off or reset.
        while (true) delay(1000);
    }
    if (!coolingAssist.begin()) Serial.println(F("WARN: cooling assist NVS unavailable"));
    if (!pidGainsSettings.begin()) Serial.println(F("WARN: PID tuning NVS unavailable"));
    if (!cooling.begin()) {
        Serial.println(F("FATAL: NVS initialization failed"));
        while (true) delay(1000);
    }
    if (!leds.begin()) {
        Serial.println(F("FATAL: unable to initialize ARGB strips"));
        while (true) delay(1000);
    }
    if (!offlineProfiles.begin()) Serial.println(F("WARN: offline profile NVS unavailable"));
    if (!airflowAssistant.begin()) Serial.println(F("WARN: airflow NVS unavailable"));
    pcPower.begin();
    if (!hardwareTemp.begin()) Serial.println(F("WARN: hardware DS18B20 NVS unavailable"));
    wifiRgb.begin();
    if (!mqtt.begin()) Serial.println(F("WARN: MQTT NVS unavailable"));
    if (!temperatureArgbSettings.begin()) Serial.println(F("WARN: temperature ARGB NVS unavailable"));
    if (!temperaturePaletteSettings.begin()) Serial.println(F("WARN: temperature palette NVS unavailable"));
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
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const char* reason = cooling.failSafeReason(ch, now);
        const uint8_t warning = strcmp(reason, "overheat") == 0 ? 2 :
            strcmp(reason, "fault") == 0 ? 3 :
            strcmp(reason, "sensor") == 0 ? 1 : 0;
        leds.setSafetyWarning(ch, warning);
    }
    pcPower.update(now);
    wifiRgb.update(now);
    mqtt.update(now);
    // Native visual sensors are sampled AFTER cooling/safety. They must never
    // change PWM, PID or the thermal watchdog. Unavailable readings expire.
    const uint32_t rgbNow = millis();
    static uint32_t lastReactiveSensorsMs = 0;
    // Avoid expensive DS18B20 ROM formatting in the cooling loop on every
    // iteration. Live RGB input changes at most once per 250 ms.
    if (leds.reactiveActive() && rgbNow-lastReactiveSensorsMs >= 250U) {
      lastReactiveSensorsMs = rgbNow;
      for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
        if (fans.tachReliable(ch))
            leds.setReactiveInput(1U+ch, fans.getRpm(ch)*10U, rgbNow);
        else
            leds.invalidateReactiveInput(1U+ch);
        if (cooling.temperatureFresh(ch, rgbNow))
            leds.setReactiveInput(9U+ch, cooling.temperature(ch), rgbNow);
        else
            leds.invalidateReactiveInput(9U+ch);
        char rom[17] = {};
        uint16_t temp = 0;
        uint32_t age = 0;
        bool valid = false;
        if (hardwareTemp.sensorInfo(ch, rom, temp, valid, age, rgbNow) && valid)
            leds.setReactiveInput(17U+ch, temp, rgbNow);
        else
            leds.invalidateReactiveInput(17U+ch);
        leds.setReactiveInput(33U+ch, cooling.appliedPwm(ch)*10U, rgbNow);
      }
    }
    // Network callbacks may stamp fresh frames after the loop timestamp.
    leds.update(rgbNow);
#if defined(ARDUINO_ARCH_ESP32)
    // Never feed before the temperature/fan safety logic and communication tasks.
    if (watchdogArmed) esp_task_wdt_reset();
#endif
    delay(1);
}

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <stdint.h>
#include <stddef.h>

// ESP32-S3-WROOM-1-N16R8 ONLY: 16 MB QSPI Flash + 8 MB Octal PSRAM.
// Deliberately NOT a cooling firmware. No fan PWM/TACH, ARGB, NVS,
// power-control, Wi-Fi, MQTT or arbitrary user GPIO is ever initialised.
// This intentionally excludes main.cpp and all other src/*.cpp in PlatformIO.

namespace {
static const size_t kTestBytes = 4096;
static uint32_t lastReportMs = 0;
static bool psramPresent = false;
static bool psramTestOk = false;
static unsigned resetReason = 0;

bool verifyPsram() {
    if (!psramFound()) return false;
    uint8_t* const data = static_cast<uint8_t*>(
        heap_caps_malloc(kTestBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!data) return false;
    for (size_t i=0;i<kTestBytes;++i)
        data[i]=static_cast<uint8_t>((i ^ (i >> 3U) ^ 0xA5U) & 0xFFU);
    bool success=true;
    for (size_t i=0;i<kTestBytes;++i) {
        const uint8_t expected=static_cast<uint8_t>(
            (i ^ (i >> 3U) ^ 0xA5U) & 0xFFU);
        if (data[i] != expected) {
            success=false;
            break;
        }
    }
    heap_caps_free(data);
    return success;
}

void report() {
    Serial.print(F("N16R8_DIAG uptime_ms="));
    Serial.print(millis());
    Serial.print(F(" reset_reason="));
    Serial.print(resetReason);
    Serial.print(F(" flash_bytes="));
    Serial.print(ESP.getFlashChipSize());
    Serial.print(F(" psram_bytes="));
    Serial.print(ESP.getPsramSize());
    Serial.print(F(" psram_present="));
    Serial.print(psramPresent ? 1 : 0);
    Serial.print(F(" psram_test="));
    Serial.print(psramTestOk ? "PASS" : "FAIL");
    Serial.print(F(" free_internal_heap="));
    Serial.println(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}
} // namespace

void setup() {
    Serial.begin(115200);
    resetReason = static_cast<unsigned>(esp_reset_reason());
    psramPresent = psramFound();
    psramTestOk = verifyPsram();
    Serial.println(F("N16R8_DIAG firmware: native USB, 16MB flash, 8MB OPI PSRAM"));
    Serial.println(F("N16R8_DIAG IMPORTANT: outputs disabled; do NOT power fans/ARGB."));
    report();
}

void loop() {
    const uint32_t now=millis();
    if (now-lastReportMs>=1000U) {
        lastReportMs=now;
        report();
    }
    delay(10);
}

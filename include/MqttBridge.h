#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include "FanController.h"
#include "CoolingController.h"
#include "ArgbController.h"

#if defined(ARDUINO_ARCH_ESP32)
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#endif

// Local MQTT / Home Assistant bridge. Network I/O runs in a separate task:
// the cooling loop never waits for a broker/TCP reconnect or MQTT publishes.
// Commands are queued and applied ONLY by update() in the controller loop.
class MqttBridge {
public:
    bool begin(FanController& fans, CoolingController& cooling, ArgbController& argb);
    void update(uint32_t nowMs);
    bool setHost(const char* host, uint16_t port);
    bool setAuth(const char* user, const char* password);
    bool setPrefix(const char* prefix);
    bool setEnabled(bool enabled);
    void printStatus(Stream& out) const;

private:
    struct Config {
        uint32_t magic = 0x4D515454UL;
        uint16_t version = 1;
        uint16_t port = 1883;
        uint8_t enabled = 0;
        char host[64] = {};
        char user[33] = {};
        char password[65] = {};
        char prefix[48] = "esp32s3/fanargb";
        uint32_t crc = 0;
    };
    struct Command {
        enum Kind : uint8_t { FanDuty, FanAuto, Temperature, ArgbColor, ArgbOff, ArgbRainbow, Brightness } kind;
        uint8_t channel;
        uint16_t value;
        uint8_t red, green, blue;
    };
    struct Snapshot {
        uint8_t pwm[board::kChannelCount] = {};
        uint16_t rpm[board::kChannelCount] = {};
        uint16_t temp[board::kChannelCount] = {};
        uint8_t tempFresh[board::kChannelCount] = {};
        uint8_t type[board::kChannelCount] = {};
        uint8_t fault[board::kChannelCount] = {};
        uint8_t tach[board::kChannelCount] = {};
        uint8_t mode[board::kChannelCount] = {};
        uint8_t rgbMode[board::kChannelCount] = {};
        uint8_t rejected[board::kChannelCount] = {};
        uint8_t dcReady = 0;
    };

    static uint32_t checksum(const Config& value);
    bool save(const Config& value);
    bool setConfig(const Config& value);
    FanController* fans_ = nullptr;
    CoolingController* cooling_ = nullptr;
    ArgbController* argb_ = nullptr;
    Preferences storage_;
    Config config_;
    uint32_t lastSnapshotMs_ = 0;
    uint8_t rejected_[board::kChannelCount] = {};

#if defined(ARDUINO_ARCH_ESP32)
    static void taskEntrypoint(void* arg);
    void networkLoop();
    void receive(char* topic, uint8_t* payload, unsigned int length);
    QueueHandle_t commands_ = nullptr;
    QueueHandle_t snapshots_ = nullptr;
    SemaphoreHandle_t configLock_ = nullptr;
    TaskHandle_t task_ = nullptr;
    volatile uint32_t configRevision_ = 0;
    volatile bool connected_ = false;
    static MqttBridge* callbackInstance_;
#endif
};

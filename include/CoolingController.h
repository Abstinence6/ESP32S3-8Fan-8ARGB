#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include "FanController.h"

// Persistent cooling control for eight independent fans. The temperature stream
// comes from the desktop agent. Missing telemetry always means MAX fan speed.
class CoolingController {
public:
    static constexpr uint8_t kCurvePoints = 5;
    static constexpr uint8_t kCalibrationPoints = 21;
    static constexpr uint32_t kSensorTimeoutMs = 10000;
    static constexpr uint8_t kFaultCapacity = 16;

    struct CurvePoint { uint8_t tempC; uint8_t pwm; };
    enum class Mode : uint8_t { Auto, Manual, Calibration, FixedRpm };
    enum class Fault : uint8_t { Stall = 1, Overheat = 2, SensorTimeout = 3, CalibrationAborted = 4 };
    struct FaultRecord { uint32_t uptimeSeconds; uint8_t channel; uint8_t code; };

    explicit CoolingController(FanController& fans, Stream& events);
    bool begin();
    void update(uint32_t nowMs);
    void setTemperature(uint8_t ch, uint16_t deciC, uint32_t nowMs, bool secondary = false);
    bool setCurve(uint8_t ch, const CurvePoint* points, bool secondary = false);
    const CurvePoint* curve(uint8_t ch, bool secondary = false) const;
    bool setManual(uint8_t ch, uint8_t pwm);
    bool canSetManual(uint8_t ch, uint8_t pwm) const;
    bool setFixedRpm(uint8_t ch, uint16_t rpm);
    bool setAuto(uint8_t ch);
    bool startCalibration(uint8_t ch, uint32_t nowMs, bool smart = false);
    bool cancelCalibration();
    bool calibrationActive() const { return activeCalibration_ >= 0; }
    bool hasCalibration(uint8_t ch) const;
    uint16_t rpmAt(uint8_t ch, uint8_t step) const;
    uint8_t minStartPwm(uint8_t ch) const;
    uint8_t minRunPwm(uint8_t ch) const;
    uint8_t appliedPwm(uint8_t ch) const;
    uint16_t temperature(uint8_t ch, bool secondary = false) const;
    bool temperatureFresh(uint8_t ch, uint32_t nowMs, bool secondary = false) const;
    Mode mode(uint8_t ch) const;
    bool closedLoop(uint8_t ch) const;
    bool setClosedLoop(uint8_t ch, bool enabled);
    bool setDualSensor(uint8_t ch, bool enabled);
    bool dualSensor(uint8_t ch) const;
    bool setPulsesPerRevolution(uint8_t ch, uint8_t ppr);
    uint8_t pulsesPerRevolution(uint8_t ch) const;
    bool setCriticalTemperature(uint8_t ch, uint8_t tempC);
    uint8_t criticalTemperature(uint8_t ch) const;
    bool setStallThreshold(uint8_t ch, uint16_t rpm);
    bool setFanThresholds(uint8_t ch, uint8_t ppr, uint8_t criticalC, uint16_t stallRpm);
    uint16_t stallThreshold(uint8_t ch) const;
    bool faulted(uint8_t ch) const;
    bool clearFault(uint8_t ch);
    uint8_t faultCount() const { return faultCount_; }
    FaultRecord faultAt(uint8_t index) const;
    bool clearHistory();
    uint16_t rpmTarget(uint8_t ch) const;
    bool setFanType(uint8_t ch, FanController::Type type);
    FanController::Type fanType(uint8_t ch) const;
    FanController::Type detectedFanType(uint8_t ch) const;
    static uint8_t interpolate(const CurvePoint* points, uint16_t tempDeciC);
    static bool validCurve(const CurvePoint* points);

private:
    // v1 layout is retained for migration of existing NVS calibration & curves.
    struct LegacyFan {
        uint32_t magic;
        uint8_t version;
        CurvePoint curve[kCurvePoints];
        uint16_t rpm[kCalibrationPoints];
        uint8_t calibrated;
        uint32_t checksum;
    };
    // v2 deployed layout, for migration to the universal-mode configuration.
    struct StoredFanV2 {
        uint32_t magic;
        uint8_t version;
        CurvePoint curve[kCurvePoints];
        CurvePoint secondCurve[kCurvePoints];
        uint16_t rpm[kCalibrationPoints];
        uint8_t calibrated;
        uint8_t minStart;
        uint8_t minRun;
        uint8_t ppr;
        uint8_t criticalC;
        uint16_t stallRpm;
        uint8_t pidEnabled;
        uint8_t dualEnabled;
        uint32_t checksum;
    };
    struct StoredFan {
        uint32_t magic;
        uint8_t version;
        CurvePoint curve[kCurvePoints];
        CurvePoint secondCurve[kCurvePoints];
        uint16_t rpm[kCalibrationPoints];
        uint8_t calibrated;
        uint8_t minStart;
        uint8_t minRun;
        uint8_t ppr;
        uint8_t criticalC;
        uint16_t stallRpm;
        uint8_t pidEnabled;
        uint8_t dualEnabled;
        uint8_t fanType; // 2=DC/no tach, 3=DC/tach (legacy 0/4 is migrated)
        uint32_t checksum;
    };
    struct FaultStore {
        uint32_t magic;
        uint8_t size;
        FaultRecord entries[kFaultCapacity];
        uint32_t checksum;
    };

    static uint32_t checksum(const void* ptr, size_t size);
    static uint32_t calculateChecksum(const StoredFan& fan);
    static void makeDefault(StoredFan& fan);
    bool writeFan(uint8_t ch, StoredFan& newValue);
    bool readFan(uint8_t ch, StoredFan& fan);
    void endCalibration(bool cancelled, bool validRpm);
    void reportPoint(uint8_t ch, uint8_t step, uint16_t rpm);
    uint16_t targetRpmFromPwm(uint8_t ch, uint8_t pwm) const;
    uint8_t pwmFromRpm(uint8_t ch, uint16_t rpm) const;
    uint8_t controlPwm(uint8_t ch, uint8_t feedforward, uint16_t targetRpm, uint32_t nowMs);
    void recordFault(uint8_t ch, Fault code, uint32_t nowMs);
    void updateStall(uint8_t ch, uint32_t nowMs);
    bool overTemperature(uint8_t ch) const;
    bool freshPair(uint8_t ch, uint32_t nowMs) const;

    FanController& fans_;
    Stream& events_;
    Preferences storage_;
    StoredFan saved_[board::kChannelCount] = {};
    Mode fanMode_[board::kChannelCount] = {};
    Mode previousCalibrationMode_ = Mode::Auto;
    uint16_t lastTemp_[board::kChannelCount] = {};
    uint16_t lastTemp2_[board::kChannelCount] = {};
    uint16_t filteredTemp_[board::kChannelCount] = {};
    uint16_t filteredTemp2_[board::kChannelCount] = {};
    uint32_t lastTempMs_[board::kChannelCount] = {};
    uint32_t lastTemp2Ms_[board::kChannelCount] = {};
    bool gotTemp_[board::kChannelCount] = {};
    bool gotTemp2_[board::kChannelCount] = {};
    bool timeoutRecorded_[board::kChannelCount] = {};
    bool overheatRecorded_[board::kChannelCount] = {};
    uint8_t manualPwm_[board::kChannelCount] = {};
    uint16_t fixedRpm_[board::kChannelCount] = {};
    uint16_t desiredRpm_[board::kChannelCount] = {};
    float integral_[board::kChannelCount] = {};
    int32_t lastError_[board::kChannelCount] = {};
    uint32_t lastPidMs_[board::kChannelCount] = {};
    uint32_t stallSinceMs_[board::kChannelCount] = {};
    uint32_t spinupUntilMs_[board::kChannelCount] = {};
    uint8_t restartAttempts_[board::kChannelCount] = {};
    bool faultLatched_[board::kChannelCount] = {};
    uint8_t faultCount_ = 0;
    FaultRecord faultHistory_[kFaultCapacity] = {};

    int8_t activeCalibration_ = -1;
    uint8_t calibrationStep_ = 0;
    uint32_t stepStartMs_ = 0;
    bool warmup_ = false;
    bool smartCalibration_ = false;
    bool downward_ = false;
    uint16_t workingRpm_[kCalibrationPoints] = {};
    uint16_t downRpm_[kCalibrationPoints] = {};
    uint8_t calRetry_ = 0;
    uint8_t calBadSamples_ = 0;
    uint32_t lastControlMs_ = 0;
};

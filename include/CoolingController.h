#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include "FanController.h"

// Channel numbers are zero-based inside firmware, one-based over Serial.
// Temperatures are deci-Celsius (example: 45.5 C -> 455).
class CoolingController {
public:
    static constexpr uint8_t kCurvePoints = 5;
    static constexpr uint8_t kCalibrationPoints = 21; // 0..100%, 5% increments
    static constexpr uint32_t kSensorTimeoutMs = 10000;

    struct CurvePoint {
        uint8_t tempC;
        uint8_t pwm;
    };

    enum class Mode : uint8_t { Auto, Manual, Calibration };

    CoolingController(FanController& fans, Stream& events);
    bool begin();
    void update(uint32_t nowMs);
    void setTemperature(uint8_t ch, uint16_t deciC, uint32_t nowMs);
    bool setCurve(uint8_t ch, const CurvePoint* points);
    const CurvePoint* curve(uint8_t ch) const;
    bool setManual(uint8_t ch, uint8_t pwm);
    bool setAuto(uint8_t ch);
    bool startCalibration(uint8_t ch, uint32_t nowMs);
    bool cancelCalibration();
    bool calibrationActive() const { return activeCalibration_ >= 0; }
    bool hasCalibration(uint8_t ch) const;
    uint16_t rpmAt(uint8_t ch, uint8_t step) const;
    uint8_t appliedPwm(uint8_t ch) const;
    uint16_t temperature(uint8_t ch) const;
    bool temperatureFresh(uint8_t ch, uint32_t nowMs) const;
    Mode mode(uint8_t ch) const;
    static uint8_t interpolate(const CurvePoint* points, uint16_t tempDeciC);
    static bool validCurve(const CurvePoint* points);

private:
    struct StoredFan {
        uint32_t magic;
        uint8_t version;
        CurvePoint curve[kCurvePoints];
        uint16_t rpm[kCalibrationPoints];
        uint8_t calibrated;
        uint32_t checksum;
    };

    static uint32_t calculateChecksum(const StoredFan& fan);
    static void makeDefault(StoredFan& fan);
    bool writeFan(uint8_t ch, StoredFan& newValue);
    bool readFan(uint8_t ch, StoredFan& fan);
    void endCalibration(bool cancelled, bool validRpm);
    void reportPoint(uint8_t ch, uint8_t step, uint16_t rpm);

    FanController& fans_;
    Stream& events_;
    Preferences storage_;
    StoredFan saved_[board::kChannelCount] = {};
    Mode fanMode_[board::kChannelCount] = {};
    Mode previousCalibrationMode_ = Mode::Auto;
    uint16_t lastTemp_[board::kChannelCount] = {};
    uint32_t lastTempMs_[board::kChannelCount] = {};
    bool gotTemp_[board::kChannelCount] = {};
    uint8_t manualPwm_[board::kChannelCount] = {};
    int8_t activeCalibration_ = -1;
    uint8_t calibrationStep_ = 0;
    uint32_t stepStartMs_ = 0;
    bool warmup_ = false;
    uint16_t workingRpm_[kCalibrationPoints] = {};
    uint32_t lastControlMs_ = 0;
};

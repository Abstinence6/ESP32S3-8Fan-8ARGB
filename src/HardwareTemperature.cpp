#include "HardwareTemperature.h"
#include <stdio.h>

const char* HardwareTemperature::modeName(Mode mode) {
    switch (mode) {
        case Mode::Local: return "LOCAL";
        case Mode::Backup: return "BACKUP";
        default: return "PC";
    }
}

bool HardwareTemperature::begin() {
#if HARDWARE_TEMP_ENABLED
    if (!preferences_.begin("ds18b20", false)) return false;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        char key[8];
        snprintf(key, sizeof(key), "fan%u", ch + 1);
        uint8_t value = 0;
        const bool stored = preferences_.getBytesLength(key) == 1 &&
            preferences_.getBytes(key, &value, 1) == 1;
        modes_[ch] = stored && value <= 2 ? static_cast<Mode>(value) : Mode::PcOnly;
    }
    sensor_.begin();
    sensor_.setResolution(12);
    sensor_.setWaitForConversion(false);
#endif
    return true;
}

bool HardwareTemperature::setMode(uint8_t channel, Mode mode) {
    if (channel >= board::kChannelCount || static_cast<uint8_t>(mode) > 2)
        return false;
#if HARDWARE_TEMP_ENABLED
    if (modes_[channel] == mode) return true;
    char key[8];
    snprintf(key, sizeof(key), "fan%u", channel + 1);
    uint8_t value = static_cast<uint8_t>(mode);
    if (preferences_.putBytes(key, &value, 1) != 1) return false;
    modes_[channel] = mode;
    return true;
#else
    return mode == Mode::PcOnly;
#endif
}

HardwareTemperature::Mode HardwareTemperature::mode(uint8_t channel) const {
    return channel < board::kChannelCount ? modes_[channel] : Mode::PcOnly;
}

bool HardwareTemperature::acceptsPc(uint8_t channel) const {
    return channel < board::kChannelCount && mode(channel) != Mode::Local;
}

void HardwareTemperature::notePc(uint8_t channel, uint32_t nowMs) {
    if (channel >= board::kChannelCount) return;
    pcReceivedMs_[channel] = nowMs;
    pcSeen_[channel] = true;
}

bool HardwareTemperature::fresh(uint32_t nowMs) const {
    return valid_ && (nowMs - sampleMs_) <= 3000U;
}

void HardwareTemperature::update(uint32_t nowMs, CoolingController& cooling) {
#if HARDWARE_TEMP_ENABLED
    // DS18B20 12-bit conversions take up to 750 ms.  Never delay the fan
    // control loop or watchdog while waiting on the OneWire bus.
    if (!conversionPending_) {
        if (lastRequestMs_ == 0 || nowMs - lastRequestMs_ >= 1000U) {
            sensor_.requestTemperatures();
            conversionMs_ = nowMs;
            lastRequestMs_ = nowMs;
            conversionPending_ = true;
        }
    } else if (nowMs - conversionMs_ >= 800U) {
        conversionPending_ = false;
        const float celsius = sensor_.getTempCByIndex(0);
        // -127 = unplugged; 85 = DS18B20 power-on default.  Reject invalid
        // readings rather than accidentally commanding a reduced fan speed.
        if (celsius >= 0.0f && celsius <= 125.0f &&
            (celsius < 84.9f || celsius > 85.1f)) {
            valueDeciC_ = static_cast<uint16_t>(celsius * 10.0f + 0.5f);
            sampleMs_ = nowMs;
            valid_ = true;
        } else {
            valid_ = false;
        }
    }
    if (!fresh(nowMs)) return;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const Mode configured = modes_[ch];
        if (configured == Mode::PcOnly) continue;
        if (configured == Mode::Backup && pcSeen_[ch] &&
            nowMs - pcReceivedMs_[ch] < 6000U) continue;
        // Feed once per physical conversion.  Never refresh the cooling
        // controller timestamp from stale hardware readings.
        if (lastInjectMs_[ch] != sampleMs_) {
            cooling.setTemperature(ch, valueDeciC_, nowMs);
            lastInjectMs_[ch] = sampleMs_;
        }
    }
#else
    (void)nowMs;
    (void)cooling;
#endif
}

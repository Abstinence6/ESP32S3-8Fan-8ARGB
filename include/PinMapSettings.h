#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "BoardConfig.h"

// Runtime routing is loaded BEFORE fans, TACH interrupts or ARGB are started.
// Changes to NVS are never applied to live outputs: a power-cycle/reboot is
// mandatory. Validate the actual PCB and external fail-ON hardware first.
namespace pinmap {

struct Pins {
    uint8_t pwm[board::kChannelCount] = {};
    uint8_t tach[board::kChannelCount] = {};
    uint8_t argb[board::kChannelCount] = {};
};

inline Pins defaults() {
    Pins result = {};
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        result.pwm[i] = board::kFanPwmPins[i];
        result.tach[i] = board::kFanTachPins[i];
        result.argb[i] = board::kArgbDataPins[i];
    }
    return result;
}

inline uint8_t at(const Pins& pins, uint8_t index) {
    return index < board::kChannelCount ? pins.pwm[index] :
        index < board::kChannelCount * 2U ? pins.tach[index - board::kChannelCount] :
        pins.argb[index - board::kChannelCount * 2U];
}

inline bool allowed(uint8_t pin, uint8_t slot) {
    if (pin > 48 || pin == 0 || pin == 3 || pin == 19 || pin == 20 ||
        (pin >= 22 && pin <= 32) || pin == 43 || pin == 44 ||
        pin == 45) return false;
    // GPIO33-37 are flash/PSRAM signals on OCTAL variants. Their existing
    // slot assignments are grandfathered, never silently moved to a new role.
    if (pin >= 33 && pin <= 37 && pin != board::pinAt(slot))
        return false;
    // GPIO46 is a strapping pin; verify external reset/boot circuitry.
    // Preserve a legacy assignment only; do not allow new users of GPIO46.
    if (pin == 46 && pin != board::pinAt(slot))
        return false;
#if PC_POWER_ENABLED
    if (pin == board::kPcPowerPin || pin == board::kPcSensePin) return false;
#endif
#if HARDWARE_TEMP_ENABLED
    if (pin == board::kHardwareTempPin) return false;
#endif
    return true;
}

inline bool validate(const Pins& pins) {
    for (uint8_t a = 0; a < 3 * board::kChannelCount; ++a) {
        const uint8_t candidate = at(pins, a);
        if (!allowed(candidate, a)) return false;
        for (uint8_t b = 0; b < a; ++b)
            if (candidate == at(pins, b)) return false;
    }
    return true;
}

class Settings {
public:
    bool begin() {
        applied_ = defaults();
        saved_ = defaults();
        if (!storage_.begin("pinmap-v1", false)) return false;
        const size_t storedLength = storage_.getBytesLength("pins");
        if (storedLength == 0) return true; // Fresh NVS: factory pin mapping.
        Record record = {};
        if (storedLength != sizeof(record) ||
            storage_.getBytes("pins", &record, sizeof(record)) != sizeof(record) ||
            record.magic != kMagic || record.version != 1 ||
            record.crc != checksum(record) || !validate(record.pins))
            return false; // Corrupt NVS must not enable incorrect GPIO outputs.
        applied_ = record.pins;
        saved_ = record.pins;
        return true;
    }
    const Pins& applied() const { return applied_; }
    const Pins& saved() const { return saved_; }
    bool rebootNeeded() const {
        return memcmp(&applied_, &saved_, sizeof(Pins)) != 0;
    }

    bool start(uint32_t nowMs) {
        if (transaction_) return false;
        staging_ = saved_;
        transaction_ = true;
        startedMs_ = nowMs;
        return true;
    }
    bool set(uint8_t kind, uint8_t channel, uint8_t gpio, uint32_t nowMs) {
        if (!active(nowMs) || channel >= board::kChannelCount || kind > 2 ||
            gpio > 48) return false;
        uint8_t* dst = kind == 0 ? staging_.pwm : kind == 1 ?
                       staging_.tach : staging_.argb;
        dst[channel] = gpio;
        // A temporary collision during a pin swap is permitted; commit
        // validates all 24 roles as a single atomic map.
        return true;
    }
    bool commit(uint32_t nowMs) {
        if (!active(nowMs) || !validate(staging_)) return false;
        if (memcmp(&staging_, &saved_, sizeof(Pins)) != 0) {
            Record record = {};
            record.magic = kMagic;
            record.version = 1;
            record.pins = staging_;
            record.crc = checksum(record);
            if (storage_.putBytes("pins", &record, sizeof(record)) != sizeof(record))
                return false;
            saved_ = staging_;
        }
        cancel();
        return true;
    }
    bool factory(uint32_t nowMs) {
        if (!start(nowMs)) return false;
        staging_ = defaults();
        if (!commit(nowMs)) {
            cancel();
            return false;
        }
        return true;
    }
    void cancel() { transaction_ = false; }
    bool active(uint32_t nowMs) {
        if (transaction_ && nowMs - startedMs_ > 30000U)
            transaction_ = false;
        return transaction_;
    }
private:
    static constexpr uint32_t kMagic = 0x50494E31UL; // PIN1
    struct Record {
        uint32_t magic = 0;
        uint8_t version = 0;
        Pins pins = {};
        uint8_t reserved[3] = {};
        uint32_t crc = 0;
    };
    static uint32_t checksum(const Record& record) {
        uint32_t hash = 2166136261UL;
        const auto* bytes = reinterpret_cast<const uint8_t*>(&record);
        for (size_t i = 0; i < offsetof(Record, crc); ++i) {
            hash ^= bytes[i];
            hash *= 16777619UL;
        }
        return hash;
    }
    Preferences storage_;
    Pins applied_ = defaults();
    Pins saved_ = defaults();
    Pins staging_ = {};
    uint32_t startedMs_ = 0;
    bool transaction_ = false;
};

inline Settings& settings() {
    static Settings instance;
    return instance;
}
inline uint8_t pwmPin(uint8_t channel) { return settings().applied().pwm[channel]; }
inline uint8_t tachPin(uint8_t channel) { return settings().applied().tach[channel]; }
inline uint8_t argbPin(uint8_t channel) { return settings().applied().argb[channel]; }

} // namespace pinmap

#include "HardwareTemperature.h"
#include <stdio.h>
#include <string.h>

namespace {
int hexValue(char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}
} // namespace

const char* HardwareTemperature::modeName(Mode mode) {
    switch (mode) {
        case Mode::Local: return "LOCAL";
        case Mode::Backup: return "BACKUP";
        default: return "PC";
    }
}

bool HardwareTemperature::parseRom(const char* hex, uint8_t (&rom)[8]) {
    if (!hex || strlen(hex) != 16) return false;
    for (uint8_t i = 0; i < 8; ++i) {
        const int hi = hexValue(hex[2 * i]);
        const int lo = hexValue(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return false;
        rom[i] = static_cast<uint8_t>((hi << 4) | lo);
    }
    return true;
}

void HardwareTemperature::formatRom(const uint8_t (&rom)[8], char (&hex)[17]) {
    snprintf(hex, 17, "%02X%02X%02X%02X%02X%02X%02X%02X",
             rom[0], rom[1], rom[2], rom[3],
             rom[4], rom[5], rom[6], rom[7]);
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
        snprintf(key, sizeof(key), "rom%u", ch + 1);
        mapped_[ch] = preferences_.getBytesLength(key) == 8 &&
            preferences_.getBytes(key, assignedRom_[ch], 8) == 8;
        if (mapped_[ch]) {
            bool allZero = true;
            for (uint8_t i = 0; i < 8; ++i)
                if (assignedRom_[ch][i] != 0) allZero = false;
            mapped_[ch] = !allZero;
        }
    }
    return rescan();
#else
    return true;
#endif
}

bool HardwareTemperature::rescan() {
#if HARDWARE_TEMP_ENABLED
    sensor_.begin();
    sensor_.setResolution(12);
    sensor_.setWaitForConversion(false);
    count_ = 0;
    for (uint8_t idx = 0; idx < sensor_.getDeviceCount() && count_ < kMaxProbes; ++idx) {
        uint8_t address[8] = {};
        if (!sensor_.getAddress(address, idx) ||
            !sensor_.validAddress(address) || !sensor_.validFamily(address))
            continue;
        bool duplicate = false;
        for (uint8_t j = 0; j < count_; ++j) {
            if (memcmp(probes_[j].rom, address, 8) == 0) duplicate = true;
        }
        if (duplicate) continue;
        Probe& probe = probes_[count_++];
        memcpy(probe.rom, address, 8);
        probe.deciC = 0;
        probe.sampleMs = 0;
        probe.valid = false;
    }
    conversionPending_ = false;
    lastRequestMs_ = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
        lastInjectMs_[ch] = 0;
    return true;
#else
    return false;
#endif
}

bool HardwareTemperature::setMode(uint8_t channel, Mode mode) {
    if (channel >= board::kChannelCount || static_cast<uint8_t>(mode) > 2)
        return false;
#if HARDWARE_TEMP_ENABLED
    if (modes_[channel] == mode) return true;
    char key[8];
    snprintf(key, sizeof(key), "fan%u", channel + 1);
    const uint8_t value = static_cast<uint8_t>(mode);
    if (preferences_.putBytes(key, &value, 1) != 1) return false;
    modes_[channel] = mode;
    return true;
#else
    return mode == Mode::PcOnly;
#endif
}

bool HardwareTemperature::setAddress(uint8_t channel, const char* romOrAuto) {
    if (channel >= board::kChannelCount || !romOrAuto) return false;
#if HARDWARE_TEMP_ENABLED
    uint8_t address[8] = {};
    const bool automatic = strcmp(romOrAuto, "AUTO") == 0;
    if (!automatic) {
        if (!parseRom(romOrAuto, address) ||
            !sensor_.validAddress(address) || !sensor_.validFamily(address))
            return false;
        bool present = false;
        for (uint8_t idx = 0; idx < count_; ++idx)
            if (memcmp(probes_[idx].rom, address, 8) == 0) present = true;
        if (!present) return false;
    }
    char key[8];
    snprintf(key, sizeof(key), "rom%u", channel + 1);
    if (preferences_.putBytes(key, address, 8) != 8) return false;
    memcpy(assignedRom_[channel], address, 8);
    mapped_[channel] = !automatic;
    lastInjectMs_[channel] = 0;
    return true;
#else
    (void)romOrAuto;
    return false;
#endif
}

HardwareTemperature::Mode HardwareTemperature::mode(uint8_t channel) const {
    return channel < board::kChannelCount ? modes_[channel] : Mode::PcOnly;
}

bool HardwareTemperature::mappedAddress(uint8_t channel, char rom[17]) const {
    if (!rom || channel >= board::kChannelCount) return false;
    if (!mapped_[channel]) {
        memcpy(rom, "AUTO", 5);
        return true;
    }
    snprintf(rom, 17, "%02X%02X%02X%02X%02X%02X%02X%02X",
             assignedRom_[channel][0], assignedRom_[channel][1],
             assignedRom_[channel][2], assignedRom_[channel][3],
             assignedRom_[channel][4], assignedRom_[channel][5],
             assignedRom_[channel][6], assignedRom_[channel][7]);
    return true;
}

int8_t HardwareTemperature::resolve(uint8_t channel) const {
    if (channel >= board::kChannelCount) return -1;
    if (!mapped_[channel]) {
        // With multiple devices, AUTO must not attach a fan to an arbitrary
        // ROM: a changed discovery order might cool the wrong component.
        return count_ == 1 ? 0 : -1;
    }
    for (uint8_t idx = 0; idx < count_; ++idx)
        if (memcmp(assignedRom_[channel], probes_[idx].rom, 8) == 0)
            return static_cast<int8_t>(idx);
    return -1;
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
    return count_ > 0 && probes_[0].valid &&
        nowMs - probes_[0].sampleMs <= 3000U;
}

bool HardwareTemperature::sensorInfo(uint8_t index, char rom[17],
                                     uint16_t& deci, bool& valid,
                                     uint32_t& ageMs, uint32_t nowMs) const {
    if (!rom || index >= count_) return false;
    snprintf(rom, 17, "%02X%02X%02X%02X%02X%02X%02X%02X",
             probes_[index].rom[0], probes_[index].rom[1],
             probes_[index].rom[2], probes_[index].rom[3],
             probes_[index].rom[4], probes_[index].rom[5],
             probes_[index].rom[6], probes_[index].rom[7]);
    valid = probes_[index].valid && nowMs - probes_[index].sampleMs <= 3000U;
    deci = valid ? probes_[index].deciC : 0;
    ageMs = valid ? nowMs - probes_[index].sampleMs : 0;
    return true;
}

void HardwareTemperature::update(uint32_t nowMs, CoolingController& cooling) {
#if HARDWARE_TEMP_ENABLED
    if (count_ == 0) return;
    // Conversion runs for every discovered probe, with a single 1-Wire request.
    // Never block the cooling loop while the DS18B20 converts (up to 750ms).
    if (!conversionPending_) {
        if (lastRequestMs_ == 0 || nowMs - lastRequestMs_ >= 1000U) {
            sensor_.requestTemperatures();
            conversionMs_ = nowMs;
            lastRequestMs_ = nowMs;
            conversionPending_ = true;
        }
    } else if (nowMs - conversionMs_ >= 800U) {
        conversionPending_ = false;
        for (uint8_t i = 0; i < count_; ++i) {
            Probe& probe = probes_[i];
            // getTempC validates the scratchpad CRC via the DallasTemperature
            // library; unplugged (-127C), reset-default (85C) and invalid
            // values are not allowed to refresh the fan watchdog.
            const float celsius = sensor_.getTempC(probe.rom);
            probe.valid = celsius >= 0.0f && celsius <= 125.0f &&
                          (celsius < 84.9f || celsius > 85.1f);
            if (probe.valid) {
                probe.deciC = static_cast<uint16_t>(celsius * 10.0f + 0.5f);
                probe.sampleMs = nowMs;
            }
        }
    }
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const Mode configured = modes_[ch];
        if (configured == Mode::PcOnly) continue;
        if (configured == Mode::Backup && pcSeen_[ch] &&
            nowMs - pcReceivedMs_[ch] < 6000U) continue;
        const int8_t index = resolve(ch);
        if (index < 0) continue;
        const Probe& probe = probes_[index];
        if (probe.valid && nowMs - probe.sampleMs <= 3000U &&
            lastInjectMs_[ch] != probe.sampleMs) {
            cooling.setHardwareTemperature(ch, probe.deciC, nowMs);
            lastInjectMs_[ch] = probe.sampleMs;
        }
    }
#else
    (void)nowMs;
    (void)cooling;
#endif
}

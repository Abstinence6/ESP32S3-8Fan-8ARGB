#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <stddef.h>
#include <string.h>
#include "CoolingController.h"
#include "ArgbController.h"

// Three explicitly saved, device-resident cooling + ARGB profiles.
// Profile selection is RAM-only. Only capture() / setBoot() write NVS.
// Default boot has no profile selected and leaves existing RGB boot policy.
class OfflineProfiles {
public:
    static constexpr uint8_t kSlots = 3;
    OfflineProfiles(CoolingController& cooling, ArgbController& leds)
        : cooling_(cooling), leds_(leds) {}

    bool begin() {
        if (!storage_.begin("offline-v1", false)) return false;
        Bank read = {};
        if (storage_.getBytesLength("bank") != sizeof(read) ||
            storage_.getBytes("bank", &read, sizeof(read)) != sizeof(read) ||
            read.magic != kMagic || read.version != 1 ||
            read.boot > kSlots || read.crc != checksum(read) ||
            !validate(read)) return true; // Fresh/corrupt NVS: no auto activation.
        bank_ = read;
        if (bank_.boot && valid(bank_.boot)) activate(bank_.boot);
        return true;
    }

    bool valid(uint8_t slot) const {
        return slot >= 1 && slot <= kSlots && bank_.slots[slot-1].saved != 0;
    }
    uint8_t active() const { return active_; }
    uint8_t boot() const { return bank_.boot; }

    bool capture(uint8_t slot) {
        if (slot < 1 || slot > kSlots || cooling_.calibrationActive()) return false;
        Bank next = bank_;
        Saved& data = next.slots[slot-1];
        data = {};
        data.saved = 1;
        for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
            const auto* curve = cooling_.curve(ch);
            if (!CoolingController::validCurve(curve)) return false;
            memcpy(data.curves[ch], curve, sizeof(data.curves[ch]));
            auto mode = leds_.getMode(ch);
            // Never replay external PC frames as if they were autonomous.
            if (mode == ArgbController::Mode::External) mode = ArgbController::Mode::Off;
            data.mode[ch] = static_cast<uint8_t>(mode);
            uint8_t r=0, g=0, b=0;
            if (!leds_.solidColor(ch,r,g,b)) return false;
            data.rgb[ch][0]=r; data.rgb[ch][1]=g; data.rgb[ch][2]=b;
            data.effects[ch] = leds_.effect(ch);
            data.reactive[ch] = leds_.reactive(ch);
        }
        return persist(next);
    }

    bool setBoot(uint8_t slot) {
        if (slot > kSlots || (slot && !valid(slot))) return false;
        Bank next = bank_;
        next.boot = slot;
        return persist(next);
    }

    bool activate(uint8_t slot) {
        if (!valid(slot) || cooling_.calibrationActive()) return false;
        const Saved& data = bank_.slots[slot-1];
        if (!cooling_.setOfflineCurves(data.curves)) return false;
        // The one-strip-per-visit renderer, warning overlay, and current budget
        // remain enforced inside ArgbController.
        for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
            switch (static_cast<ArgbController::Mode>(data.mode[ch])) {
                case ArgbController::Mode::Off: leds_.setOff(ch); break;
                case ArgbController::Mode::Solid:
                    leds_.setSolid(ch,data.rgb[ch][0],data.rgb[ch][1],data.rgb[ch][2]); break;
                case ArgbController::Mode::Rainbow: leds_.setRainbow(ch); break;
                case ArgbController::Mode::Effect: leds_.setEffect(ch,data.effects[ch]); break;
                case ArgbController::Mode::Reactive: leds_.setReactive(ch,data.reactive[ch]); break;
                default: return false;
            }
        }
        active_ = slot;
        return true;
    }

    bool clear() {
        if (cooling_.calibrationActive()) return false;
        cooling_.clearOfflineCurves();
        active_ = 0;
        // Existing ARGB output is intentionally unchanged until a new scene
        // is selected. Clear never silently disables fault indication.
        return true;
    }

private:
    struct Saved {
        uint8_t saved;
        CoolingController::CurvePoint curves[board::kChannelCount][CoolingController::kCurvePoints];
        uint8_t mode[board::kChannelCount];
        uint8_t rgb[board::kChannelCount][3];
        argbeffects::Scene effects[board::kChannelCount];
        argbreaction::Config reactive[board::kChannelCount];
    };
    struct Bank {
        uint32_t magic;
        uint8_t version;
        uint8_t boot;
        uint8_t reserved[2];
        Saved slots[kSlots];
        uint32_t crc;
    };
    static constexpr uint32_t kMagic = 0x4F465031UL; // OFP1
    static uint32_t checksum(const Bank& data) {
        uint32_t hash=2166136261UL;
        const auto* bytes=reinterpret_cast<const uint8_t*>(&data);
        for (size_t i=0; i<offsetof(Bank, crc); ++i) {
            hash ^= bytes[i];
            hash *= 16777619UL;
        }
        return hash;
    }
    static bool validate(const Bank& data) {
        for (uint8_t slot=0; slot<kSlots; ++slot) {
            const Saved& item = data.slots[slot];
            if (item.saved > 1) return false;
            if (!item.saved) continue;
            for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
                if (!CoolingController::validCurve(item.curves[ch]) ||
                    item.mode[ch] > static_cast<uint8_t>(ArgbController::Mode::Reactive) ||
                    item.mode[ch] == static_cast<uint8_t>(ArgbController::Mode::External) ||
                    !argbeffects::valid(item.effects[ch]) ||
                    !argbreaction::valid(item.reactive[ch])) return false;
            }
        }
        return true;
    }
    bool persist(Bank& next) {
        if (!next.magic) next.magic = kMagic;
        next.version = 1;
        if (!validate(next)) return false;
        next.crc = checksum(next);
        if (!memcmp(&next,&bank_,sizeof(next))) return true;
        if (storage_.putBytes("bank",&next,sizeof(next)) != sizeof(next))
            return false;
        bank_=next;
        return true;
    }
    CoolingController& cooling_;
    ArgbController& leds_;
    Preferences storage_;
    Bank bank_ = {};
    uint8_t active_=0;
};

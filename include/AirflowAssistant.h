#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <stddef.h>
#include <string.h>
#include "BoardConfig.h"
#include "FanController.h"

// Passive airflow balance ESTIMATE, NOT a pressure / airflow measurement.
// Requires user-provided rated CFM, rated RPM, installation restriction and
// trustworthy fan TACH. No PWM writes, ever.
class AirflowAssistant {
public:
    struct Channel {
        uint8_t direction = 0; // 0 unknown, 1 intake, 2 exhaust
        uint16_t maxRpm = 0;
        uint16_t cfmDeci = 0; // rated 0.1 CFM at max RPM
        uint8_t restriction = 100; // 1..100%, user-estimated case/filter factor
    };
    struct Result {
        uint32_t intakeDeci = 0;
        uint32_t exhaustDeci = 0;
        int16_t balancePercent = 0; // signed proxy, -100..100; NOT Pascals
        uint8_t configured = 0;
        uint8_t measured = 0;
        uint8_t unavailable = 0;
        bool usable = false; // only if both roles exist and every TACH is valid
    };

    explicit AirflowAssistant(FanController& fans): fans_(fans) {}
    bool begin() {
        if (!storage_.begin("airflow-v1", false)) return false;
        Record record={};
        if (storage_.getBytesLength("channels") != sizeof(record) ||
            storage_.getBytes("channels",&record,sizeof(record)) != sizeof(record) ||
            record.magic != kMagic || record.version != 1 ||
            record.crc != checksum(record) || !valid(record)) return true;
        data_=record;
        return true;
    }

    Channel channel(uint8_t ch) const {
        return ch<board::kChannelCount ? data_.channels[ch] : Channel{};
    }
    bool configure(uint8_t ch, uint8_t direction, uint16_t rpm, uint16_t cfmDeci,
                   uint8_t restriction) {
        if (ch>=board::kChannelCount) return false;
        Channel candidate={};
        candidate.direction=direction;
        candidate.maxRpm=rpm;
        candidate.cfmDeci=cfmDeci;
        candidate.restriction=restriction;
        if (!validChannel(candidate)) return false;
        Record next=data_;
        next.channels[ch]=candidate;
        next.magic=kMagic;
        next.version=1;
        next.crc=checksum(next);
        if (!memcmp(&next,&data_,sizeof(next))) return true;
        if (storage_.putBytes("channels",&next,sizeof(next)) != sizeof(next)) return false;
        data_=next;
        return true;
    }

    Result estimate() const {
        Result result={};
        uint8_t intakeCount=0,exhaustCount=0;
        for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
            const Channel& cfg=data_.channels[ch];
            if (cfg.direction == 0) continue;
            ++result.configured;
            if (cfg.direction == 1) ++intakeCount;
            else ++exhaustCount;
            if (!fans_.tachReliable(ch) || !fans_.hasRpmFeedback(ch) ||
                fans_.getRpm(ch) == 0) {
                ++result.unavailable;
                continue;
            }
            ++result.measured;
            const uint32_t rpm=fans_.getRpm(ch);
            const uint32_t capped=rpm < cfg.maxRpm ? rpm : cfg.maxRpm;
            const uint32_t flow=static_cast<uint32_t>(
                (static_cast<uint64_t>(cfg.cfmDeci)*capped*cfg.restriction +
                 static_cast<uint64_t>(cfg.maxRpm)*50U) /
                (static_cast<uint64_t>(cfg.maxRpm)*100U));
            if (cfg.direction == 1) result.intakeDeci+=flow;
            else result.exhaustDeci+=flow;
        }
        result.usable=intakeCount>0 && exhaustCount>0 &&
                      result.configured==result.measured;
        if (result.usable) {
            const uint32_t larger=result.intakeDeci > result.exhaustDeci ?
                result.intakeDeci : result.exhaustDeci;
            if (larger) {
                const int32_t diff=static_cast<int32_t>(result.intakeDeci) -
                                   static_cast<int32_t>(result.exhaustDeci);
                result.balancePercent=static_cast<int16_t>(
                    diff*100L/static_cast<int32_t>(larger));
            }
        }
        return result;
    }

    // A proxy of estimated CFM balance, not an actual case static pressure.
    static const char* tendency(const Result& result) {
        if (!result.usable) return "unavailable";
        if (result.balancePercent > 10) return "intake-biased";
        if (result.balancePercent < -10) return "exhaust-biased";
        return "balanced-estimate";
    }

private:
    struct Record {
        uint32_t magic=0;
        uint8_t version=0;
        uint8_t reserved[3]={};
        Channel channels[board::kChannelCount]={};
        uint32_t crc=0;
    };
    static constexpr uint32_t kMagic=0x41495231UL; // AIR1
    static bool validChannel(const Channel& c) {
        if (c.direction>2) return false;
        if (c.direction==0) return c.maxRpm==0 && c.cfmDeci==0;
        return c.maxRpm>=300 && c.maxRpm<=25000 &&
               c.cfmDeci>=1 && c.cfmDeci<=3000 &&
               c.restriction>=1 && c.restriction<=100;
    }
    static bool valid(const Record& r) {
        for (const auto& c:r.channels)
            if (!validChannel(c)) return false;
        return true;
    }
    static uint32_t checksum(const Record& r) {
        const auto* p=reinterpret_cast<const uint8_t*>(&r);
        uint32_t h=2166136261UL;
        for (size_t i=0;i<offsetof(Record,crc);++i) {
            h^=p[i]; h*=16777619UL;
        }
        return h;
    }
    FanController& fans_;
    Preferences storage_;
    Record data_={};
};

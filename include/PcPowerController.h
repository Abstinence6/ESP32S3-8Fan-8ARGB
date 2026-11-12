#pragma once
#include <Arduino.h>

// Opt-in PC case-power interface. Never drives a motherboard header high.
// External isolated/open-collector hardware is recommended for PWR_SW and PLED.
class PcPowerController {
public:
    enum class State : uint8_t { Unknown, Off, On };
    enum class Action : uint8_t { On, Off, ForceOff };
    bool begin();
    void update(uint32_t nowMs);
    bool request(Action action, uint32_t nowMs);
    State state() const { return state_; }
    bool busy() const { return pressing_; }
    bool enabled() const { return enabled_; }
    const char* stateText() const;
private:
    void release();
    bool enabled_ = false;
    bool pressing_ = false;
    bool candidateHigh_ = false;
    bool candidateKnown_ = false;
    State state_ = State::Unknown;
    uint32_t candidateSince_ = 0;
    uint32_t pressStarted_ = 0;
    uint32_t pressDuration_ = 0;
    uint32_t lastRelease_ = 0;
    bool hadRelease_ = false;
};

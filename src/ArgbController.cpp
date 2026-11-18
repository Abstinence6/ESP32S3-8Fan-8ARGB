#include "ArgbController.h"
#include "PinMapSettings.h"

#include <stddef.h>
#include <string.h>

namespace {
constexpr uint32_t kArgbMagic = 0x41524734UL; // ARG4
constexpr uint32_t kBrightnessMagic = 0x42524731UL; // BRG1, separate CRC-checked NVS record
constexpr uint32_t kExternalTimeoutMs = 3000;
constexpr uint32_t kEffectMagic = 0x46584331UL; // FXC1
constexpr uint32_t kReactiveMagic = 0x52584631UL; // RXF1
}

uint32_t ArgbController::checksum(const Config& config) {
    uint32_t hash = 2166136261UL;
    const uint8_t* data = reinterpret_cast<const uint8_t*>(&config);
    for (size_t i = 0; i < offsetof(Config, crc); ++i) {
        hash ^= data[i];
        hash *= 16777619UL;
    }
    return hash;
}
uint32_t ArgbController::brightnessChecksum(const BrightnessConfig& config) {
    uint32_t hash = 2166136261UL;
    const uint8_t* data = reinterpret_cast<const uint8_t*>(&config);
    for (size_t i = 0; i < offsetof(BrightnessConfig, crc); ++i) {
        hash ^= data[i];
        hash *= 16777619UL;
    }
    return hash;
}
uint32_t ArgbController::effectChecksum(const EffectStore& config) {
    uint32_t hash = 2166136261UL;
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&config);
    for (size_t i = 0; i < offsetof(EffectStore, crc); ++i) {
        hash ^= bytes[i];
        hash *= 16777619UL;
    }
    return hash;
}
uint32_t ArgbController::reactiveChecksum(const ReactiveStore& config) {
    uint32_t hash = 2166136261UL;
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&config);
    for (size_t i=0; i<offsetof(ReactiveStore, crc); ++i) {
        hash ^= bytes[i]; hash *= 16777619UL;
    }
    return hash;
}
bool ArgbController::begin() {
    if (!storage_.begin("argb-v4", false)) return false;
    Config config = {};
    bool valid = storage_.getBytesLength("config") == sizeof(config) &&
        storage_.getBytes("config", &config, sizeof(config)) == sizeof(config) &&
        config.magic == kArgbMagic && config.crc == checksum(config) &&
        config.budgetMa >= 100 && config.budgetMa <= 20000;
    uint32_t idleBaselineMa = 0;
    if (valid) for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        if (config.counts[i] == 0 || config.counts[i] > board::kMaxArgbPixelsPerFrame ||
            config.reversed[i] > 1) valid = false;
        idleBaselineMa += config.counts[i];
    }
    // An old impossible budget cannot suppress the estimated idle current.
    powerLimitMa_ = valid
        ? (config.budgetMa < idleBaselineMa ? idleBaselineMa : config.budgetMa)
        : 2000;
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        strips_[i].updateType(NEO_GRB + NEO_KHZ800);
        strips_[i].updateLength(valid ? config.counts[i] : board::kArgbLedCounts[i]);
        strips_[i].setPin(pinmap::argbPin(i));
        strips_[i].begin();
        strips_[i].setBrightness(255);
        brightness_[i] = board::kInitialArgbBrightness;
        savedBrightness_[i] = board::kInitialArgbBrightness;
        modes_[i] = Mode::Off;
        reversed_[i] = valid && config.reversed[i] != 0;
        strips_[i].clear();
        strips_[i].show();
    }
    // Preserve legacy ARG4 geometry NVS layout. Brightness is a separate
    // atomic record, avoiding any destructive migration of strip settings.
    BrightnessConfig savedBrightness = {};
    if (storage_.getBytesLength("brightness") == sizeof(savedBrightness) &&
        storage_.getBytes("brightness", &savedBrightness, sizeof(savedBrightness)) == sizeof(savedBrightness) &&
        savedBrightness.magic == kBrightnessMagic &&
        savedBrightness.crc == brightnessChecksum(savedBrightness)) {
        for (uint8_t i = 0; i < board::kChannelCount; ++i) {
            brightness_[i] = savedBrightness.levels[i];
            savedBrightness_[i] = savedBrightness.levels[i];
        }
    }
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        effects_[ch] = argbeffects::defaults();
        savedEffects_[ch] = effects_[ch];
    }
    EffectStore stored = {};
    bool validEffects = storage_.getBytesLength("effects") == sizeof(stored) &&
        storage_.getBytes("effects", &stored, sizeof(stored)) == sizeof(stored) &&
        stored.magic == kEffectMagic && stored.version == 1 &&
        stored.crc == effectChecksum(stored);
    if (validEffects)
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
            if (!argbeffects::valid(stored.scenes[ch]) || stored.boot[ch] > 1)
                validEffects = false;
    if (validEffects) {
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            effects_[ch] = stored.scenes[ch];
            savedEffects_[ch] = stored.scenes[ch];
            bootEffects_[ch] = stored.boot[ch] != 0;
            savedBootEffects_[ch] = bootEffects_[ch];
            if (bootEffects_[ch]) startEffect(ch);
        }
    }
    // Reactive settings have an independent CRC-checked NVS record so all
    // older FX modes, brightness, geometry and cooling profiles survive.
    for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
        reactive_[ch] = argbreaction::defaults();
        savedReactive_[ch] = reactive_[ch];
    }
    ReactiveStore reaction = {};
    bool validReaction = storage_.getBytesLength("reactive") == sizeof(reaction) &&
        storage_.getBytes("reactive", &reaction, sizeof(reaction)) == sizeof(reaction) &&
        reaction.magic == kReactiveMagic && reaction.version == 1 &&
        reaction.crc == reactiveChecksum(reaction);
    if (validReaction)
        for (uint8_t ch=0; ch<board::kChannelCount; ++ch)
            if (!argbreaction::valid(reaction.scenes[ch]) || reaction.boot[ch] > 1)
                validReaction = false;
    if (validReaction)
        for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
            reactive_[ch] = reaction.scenes[ch];
            savedReactive_[ch] = reaction.scenes[ch];
            bootReactive_[ch] = reaction.boot[ch] != 0;
            savedBootReactive_[ch] = bootReactive_[ch];
            // An explicit reactive boot opt-in takes precedence over FX boot.
            if (bootReactive_[ch]) startReactive(ch);
        }
    // Corrupt NVS reverts new reactive configurations to disabled/off.
    previousFrameMs_ = millis();
    return true;
}
void ArgbController::markDirty(uint8_t ch) { dirty_[ch] = true; }
void ArgbController::setSafetyWarning(uint8_t ch, uint8_t code) {
    if (ch >= board::kChannelCount || code > 3 || safetyWarnings_[ch] == code) return;
    safetyWarnings_[ch] = code;
    markDirty(ch);
}
uint8_t ArgbController::safetyWarning(uint8_t ch) const {
    return ch < board::kChannelCount ? safetyWarnings_[ch] : 0;
}
ArgbController::Rgb ArgbController::effectiveColor(uint8_t ch, uint16_t pixel) const {
    // A non-destructive override on only the first three LEDs: original scene
    // buffers remain intact and can immediately resume when the fault clears.
    if (safetyWarnings_[ch] && warningOn_ && pixel < 3U) {
        if (safetyWarnings_[ch] == 1) return Rgb(255, 95, 0);   // missing sensor
        if (safetyWarnings_[ch] == 2) return Rgb(255, 0, 0);    // thermal
        return Rgb(255, 0, 120);                                // TACH / stall
    }
    const uint16_t index = pixel * 3U;
    return Rgb(frame_[ch][index], frame_[ch][index + 1], frame_[ch][index + 2]);
}
uint8_t ArgbController::effectiveBrightness(uint8_t ch, uint16_t pixel) const {
    // Even an intentionally-off zone can warn. Limit indicator brightness,
    // and apply the SAME global power budget as the underlying RGB scene.
    if (safetyWarnings_[ch] && warningOn_ && pixel < 3U) return 64;
    return brightness_[ch];
}

uint32_t ArgbController::estimatedFullCurrent() const {
    uint32_t total = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        total += count; // ~1 mA idle per pixel (estimate, depends on LED model)
        for (uint16_t i = 0; i < count; ++i) {
            const Rgb color = effectiveColor(ch, i);
            const uint32_t channels = static_cast<uint32_t>(color.r) + color.g + color.b;
            total += channels * effectiveBrightness(ch, i) * 20U / (255U * 255U);
        }
    }
    return total;
}
uint32_t ArgbController::estimatedLimitedCurrent() const {
    // Estimate only; this is not a measurement or a substitute for a fuse.
    uint32_t baseline = 0;
    uint64_t weightedColor = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        baseline += count;
        for (uint16_t i = 0; i < count; ++i) {
            const Rgb color = effectiveColor(ch, i);
            weightedColor += static_cast<uint64_t>(color.r + color.g + color.b) *
                             effectiveBrightness(ch, i) * 20U;
        }
    }
    return baseline + static_cast<uint32_t>(weightedColor * lastScale_ /
        (255ULL * 255ULL * 255ULL));
}
void ArgbController::render() {
    uint32_t baseline = 0;
    uint64_t requestedColor = 0;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        const uint16_t count = strips_[ch].numPixels();
        baseline += count;
        for (uint16_t i = 0; i < count; ++i) {
            const Rgb color = effectiveColor(ch, i);
            requestedColor += static_cast<uint64_t>(color.r + color.g + color.b) *
                              effectiveBrightness(ch, i) * 20U;
        }
    }
    const uint32_t allowance = powerLimitMa_ > baseline ? powerLimitMa_ - baseline : 0;
    // RequestedColor is in units of mA * 255 * 255 (RGB channels assume 20 mA max).
    const uint64_t desired = requestedColor;
    const uint64_t maxColor = static_cast<uint64_t>(allowance) * 255U * 255U;
    const uint16_t scale = desired > maxColor && desired
        ? static_cast<uint16_t>(maxColor * 255U / desired) : 255;
    if (lastScale_ != scale) {
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) markDirty(ch);
        lastScale_ = scale;
    }
    for (uint8_t n = 0; n < board::kChannelCount; ++n) {
        const uint8_t ch = (renderCursor_ + n) % board::kChannelCount;
        if (!dirty_[ch]) continue;
        dirty_[ch] = false;
        renderCursor_ = (ch + 1) % board::kChannelCount;
        const uint16_t count = strips_[ch].numPixels();
        for (uint16_t i = 0; i < count; ++i) {
            const Rgb color = effectiveColor(ch, i);
            const uint32_t multiplier = static_cast<uint32_t>(effectiveBrightness(ch, i)) * scale;
            const uint8_t r = static_cast<uint8_t>(static_cast<uint32_t>(color.r) * multiplier / (255U * 255U));
            const uint8_t g = static_cast<uint8_t>(static_cast<uint32_t>(color.g) * multiplier / (255U * 255U));
            const uint8_t b = static_cast<uint8_t>(static_cast<uint32_t>(color.b) * multiplier / (255U * 255U));
            const uint16_t idx = reversed_[ch] ? count - i - 1 : i;
            strips_[ch].setPixelColor(idx, strips_[ch].Color(r,g,b));
        }
        strips_[ch].show();
        break; // Give the control loop a chance to run between strip transfers.
    }
}

void ArgbController::drawSolid(uint8_t ch) {
    for (uint16_t i = 0; i < strips_[ch].numPixels(); ++i) {
        const uint16_t n = i * 3U;
        frame_[ch][n] = colors_[ch].r;
        frame_[ch][n+1] = colors_[ch].g;
        frame_[ch][n+2] = colors_[ch].b;
    }
    markDirty(ch);
    // LED output deferred to update() so fan control/serial input get priority.
}
bool ArgbController::solidColor(uint8_t ch, uint8_t& r,
                                uint8_t& g, uint8_t& b) const {
    if (ch >= board::kChannelCount) return false;
    r = colors_[ch].r; g = colors_[ch].g; b = colors_[ch].b;
    return true;
}

bool ArgbController::setSolid(uint8_t ch, uint8_t r, uint8_t g, uint8_t b) {
    if (ch >= board::kChannelCount) return false;
    if (modes_[ch] == Mode::External || modes_[ch] == Mode::Effect ||
        modes_[ch] == Mode::Reactive)
        brightness_[ch] = savedBrightness_[ch];
    modes_[ch] = Mode::Solid;
    colors_[ch].r = r; colors_[ch].g = g; colors_[ch].b = b;
    drawSolid(ch);
    return true;
}
bool ArgbController::setOff(uint8_t ch) {
    if (ch >= board::kChannelCount) return false;
    if (modes_[ch] == Mode::External || modes_[ch] == Mode::Effect ||
        modes_[ch] == Mode::Reactive)
        brightness_[ch] = savedBrightness_[ch];
    modes_[ch] = Mode::Off;
    memset(frame_[ch], 0, sizeof(frame_[ch]));
    markDirty(ch);
    // LED output deferred to update() so fan control/serial input get priority.
    return true;
}
bool ArgbController::setRainbow(uint8_t ch) {
    if (ch >= board::kChannelCount) return false;
    if (modes_[ch] == Mode::External || modes_[ch] == Mode::Effect ||
        modes_[ch] == Mode::Reactive)
        brightness_[ch] = savedBrightness_[ch];
    modes_[ch] = Mode::Rainbow;
    return true;
}
bool ArgbController::setEffect(uint8_t ch, const argbeffects::Scene& config) {
    if (ch >= board::kChannelCount || !argbeffects::valid(config)) return false;
    effects_[ch] = config;
    modes_[ch] = Mode::Effect;
    brightness_[ch] = config.brightness;
    argbeffects::render(config, strips_[ch].numPixels(), millis(), frame_[ch]);
    markDirty(ch);
    return true;
}
bool ArgbController::startEffect(uint8_t ch) {
    return ch < board::kChannelCount && setEffect(ch, effects_[ch]);
}
bool ArgbController::setEffectBoot(uint8_t ch, bool enabled) {
    if (ch >= board::kChannelCount) return false;
    bootEffects_[ch] = enabled;
    return true;
}
const argbeffects::Scene& ArgbController::effect(uint8_t ch) const {
    static const argbeffects::Scene factory = argbeffects::defaults();
    return ch < board::kChannelCount ? effects_[ch] : factory;
}
bool ArgbController::effectBoot(uint8_t ch) const {
    return ch < board::kChannelCount && bootEffects_[ch];
}
bool ArgbController::saveEffects() {
    bool changed = false;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
        if (memcmp(&effects_[ch], &savedEffects_[ch], sizeof(effects_[ch])) ||
            bootEffects_[ch] != savedBootEffects_[ch]) changed = true;
    if (!changed) return true;
    EffectStore stored = {};
    stored.magic = kEffectMagic;
    stored.version = 1;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        stored.scenes[ch] = effects_[ch];
        stored.boot[ch] = bootEffects_[ch] ? 1 : 0;
    }
    stored.crc = effectChecksum(stored);
    if (storage_.putBytes("effects", &stored, sizeof(stored)) != sizeof(stored)) return false;
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
        savedEffects_[ch] = effects_[ch];
        savedBootEffects_[ch] = bootEffects_[ch];
    }
    return true;
}
bool ArgbController::setReactiveInput(uint8_t source, uint32_t value, uint32_t nowMs) {
    if (source == 0 || source > argbreaction::kMaxSource || value > argbreaction::kMaxValue)
        return false;
    inputs_[source].value = value;
    inputs_[source].stampMs = nowMs;
    inputs_[source].valid = true;
    return true;
}
void ArgbController::invalidateReactiveInput(uint8_t source) {
    if (source && source <= argbreaction::kMaxSource) inputs_[source].valid = false;
}
bool ArgbController::reactiveInput(uint8_t source, uint32_t nowMs, uint32_t& out) const {
    if (!source || source > argbreaction::kMaxSource ||
        !inputs_[source].valid || nowMs - inputs_[source].stampMs > argbreaction::kFreshMs)
        return false;
    out = inputs_[source].value;
    return true;
}
void ArgbController::drawReactive(uint8_t ch, uint32_t nowMs) {
    uint32_t value = 0;
    const auto& cfg = reactive_[ch];
    bool valid = reactiveInput(cfg.source, nowMs, value);
    if (!valid && cfg.fallback)
        valid = reactiveInput(cfg.fallback, nowMs, value);
    argbreaction::render(cfg, strips_[ch].numPixels(), nowMs, value, valid, frame_[ch]);
    markDirty(ch);
}
bool ArgbController::setReactive(uint8_t ch, const argbreaction::Config& cfg) {
    if (ch >= board::kChannelCount || !argbreaction::valid(cfg)) return false;
    reactive_[ch] = cfg;
    modes_[ch] = Mode::Reactive;
    brightness_[ch] = cfg.scene.brightness;
    drawReactive(ch, millis());
    return true;
}
bool ArgbController::startReactive(uint8_t ch) {
    return ch < board::kChannelCount && setReactive(ch, reactive_[ch]);
}
bool ArgbController::setReactiveBoot(uint8_t ch, bool enabled) {
    if (ch >= board::kChannelCount) return false;
    bootReactive_[ch] = enabled;
    return true;
}
const argbreaction::Config& ArgbController::reactive(uint8_t ch) const {
    static const argbreaction::Config factory = argbreaction::defaults();
    return ch < board::kChannelCount ? reactive_[ch] : factory;
}
bool ArgbController::reactiveBoot(uint8_t ch) const {
    return ch < board::kChannelCount && bootReactive_[ch];
}
bool ArgbController::reactiveActive() const {
    for (uint8_t ch=0; ch<board::kChannelCount; ++ch)
        if (modes_[ch] == Mode::Reactive) return true;
    return false;
}
bool ArgbController::saveReactive() {
    bool changed = false;
    for (uint8_t ch=0; ch<board::kChannelCount; ++ch)
        if (memcmp(&reactive_[ch], &savedReactive_[ch], sizeof(reactive_[ch])) ||
            bootReactive_[ch] != savedBootReactive_[ch]) changed = true;
    if (!changed) return true;
    ReactiveStore stored = {};
    stored.magic = kReactiveMagic;
    stored.version = 1;
    for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
        stored.scenes[ch] = reactive_[ch];
        stored.boot[ch] = bootReactive_[ch] ? 1 : 0;
    }
    stored.crc = reactiveChecksum(stored);
    if (storage_.putBytes("reactive", &stored, sizeof(stored)) != sizeof(stored))
        return false;
    for (uint8_t ch=0; ch<board::kChannelCount; ++ch) {
        savedReactive_[ch] = reactive_[ch];
        savedBootReactive_[ch] = bootReactive_[ch];
    }
    return true;
}
bool ArgbController::setPixels(uint8_t ch, const uint8_t* rgb, uint16_t count) {
    if (ch >= board::kChannelCount || !rgb || !count ||
        count > board::kMaxArgbPixelsPerFrame || count > strips_[ch].numPixels()) return false;
    if (modes_[ch] != Mode::External) brightness_[ch] = 255;
    modes_[ch] = Mode::External;
    lastExternalFrameMs_[ch] = millis();
    memcpy(frame_[ch], rgb, count * 3U);
    memset(frame_[ch] + count * 3U, 0, (strips_[ch].numPixels() - count) * 3U);
    markDirty(ch);
    // LED output deferred to update() so fan control/serial input get priority.
    return true;
}
bool ArgbController::configureStrip(uint8_t ch, uint16_t count, bool reversed) {
    if (ch >= board::kChannelCount) return false;
    return configureStripAndBudget(ch, count, reversed, powerLimitMa_);
}
bool ArgbController::configureStripAndBudget(uint8_t ch, uint16_t count,
                                             bool reversed, uint16_t budgetMa) {
    if (ch >= board::kChannelCount || count == 0 ||
        count > board::kMaxArgbPixelsPerFrame ||
        budgetMa < 100 || budgetMa > 20000) return false;
    uint32_t idleBaselineMa = count;
    for (uint8_t i = 0; i < board::kChannelCount; ++i)
        if (i != ch) idleBaselineMa += strips_[i].numPixels();
    if (budgetMa < idleBaselineMa) return false;

    const bool geometryChanged = strips_[ch].numPixels() != count ||
                                 reversed_[ch] != reversed;
    const bool budgetChanged = powerLimitMa_ != budgetMa;
    if (!geometryChanged && !budgetChanged) return true; // preserve scene; no flash wear

    Config config = {};
    config.magic = kArgbMagic;
    config.budgetMa = budgetMa;
    for (uint8_t i = 0; i < board::kChannelCount; ++i) {
        config.counts[i] = (i == ch) ? count : strips_[i].numPixels();
        config.reversed[i] = (i == ch) ? reversed : reversed_[i];
    }
    config.crc = checksum(config);
    if (storage_.putBytes("config", &config, sizeof(config)) != sizeof(config))
        return false; // never alter RAM settings on a failed NVS commit

    if (geometryChanged) {
        strips_[ch].updateLength(count);
        reversed_[ch] = reversed;
        memset(frame_[ch], 0, sizeof(frame_[ch]));
        modes_[ch] = Mode::Off;
        markDirty(ch);
    }
    if (budgetChanged) {
        powerLimitMa_ = budgetMa;
        for (uint8_t i = 0; i < board::kChannelCount; ++i) markDirty(i);
    }
    return true;
}
bool ArgbController::setPowerBudget(uint16_t ma) {
    return configureStripAndBudget(0, strips_[0].numPixels(), reversed_[0], ma);
}
bool ArgbController::isReversed(uint8_t ch) const { return ch < board::kChannelCount && reversed_[ch]; }
uint16_t ArgbController::pixelCount(uint8_t ch) const { return ch < board::kChannelCount ? strips_[ch].numPixels() : 0; }
bool ArgbController::setBrightness(uint8_t ch, uint8_t value) {
    if (ch >= board::kChannelCount) return false;
    if (savedBrightness_[ch] != value) {
        BrightnessConfig updated = {};
        updated.magic = kBrightnessMagic;
        for (uint8_t i = 0; i < board::kChannelCount; ++i)
            updated.levels[i] = savedBrightness_[i];
        updated.levels[ch] = value;
        updated.crc = brightnessChecksum(updated);
        // NVS failure cannot claim success or alter RAM; raw RGB frames
        // never trigger these writes, avoiding flash wear.
        if (storage_.putBytes("brightness", &updated, sizeof(updated)) != sizeof(updated))
            return false;
        savedBrightness_[ch] = value;
    }
    brightness_[ch] = value;
    markDirty(ch);
    // LED output deferred to update() so fan control/serial input get priority.
    return true;
}
ArgbController::Mode ArgbController::getMode(uint8_t ch) const { return ch < board::kChannelCount ? modes_[ch] : Mode::Off; }
uint8_t ArgbController::getBrightness(uint8_t ch) const { return ch < board::kChannelCount ? brightness_[ch] : 0; }
uint8_t ArgbController::getStoredBrightness(uint8_t ch) const {
    return ch < board::kChannelCount ? savedBrightness_[ch] : 0;
}
void ArgbController::update(uint32_t nowMs) {
    const bool pulse = (nowMs / 500U) % 2U == 0;
    if (pulse != warningOn_) {
        warningOn_ = pulse;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
            if (safetyWarnings_[ch]) markDirty(ch);
    }
    // External frames and Serial commands only mark dirty; no LED show() inside
    // those handlers can monopolize the USB/TACH control loop.
    for (uint8_t ch = 0; ch < board::kChannelCount; ++ch)
        if (modes_[ch] == Mode::External && nowMs - lastExternalFrameMs_[ch] > kExternalTimeoutMs)
            setOff(ch);
    if (nowMs - previousFrameMs_ >= board::kArgbFrameMs) {
        previousFrameMs_ = nowMs;
        for (uint8_t ch = 0; ch < board::kChannelCount; ++ch) {
            if (modes_[ch] == Mode::Reactive) {
                drawReactive(ch, nowMs);
                continue;
            }
            if (modes_[ch] == Mode::Effect) {
                if (effects_[ch].pattern != static_cast<uint8_t>(argbeffects::Pattern::Gradient)) {
                    argbeffects::render(effects_[ch], strips_[ch].numPixels(), nowMs, frame_[ch]);
                    markDirty(ch);
                }
                continue;
            }
            if (modes_[ch] != Mode::Rainbow) continue;
            const uint16_t count = strips_[ch].numPixels();
            for (uint16_t pixel = 0; pixel < count; ++pixel) {
                const uint16_t hue = static_cast<uint16_t>(
                    rainbowHue_ + (static_cast<uint32_t>(pixel) * 65536UL) / count);
                const uint32_t color = Adafruit_NeoPixel::gamma32(Adafruit_NeoPixel::ColorHSV(hue));
                const uint16_t n = pixel * 3U;
                frame_[ch][n] = static_cast<uint8_t>(color >> 16U);
                frame_[ch][n+1] = static_cast<uint8_t>(color >> 8U);
                frame_[ch][n+2] = static_cast<uint8_t>(color);
            }
            markDirty(ch);
        }
        rainbowHue_ += 192;
    }
    // Max one strip per ~6 ms visit, while rainbow animation keeps its
    // previous 40 ms cadence. The ESP controls cooling before reaching here.
    if (nowMs - previousRenderMs_ >= 6U) {
        previousRenderMs_ = nowMs;
        render();
    }
}

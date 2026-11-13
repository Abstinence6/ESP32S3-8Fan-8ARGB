"""Non-decreasing-on-rise temperature smoothing and automatic profile decisions.

This module never outputs a PWM duty.  The ESP32 applies its own curve,
calibration, critical-temperature protection and 10-second stale-data guard.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class _Channel:
    filtered: float
    stamp: float
    below_since: float | None = None


class SafeTemperatureFilter:
    """Immediate temperature rises; delayed and rate-limited decreases.

    On lost/invalid input, return None instead of holding the previous sample.
    """
    def __init__(self, hysteresis: float = 1.5, hold_seconds: float = 4.0,
                 falling_celsius_per_second: float = 2.0):
        if hysteresis < 0 or hold_seconds < 0 or falling_celsius_per_second <= 0:
            raise ValueError("Invalid smoothing parameters")
        self.hysteresis = hysteresis
        self.hold_seconds = hold_seconds
        self.fall_rate = falling_celsius_per_second
        self._states: dict[int, _Channel] = {}

    def update(self, channel: int, temperature: float | None, now: float) -> float | None:
        if not 1 <= channel <= 8:
            raise ValueError("Invalid fan channel")
        if temperature is None or not math.isfinite(temperature) or not 0 <= temperature <= 125:
            self._states.pop(channel, None)
            return None
        state = self._states.get(channel)
        if state is None or now <= state.stamp or now - state.stamp > 8:
            self._states[channel] = _Channel(temperature, now)
            return temperature
        elapsed = now - state.stamp
        state.stamp = now
        if temperature >= state.filtered:  # critical spikes must NEVER be delayed
            state.filtered = temperature
            state.below_since = None
        elif state.filtered - temperature < self.hysteresis:
            state.below_since = None
        elif state.below_since is None:
            state.below_since = now
        elif now - state.below_since >= self.hold_seconds:
            state.filtered = max(temperature, state.filtered - self.fall_rate * elapsed)
        return round(state.filtered, 2)


class AutoProfileSelector:
    """Debounced Windows profiles with a minimum interval between NVS writes.

    Active only when the user has explicitly enabled automatic profiles.
    """
    def __init__(self, high_load: float = 70.0, low_load: float = 35.0,
                 dwell_seconds: float = 40.0, min_change_seconds: float = 900.0):
        self.high_load = high_load
        self.low_load = low_load
        self.dwell_seconds = dwell_seconds
        self.min_change_seconds = min_change_seconds
        self.current: str | None = None
        self.candidate: str | None = None
        self.candidate_since: float = 0.0
        self.last_applied: float = -1e12

    def recommend(self, gpu_load: float | None, hour: int) -> str:
        if not 0 <= hour <= 23:
            raise ValueError("Invalid local hour")
        if gpu_load is not None and (not math.isfinite(gpu_load) or not 0 <= gpu_load <= 100):
            gpu_load = None
        gaming = (gpu_load is not None and gpu_load >= self.high_load or
                  self.current == "Performance" and gpu_load is not None and gpu_load >= self.low_load)
        if gaming:
            return "Performance"
        if hour >= 23 or hour < 7:
            return "Silent"
        return "Balanced"

    def consider(self, gpu_load: float | None, hour: int, now: float) -> str | None:
        desired = self.recommend(gpu_load, hour)
        if desired == self.current:
            self.candidate = None
            return None
        if desired != self.candidate:
            self.candidate = desired
            self.candidate_since = now
            return None
        if (now - self.candidate_since < self.dwell_seconds or
                now - self.last_applied < self.min_change_seconds):
            return None
        return desired

    def applied(self, profile: str, now: float) -> None:
        if profile not in ("Silent", "Balanced", "Performance"):
            raise ValueError("Invalid profile")
        self.current = profile
        self.last_applied = now
        self.candidate = None

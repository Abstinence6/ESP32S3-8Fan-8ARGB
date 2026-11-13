"""Passive tachometer anomaly monitoring; never issues fan power commands.

Long-running RPM trends are persisted separately in telemetry_store.py.
A missing TACH is a diagnostic suspicion, not proof of stopped fan blades.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median


@dataclass
class _FanWindow:
    duty: int = -1
    observations: deque[float] = field(default_factory=lambda: deque(maxlen=8))
    zero_samples: int = 0
    flagged: str = ""


class TachHealthMonitor:
    def __init__(self, window: int = 8, min_samples: int = 4):
        self.window = window
        self.min_samples = min_samples
        self._fans: dict[int, _FanWindow] = {}

    def observe(self, channel: int, *, pwm: int, rpm: int,
                has_feedback: bool, fault: bool = False) -> str | None:
        if not 1 <= channel <= 8 or not 0 <= pwm <= 100 or rpm < 0:
            return None
        entry = self._fans.setdefault(channel, _FanWindow())
        if not has_feedback:
            entry.observations.clear()
            entry.zero_samples = 0
            entry.flagged = ""
            return None
        # A new duty is a different operating point, not a hardware failure.
        if abs(pwm - entry.duty) >= 4:
            entry.duty = pwm
            entry.observations.clear()
            entry.zero_samples = 0
            entry.flagged = ""
        if rpm == 0 and pwm >= 35:
            entry.zero_samples += 1
            if entry.zero_samples >= 3 and entry.flagged != "missing":
                entry.flagged = "missing"
                return f"Fan {channel}: зник сигнал TACH при {pwm}% PWM (можливий обрив або зупинка)"
            return None
        entry.zero_samples = 0
        if rpm <= 0 or fault:
            return None
        entry.observations.append(float(rpm))
        if len(entry.observations) < self.min_samples:
            return None
        baseline = median(entry.observations)
        if baseline < 200:
            return None
        deviations = [
            abs(v - baseline) / baseline
            for v in entry.observations
        ]
        # Ignore one-off spikes. Require at least three large deviations
        # at a nearly unchanged duty to avoid nuisance warnings.
        unstable = sum(d > 0.25 for d in deviations) >= 3
        if unstable and entry.flagged != "unstable":
            entry.flagged = "unstable"
            return f"Fan {channel}: нестабільні RPM при {pwm}% PWM, перевір TACH/живлення"
        if not unstable and entry.flagged == "unstable":
            entry.flagged = ""
        if entry.flagged == "missing":
            entry.flagged = ""
        return None

    def reset(self) -> None:
        self._fans.clear()

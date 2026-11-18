"""Passive tachometer anomaly monitoring; never issues fan power commands.

Long-running RPM trends are persisted separately in telemetry_store.py.
A missing TACH is a diagnostic suspicion, not proof of stopped fan blades.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median
import json


@dataclass
class _FanWindow:
    duty: int = -1
    observations: deque[float] = field(default_factory=lambda: deque(maxlen=8))
    zero_samples: int = 0
    flagged: str = ""
    degraded_samples: int = 0


class TachHealthMonitor:
    def __init__(self, window: int = 8, min_samples: int = 4):
        self.window = window
        self.min_samples = min_samples
        self._fans: dict[int, _FanWindow] = {}
        self.references: dict[int, tuple[int, int]] = {}

    def set_reference(self, channel: int, pwm: int, rpm: int) -> None:
        if type(channel) is not int or not 1 <= channel <= 8 or \
           type(pwm) is not int or not 35 <= pwm <= 100 or \
           type(rpm) is not int or not 200 <= rpm <= 25000:
            raise ValueError("Invalid RPM reference")
        self.references[channel] = (pwm, rpm)
        self._fans.pop(channel, None)

    def clear_reference(self, channel: int) -> None:
        self.references.pop(channel, None)
        self._fans.pop(channel, None)

    def candidate_reference(self, channel: int) -> tuple[int, int] | None:
        entry = self._fans.get(channel)
        if not entry or entry.duty < 35 or len(entry.observations) < self.min_samples:
            return None
        values = tuple(entry.observations)
        baseline = median(values)
        if baseline < 200 or (max(values) - min(values)) > baseline * 0.08:
            return None
        return entry.duty, round(baseline)

    def status(self, channel: int) -> str:
        if channel not in self.references:
            return "Без еталона"
        entry = self._fans.get(channel)
        if not entry or len(entry.observations) < self.min_samples:
            return "Очікування вимірювань"
        return "Падіння RPM" if entry.flagged == "degraded" else "Норма"

    def import_references(self, raw: str) -> None:
        self.references = load_references(raw)
        self._fans.clear()

    def export_references(self) -> str:
        return dump_references(self.references)

    def observe(self, channel: int, *, pwm: int, rpm: int,
                has_feedback: bool, fault: bool = False) -> str | None:
        if not 1 <= channel <= 8 or not 0 <= pwm <= 100 or rpm < 0:
            return None
        entry = self._fans.setdefault(channel, _FanWindow())
        if not has_feedback:
            entry.observations.clear()
            entry.zero_samples = 0
            entry.flagged = ""
            entry.degraded_samples = 0
            return None
        # A new duty is a different operating point, not a hardware failure.
        if abs(pwm - entry.duty) >= 4:
            entry.duty = pwm
            entry.observations.clear()
            entry.zero_samples = 0
            entry.flagged = ""
            entry.degraded_samples = 0
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
        reference = self.references.get(channel)
        if reference and abs(pwm - reference[0]) <= 3:
            if baseline < reference[1] * 0.80:
                entry.degraded_samples += 1
                if entry.degraded_samples >= 3:
                    if entry.flagged != "degraded":
                        entry.flagged = "degraded"
                        reduction = round((1 - baseline / reference[1]) * 100)
                        return f"Fan {channel}: RPM нижче еталона на {reduction}% при {pwm}% PWM"
                    return None  # Do not overwrite the active degradation with a noise warning.
            else:
                entry.degraded_samples = 0
                if entry.flagged == "degraded":
                    entry.flagged = ""
        else:
            entry.degraded_samples = 0
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


def load_references(raw: str) -> dict[int, tuple[int, int]]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Invalid reference version")
        values = data.get("fans")
        if not isinstance(values, dict) or len(values) > 8:
            raise ValueError("Invalid references")
        monitor = TachHealthMonitor()
        for key, pair in values.items():
            if not isinstance(key, str) or not key.isdecimal() or \
               not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Invalid reference entry")
            monitor.set_reference(int(key), pair[0], pair[1])
        return monitor.references
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Invalid references") from exc


def dump_references(references: dict[int, tuple[int, int]]) -> str:
    monitor = TachHealthMonitor()
    for ch, (pwm, rpm) in references.items():
        monitor.set_reference(ch, pwm, rpm)
    return json.dumps({"version": 1, "fans": {
        str(ch): list(pair) for ch, pair in sorted(monitor.references.items())
    }}, sort_keys=True)

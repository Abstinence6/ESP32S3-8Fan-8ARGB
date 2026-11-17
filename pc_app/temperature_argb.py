"""Per-zone temperature-driven ARGB: pure, testable sensor and color mapping.

The PC owns the temperature source; the ESP still enforces ARGB current limits.
Missing/stale sensor input must never be displayed as a cool/healthy blue/green.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

try:
    from .temperature_palette import Palette, color_at
except ImportError:
    from temperature_palette import Palette, color_at

try:
    from .monitor import (
        GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED, MAX_ALL, MAX_CPU_GPU,
        TemperatureSensor, resolve_temperature,
    )
except ImportError:
    from monitor import (
        GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED, MAX_ALL, MAX_CPU_GPU,
        TemperatureSensor, resolve_temperature,
    )

OFF = "__OFF__"
ASSIGNMENTS = (OFF, MAX_ALL, MAX_CPU_GPU, GROUP_MAX, GROUP_AVG, GROUP_WEIGHTED)
MISSING_RGB = (255, 88, 0)  # amber; unavailable sensor is never represented as cold

@dataclass(frozen=True)
class ZoneTemperatureConfig:
    source: str = OFF
    group_ids: tuple[str, ...] = ()
    low_c: int = 30
    high_c: int = 85
    brightness: int = 64

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source or len(self.source.encode("utf-8")) > 95:
            raise ValueError("Invalid temperature source")
        if not isinstance(self.group_ids, tuple) or len(self.group_ids) > 8 or any(
            not isinstance(item, str) or not 0 < len(item.encode("utf-8")) <= 95 for item in self.group_ids
        ):
            raise ValueError("Invalid temperature sensor group")
        if len(self.group_ids) != len(set(self.group_ids)):
            raise ValueError("Duplicate temperature sensors in group")
        if not (0 <= self.low_c < self.high_c <= 125):
            raise ValueError("Invalid temperature range")
        if not 0 <= self.brightness <= 128:
            raise ValueError("Invalid ARGB brightness")

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "group_ids": list(self.group_ids),
            "low_c": self.low_c,
            "high_c": self.high_c,
            "brightness": self.brightness,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ZoneTemperatureConfig":
        if not isinstance(value, dict):
            raise ValueError("Expected temperature zone object")
        group = value.get("group_ids", [])
        if not isinstance(group, list):
            raise ValueError("Invalid group format")
        return cls(
            source=value.get("source", OFF), group_ids=tuple(group),
            low_c=value.get("low_c", 30), high_c=value.get("high_c", 85),
            brightness=value.get("brightness", 64),
        )


def temperature_color(celsius: float | None, settings: ZoneTemperatureConfig,
                      palette: Palette | None = None) -> tuple[int, int, int]:
    """Blue -> green -> yellow -> red, with a conspicuous amber missing state."""
    if celsius is None or not isinstance(celsius, (float, int)) or (
        isinstance(celsius, bool) or not math.isfinite(celsius) or not 0 <= celsius <= 125
    ):
        target = MISSING_RGB
    elif palette is not None:
        target = color_at(celsius, palette)
    else:
        level = min(1.0, max(0.0, (celsius - settings.low_c) /
                              (settings.high_c - settings.low_c)))
        anchors = (
            (0.0, (0, 100, 255)),
            (0.35, (0, 220, 65)),
            (0.70, (255, 190, 0)),
            (1.0, (255, 0, 0)),
        )
        target = anchors[-1][1]
        for (x0, c0), (x1, c1) in zip(anchors, anchors[1:]):
            if level <= x1:
                fraction = (level - x0) / (x1 - x0)
                target = tuple(round(v0 + (v1 - v0) * fraction)
                               for v0, v1 in zip(c0, c1))
                break
    return tuple(round(channel * settings.brightness / 255) for channel in target)


def zone_color(settings: ZoneTemperatureConfig, sensors: list[TemperatureSensor],
               *, fresh: bool, palette: Palette | None = None) -> tuple[int, int, int] | None:
    """One sensor or a strict group (all member IDs must be present)."""
    if settings.source == OFF:
        return None
    reading = resolve_temperature(settings.source, sensors, settings.group_ids) if fresh else None
    return temperature_color(reading, settings, palette)

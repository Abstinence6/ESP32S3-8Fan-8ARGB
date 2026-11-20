"""Shared PC sensor -> safe USB command planning for GUI and headless agent.

The ESP32 remains the authority for cooling, thermal timeouts and PWM. Missing
or invalid readings intentionally produce no TEMP command, not a guessed value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import time
from typing import Mapping, Sequence

try:
    from .monitor import MAX_ALL, TemperatureResolution, resolve_temperature_evidence
    from .protocol import make_temperature_command, make_curve_command
    from .cooling_assist import extract_power_watts, power_payload
    from .profiles import PRESETS
except ImportError:  # standalone PyInstaller / running pc_app/main.py directly
    from monitor import MAX_ALL, TemperatureResolution, resolve_temperature_evidence
    from protocol import make_temperature_command, make_curve_command
    from cooling_assist import extract_power_watts, power_payload
    from profiles import PRESETS


@dataclass(frozen=True)
class FanSensorRoute:
    primary: str = MAX_ALL
    secondary: str = MAX_ALL
    group_ids: tuple[str, ...] = ()
    weights: Mapping[str, object] = field(default_factory=dict)
    dual: bool = False


@dataclass(frozen=True)
class SensorPlan:
    commands: tuple[str, ...]
    cpu_watts: float | None
    gpu_watts: float | None


def routes_from_settings(settings) -> tuple[FanSensorRoute, ...]:
    """Read the eight persisted routes used by the background agent."""
    routes = []
    for ch in range(1, 9):
        try:
            group = json.loads(str(settings.value(f"groupSensors{ch}", "[]")))
            weights = json.loads(str(settings.value(f"groupWeights{ch}", "{}")))
        except (TypeError, ValueError):
            group, weights = [], {}
        if not isinstance(group, list):
            group = []
        if not isinstance(weights, dict):
            weights = {}
        routes.append(FanSensorRoute(
            primary=str(settings.value(f"source{ch}", MAX_ALL)),
            secondary=str(settings.value(f"source2{ch}", MAX_ALL)),
            group_ids=tuple(item for item in group if isinstance(item, str)),
            weights=weights,
            dual=str(settings.value(f"dualEnabled{ch}", "false")).lower() in ("true", "1"),
        ))
    return tuple(routes)


def resolve_route_temperature(assignment, sensors, group_ids, weights) -> TemperatureResolution:
    """Expose the same safety-checked resolution to routing and read-only UI."""
    try:
        result = resolve_temperature_evidence(assignment, sensors, group_ids, weights)
    except (ValueError, TypeError, OverflowError):
        return TemperatureResolution()
    value = result.celsius
    if value is not None and not (math.isfinite(value) and 0 <= value <= 125):
        return TemperatureResolution()
    return result


def plan_sensor_telemetry(
    routes: Sequence[FanSensorRoute], sensors, metrics=(), *,
    filter_engine=None, smoothing: bool = False, now: float | None = None,
    include_power: bool = True,
) -> SensorPlan:
    """Return ordered serial commands without sending or retaining stale data."""
    if len(routes) != 8:
        raise ValueError("Expected eight fan routes")
    if now is None:
        now = time.monotonic()
    commands: list[str] = []
    for ch, route in enumerate(routes, start=1):
        primary = resolve_route_temperature(route.primary, sensors, route.group_ids, route.weights).celsius
        if smoothing and filter_engine is not None:
            primary = filter_engine.update(ch, primary, now)
        if primary is not None:
            commands.append(make_temperature_command(ch, primary))
        if route.dual:
            secondary = resolve_route_temperature(route.secondary, sensors, route.group_ids, route.weights).celsius
            if secondary is not None:
                commands.append(make_temperature_command(ch, secondary).replace("TEMP ", "TEMP2 ", 1))
    cpu_w, gpu_w = extract_power_watts(metrics)
    if include_power:
        commands.append(power_payload(cpu_w, gpu_w))
    return SensorPlan(tuple(commands), cpu_w, gpu_w)


def choose_automatic_profile(metrics, selector, *, hour: int, now: float) -> str | None:
    """Exactly the same GPU-load decision for foreground and headless modes."""
    loads = []
    for metric in metrics:
        name = str(getattr(metric, "name", "")).casefold()
        value = getattr(metric, "value", None)
        if (getattr(metric, "kind", None) == "load" and "gpu" in name and
            ("utilization" in name or "load" in name) and
            isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(value) and 0 <= value <= 100):
            loads.append(float(value))
    return selector.consider(max(loads, default=None), hour, now)


def automatic_profile_commands(profile: str) -> tuple[str, ...]:
    """Plan all eight profile updates; caller records success after sending."""
    if profile not in ("Silent", "Balanced", "Performance"):
        raise ValueError("Invalid automatic profile")
    return tuple(make_curve_command(ch, list(PRESETS[profile])) for ch in range(1, 9))

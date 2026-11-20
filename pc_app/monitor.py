"""Libre Hardware Monitor temperature collection (stdlib-only, testable)."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import urllib.request
from typing import Any, Mapping


@dataclass(frozen=True)
class TemperatureSensor:
    sensor_id: str
    name: str
    celsius: float


@dataclass(frozen=True)
class TemperatureResolution:
    celsius: float | None = None
    contributors: tuple[TemperatureSensor, ...] = ()
    missing_ids: tuple[str, ...] = ()


DEFAULT_LHM_URL = "http://127.0.0.1:8085/data.json"
MAX_ALL = "__MAX_ALL__"
MAX_CPU_GPU = "__MAX_CPU_GPU__"
GROUP_AVG = "__GROUP_AVG__"
GROUP_MAX = "__GROUP_MAX__"
GROUP_WEIGHTED = "__GROUP_WEIGHTED__"


# LibreHardwareMonitor 0.9.6 may supply *formatted strings* even under
# RawValue (example: "46.9 °C"). Older versions return numeric RawValue.
# Reject implausible/invalid readings rather than sending unsafe temperatures.
_TEMPERATURE_VALUE = re.compile(
    r"(?P<value>[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+))(?:\s*(?:°\s*)?(?P<unit>[cCfF]))?"
)


def _temperature_celsius(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)  # numeric RawValue from LHM is Celsius
    elif isinstance(raw, str):
        match = _TEMPERATURE_VALUE.fullmatch(raw.strip())
        if not match:
            return None
        value = float(match.group("value").replace(",", "."))
        if (match.group("unit") or "").upper() == "F":
            value = (value - 32.0) * 5.0 / 9.0
    else:
        return None
    # The ESP's TEMP protocol accepts 0..125 C. An invalid reading must
    # never be clamped or substituted: its stale-temperature fail-safe stays active.
    return value if math.isfinite(value) and 0.0 <= value <= 125.0 else None


def parse_temperatures(tree: Any) -> list[TemperatureSensor]:
    """Return all valid *temperature* sensors using stable LHM SensorId keys."""
    found: list[TemperatureSensor] = []
    seen: set[str] = set()

    def visit(node: Any, ancestors: tuple[str, ...]) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, ancestors)
            return
        if not isinstance(node, dict):
            return
        name = str(node.get("Text", "")).strip()
        sensor_id = node.get("SensorId")
        if node.get("Type") == "Temperature" and isinstance(sensor_id, str) and sensor_id:
            celsius = _temperature_celsius(node.get("RawValue"))
            if celsius is None:
                celsius = _temperature_celsius(node.get("Value"))
            if celsius is not None and sensor_id not in seen:
                label = " / ".join(p for p in (*ancestors, name) if p)
                found.append(TemperatureSensor(sensor_id, label or sensor_id, celsius))
                seen.add(sensor_id)
        next_ancestors = ancestors + ((name,) if name and node.get("Type") != "Temperature" else ())
        visit(node.get("Children", []), next_ancestors)

    visit(tree, ())
    return sorted(found, key=lambda sensor: sensor.name.lower())


def fetch_temperatures(url: str = DEFAULT_LHM_URL, timeout: float = 1.0) -> list[TemperatureSensor]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        tree = json.load(response)
    return parse_temperatures(tree)


def resolve_temperature(
    assignment: str,
    sensors: list[TemperatureSensor],
    group_ids: list[str] | tuple[str, ...] = (),
    weights: dict[str, float] | None = None,
) -> float | None:
    return resolve_temperature_evidence(assignment, sensors, group_ids, weights).celsius


def resolve_temperature_evidence(
    assignment: str,
    sensors: list[TemperatureSensor],
    group_ids: list[str] | tuple[str, ...] = (),
    weights: Mapping[str, float] | None = None,
) -> TemperatureResolution:
    """Resolve a route and identify the sensor(s) behind its result.

    An empty group or any missing group member returns None. Do not silently
    average fewer sensors: on missing readings the ESP must time out to safe PWM.
    """
    if assignment in (MAX_ALL, MAX_CPU_GPU):
        winner = max(
            (sensor for sensor in sensors
             if assignment == MAX_ALL
             or sensor.sensor_id.casefold().startswith(("nwinfo/cpu/", "nwinfo/gpu/"))
             or any(tag in sensor.name.casefold() for tag in
                    ("cpu", "gpu", "intel core", "amd radeon", "nvidia"))),
            key=lambda sensor: sensor.celsius,
            default=None,
        )
        return TemperatureResolution(winner.celsius, (winner,)) if winner else TemperatureResolution()
    if assignment in (GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED):
        chosen = set(group_ids)
        if not chosen:
            return TemperatureResolution()
        by_id = {sensor.sensor_id: sensor for sensor in sensors}
        missing = tuple(sorted(chosen - by_id.keys()))
        if missing:
            return TemperatureResolution(missing_ids=missing)
        members = tuple(by_id[ident] for ident in chosen)
        values = [sensor.celsius for sensor in members]
        if assignment == GROUP_AVG:
            return TemperatureResolution(sum(values) / len(values), members)
        if assignment == GROUP_MAX:
            winner = max(members, key=lambda sensor: sensor.celsius)
            return TemperatureResolution(winner.celsius, (winner,))
        factors = [float((weights or {}).get(ident, 1.0)) for ident in chosen]
        if any(not math.isfinite(weight) or weight <= 0 for weight in factors):
            return TemperatureResolution()
        value = sum(value * weight for value, weight in zip(values, factors)) / sum(factors)
        return TemperatureResolution(value, members)
    for sensor in sensors:
        if sensor.sensor_id == assignment:
            return TemperatureResolution(sensor.celsius, (sensor,))
    return TemperatureResolution(missing_ids=(assignment,))

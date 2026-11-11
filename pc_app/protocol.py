"""Wire protocol shared between the Windows GUI and the ESP32-S3 firmware."""
from __future__ import annotations

from dataclasses import dataclass
import re

POINTS = 5
DEFAULT_CURVE = [(25, 25), (35, 35), (50, 55), (65, 80), (80, 100)]


@dataclass(frozen=True)
class FanStatus:
    channel: int
    pwm: int
    rpm: int
    deci_c: int
    mode: str
    fresh: bool
    target_rpm: int | None = None
    fault: bool = False
    detected_type: int | None = None
    rpm_feedback: bool = True


STATUS_RE = re.compile(
    r"^CH ([1-8]) FAN=(\d+)% RPM=(\d+) TEMP=(\d+) "
    r"MODE=(auto|manual|cal|rpm) SENSOR=(ok|stale)(?:\s+(.*))?$"
)


def parse_status(line: str) -> FanStatus | None:
    match = STATUS_RE.fullmatch(line.strip())
    if not match:
        return None
    ch, pwm, rpm, temp, mode, sensor, extra = match.groups()
    metadata: dict[str, str] = {}
    for token in (extra or "").split():
        if "=" in token:
            key, value = token.split("=", 1)
            metadata[key] = value
    try:
        target = int(metadata["TARGET"]) if "TARGET" in metadata else None
        wiring = int(metadata["TYPE"]) if "TYPE" in metadata else None
        fault = bool(int(metadata.get("FAULT", "0")))
        feedback = bool(int(metadata.get("RPM_OK", "1")))
    except ValueError:
        return None
    return FanStatus(int(ch), int(pwm), int(rpm), int(temp), mode,
                     sensor == "ok", target, fault, wiring, feedback)


def validate_curve(points: list[tuple[int, int]]) -> bool:
    if len(points) != POINTS:
        return False
    for index, (temp, pwm) in enumerate(points):
        if not (0 <= temp <= 125 and 0 <= pwm <= 100):
            return False
        if index and (temp <= points[index - 1][0] or pwm < points[index - 1][1]):
            return False
    return True


def make_curve_command(ch: int, points: list[tuple[int, int]]) -> str:
    if not 1 <= ch <= 8 or not validate_curve(points):
        raise ValueError("curve must have 5 ordered temperature/PWM points")
    return "CURVE " + str(ch) + " " + " ".join(f"{t} {p}" for t, p in points)


def parse_curve(line: str) -> tuple[int, list[tuple[int, int]]] | None:
    tokens = line.split()
    if len(tokens) != 12 or tokens[0] != "CURVE":
        return None
    try:
        values = [int(token) for token in tokens[1:]]
    except ValueError:
        return None
    ch, raw = values[0], values[1:]
    points = list(zip(raw[::2], raw[1::2]))
    if 1 <= ch <= 8 and validate_curve(points):
        return ch, points
    return None


def make_temperature_command(ch: int, celsius: float) -> str:
    if not 1 <= ch <= 8:
        raise ValueError("fan channel must be 1..8")
    deci = round(celsius * 10)
    if not 0 <= deci <= 1250:
        raise ValueError("temperature must be 0..125.0 C")
    return f"TEMP {ch} {deci}"

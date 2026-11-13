"""Original ARGB patterns encoded as RGB bytes for the ESP32 serial protocol.

Brightness is capped in the GUI, and the ESP32 retains its independent
total-current limiter. Streaming affects LEDs only, never fan PWM.
"""
from __future__ import annotations
import math


MODES = ("Gradient", "Wave", "Breathe", "Chase", "Static")


def render_effect(
    mode: str, count: int, seconds: float,
    primary: tuple[int, int, int], secondary: tuple[int, int, int],
    brightness: int = 64, speed: float = 1.0,
) -> bytes:
    if mode not in MODES or not 1 <= count <= 170 or not 0 <= brightness <= 255:
        raise ValueError("Invalid ARGB effect settings")
    if any(len(c) != 3 or any(type(x) is not int or not 0 <= x <= 255 for x in c)
           for c in (primary, secondary)):
        raise ValueError("Invalid color")
    if not math.isfinite(speed) or not 0.05 <= speed <= 5:
        raise ValueError("Invalid speed")
    if not math.isfinite(seconds):
        raise ValueError("Invalid timestamp")
    out = bytearray()
    for i in range(count):
        pos = i / max(1, count - 1)
        wave = 0.5 + 0.5 * math.sin(seconds * speed * 3.0 - pos * math.tau)
        if mode == "Static":
            blend = 0.0
            opacity = 1.0
        elif mode == "Gradient":
            blend = pos
            opacity = 1.0
        elif mode == "Wave":
            blend = wave
            opacity = 1.0
        elif mode == "Breathe":
            blend = pos
            opacity = 0.12 + 0.88 * (0.5 + 0.5 * math.sin(seconds * speed * 2))
        else:  # Chase: avoid more than 25% at a time, gentle falloff
            head = (seconds * speed * 0.2) % 1.0
            delta = min(abs(pos - head), 1.0 - abs(pos - head))
            blend = 0
            opacity = max(0.0, 1.0 - delta * 5.0)
        for a, b in zip(primary, secondary):
            out.append(round((a * (1 - blend) + b * blend) * brightness / 255 * opacity))
    return bytes(out)

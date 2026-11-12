"""Versioned fan + ARGB scene presets; no automatic hardware writes on import."""
from __future__ import annotations

import json

VERSION = 1
FAN_CURVES = {
    "Silent": [[25, 30], [35, 35], [45, 45], [60, 75], [75, 100]],
    "Balanced": [[25, 35], [35, 45], [50, 65], [65, 85], [80, 100]],
    "Performance": [[25, 45], [35, 55], [45, 75], [55, 95], [70, 100]],
}
RGB_SCENES = {
    "Off": {"mode": "off"},
    "Static warm": {"mode": "solid", "rgb": [255, 110, 30], "brightness": 64},
    "Static cool": {"mode": "solid", "rgb": [60, 130, 255], "brightness": 64},
    "Rainbow": {"mode": "rainbow", "brightness": 64},
    "OpenRGB": {"mode": "external"},
}


def create_configuration(fan_profile: str = "Balanced", rgb_scene: str = "Off") -> dict:
    if fan_profile not in FAN_CURVES or rgb_scene not in RGB_SCENES:
        raise ValueError("Unknown preset")
    return {
        "version": VERSION,
        "fan_curves": [[point[:] for point in FAN_CURVES[fan_profile]] for _ in range(8)],
        "argb": [dict(RGB_SCENES[rgb_scene]) for _ in range(8)],
    }


def validate_configuration(data: object) -> dict:
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise ValueError("Unsupported configuration version")
    curves = data.get("fan_curves")
    rgb = data.get("argb")
    if not isinstance(curves, list) or len(curves) != 8 or not isinstance(rgb, list) or len(rgb) != 8:
        raise ValueError("Expected 8 fan curves and 8 ARGB channels")
    for curve in curves:
        if not isinstance(curve, list) or len(curve) != 5:
            raise ValueError("Each fan requires 5 points")
        prev_t, prev_pwm = -1, -1
        for point in curve:
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(x) is not int for x in point)):
                raise ValueError("Invalid fan curve point")
            t, pwm = point
            if not 0 <= t <= 125 or not 0 <= pwm <= 100 or t <= prev_t or pwm < prev_pwm:
                raise ValueError("Fan curves must be ordered and monotonic")
            prev_t, prev_pwm = t, pwm
    for scene in rgb:
        if not isinstance(scene, dict) or scene.get("mode") not in ("off", "solid", "rainbow", "external"):
            raise ValueError("Invalid ARGB mode")
        if scene["mode"] == "solid":
            color = scene.get("rgb")
            if (not isinstance(color, list) or len(color) != 3 or
                    any(type(c) is not int or not 0 <= c <= 255 for c in color)):
                raise ValueError("Invalid RGB color")
        if scene["mode"] in ("solid", "rainbow"):
            b = scene.get("brightness")
            if type(b) is not int or not 0 <= b <= 255:
                raise ValueError("Invalid brightness")
    return data


def to_json(data: dict) -> str:
    validate_configuration(data)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def from_json(text: str) -> dict:
    return validate_configuration(json.loads(text))


def commands(data: dict) -> list[str]:
    """Only explicit opt-in application sends commands. Never alters fan type/PWM interlock."""
    validate_configuration(data)
    lines = []
    for ch, curve in enumerate(data["fan_curves"], 1):
        lines.append("CURVE " + str(ch) + " " + " ".join(f"{t} {p}" for t, p in curve))
    for ch, scene in enumerate(data["argb"], 1):
        mode = scene["mode"]
        if mode == "off":
            lines.append(f"OFF {ch}")
        elif mode == "solid":
            lines.append(f"BRIGHT {ch} {scene['brightness']}")
            lines.append(f"LED {ch} " + " ".join(map(str, scene["rgb"])))
        elif mode == "rainbow":
            lines.append(f"BRIGHT {ch} {scene['brightness']}")
            lines.append(f"RAINBOW {ch}")
        # External is an intent: it requires live OpenRGB frames, not an ESP serial mode.
    return lines


def openrgb_e131_manifest(led_counts: list[int], host: str = "127.0.0.1") -> dict:
    """Reference settings for manually creating OpenRGB E1.31 Devices (not OpenRGB's native import format)."""
    if (len(led_counts) != 8 or any(type(n) is not int or n < 1 or n > 170 for n in led_counts)):
        raise ValueError("Expected eight LED counts, each 1..170")
    return {"format": "esp32s3-openrgb-e131-reference-v1",
            "note": "Reference only: enter each device manually in OpenRGB Settings > E1.31 Devices",
            "transport": "sACN E1.31 / UDP 5568",
            "devices": [{"name": f"ESP32 ARGB {ch}", "ip": host, "universe": ch,
                         "start_channel": 1, "led_count": n, "color_order": "RGB",
                         "type": "Linear"} for ch, n in enumerate(led_counts, 1)]}

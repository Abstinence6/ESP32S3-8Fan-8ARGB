"""Presentation-neutral actions for the Windows dashboard.

ARGB scene selection must never modify cooling curves or fan power.
"""
from __future__ import annotations

from collections.abc import Iterable

try:
    from .config_presets import RGB_SCENES
except ImportError:  # app launched as pc_app/main.py or from PyInstaller
    from config_presets import RGB_SCENES


def make_scene_commands(scene_name: str, channels: Iterable[int]) -> list[str]:
    """Build only ARGB serial commands for selected 1-based output channels.

    An OpenRGB scene uses live sACN packets, so it has no static LED command.
    Caller enables the E1.31 USB bridge or configures direct Wi-Fi streaming.
    """
    if scene_name not in RGB_SCENES:
        raise ValueError("Невідомий світловий пресет")
    selected = list(channels)
    if not selected or len(set(selected)) != len(selected) or any(
        type(ch) is not int or not 1 <= ch <= 8 for ch in selected
    ):
        raise ValueError("Вибери канали ARGB від 1 до 8 без повторень")

    scene = RGB_SCENES[scene_name]
    mode = scene["mode"]
    result: list[str] = []
    for channel in selected:
        if mode == "off":
            result.append(f"OFF {channel}")
        elif mode == "solid":
            red, green, blue = scene["rgb"]
            result.append(f"BRIGHT {channel} {scene['brightness']}")
            result.append(f"LED {channel} {red} {green} {blue}")
        elif mode == "rainbow":
            result.append(f"BRIGHT {channel} {scene['brightness']}")
            result.append(f"RAINBOW {channel}")
    return result

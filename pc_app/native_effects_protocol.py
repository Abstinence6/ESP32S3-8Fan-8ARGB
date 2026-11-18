"""Strict ASCII interface for ESP32-native, safe RGB scenes."""
from __future__ import annotations
from dataclasses import dataclass

MODES = ("Gradient", "Wave", "Breathe", "Chase")

@dataclass(frozen=True)
class EffectState:
    channel: int
    mode: int
    primary: tuple[int,int,int]
    secondary: tuple[int,int,int]
    speed: int
    brightness: int
    direction: int
    boot: bool
    active: bool

def make_fx_set(channel, mode, primary, secondary, speed, brightness, direction):
    if (type(channel) is not int or not 1 <= channel <= 8 or
        type(mode) is not int or not 1 <= mode <= 4 or
        type(speed) is not int or not 1 <= speed <= 10 or
        type(brightness) is not int or not 0 <= brightness <= 255 or
        type(direction) is not int or direction not in (0,1) or
        any(not isinstance(rgb,(tuple,list)) or len(rgb)!=3 or
            any(type(c) is not int or not 0 <= c <= 255 for c in rgb)
            for rgb in (primary,secondary))):
        raise ValueError("Invalid native ARGB scene")
    return (f"FX SET {channel} {mode} " +
            " ".join(map(str,(*primary,*secondary))) +
            f" {speed} {brightness} {direction}")

def parse_fx_line(line: str) -> EffectState | None:
    if not line.startswith("FX CH="):
        return None
    try:
        parts = dict(field.split("=",1) for field in line.split()[1:] if "=" in field)
        primary = tuple(int(s) for s in parts["R1"].split(","))
        secondary = tuple(int(s) for s in parts["R2"].split(","))
        ch, mode = int(parts["CH"]), int(parts["MODE"])
        speed, bright, direction = int(parts["SPEED"]), int(parts["BRIGHT"]), int(parts["DIR"])
        boot, active = int(parts["BOOT"]), int(parts["ACTIVE"])
        make_fx_set(ch,mode,primary,secondary,speed,bright,direction)
        if boot not in (0,1) or active not in (0,1):
            raise ValueError("Invalid FX flags")
        return EffectState(ch,mode,primary,secondary,speed,bright,direction,bool(boot),bool(active))
    except (KeyError,TypeError,ValueError):
        return None

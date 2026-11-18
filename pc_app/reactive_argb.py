"""Versioned sensor-reactive ARGB configuration and USB telemetry.

The ESP32 does all LED rendering. Windows sends only selected, valid scalar
measurements at normal NWinfo sampling cadence (no RGB frame streaming).
Temperature measurements remain distinct from control-loop TEMP commands.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import math

SOURCE_MAX = 40
MAX_TENTHS = 10_000_000
REMOTE_START = 25
MAPPING_KEY = "reactiveHostSourcesV1"

@dataclass(frozen=True)
class ReactiveScene:
    channel: int
    source: int
    fallback: int
    style: int
    low: int
    high: int
    pattern: int
    primary: tuple[int,int,int]
    secondary: tuple[int,int,int]
    speed: int
    brightness: int
    direction: int
    boot: bool = False
    active: bool = False
    fresh: bool = False
    value: int = 0

def local_source(source: int) -> bool:
    return 1 <= source <= 24 or 33 <= source <= 40

def validate_scene(s: ReactiveScene) -> ReactiveScene:
    if (type(s.channel) is not int or not 1 <= s.channel <= 8 or
        type(s.source) is not int or not 1 <= s.source <= SOURCE_MAX or
        type(s.fallback) is not int or (s.fallback != 0 and not local_source(s.fallback)) or
        type(s.style) is not int or not 1 <= s.style <= 4 or
        type(s.low) is not int or type(s.high) is not int or
        not 0 <= s.low < s.high <= MAX_TENTHS or
        type(s.pattern) is not int or not 1 <= s.pattern <= 4 or
        type(s.speed) is not int or not 1 <= s.speed <= 10 or
        type(s.brightness) is not int or not 0 <= s.brightness <= 255 or
        type(s.direction) is not int or s.direction not in (0,1) or
        any(not isinstance(c,(tuple,list)) or len(c)!=3 or
            any(type(v) is not int or not 0 <= v <= 255 for v in c)
            for c in (s.primary,s.secondary))):
        raise ValueError("Invalid reactive ARGB scene")
    return s

def default_scene(channel: int = 1) -> ReactiveScene:
    return ReactiveScene(channel, 8 + channel, 0, 1, 300, 850, 2,
                         (0,100,255), (255,0,0), 3, 64, 0)

def make_set(s: ReactiveScene) -> str:
    validate_scene(s)
    tokens = [s.channel,s.source,s.fallback,s.style,s.low,s.high,s.pattern,
              *s.primary,*s.secondary,s.speed,s.brightness,s.direction]
    line = "RFX SET " + " ".join(map(str,tokens))
    if len(line) >= 239:
        raise ValueError("Reactive command too long")
    return line

def parse_readback(line: str) -> ReactiveScene | None:
    if not line.startswith("RFX CH=") or len(line) > 300:
        return None
    try:
        fields = {}
        for token in line.split()[1:]:
            key,value = token.split("=",1)
            if key in fields:
                raise ValueError("Duplicate reactive field")
            fields[key] = value
        primary,secondary = (tuple(int(v) for v in fields[name].split(","))
                             for name in ("R1","R2"))
        boot,active,fresh = (int(fields[k]) for k in ("BOOT","ACTIVE","FRESH"))
        if any(v not in (0,1) for v in (boot,active,fresh)):
            raise ValueError("Invalid readback flags")
        scene = ReactiveScene(
            channel=int(fields["CH"]),source=int(fields["SRC"]),
            fallback=int(fields["FALL"]),style=int(fields["STYLE"]),
            low=int(fields["LOW"]),high=int(fields["HIGH"]),
            pattern=int(fields["PATTERN"]),primary=primary,secondary=secondary,
            speed=int(fields["SPEED"]),brightness=int(fields["BRIGHT"]),
            direction=int(fields["DIR"]),boot=bool(boot),active=bool(active),
            fresh=bool(fresh),value=int(fields["VALUE"]),
        )
        if not 0 <= scene.value <= MAX_TENTHS:
            raise ValueError("Invalid live reading")
        return validate_scene(scene)
    except (KeyError,TypeError,ValueError):
        return None

def validate_slot(source: str) -> str:
    if not isinstance(source,str) or len(source) > 256 or any(
        ord(c) < 32 for c in source
    ):
        raise ValueError("Invalid NWinfo sensor ID")
    if source and not source.startswith(("metric:nwinfo/","temp:nwinfo/")):
        raise ValueError("Only real NWinfo numeric or temperature sensors are supported")
    return source

def load_slots(raw: str) -> tuple[str,...]:
    if not raw:
        return ("",)*8
    try:
        data=json.loads(raw)
        slots=data["slots"]
        if (not isinstance(data,dict) or data.get("version") != 1 or
            not isinstance(slots,list) or len(slots)!=8):
            raise ValueError("Invalid reactive slot schema")
        return tuple(validate_slot(s) for s in slots)
    except (TypeError,KeyError,json.JSONDecodeError) as exc:
        raise ValueError("Invalid reactive slot configuration") from exc

def dump_slots(slots) -> str:
    slots=tuple(slots)
    if len(slots)!=8:
        raise ValueError("Exactly eight reactive slots required")
    slots=tuple(validate_slot(s) for s in slots)
    return json.dumps({"version":1,"slots":slots},ensure_ascii=False)

def value_commands(raw: str, temperatures, metrics) -> tuple[str,...]:
    """Never transmit missing or stale/nonfinite values as zero/healthy."""
    slots=load_slots(raw)
    temp={s.sensor_id:s.celsius for s in temperatures}
    data={m.sensor_id:m.value for m in metrics}
    out=[]
    for channel,key in enumerate(slots,1):
        if not key: continue  # MQTT/HA may supply this slot instead.
        value = (temp if key.startswith("temp:") else data).get(key.split(":",1)[1])
        if (type(value) not in (float,int) or not math.isfinite(value) or
            not 0 <= value <= MAX_TENTHS/10):
            continue
        raw_value=round(value*10)
        if 0 <= raw_value <= MAX_TENTHS:
            out.append(f"RVAL {channel} {raw_value}")
    return tuple(out)

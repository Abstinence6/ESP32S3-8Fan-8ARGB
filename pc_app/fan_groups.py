"""Validated fan-group metadata and fail-closed atomic mask command planner.

The ESP executes each mask through CoolingController; group names and
memberships belong to the Windows UI and never replace per-channel safety.
"""
from __future__ import annotations
from dataclasses import dataclass
import json

@dataclass(frozen=True)
class FanGroup:
    name: str
    channels: tuple[int, ...]

    @property
    def mask(self) -> int:
        return sum(1 << (ch - 1) for ch in self.channels)

def validate(groups) -> tuple[FanGroup, ...]:
    if len(groups) > 8:
        raise ValueError("Too many fan groups")
    used: set[int] = set()
    names: set[str] = set()
    result: list[FanGroup] = []
    for group in groups:
        name = group.name.strip()
        if not name or len(name) > 48 or any(ord(c) < 32 for c in name):
            raise ValueError("Invalid group name")
        ids = tuple(sorted(set(group.channels)))
        if not ids or any(type(ch) is not int or not 1 <= ch <= 8 for ch in ids):
            raise ValueError("Invalid channel")
        if len(ids) != len(group.channels) or used.intersection(ids):
            raise ValueError("Fan belongs to multiple groups")
        if name.casefold() in names:
            raise ValueError("Duplicate group name")
        names.add(name.casefold())
        used.update(ids)
        result.append(FanGroup(name, ids))
    return tuple(result)

def loads(raw: str) -> tuple[FanGroup, ...]:
    if not raw:
        return ()
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("Unsupported group data")
        groups = value["groups"]
        if not isinstance(groups, list):
            raise ValueError("Invalid group list")
        entries = []
        for item in groups:
            if not isinstance(item, dict) or type(item.get("name")) is not str or not isinstance(item.get("channels"), list):
                raise ValueError("Invalid group entry")
            channels = item["channels"]
            if any(type(ch) is not int for ch in channels):
                raise ValueError("Invalid channel entry")
            entries.append(FanGroup(item["name"], tuple(channels)))
        return validate(entries)
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid fan-group configuration") from exc

def dumps(groups) -> str:
    validated = validate(groups)
    return json.dumps({"version": 1, "groups": [
        {"name": g.name, "channels": list(g.channels)} for g in validated
    ]}, ensure_ascii=False)

def command(group: FanGroup, action: str, duty: int | None = None) -> str:
    validate([group])
    if action == "auto" and duty is None:
        return f"FANMASK AUTO {group.mask}"
    if action == "manual" and type(duty) is int and 0 <= duty <= 100:
        return f"FANMASK MANUAL {group.mask} {duty}"
    raise ValueError("Invalid group command")

def profile_commands(group: FanGroup, profile: str) -> tuple[str, ...]:
    """Explicit persistent curve commands, for a user-confirmed group action."""
    validate([group])
    try:
        from .profiles import PRESETS
        from .protocol import make_curve_command
    except ImportError:
        from profiles import PRESETS
        from protocol import make_curve_command
    if profile not in PRESETS:
        raise ValueError("Invalid fan-group profile")
    return tuple(make_curve_command(ch, list(PRESETS[profile])) for ch in group.channels)

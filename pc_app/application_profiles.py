"""Pure process-profile policy plus a Windows process-enumeration adapter.

Application rules never write cooling NVS. ESP receives a complete leased
RTCURVE transaction; it remains the final safety authority for every fan.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import re
from typing import Iterable

try:
    from .profiles import PRESETS
except ImportError:
    from profiles import PRESETS

_NAME = re.compile(r"[\w .()+-]{1,124}\.exe\Z", re.IGNORECASE)

@dataclass(frozen=True)
class AppRule:
    executable: str
    profile: str
    priority: int = 50

@dataclass(frozen=True)
class ProfileDecision:
    ready: bool
    profile: str | None
    executable: str | None

def validate_rules(rules: Iterable[AppRule]) -> tuple[AppRule, ...]:
    rules = tuple(rules)
    if len(rules) > 24:
        raise ValueError("Too many application rules")
    seen = set()
    output = []
    for rule in rules:
        name = rule.executable.strip().casefold()
        if not _NAME.fullmatch(name) or name in seen or rule.profile not in PRESETS or \
           type(rule.priority) is not int or not 0 <= rule.priority <= 100:
            raise ValueError("Invalid application profile rule")
        seen.add(name)
        output.append(AppRule(name, rule.profile, rule.priority))
    return tuple(output)

def loads(raw: str) -> tuple[AppRule, ...]:
    if not raw:
        return ()
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("Unsupported profile config")
        rows = value["rules"]
        if not isinstance(rows, list):
            raise ValueError("Invalid rule list")
        if any(not isinstance(item, dict) for item in rows):
            raise ValueError("Invalid application profile rule")
        return validate_rules(AppRule(**item) for item in rows)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid application profile config") from exc

def dumps(rules: Iterable[AppRule]) -> str:
    clean = validate_rules(rules)
    return json.dumps({"version":1,"rules":[{"executable":r.executable,
        "profile":r.profile,"priority":r.priority} for r in clean]},ensure_ascii=False)

def scan_processes() -> frozenset[str]:
    """Read names only, never command lines or arguments; no process launching."""
    import psutil
    found = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
            if isinstance(name, str):
                found.add(name.casefold())
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            continue
    return frozenset(found)

class ApplicationProfilePolicy:
    """Stable choice with dwell to avoid flapping on short-lived processes."""
    def __init__(self, dwell_seconds: float = 4.0):
        self.dwell_seconds = dwell_seconds
        self.candidate: tuple[str | None, str | None] | None = None
        self.candidate_since = 0.0

    def reset(self) -> None:
        self.candidate = None

    def consider(self, rules: Iterable[AppRule], running: Iterable[str], *, now: float) -> ProfileDecision:
        found = {item.casefold() for item in running}
        matching = [r for r in validate_rules(rules) if r.executable in found]
        selected = min(matching, key=lambda r: (-r.priority, r.executable)) if matching else None
        target = (selected.profile, selected.executable) if selected else (None, None)
        if target != self.candidate:
            self.candidate = target
            self.candidate_since = now
            return ProfileDecision(False, *target)
        return ProfileDecision(now - self.candidate_since >= self.dwell_seconds, *target)


def runtime_commands(profile: str) -> tuple[str, ...]:
    if profile not in PRESETS:
        raise ValueError("Invalid runtime profile")
    curve = " ".join(f"{t} {p}" for t, p in PRESETS[profile])
    return ("RTCURVE BEGIN", *(f"RTCURVE SET {ch} {curve}" for ch in range(1, 9)),
            "RTCURVE COMMIT")

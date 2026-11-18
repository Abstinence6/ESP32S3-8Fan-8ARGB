"""Portable, sensitive-data-free Windows companion backup.

Only allowlisted QSettings values; no WLAN passwords, MQTT credentials,
hardware guard overrides or executable paths are exported.
"""
from __future__ import annotations

import json
import re

SCHEMA = 1
_ALLOWED = re.compile(
    r"^(?:source[1-8]|source2[1-8]|groupSensors[1-8]|"
    r"groupWeights[1-8]|dualEnabled[1-8]|customCurves|"
    r"autoProfiles|smoothTemperatures|minimizeToTray|"
    r"sacnEnabled|argbStudioPreset|nwinfoProviders|"
    r"fanGroupsV1|fanHealthRefsV1|appProfileRulesV1|appProfilesEnabled)$"
)


def export_settings(settings) -> dict:
    values = {}
    for key in settings.allKeys():
        if _ALLOWED.fullmatch(key):
            value = settings.value(key)
            if isinstance(value, (int, float, str, bool)) and len(str(value)) <= 25000:
                values[key] = str(value)
    return {"schema": SCHEMA, "application": "FanARGBControl", "settings": values}


def validate_backup(data: object) -> dict[str, str]:
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA
            or data.get("application") != "FanARGBControl"):
        raise ValueError("Invalid or unsupported FanARGB backup")
    values = data.get("settings")
    if not isinstance(values, dict) or len(values) > 80:
        raise ValueError("Invalid settings collection")
    for key, value in values.items():
        if (not isinstance(key, str) or not _ALLOWED.fullmatch(key)
                or not isinstance(value, str) or len(value) > 25000):
            raise ValueError("Untrusted setting key or value")
    # New structured preferences have their own strict validators. A backup
    # never carries full process paths, credentials or arbitrary executable code.
    try:
        from .fan_groups import loads as groups_loads
        from .application_profiles import loads as app_loads
        from .tach_health import load_references
    except ImportError:
        from fan_groups import loads as groups_loads
        from application_profiles import loads as app_loads
        from tach_health import load_references
    for key, reader in (("fanGroupsV1", groups_loads),
                        ("appProfileRulesV1", app_loads),
                        ("fanHealthRefsV1", load_references)):
        if key in values:
            reader(values[key])
    return values


def restore_settings(settings, data: object) -> int:
    validated = validate_backup(data)
    for key, value in validated.items():
        settings.setValue(key, value)
    settings.sync()
    return len(validated)


def to_json(settings) -> str:
    return json.dumps(export_settings(settings), indent=2, ensure_ascii=False) + "\n"


def from_json(source: str) -> dict:
    return json.loads(source)

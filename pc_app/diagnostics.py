"""Parse read-only ESP32 fan HEALTH records; no commands changing fan duty."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import zipfile


@dataclass(frozen=True)
class FanHealth:
    channel: int
    pwm: int
    rpm: int
    tach: str
    valid: bool
    fresh: bool
    fault: bool
    dc_ready: bool
    mode: str
    source: str = "unknown"
    age_ms: int | None = None
    failsafe: str = "unknown"

    @property
    def assessment(self) -> str:
        if self.fault:
            return "Аварія"
        if not self.fresh:
            return "Немає температури · безпечні 100%"
        if self.failsafe == "overheat":
            return "Перегрів · аварійні 100%"
        if self.tach == "unseen" and self.pwm > 25:
            return "TACH не спостерігається"
        if not self.dc_ready:
            return "DC PWM заблоковано апаратним захистом"
        return "OK"


def parse_health(line: str) -> FanHealth | None:
    words = line.strip().split()
    if len(words) < 9 or words[0] != "HEALTH":
        return None
    try:
        channel = int(words[1])
        fields = dict(item.split("=", 1) for item in words[2:] if "=" in item)
        pwm = int(fields["PWM"])
        rpm = int(fields["RPM"])
        tach = fields["TACH"]
        if not (1 <= channel <= 8 and 0 <= pwm <= 100 and
                0 <= rpm <= 25000 and tach in ("na", "seen", "unseen")):
            return None
        source = fields.get("SOURCE", "unknown")
        age_text = fields.get("AGE_MS", "-")
        failsafe = fields.get("FAILSAFE", "unknown")
        if (source not in ("usb", "ds18b20", "mqtt", "none", "unknown") or
                failsafe not in ("none", "fault", "sensor", "overheat", "dc_lock", "unknown") or
                (age_text != "-" and (not age_text.isdigit() or len(age_text) > 10))):
            return None
        age_ms = None if age_text == "-" else int(age_text)
        return FanHealth(
            channel, pwm, rpm, tach, fields["TACH_VALID"] == "1",
            fields["SENSOR"] == "ok", fields["FAULT"] == "1",
            fields["DC_READY"] == "1", fields["MODE"],
            source, age_ms, failsafe,
        )
    except (KeyError, ValueError):
        return None


def export_support_bundle(path: str | Path, records: dict[int, FanHealth]) -> None:
    """Write a diagnostics-only ZIP; intentionally omit credentials and raw logs.

    This is a snapshot of the last HEALTH response, not proof the readings
    are still live. The user chooses the output path explicitly.
    """
    target = Path(path)
    if target.suffix.lower() != ".zip":
        raise ValueError("Діагностичний пакет повинен мати розширення .zip")
    if not 0 <= len(records) <= 8 or any(
        ch != record.channel or not 1 <= ch <= 8
        for ch, record in records.items()
    ):
        raise ValueError("Invalid fan diagnostic records")

    report = {
        "schema": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "latest observed HEALTH snapshot; not guaranteed live",
        "fans": [asdict(records[ch]) for ch in sorted(records)],
    }
    temporary = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr(
                "diagnostics.json",
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
            output.writestr(
                "README.txt",
                "FanARGB diagnostic snapshot. Contains no credentials, "
                "network configuration, raw command history or file paths.\n"
                "Check the timestamp before treating readings as current.\n",
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

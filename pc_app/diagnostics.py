"""Parse read-only ESP32 fan HEALTH records; no commands changing fan duty."""
from __future__ import annotations
from dataclasses import dataclass


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

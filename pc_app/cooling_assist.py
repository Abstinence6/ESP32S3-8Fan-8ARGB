"""Strict wire contract for predictive cooling and Intake/Exhaust NVS settings."""
from __future__ import annotations
from dataclasses import dataclass

ROLES = ("Без групи", "Intake", "Exhaust")
SOURCES = ("Без випередження", "CPU Power", "GPU Power", "MAX(CPU,GPU)")


@dataclass(frozen=True)
class CoolingAssistConfig:
    enabled: bool = False
    cpu_start: int = 65
    cpu_full: int = 160
    gpu_start: int = 100
    gpu_full: int = 300
    boost: int = 15
    bias: int = 5
    roles: tuple[int, ...] = (0,) * 8
    sources: tuple[int, ...] = (3,) * 8

    def validate(self) -> "CoolingAssistConfig":
        if (type(self.enabled) is not bool or
            not all(type(x) is int for x in
                    (self.cpu_start, self.cpu_full, self.gpu_start,
                     self.gpu_full, self.boost, self.bias)) or
            not 10 <= self.cpu_start < self.cpu_full <= 3000 or
            not 10 <= self.gpu_start < self.gpu_full <= 3000 or
            not 0 <= self.boost <= 25 or not 0 <= self.bias <= 15 or
            len(self.roles) != 8 or len(self.sources) != 8 or
            any(type(r) is not int or r not in (0, 1, 2) for r in self.roles) or
            any(type(s) is not int or s not in (0, 1, 2, 3) for s in self.sources)):
            raise ValueError("Недопустима конфігурація випереджального охолодження")
        return self


def make_assist_command(config: CoolingAssistConfig) -> str:
    c = config.validate()
    fields = (
        int(c.enabled), c.cpu_start, c.cpu_full, c.gpu_start,
        c.gpu_full, c.boost, c.bias,
    )
    parts = ["ASSIST", "SET", *(str(x) for x in fields)]
    for role, source in zip(c.roles, c.sources):
        parts.extend((str(role), str(source)))
    command = " ".join(parts)
    if len(command) >= 240:
        raise ValueError("Команда перевищує буфер ESP32")
    return command


def parse_assist_reply(line: str) -> CoolingAssistConfig:
    if not isinstance(line, str) or len(line) > 240 or not line.startswith("ASSIST ENABLE="):
        raise ValueError("Неочікувана відповідь ASSIST")
    fields: dict[str, str] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            raise ValueError("Некоректне поле ASSIST")
        key, value = token.split("=", 1)
        if key in fields:
            raise ValueError("Повторюване поле ASSIST")
        fields[key] = value
    try:
        items = [pair.split(":") for pair in fields["MAP"].split(",")]
        if len(items) != 8 or any(len(x) != 2 for x in items):
            raise ValueError("Неповна карта груп")
        if fields["ENABLE"] not in ("0", "1"):
            raise ValueError("Некоректний ENABLE")
        c = CoolingAssistConfig(
            enabled=fields["ENABLE"] == "1",
            cpu_start=int(fields["CPU_START"]), cpu_full=int(fields["CPU_FULL"]),
            gpu_start=int(fields["GPU_START"]), gpu_full=int(fields["GPU_FULL"]),
            boost=int(fields["BOOST"]), bias=int(fields["BIAS"]),
            roles=tuple(int(pair[0]) for pair in items),
            sources=tuple(int(pair[1]) for pair in items),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Некоректна відповідь конфігурації ASSIST") from exc
    return c.validate()


def power_payload(cpu_w: float | None, gpu_w: float | None) -> str:
    def sanitize(value: float | None) -> int:
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return 65535
        # NWinfo rejects values outside 0..3000W; this keeps its trust contract.
        from math import isfinite
        return round(value) if isfinite(value) and 0 <= value <= 3000 else 65535
    return f"PWRDATA {sanitize(cpu_w)} {sanitize(gpu_w)}"

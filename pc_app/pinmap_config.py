"""Safety validation for the ESP32-S3 PWM/TACH/ARGB GPIO mapping."""
from __future__ import annotations

TYPES = ("PWM", "TACH", "ARGB")
DEFAULTS = {
    "PWM": (21, 35, 39, 42, 6, 16, 10, 14),
    "TACH": (47, 36, 40, 2, 5, 15, 9, 13),
    "ARGB": (48, 37, 41, 1, 4, 7, 46, 12),
}
# Standard native-USB N16R8 image uses these pins for FAN2/ARGB2 instead of
# GPIO35/36/37, which are permanently occupied by Octal PSRAM.
N16R8_DEFAULTS = {
    kind: tuple(8 if kind == "PWM" and i == 1 else
                11 if kind == "TACH" and i == 1 else
                17 if kind == "ARGB" and i == 1 else pin
                for i, pin in enumerate(values))
    for kind, values in DEFAULTS.items()
}


def allowed_for_slot(pin: int, kind: str, channel: int) -> bool:
    if kind not in TYPES or not 1 <= channel <= 8 or type(pin) is not int:
        return False
    if (not 0 <= pin <= 48 or pin in (0, 3, 19, 20, 43, 44, 45) or
            22 <= pin <= 32):
        return False
    if 33 <= pin <= 37 or pin == 46:
        return pin == DEFAULTS[kind][channel - 1]
    return True


def validate_map(pins: dict[str, tuple[int, ...] | list[int]]) -> None:
    if set(pins) != set(TYPES):
        raise ValueError("Потрібна карта PWM, TACH, ARGB")
    used: set[int] = set()
    for kind in TYPES:
        values = pins[kind]
        if len(values) != 8:
            raise ValueError(f"{kind}: потрібно 8 GPIO")
        for channel, pin in enumerate(values, 1):
            if not allowed_for_slot(pin, kind, channel):
                raise ValueError(f"{kind} {channel}: GPIO{pin} недоступний або зарезервований")
            if pin in used:
                raise ValueError(f"GPIO{pin} призначений кільком виходам")
            used.add(pin)


def default_map(*, n16r8: bool = False) -> dict[str, list[int]]:
    defaults = N16R8_DEFAULTS if n16r8 else DEFAULTS
    return {key: list(values) for key, values in defaults.items()}

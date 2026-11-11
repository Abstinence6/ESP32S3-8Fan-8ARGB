"""Named safe monotonic cooling presets; flashing happens only on user approval."""
from __future__ import annotations

from typing import Sequence

PRESETS: dict[str, list[tuple[int, int]]] = {
    "Silent": [(25, 30), (35, 35), (45, 45), (60, 75), (75, 100)],
    "Balanced": [(25, 35), (35, 45), (50, 65), (65, 85), (80, 100)],
    "Performance": [(25, 45), (35, 55), (45, 75), (55, 95), (70, 100)],
}


def validate_profiles(curves: Sequence[list[tuple[int, int]]]) -> bool:
    from .protocol import validate_curve
    return len(curves) == 8 and all(validate_curve(c) for c in curves)

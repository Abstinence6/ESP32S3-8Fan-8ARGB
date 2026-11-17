"""Verified ESP32-backed 4..8-point temperature palettes (in °C)."""
from __future__ import annotations
import math

DEFAULT_PALETTE: tuple[tuple[int, int, int, int], ...] = (
    (30, 0, 100, 255),
    (49, 0, 220, 65),
    (69, 255, 190, 0),
    (85, 255, 0, 0),
)
Palette = tuple[tuple[int, int, int, int], ...]


def validate_palette(points: Palette) -> Palette:
    if not isinstance(points, tuple) or not 4 <= len(points) <= 8:
        raise ValueError("Палітра потребує 4–8 точок")
    previous = -1
    for point in points:
        if not isinstance(point, tuple) or len(point) != 4 or any(type(v) is not int for v in point):
            raise ValueError("Точки палітри мають містити чотири цілі числа")
        temp, r, g, b = point
        if not previous < temp <= 125 or temp < 0 or any(not 0 <= x <= 255 for x in (r, g, b)):
            raise ValueError("Температурні точки мають зростати, RGB має бути 0–255")
        previous = temp
    return points


def make_palette_command(channel: int, points: Palette) -> str:
    if type(channel) is not int or not 1 <= channel <= 8:
        raise ValueError("Невірна зона ARGB")
    validate_palette(points)
    text = "TPAL SET " + str(channel) + " " + str(len(points))
    for p in points:
        text += " " + " ".join(map(str, p))
    if len(text) >= 240:
        raise ValueError("Команда палітри надто довга")
    return text


def parse_palette_reply(line: str) -> tuple[int, Palette]:
    if not isinstance(line, str) or len(line) > 240 or not line.startswith("TPAL CH="):
        raise ValueError("Неочікувана відповідь TPAL")
    fields = {}
    for token in line.split():
        if "=" in token:
            key, value = token.split("=", 1)
            if key in fields:
                raise ValueError("Дубльоване поле TPAL")
            fields[key] = value
    try:
        ch = int(fields["CH"])
        count = int(fields["COUNT"])
        points: Palette = tuple(
            tuple(map(int, part.split(","))) for part in fields["DATA"].split(";")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Пошкоджена відповідь TPAL") from exc
    if not 1 <= ch <= 8 or count != len(points):
        raise ValueError("Зона або кількість точок не збігаються")
    return ch, validate_palette(points)


def color_at(celsius: float, points: Palette) -> tuple[int, int, int]:
    validate_palette(points)
    if isinstance(celsius, bool) or not isinstance(celsius, (int, float)) or not math.isfinite(celsius):
        raise ValueError("Відсутня актуальна температура")
    if celsius <= points[0][0]:
        return points[0][1:]
    for (t0, r0, g0, b0), (t1, r1, g1, b1) in zip(points, points[1:]):
        if celsius <= t1:
            fraction = (celsius - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * fraction) for a, b in
                         zip((r0, g0, b0), (r1, g1, b1)))
    return points[-1][1:]

"""Read real Windows CPU/GPU/SSD temperatures with bundled NWinfo.

No LibreHardwareMonitor application, web server, WMI thermal-zone guessing,
or external monitoring service is needed. NWinfo's built-in CPU/GPU/SMART
providers are explicitly selected; driver permission may be required for CPU.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote
from typing import Any

try:
    from .monitor import TemperatureSensor
except ImportError:
    from monitor import TemperatureSensor


# Only live values. Do not mistake threshold/alarms/max recorded values for
# current temperatures. NWinfo CPU => Package/Core Temperature; GPU/SMART =>
# Temperature. The source code is https://github.com/a1ive/nwinfo.
LIVE_TEMPERATURE_KEYS = frozenset({
    "temperature", "package temperature", "core temperature",
    "gpu temperature", "hotspot temperature", "memory junction temperature",
    "ccd temperature", "tctl temperature",
})
_PROVIDERS = ("CPU", "GPU", "SMART")
_NUMBER = re.compile(r"^[+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:\s*°?\s*[cC])?$")


def _temperature(value: object) -> float | None:
    if type(value) in (float, int):
        number = float(value)
    elif isinstance(value, str) and _NUMBER.fullmatch(value.strip()):
        text = value.strip().replace(",", ".")
        number = float(re.sub(r"\s*°?\s*[cC]$", "", text))
    else:
        return None
    # A zero/negative reading usually means the GPU SDK returned unavailable.
    # Do not drive a fan curve from invalid temperatures.
    if not math.isfinite(number) or not 5.0 <= number <= 125.0:
        return None
    return number


def _find_sensor_section(tree: Any) -> dict:
    if isinstance(tree, dict):
        for key, value in tree.items():
            if str(key).lower() == "sensors" and isinstance(value, dict):
                return value
        for value in tree.values():
            result = _find_sensor_section(value)
            if result:
                return result
    elif isinstance(tree, list):
        for child in tree:
            result = _find_sensor_section(child)
            if result:
                return result
    return {}


def parse_nwinfo_temperatures(tree: Any) -> list[TemperatureSensor]:
    """Parse NWinfo --format=JSON / --sensors=CPU,GPU,SMART output.

    Only named live thermal attributes within the selected providers count.
    Unknown schemas/metadata do not silently become synthetic temperatures.
    """
    sensor_tree = _find_sensor_section(tree)
    found: dict[str, TemperatureSensor] = {}

    def visit(provider: str, node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(provider, child, (*path, str(index)))
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            label = str(key)
            if label.strip().lower() in LIVE_TEMPERATURE_KEYS:
                celsius = _temperature(value)
                if celsius is not None:
                    pieces = (*path, label)
                    ident = "/".join(quote(str(p).casefold(), safe="") for p in pieces)
                    sensor_id = f"nwinfo/{provider.lower()}/{ident}"
                    description = " / ".join((provider, *pieces))
                    found[sensor_id] = TemperatureSensor(sensor_id, description, celsius)
            elif isinstance(value, (dict, list)):
                visit(provider, value, (*path, label))

    if isinstance(sensor_tree, dict):
        for provider in _PROVIDERS:
            data = next((v for k, v in sensor_tree.items() if str(k).upper() == provider), None)
            if data is not None:
                visit(provider, data, ())
    return sorted(found.values(), key=lambda s: s.name.casefold())


def locate_nwinfo() -> Path:
    """Find the verified, bundled CLI next to the PyInstaller runtime files."""
    override = os.environ.get("FANARGB_NWINFO_EXE")
    if override:
        path = Path(override)
        if path.is_file() and path.name.lower() == "nwinfo.exe":
            return path
        raise FileNotFoundError("FANARGB_NWINFO_EXE має вказувати на файл nwinfo.exe")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    candidates = [
        root / "nwinfo" / "nwinfo.exe",
        root / "nwinfo" / "NWinfo" / "nwinfo.exe",
        root / "nwinfo.exe",
        Path(__file__).resolve().parent / "nwinfo.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = sorted((root / "nwinfo").rglob("nwinfo.exe")) if (root / "nwinfo").is_dir() else []
    if matches:
        return matches[0]
    raise FileNotFoundError(
        "Вбудований NWinfo не знайдено. Використай повну Windows-збірку FanARGBControl."
    )


def fetch_temperatures(timeout: float = 4.0) -> list[TemperatureSensor]:
    """Run local built-in hardware providers in a separate process.

    Does not use the NWinfo LHM/HWINFO/GPU-Z providers. Running subprocess in
    the existing executor means a driver/SDK delay never blocks the Qt GUI.
    """
    executable = locate_nwinfo()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                str(executable), "--format=JSON", "--cp=UTF8",
                "--temp-unit=C", "--hide-sensitive",
                "--sensors=CPU,GPU,SMART",
            ],
            cwd=str(executable.parent), capture_output=True,
            timeout=timeout, check=True, creationflags=flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("NWinfo перевищив час очікування. Перевір доступ до датчиків.") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"NWinfo завершився з кодом {exc.returncode}: {details[:180]}") from exc
    try:
        data = json.loads(completed.stdout.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("NWinfo повернув некоректну JSON-відповідь") from exc
    if not _find_sensor_section(data):
        raise RuntimeError("NWinfo не надав групу Sensors (драйвер/права/сумісність)")
    return parse_nwinfo_temperatures(data)

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
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import quote
from typing import Any

try:
    from .monitor import TemperatureSensor
except ImportError:
    from monitor import TemperatureSensor


# Temperatures that can actually drive a fan: never read alarms, historical
# maxima, offsets or thermal limits such as Tj Max / Tcc / T-Control.
# Field names are grounded in NWinfo's built-in CPU/GPU/SMART/DIMM/INTEL/ZEN
# providers (libnw/sensor/*.c).
LIVE_TEMPERATURE_KEYS = frozenset({
    "temperature", "package temperature", "core temperature",
    "gpu temperature", "hotspot temperature", "memory junction temperature",
    "ccd temperature", "tctl temperature", "tctl", "tdie",
    "gfx temperature", "l3 temperature", "pch temperature",
    "pp0 temperature", "pp1 temperature", "edram temperature",
    "gt temperature", "package dppm temperature", "soc temperature",
    "vrm temperature", "chipset temperature", "motherboard temperature",
})
_TEMPERATURE_INDEXED = re.compile(
    r"^(?:tccd\d+|ccd\s*\d+\s*(?:temp|temperature)|"
    r"core\s+temperature\s+\d+|core\s+\d+\s+temperature)$",
    re.IGNORECASE,
)
_PROVIDERS = ("CPU", "GPU", "SMART", "DIMM", "INTEL", "ZEN", "DISK")

@dataclass(frozen=True)
class HardwareMetric:
    sensor_id: str
    name: str
    value: float
    unit: str
    kind: str


class SensorBatch(list):
    """Backward compatible list of temperatures with additional live metrics."""
    def __init__(self, readings=(), metrics=()):
        super().__init__(readings)
        self.metrics: list[HardwareMetric] = list(metrics)


def _metric_type(name: str) -> tuple[str, str] | None:
    name = name.lower().strip()
    if name in {"utilization", "load", "memory usage", "life", "signal quality"}:
        return ("%", "load")
    if name == "fan speed":
        return ("RPM", "fan")
    if name in {"read iops", "write iops"}:
        return ("IOPS", "disk")
    if name in {"read latency ms", "write latency ms"}:
        return ("ms", "disk")
    if name in {"frequency", "memory frequency", "bus clock",
                "bclk mhz", "uclk mhz", "qclk mhz", "uncore frequency mhz",
                "gfx clock", "fabric clock", "uncore clock", "memory clock", "l3 clock"
               } or re.fullmatch(r"core clock \d+", name):
        return ("MHz", "frequency")
    if (name in {"power", "package power", "socket power", "dram power",
                 "pp0 power", "pp1 power"}
            or re.fullmatch(r"core power \d+", name)):
        return ("W", "power")
    if (name in {"voltage", "core voltage", "soc voltage", "sa voltage",
                 "gfx voltage", "svi core vcc", "svi soc vcc"}
            or re.fullmatch(r"core voltage \d+", name)):
        return ("V", "voltage")
    return None


def _metric_number(value: object, unit: str) -> float | None:
    if type(value) in (float, int):
        val = float(value)
    elif isinstance(value, str) and re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)", value.strip()):
        val = float(value.strip().replace(",", "."))
    else:
        return None
    upper = {"%": 100, "RPM": 30000, "MHz": 20000,
             "W": 3000, "V": 25, "IOPS": 100000000, "ms": 60000}[unit]
    return val if math.isfinite(val) and 0 <= val <= upper else None


def parse_nwinfo_metrics(tree: Any) -> list[HardwareMetric]:
    """Whitelist real live numerical metrics; never expose them as fan sources."""
    sensor_tree = _find_sensor_section(tree)
    found: dict[str, HardwareMetric] = {}

    def visit(provider: str, node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, list):
            for i, child in enumerate(node):
                visit(provider, child, (*path, str(i)))
        elif isinstance(node, dict):
            for key, value in node.items():
                label = str(key)
                kind = _metric_type(label)
                if kind is not None and not isinstance(value, (dict, list)):
                    unit, category = kind
                    number = _metric_number(value, unit)
                    if number is not None:
                        pieces = (*path, label)
                        ident = "/".join(quote(str(p).casefold(), safe="") for p in pieces)
                        metric_id = f"nwinfo/{provider.lower()}/{ident}"
                        found[metric_id] = HardwareMetric(
                            metric_id, " / ".join((provider, *pieces)), number, unit, category
                        )
                elif isinstance(value, (dict, list)):
                    visit(provider, value, (*path, label))

    for provider in _PROVIDERS:
        data = next((v for k, v in sensor_tree.items() if str(k).upper() == provider), None)
        if data is not None:
            visit(provider, data, ())
    return sorted(found.values(), key=lambda m: (m.kind, m.name.casefold()))
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
    """Parse NWinfo built-in providers without treating limits as temperatures.

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
            if (label.strip().lower() in LIVE_TEMPERATURE_KEYS
                    or _TEMPERATURE_INDEXED.fullmatch(label.strip())):
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
    source = Path(__file__).resolve().parent
    folders = [
        root / "nwinfo", root / "dist" / "nwinfo",
        source / "nwinfo", source / "dist" / "nwinfo",
    ]
    for folder in folders:
        if not folder.is_dir():
            continue
        matches = sorted(
            (p for p in folder.rglob("*") if p.is_file() and p.name.lower() == "nwinfo.exe"),
            key=lambda p: (len(p.parts), str(p).casefold()),
        )
        if matches:
            return matches[0]
    for path in (root / "nwinfo.exe", source / "nwinfo.exe"):
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Вбудований NWinfo не знайдено. Використай повну Windows-збірку FanARGBControl."
    )


def fetch_temperatures(
    timeout: float = 4.0,
    providers: tuple[str, ...] = ("CPU", "GPU", "SMART"),
) -> list[TemperatureSensor]:
    """Run local built-in hardware providers in a separate process.

    Does not use the NWinfo LHM/HWINFO/GPU-Z providers. Running subprocess in
    the existing executor means a driver/SDK delay never blocks the Qt GUI.
    """
    if not providers or any(provider not in _PROVIDERS for provider in providers):
        raise ValueError("NWinfo: невідоме джерело датчиків")
    executable = locate_nwinfo()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    commands = [
        str(executable), "--format=JSON", "--cp=UTF8",
        "--temp-unit=C", "--hide-sensitive",
    ]
    # AMD/NVIDIA/Intel GPU sensors use vendor drivers and do not need
    # NWinfo's low-level MSR driver. Avoid its slow boot/security path.
    if providers in (("GPU",), ("DISK",)):
        commands.append("--driver=NONE")
    commands.append("--sensors=" + ",".join(providers))
    try:
        completed = subprocess.run(
            commands,
            cwd=str(executable.parent), capture_output=True,
            timeout=timeout, check=True, creationflags=flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"NWinfo [{','.join(providers)}] перевищив час очікування ({timeout:g} с)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"NWinfo [{','.join(providers)}] завершився з кодом {exc.returncode}: {details[:180]}"
        ) from exc
    try:
        data = json.loads(completed.stdout.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("NWinfo повернув некоректну JSON-відповідь") from exc
    if not _find_sensor_section(data):
        raise RuntimeError("NWinfo не надав групу Sensors (драйвер/права/сумісність)")
    return SensorBatch(parse_nwinfo_temperatures(data), parse_nwinfo_metrics(data))


class NwinfoSensorSampler:
    """Asynchronous, independent CPU/GPU/SMART probes.

    One hung SMART/CPU call never blocks GPU updates or the Qt/event loop.
    Only recently confirmed temperatures are exposed; stale readings expire
    *before* the ESP's 10-second temperature watchdog.
    """

    # A CPU ring-0 driver may take well over four seconds on first use.
    # All timeouts are per provider; a hung CPU never blocks a fast GPU.
    _timeout = {"GPU": 8.0, "CPU": 15.0, "SMART": 5.0,
                "DIMM": 6.0, "INTEL": 12.0, "ZEN": 12.0, "DISK": 5.0}
    _frequency = {"GPU": 2.0, "CPU": 2.0, "SMART": 3.0,
                  "DIMM": 5.0, "INTEL": 5.0, "ZEN": 5.0, "DISK": 5.0}
    _max_age = 7.0
    _retry_delay = 8.0

    def __init__(self, executor=None):
        self._owns_executor = executor is None
        self._executor = executor if executor is not None else ThreadPoolExecutor(
            max_workers=len(_PROVIDERS), thread_name_prefix="NWinfoProvider"
        )
        self._inflight: dict[str, Future] = {}
        self._next_scan: dict[str, float] = {}
        self._latest: dict[str, tuple[float, list[TemperatureSensor]]] = {}
        self._metric_latest: dict[str, tuple[float, list[HardwareMetric]]] = {}
        self._initialized = False
        self._ever_valid = False
        self._closed = False
        self.problems: dict[str, str] = {}

    def poll(self, now: float | None = None) -> list[TemperatureSensor] | None:
        """Return fresh values, [] when unavailable, or None while first probing.

        Call every ~2 seconds from the GUI/agent's existing worker. This does
        *not* wait for a Windows sensor subprocess to exit.
        """
        if self._closed:
            return []
        now = time.monotonic() if now is None else now
        self._last_poll_at = now
        if not self._initialized:
            self._next_scan = {
                "GPU": now, "CPU": now, "DIMM": now + 2.0,
                "INTEL": now + 3.0, "ZEN": now + 4.0,
                "SMART": now + 5.0, "DISK": now + 6.0,
            }
            self._initialized = True

        for provider, future in tuple(self._inflight.items()):
            if not future.done():
                continue
            del self._inflight[provider]
            try:
                readings = future.result()
                metrics = getattr(readings, "metrics", [])
                if readings or metrics:
                    self._latest[provider] = (now, readings)
                    self._metric_latest[provider] = (now, metrics)
                    if readings:
                        self._ever_valid = True
                    self.problems.pop(provider, None)
                    self._next_scan[provider] = now + self._frequency[provider]
                else:
                    # Some platforms do not have Zen, Intel, DIMM thermistors
                    # or supported disk counters; absence is not an error.
                    if provider in ("DIMM", "INTEL", "ZEN", "DISK"):
                        self.problems.pop(provider, None)
                    else:
                        self.problems[provider] = "показань немає"
                    self._latest.pop(provider, None)
                    self._metric_latest.pop(provider, None)
                    self._next_scan[provider] = now + self._retry_delay
            except Exception as exc:
                self.problems[provider] = str(exc)
                self._next_scan[provider] = now + self._retry_delay

        for provider in ("GPU", "CPU", "SMART", "DIMM", "INTEL", "ZEN", "DISK"):
            if provider not in self._inflight and now >= self._next_scan[provider]:
                self._inflight[provider] = self._executor.submit(
                    fetch_temperatures,
                    self._timeout[provider],
                    (provider,),
                )

        fresh = [
            sensor
            for stamp, values in self._latest.values()
            if 0 <= now - stamp < self._max_age
            for sensor in values
        ]
        if fresh:
            return sorted(fresh, key=lambda s: s.name.casefold())
        # Only initial discovery is pending; do not mistake it for failure.
        if not self._ever_valid and self._inflight and not self.metrics:
            return None
        # After a former valid sample expires, return [] so neither GUI nor
        # background agent can continue using or forwarding stale temperatures.
        return []

    @property
    def metrics(self) -> list[HardwareMetric]:
        if not self._initialized:
            return []
        now = getattr(self, "_last_poll_at", time.monotonic())
        return sorted(
            (metric for stamp, values in self._metric_latest.values()
             if 0 <= now - stamp < self._max_age for metric in values),
            key=lambda item: (item.kind, item.name.casefold()),
        )

    def close(self) -> None:
        self._closed = True
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

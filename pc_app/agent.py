"""Headless user-session companion for live PC temperatures and OpenRGB E1.31.

Run: FanARGBControl.exe --headless
This is a logon-session process, NOT a Windows service; it owns the ESP COM port.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import time
from concurrent.futures import ThreadPoolExecutor, Future

try:
    from .monitor import MAX_ALL, DEFAULT_LHM_URL, fetch_temperatures, resolve_temperature
    from .protocol import make_temperature_command
except ImportError:  # packaged as a standalone PyInstaller entrypoint
    from monitor import MAX_ALL, DEFAULT_LHM_URL, fetch_temperatures, resolve_temperature
    from protocol import make_temperature_command


def load_assignments(settings: QSettings) -> list[tuple[str, list[str], dict[str, float], str, bool]]:
    items = []
    for ch in range(1, 9):
        try:
            group = json.loads(str(settings.value(f"groupSensors{ch}", "[]")))
            weights = json.loads(str(settings.value(f"groupWeights{ch}", "{}")))
            group = group if isinstance(group, list) else []
            weights = weights if isinstance(weights, dict) else {}
        except (ValueError, TypeError):
            group, weights = [], {}
        dual = str(settings.value(f"dualEnabled{ch}", "false")).lower() in ("true", "1")
        items.append((str(settings.value(f"source{ch}", MAX_ALL)), group, weights,
                      str(settings.value(f"source2{ch}", MAX_ALL)), dual))
    return items


def make_sensor_commands(settings: QSettings, sensors) -> list[str]:
    lines: list[str] = []
    for ch, (assignment, group, weights, second, dual) in enumerate(load_assignments(settings), start=1):
        primary = resolve_temperature(assignment, sensors, group, weights)
        if primary is not None:
            lines.append(make_temperature_command(ch, primary))
        if dual:
            aux = resolve_temperature(second, sensors, group, weights)
            if aux is not None:
                lines.append(make_temperature_command(ch, aux).replace("TEMP ", "TEMP2 ", 1))
    return lines


def setup_logging() -> logging.Logger:
    folder = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "FanARGBControl")
    os.makedirs(folder, exist_ok=True)
    logger = logging.getLogger("fanargb-agent")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(RotatingFileHandler(os.path.join(folder, "agent.log"),
                                             maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    return logger


def run_agent() -> int:
    import serial
    from PySide6.QtCore import QSettings
    try:
        from .sacn_bridge import E131Listener, SERIAL_BAUD, encode_rgb_frame
    except ImportError:
        from sacn_bridge import E131Listener, SERIAL_BAUD, encode_rgb_frame
    settings = QSettings("FanARGB", "FanARGBControl")
    log = setup_logging()
    output: serial.Serial | None = None
    led_counts: list[int] | None = None
    buffer = ""
    listener = E131Listener()
    try:
        listener.start() # localhost only, port 5568
    except OSError as exc:
        log.error("Cannot bind OpenRGB E1.31 port: %s", exc)
        return 2
    temp_future: Future | None = None
    temp_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="LHMAgent")
    next_connect = 0.0
    next_temps = 0.0
    last_rgb = 0.0
    last_frames: dict[int, bytes] = {}
    try:
        while True:
            now = time.monotonic()
            if output is None and now >= next_connect:
                next_connect = now + 5.0
                port_name = str(settings.value("port", ""))
                if port_name:
                    try:
                        output = serial.Serial(port_name, SERIAL_BAUD, timeout=0, write_timeout=0.25)
                        led_counts = None
                        buffer = ""
                        log.info("Connected to %s", port_name)
                        # Device can reboot on DTR. Query after a safe warm-up delay.
                        time.sleep(2.2)
                        output.write(b"PING\nLEDS\nSTATUS\n")
                    except (serial.SerialException, OSError) as exc:
                        output = None
                        log.warning("Unable to connect %s: %s", port_name, exc)
            if output is not None:
                try:
                    rx = output.read(output.in_waiting or 0)
                    if rx:
                        buffer += rx.decode("ascii", errors="replace")
                        if len(buffer) > 8192: buffer = ""
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            fields = line.strip().split()
                            if len(fields) == 9 and fields[0] == "LEDCOUNTS":
                                vals = [int(v) for v in fields[1:]]
                                if all(1 <= n <= 170 for n in vals): led_counts = vals
                    if now >= next_temps and temp_future is None:
                        next_temps = now + 2.0
                        url = str(settings.value("lhmUrl", DEFAULT_LHM_URL))
                        temp_future = temp_executor.submit(fetch_temperatures, url, 0.8)
                    if temp_future is not None and temp_future.done():
                        try:
                            for msg in make_sensor_commands(settings, temp_future.result()):
                                output.write((msg + "\n").encode("ascii"))
                        except Exception as exc:
                            log.warning("Sensor read failed; ESP thermal watchdog stays active: %s", exc)
                        temp_future = None
                    last_frames.update(listener.read_latest())
                    if led_counts is not None and now - last_rgb >= 0.04 and last_frames:
                        last_rgb = now
                        sending, last_frames = last_frames, {}
                        for ch, rgb in sorted(sending.items()):
                            rgb = rgb[:led_counts[ch-1] * 3]
                            if len(rgb) < 3: continue
                            packet = encode_rgb_frame(ch, rgb)
                            if output.write(packet) != len(packet):
                                raise serial.SerialTimeoutException("short USB RGB write")
                except (serial.SerialException, OSError, ValueError) as exc:
                    log.warning("Serial disconnected: %s", exc)
                    try: output.close()
                    except (OSError, serial.SerialException): pass
                    output = None
                    led_counts = None
                    last_frames.clear()
                    next_connect = now + 5.0
            else:
                # Drop unattended frames while no COM port is available.
                listener.read_latest()
            time.sleep(0.02)
    except KeyboardInterrupt:
        return 0
    finally:
        listener.stop()
        temp_executor.shutdown(wait=False, cancel_futures=True)
        if output is not None:
            output.close()

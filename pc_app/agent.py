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
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

try:
    from .monitor import MAX_ALL, resolve_temperature
    from .nwinfo_sensors import NwinfoSensorSampler
    from .protocol import make_temperature_command
    from .smart_control import SafeTemperatureFilter, AutoProfileSelector
    from .profiles import PRESETS
    from .protocol import make_curve_command
    from .serial_owner import SerialOwnerServer
    from .serial_tx import SerialTransmitter
except ImportError:  # packaged as a standalone PyInstaller entrypoint
    from monitor import MAX_ALL, resolve_temperature
    from nwinfo_sensors import NwinfoSensorSampler
    from protocol import make_temperature_command
    from smart_control import SafeTemperatureFilter, AutoProfileSelector
    from profiles import PRESETS
    from protocol import make_curve_command
    from serial_owner import SerialOwnerServer
    from serial_tx import SerialTransmitter


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


def make_sensor_commands(settings: QSettings, sensors,
                         filter_engine: SafeTemperatureFilter | None = None,
                         now: float | None = None) -> list[str]:
    lines: list[str] = []
    if now is None:
        now = time.monotonic()
    smoothing = str(settings.value("smoothTemperatures", "true")).lower() in ("true", "1")
    for ch, (assignment, group, weights, second, dual) in enumerate(load_assignments(settings), start=1):
        primary = resolve_temperature(assignment, sensors, group, weights)
        if filter_engine is not None and smoothing:
            primary = filter_engine.update(ch, primary, now)
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
    tx: SerialTransmitter | None = None
    port_name = str(settings.value("port", ""))
    try:
        owner = SerialOwnerServer(port_name)
    except OSError as exc:
        log.error("Another background agent is already running: %s", exc)
        return 3
    led_counts: list[int] | None = None
    buffer = ""
    listener = E131Listener()
    try:
        listener.start() # localhost only, port 5568
    except OSError as exc:
        log.error("Cannot bind OpenRGB E1.31 port: %s", exc)
        return 2
    temp_future: Future | None = None
    temp_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="SensorAgent")
    sensor_sampler = NwinfoSensorSampler()
    stored_providers = str(settings.value("nwinfoProviders", ""))
    if stored_providers:
        sensor_sampler.set_enabled(set(stored_providers.split(",")))
    smooth_filter = SafeTemperatureFilter()
    auto_profiles = AutoProfileSelector()
    next_connect = 0.0
    query_due = 0.0
    client_was_connected = False
    next_temps = 0.0
    last_rgb = 0.0
    last_frames: dict[int, bytes] = {}
    try:
        while True:
            now = time.monotonic()
            if output is None and now >= next_connect:
                next_connect = now + 5.0
                if port_name:
                    try:
                        output = serial.Serial(port_name, SERIAL_BAUD, timeout=0, write_timeout=0.25)
                        tx = SerialTransmitter(output)
                        led_counts = None
                        buffer = ""
                        log.info("Connected to %s", port_name)
                        # DTR may reset ESP. Do not block the agent/GUI for 2.2 s.
                        query_due = now + 2.2
                    except (serial.SerialException, OSError) as exc:
                        output = None
                        log.warning("Unable to connect %s: %s", port_name, exc)
            owner.poll(tx if tx is not None else output)
            if owner.has_client != client_was_connected:
                last_frames.clear() # never replay stale RGB across GUI handoff
                if tx is not None:
                    tx.clear()
                client_was_connected = owner.has_client
            if output is not None:
                try:
                    if query_due and now >= query_due:
                        tx.write(b"PING\nLEDS\nSTATUS\n")
                        query_due = 0.0
                    rx = output.read(output.in_waiting or 0)
                    if rx:
                        owner.forward(rx)
                    if rx:
                        buffer += rx.decode("ascii", errors="replace")
                        if len(buffer) > 8192: buffer = ""
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            fields = line.strip().split()
                            if len(fields) == 9 and fields[0] == "LEDCOUNTS":
                                vals = [int(v) for v in fields[1:]]
                                if all(1 <= n <= 170 for n in vals): led_counts = vals
                    if not owner.has_client and now >= next_temps and temp_future is None:
                        next_temps = now + 2.0
                        temp_future = temp_executor.submit(sensor_sampler.poll)
                    if temp_future is not None and temp_future.done():
                        try:
                            sample = temp_future.result()
                            if not owner.has_client and sample is not None:
                                for msg in make_sensor_commands(settings, sample, smooth_filter):
                                    tx.send_command(msg)
                                settings.sync()
                                if str(settings.value("autoProfiles", "false")).lower() in ("true", "1"):
                                    gpu_load = [
                                        m.value for m in sensor_sampler.metrics
                                        if m.kind == "load" and "gpu" in m.name.casefold()
                                        and ("utilization" in m.name.casefold()
                                             or "load" in m.name.casefold())
                                    ]
                                    desired = auto_profiles.consider(
                                        max(gpu_load) if gpu_load else None,
                                        datetime.now().hour, time.monotonic()
                                    )
                                    if desired:
                                        for ch in range(1, 9):
                                            tx.send_command(make_curve_command(ch, list(PRESETS[desired])))
                                        auto_profiles.applied(desired, time.monotonic())
                                        log.info("Automatic profile applied: %s", desired)
                        except Exception as exc:
                            log.warning("Sensor read failed; ESP thermal watchdog stays active: %s", exc)
                        temp_future = None
                    last_frames.update(listener.read_latest())
                    if not owner.has_client and led_counts is not None and now - last_rgb >= 0.04 and last_frames:
                        last_rgb = now
                        sending, last_frames = last_frames, {}
                        for ch, rgb in sorted(sending.items()):
                            rgb = rgb[:led_counts[ch-1] * 3]
                            if len(rgb) < 3: continue
                            packet = encode_rgb_frame(ch, rgb)
                            tx.queue_rgb(ch, packet)
                    if tx is not None:
                        tx.flush_rgb(now)
                except (serial.SerialException, OSError, ValueError) as exc:
                    log.warning("Serial disconnected: %s", exc)
                    try: output.close()
                    except (OSError, serial.SerialException): pass
                    output = None
                    if tx is not None:
                        tx.clear()
                    tx = None
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
        owner.close()
        listener.stop()
        temp_executor.shutdown(wait=False, cancel_futures=True)
        sensor_sampler.close()
        if output is not None:
            output.close()

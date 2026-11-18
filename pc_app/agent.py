"""Headless user-session companion for live PC temperatures and OpenRGB E1.31.

Run: FanARGBControl.exe --headless
This is a logon-session process, NOT a Windows service; it owns the ESP COM port.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

try:
    from .nwinfo_sensors import NwinfoSensorSampler
    from .sensor_pipeline import (
        routes_from_settings, plan_sensor_telemetry,
        choose_automatic_profile, automatic_profile_commands,
    )
    from .smart_control import SafeTemperatureFilter, AutoProfileSelector
    from .serial_owner import SerialOwnerServer
    from .serial_tx import SerialTransmitter
    from .rgb_stream import AdaptiveRgbStream
    from .telemetry_store import TelemetryStore
    from .tach_health import TachHealthMonitor
    from .reactive_argb import MAPPING_KEY, value_commands
    from .application_profiles import (
        ApplicationProfilePolicy, loads as load_application_rules,
        runtime_commands, scan_processes,
    )
    from .protocol import parse_status
except ImportError:  # packaged as a standalone PyInstaller entrypoint
    from nwinfo_sensors import NwinfoSensorSampler
    from sensor_pipeline import (
        routes_from_settings, plan_sensor_telemetry,
        choose_automatic_profile, automatic_profile_commands,
    )
    from smart_control import SafeTemperatureFilter, AutoProfileSelector
    from serial_owner import SerialOwnerServer
    from serial_tx import SerialTransmitter
    from rgb_stream import AdaptiveRgbStream
    from telemetry_store import TelemetryStore
    from tach_health import TachHealthMonitor
    from reactive_argb import MAPPING_KEY, value_commands
    from application_profiles import (
        ApplicationProfilePolicy, loads as load_application_rules,
        runtime_commands, scan_processes,
    )
    from protocol import parse_status


def make_sensor_commands(settings: QSettings, sensors,
                         filter_engine: SafeTemperatureFilter | None = None,
                         now: float | None = None, *, metrics=None) -> list[str]:
    """Compatibility entrypoint: GUI and agent now use the same planner."""
    smoothing = str(settings.value("smoothTemperatures", "true")).lower() in ("true", "1")
    plan = plan_sensor_telemetry(
        routes_from_settings(settings), sensors, () if metrics is None else metrics,
        filter_engine=filter_engine, smoothing=smoothing, now=now,
        include_power=metrics is not None,
    )
    return list(plan.commands)


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
        from .sacn_bridge import E131Listener, SERIAL_BAUD
    except ImportError:
        from sacn_bridge import E131Listener, SERIAL_BAUD
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
    process_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ProcessProfile")
    sensor_sampler = NwinfoSensorSampler()
    stored_providers = str(settings.value("nwinfoProviders", ""))
    if stored_providers:
        sensor_sampler.set_enabled(set(stored_providers.split(",")))
    smooth_filter = SafeTemperatureFilter()
    auto_profiles = AutoProfileSelector()
    app_policy = ApplicationProfilePolicy()
    app_scan_future: Future | None = None
    app_next_scan = 0.0
    app_active: str | None = None
    app_last_lease = 0.0
    runtime_curve_supported = False
    reactive_fx_supported = False
    telemetry = TelemetryStore()
    tach_monitor = TachHealthMonitor()
    last_refs_raw = str(settings.value("fanHealthRefsV1", ""))
    try:
        tach_monitor.import_references(last_refs_raw)
    except ValueError:
        log.warning("Invalid Fan Health reference settings; passive check disabled")
    next_connect = 0.0
    query_due = 0.0
    next_status = 0.0
    client_was_connected = False
    next_temps = 0.0
    rgb_stream = AdaptiveRgbStream()
    try:
        while True:
            now = time.monotonic()
            if output is None and now >= next_connect:
                next_connect = now + 5.0
                if port_name:
                    try:
                        output = serial.Serial(port_name, SERIAL_BAUD, timeout=0, write_timeout=0.25)
                        tx = SerialTransmitter(output)
                        rgb_stream.reset()
                        led_counts = None
                        runtime_curve_supported = False
                        reactive_fx_supported = False
                        app_active = None
                        app_policy.reset()
                        buffer = ""
                        log.info("Connected to %s", port_name)
                        # DTR may reset ESP. Do not block the agent/GUI for 2.2 s.
                        query_due = now + 2.2
                        next_status = now + 7.2
                    except (serial.SerialException, OSError) as exc:
                        output = None
                        log.warning("Unable to connect %s: %s", port_name, exc)
            owner.poll(tx if tx is not None else output)
            if owner.has_client != client_was_connected:
                rgb_stream.reset() # never replay stale RGB across GUI handoff
                if tx is not None:
                    tx.clear()
                client_was_connected = owner.has_client
                app_active = None  # GUI owns policy while attached.
                app_policy.reset()
                if not owner.has_client:
                    next_status = 0.0  # refresh immediately after GUI releases COM
            if output is not None:
                try:
                    if query_due and now >= query_due:
                        tx.write(b"PING\nVERSION?\nLEDS\nSTATUS\n")
                        query_due = 0.0
                    if not owner.has_client and not query_due and now >= next_status:
                        tx.send_command("STATUS")
                        next_status = now + 5.0
                    rx = output.read(output.in_waiting or 0)
                    if rx:
                        owner.forward(rx)
                    if rx:
                        buffer += rx.decode("ascii", errors="replace")
                        if len(buffer) > 8192: buffer = ""
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if line.startswith("FW VERSION="):
                                values = dict(part.split("=", 1) for part in line.split() if "=" in part)
                                runtime_curve_supported = values.get("RTCURVE") == "1"
                                reactive_fx_supported = values.get("RFX") == "1"
                            status = parse_status(line.strip())
                            if status:
                                telemetry.record_fan(
                                    status.channel, pwm=status.pwm, rpm=status.rpm,
                                    temperature=status.deci_c / 10 if status.fresh else None,
                                    fresh=status.fresh, fault=status.fault,
                                )
                                warning = tach_monitor.observe(
                                    status.channel, pwm=status.pwm, rpm=status.rpm,
                                    has_feedback=status.rpm_feedback, fault=status.fault,
                                )
                                if warning:
                                    log.warning(warning)
                                    telemetry.record_alert("TACH", warning)
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
                                for msg in make_sensor_commands(
                                    settings, sample, smooth_filter,
                                    metrics=sensor_sampler.metrics,
                                ):
                                    tx.send_command(msg)
                                if reactive_fx_supported:
                                    settings.sync()
                                    for msg in value_commands(
                                        str(settings.value(MAPPING_KEY,"")),
                                        sample, sensor_sampler.metrics,
                                    ):
                                        tx.send_command(msg)
                                for metric in sensor_sampler.metrics:
                                    telemetry.record_metric(
                                        metric.sensor_id, metric.name, metric.value, metric.unit
                                    )
                                settings.sync()
                                # The GUI may have captured a fresh baseline while
                                # this agent was yielding COM to the GUI.
                                try:
                                    stored_refs = str(settings.value("fanHealthRefsV1", ""))
                                    if stored_refs != last_refs_raw:
                                        tach_monitor.import_references(stored_refs)
                                        last_refs_raw = stored_refs
                                except ValueError:
                                    pass
                                if (not app_active and
                                        str(settings.value("autoProfiles", "false")).lower() in ("true", "1")):
                                    desired = choose_automatic_profile(
                                        sensor_sampler.metrics, auto_profiles,
                                        hour=datetime.now().hour, now=time.monotonic(),
                                    )
                                    if desired:
                                        for command in automatic_profile_commands(desired):
                                            tx.send_command(command)
                                        auto_profiles.applied(desired, time.monotonic())
                                        log.info("Automatic profile applied: %s", desired)
                        except Exception as exc:
                            log.warning("Sensor read failed; ESP thermal watchdog stays active: %s", exc)
                        temp_future = None
                    # Process enumeration runs outside the serial/cooling loop.
                    if not owner.has_client and not query_due and runtime_curve_supported:
                        if app_scan_future is None and now >= app_next_scan:
                            app_scan_future = process_executor.submit(scan_processes)
                            app_next_scan = now + 5.0
                        if app_scan_future is not None and app_scan_future.done():
                            try:
                                running = app_scan_future.result()
                                settings.sync()
                                enabled = str(settings.value("appProfilesEnabled", "false")).lower() in ("true", "1")
                                rules = load_application_rules(str(settings.value("appProfileRulesV1", ""))) if enabled else ()
                                decision = app_policy.consider(rules, running, now=now)
                                if decision.ready and decision.profile != app_active:
                                    actions = runtime_commands(decision.profile) if decision.profile else ("RTCURVE CLEAR",)
                                    for command in actions:
                                        tx.send_command(command)
                                    app_active = decision.profile
                                    app_last_lease = now
                                    log.info("Application cooling profile: %s", app_active or "base")
                            except (ValueError, ImportError, OSError) as exc:
                                log.warning("Application-profile scan failed: %s", exc)
                                # Do not keep a now-unverifiable process override
                                # alive. The firmware still owns all thermal guards.
                                if app_active:
                                    tx.send_command("RTCURVE CLEAR")
                                app_active = None
                                app_policy.reset()
                            finally:
                                app_scan_future = None
                        if app_active and now - app_last_lease > 6.0:
                            tx.send_command("RTCURVE KEEPALIVE")
                            app_last_lease = now
                    frames = listener.read_latest()
                    if not owner.has_client and led_counts is not None:
                        rgb_stream.offer(frames, led_counts, now=now)
                        rgb_stream.dispatch(tx.queue_rgb, now=now)
                    else:
                        rgb_stream.reset()
                    if tx is not None:
                        tx.flush_rgb(now, max_frames=4)
                except (serial.SerialException, OSError, ValueError) as exc:
                    log.warning("Serial disconnected: %s", exc)
                    try: output.close()
                    except (OSError, serial.SerialException): pass
                    output = None
                    if tx is not None:
                        tx.clear()
                    tx = None
                    led_counts = None
                    runtime_curve_supported = False
                    reactive_fx_supported = False
                    app_active = None
                    app_policy.reset()
                    rgb_stream.reset()
                    next_connect = now + 5.0
            else:
                # Drop unattended frames while no COM port is available.
                listener.read_latest()
                rgb_stream.reset()
            time.sleep(0.02)
    except KeyboardInterrupt:
        return 0
    finally:
        owner.close()
        listener.stop()
        temp_executor.shutdown(wait=False, cancel_futures=True)
        process_executor.shutdown(wait=False, cancel_futures=True)
        sensor_sampler.close()
        telemetry.close()
        if output is not None:
            output.close()

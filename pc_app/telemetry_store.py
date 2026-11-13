"""Bounded, asynchronous SQLite history for PC and ESP32 telemetry.

Writes occur off the Qt thread; SQLite WAL supports a background agent and
desktop GUI. Only measured data are recorded; stale values are SQL NULL, not
a guessed temperature. Retention defaults to 30 days.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time


def default_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    return base / "FanARGBControl" / "telemetry.sqlite3"


class TelemetryStore:
    def __init__(self, path: str | Path | None = None,
                 retention_days: int = 30, min_fan_interval: float = 10.0):
        if not 1 <= retention_days <= 365 or min_fan_interval <= 0:
            raise ValueError("Invalid retention/interval")
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.min_fan_interval = min_fan_interval
        self._q: queue.Queue[tuple | None] = queue.Queue(maxsize=4096)
        self._last_fan: dict[int, float] = {}
        self._last_metric: dict[str, float] = {}
        self.dropped = 0
        self._closed = False
        self._ready = threading.Event()
        self._error: str | None = None
        self._thread = threading.Thread(
            target=self._writer, name="FanARGB-Telemetry", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=4)

    def _writer(self) -> None:
        try:
            with sqlite3.connect(str(self.path), timeout=5) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA busy_timeout=5000")
                db.execute("CREATE TABLE IF NOT EXISTS fan_samples ("
                           "ts REAL NOT NULL, channel INTEGER NOT NULL, "
                           "pwm INTEGER NOT NULL, rpm INTEGER NOT NULL, "
                           "temp_c REAL, fresh INTEGER NOT NULL, "
                           "fault INTEGER NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS ix_fan_ts "
                           "ON fan_samples(ts, channel)")
                db.execute("CREATE TABLE IF NOT EXISTS metrics ("
                           "ts REAL NOT NULL, sensor_id TEXT NOT NULL, "
                           "name TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS ix_metric_ts ON metrics(ts)")
                db.execute("CREATE TABLE IF NOT EXISTS alerts ("
                           "ts REAL NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS ix_alert_ts ON alerts(ts)")
                cutoff = time.time() - self.retention_days * 86400
                for table in ("fan_samples", "metrics", "alerts"):
                    db.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
                db.commit()
                self._ready.set()
                while True:
                    try:
                        message = self._q.get(timeout=1.5)
                    except queue.Empty:
                        continue
                    if message is None:
                        break
                    kind, values = message
                    table = {
                        "fan": "fan_samples(ts, channel, pwm, rpm, temp_c, fresh, fault)",
                        "metric": "metrics(ts, sensor_id, name, value, unit)",
                        "alert": "alerts(ts, category, message)",
                    }[kind]
                    placeholders = ",".join("?" for _ in values)
                    db.execute(f"INSERT INTO {table} VALUES({placeholders})", values)
                    db.commit()
        except (OSError, sqlite3.Error) as exc:
            self._error = str(exc)
            self._ready.set()

    @property
    def error(self) -> str | None:
        return self._error

    def _enqueue(self, kind: str, values: tuple) -> None:
        if self._closed or self._error:
            return
        try:
            self._q.put_nowait((kind, values))
        except queue.Full:
            self.dropped += 1

    def record_fan(self, channel: int, *, pwm: int, rpm: int,
                   temperature: float | None, fresh: bool, fault: bool,
                   ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        if not 1 <= channel <= 8 or not 0 <= pwm <= 100 or rpm < 0:
            return
        if ts - self._last_fan.get(channel, float("-inf")) < self.min_fan_interval:
            return
        self._last_fan[channel] = ts
        self._enqueue("fan", (ts, channel, pwm, rpm,
                             temperature if fresh else None, int(fresh), int(fault)))

    def record_metric(self, sensor_id: str, name: str, value: float, unit: str,
                      ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        if not sensor_id or not name or ts - self._last_metric.get(sensor_id, float("-inf")) < 20:
            return
        self._last_metric[sensor_id] = ts
        self._enqueue("metric", (ts, sensor_id[:256], name[:256], value, unit[:20]))

    def record_alert(self, category: str, message: str, ts: float | None = None) -> None:
        self._enqueue("alert", (time.time() if ts is None else ts, category[:64], message[:500]))

    def export_csv(self, path: str | Path, hours: int = 24 * 7) -> int:
        if not 1 <= hours <= 24 * self.retention_days:
            raise ValueError("Invalid export window")
        with sqlite3.connect(str(self.path), timeout=5) as db, open(path, "w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            writer.writerow(("timestamp", "channel", "pwm_percent",
                             "rpm", "temp_c", "fresh", "fault"))
            rows = db.execute(
                "SELECT ts, channel, pwm, rpm, temp_c, fresh, fault FROM fan_samples "
                "WHERE ts >= ? ORDER BY ts ASC LIMIT 250000",
                (time.time() - hours * 3600,),
            )
            count = 0
            for row in rows:
                writer.writerow(row)
                count += 1
            return count

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._q.put(None, timeout=2)
        except queue.Full:
            return
        self._thread.join(timeout=5)

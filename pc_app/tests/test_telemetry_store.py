import csv
from contextlib import closing
from pathlib import Path
import sqlite3
import time
import tempfile
import unittest

from pc_app.telemetry_store import TelemetryStore


class TelemetryStoreTests(unittest.TestCase):
    def test_fan_history_is_persistent_sparse_and_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "history.sqlite3"
            t = TelemetryStore(db, min_fan_interval=5)
            self.assertIsNone(t.error)
            t.record_fan(1, pwm=100, rpm=1234, temperature=52.0,
                         fresh=True, fault=False, ts=100)
            t.record_fan(1, pwm=100, rpm=1235, temperature=53.0,
                         fresh=True, fault=False, ts=101)  # dedup
            t.record_fan(1, pwm=100, rpm=0, temperature=0,
                         fresh=False, fault=True, ts=106)
            t.record_alert("TACH", "Lost fan tach", ts=106)
            t.close()
            with closing(sqlite3.connect(db)) as conn:
                rows = conn.execute("SELECT rpm, temp_c, fresh FROM fan_samples").fetchall()
                self.assertEqual(rows, [(1234, 52.0, 1), (0, None, 0)])
                alerts = conn.execute("SELECT category FROM alerts").fetchall()
                self.assertEqual(alerts, [("TACH",)])

    def test_retention_runs_while_store_remains_open(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "history.sqlite3"
            t = TelemetryStore(db, retention_days=1)
            self.assertIsNone(t.error)
            # A zero interval forces the periodic check on every writer tick.
            t.RETENTION_CHECK_SECONDS = 0
            t.record_alert("old", "Expired record", ts=time.time() - 3 * 86400)
            t.record_alert("new", "Recent record", ts=time.time())
            t.close()
            with closing(sqlite3.connect(db)) as conn:
                rows = conn.execute(
                    "SELECT category FROM alerts ORDER BY ts ASC"
                ).fetchall()
            self.assertEqual(rows, [("new",)])

    def test_csv_export_does_not_silently_truncate_large_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            t = TelemetryStore(root / "history.sqlite3")
            t.close()
            # Eight fans logged every 10 seconds exceed 250k rows in a week.
            count = 250001
            now = time.time()
            with closing(sqlite3.connect(t.path)) as conn:
                conn.executemany(
                    "INSERT INTO fan_samples VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ((now, 1, 65, 1100, 45.0, 1, 0) for _ in range(count)),
                )
                conn.commit()
            result = t.export_csv(root / "complete.csv")
            self.assertEqual(result, count)

    def test_csv_exports_measurements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            t = TelemetryStore(root / "history.sqlite3")
            t.record_fan(2, pwm=70, rpm=1500, temperature=45.5,
                         fresh=True, fault=False)
            t.close()
            out = root / "data.csv"
            count = t.export_csv(out)
            self.assertEqual(count, 1)
            with open(out, encoding="utf-8-sig") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[1][1:4], ["2", "70", "1500"])


if __name__ == "__main__":
    unittest.main()

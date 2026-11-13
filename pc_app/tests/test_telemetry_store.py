import csv
from pathlib import Path
import sqlite3
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
            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT rpm, temp_c, fresh FROM fan_samples").fetchall()
                self.assertEqual(rows, [(1234, 52.0, 1), (0, None, 0)])
                alerts = conn.execute("SELECT category FROM alerts").fetchall()
                self.assertEqual(alerts, [("TACH",)])

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

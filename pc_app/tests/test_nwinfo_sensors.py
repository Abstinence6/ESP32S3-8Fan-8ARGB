import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pc_app.nwinfo_sensors import (
    fetch_temperatures, parse_nwinfo_temperatures, _temperature, locate_nwinfo,
)


# Mirrors a1ive/nwinfo's built-in CPU/GPU/SMART node attributes
# (libnw/sensor/{cpu_sensors,gpu_sensors,disk_smart}.c).
REPORT = {"Sensors": {
    "CPU": {
        "Utilization": 15.3,
        "Intel Core i5-11600": {
            "Package Temperature": 59.0, "Core Temperature": 55.0,
            "Package Power": 78.0, "Max Temperature": 105.0,
        },
    },
    "GPU": {"AMD Radeon RX 9070 XT": {
        "Temperature": 68.25,
        "Memory Frequency": 1520,
        "Utilization": 97,
        "Power": 205,
    }},
    "SMART": {"SSD 1TB": {"Temperature": 41.0, "Alarm Temperature": 80.0}},
}}


class NwinfoSensorsTests(unittest.TestCase):
    def test_real_provider_field_names_and_stable_ids(self):
        sensors = parse_nwinfo_temperatures(REPORT)
        self.assertEqual(len(sensors), 4)
        self.assertEqual({round(s.celsius, 2) for s in sensors}, {59, 55, 68.25, 41})
        self.assertTrue(any("GPU / AMD Radeon" in s.name for s in sensors))
        self.assertTrue(all(s.sensor_id.startswith("nwinfo/") for s in sensors))
        self.assertEqual(
            [s.sensor_id for s in sensors],
            [s.sensor_id for s in parse_nwinfo_temperatures(REPORT)],
        )

    def test_real_world_wrapping_and_numeric_strings(self):
        nested = {"NWinfo": {"Sensors": {
            "CPU": {"Intel": {"Package Temperature": "47.5"}},
            "GPU": {"AMD": {"Temperature": "52.2 °C"}},
        }}}
        sensors = parse_nwinfo_temperatures(nested)
        self.assertEqual({s.celsius for s in sensors}, {47.5, 52.2})

    def test_do_not_use_invalid_temperature_or_thresholds(self):
        invalid = {"Sensors": {
            "CPU": {"Intel": {"Package Temperature": 0.0,
                              "Core Temperature": 999.0,
                              "Alarm Temperature": 60.0}},
            "GPU": {"AMD": {"Temperature": -1,
                            "Utilization": 95}},
            "SMART": {"Drive": {"Temperature": None}},
        }}
        self.assertEqual(parse_nwinfo_temperatures(invalid), [])
        for v in [True, None, -5, 0, 130, float("nan"), float("inf"), "--", "99 W"]:
            self.assertIsNone(_temperature(v))

    def test_backend_is_local_and_never_uses_lhm_provider(self):
        raw = json.dumps({"NWinfo": REPORT}).encode("utf-8")
        success = subprocess.CompletedProcess(args=[], returncode=0, stdout=raw, stderr=b"")
        with (
            patch("pc_app.nwinfo_sensors.locate_nwinfo", return_value=Path("C:/nwinfo/nwinfo.exe")),
            patch("pc_app.nwinfo_sensors.subprocess.run", return_value=success) as runner,
        ):
            sensors = fetch_temperatures()
        self.assertEqual(len(sensors), 4)
        command = runner.call_args.args[0]
        self.assertIn("--sensors=CPU,GPU,SMART", command)
        self.assertFalse(any("LHM" in flag or "HWINFO" in flag for flag in command))
        self.assertEqual(runner.call_args.kwargs["timeout"], 4.0)

    def test_error_without_backend_and_without_valid_sensor_json(self):
        with patch("pc_app.nwinfo_sensors.locate_nwinfo", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(FileNotFoundError):
                fetch_temperatures()
        with (
            patch("pc_app.nwinfo_sensors.locate_nwinfo", return_value=Path("C:/nwinfo/nwinfo.exe")),
            patch("pc_app.nwinfo_sensors.subprocess.run",
                  return_value=subprocess.CompletedProcess([], 0, b'{"NWinfo": {}}', b"")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Sensors"):
                fetch_temperatures()


if __name__ == "__main__":
    unittest.main()

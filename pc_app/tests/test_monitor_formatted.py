"""Regression for LibreHardwareMonitor 0.9.6 string RawValue sensor readings.

Reference: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/issues/2253
"""
import io
import json
from unittest.mock import patch
import unittest

from pc_app.monitor import TemperatureSensor, fetch_temperatures, parse_temperatures


def fixture(*readings):
    return {
        "Text": "PC",
        "Children": [{
            "Text": "CPU",
            "Children": [{
                "Text": "Temperatures",
                "Children": [
                    {"Text": label, "Type": "Temperature", "SensorId": f"/cpu/temp/{i}",
                     "RawValue": raw, "Value": value, "Children": []}
                    for i, (label, raw, value) in enumerate(readings)
                ],
            }],
        }],
    }


class LhmFormattedTemperatureTests(unittest.TestCase):
    def test_lhm_096_formatted_raw_values_become_celsius(self):
        sensors = parse_temperatures(fixture(
            ("CPU Package", "46.9 °C", "46.9 °C"),
            ("CCD1 (Tdie)", "47.3 °C", "47.3 °C"),
        ))
        self.assertEqual(len(sensors), 2)
        self.assertEqual([s.celsius for s in sensors], [47.3, 46.9] if
                         sensors[0].name.endswith("CCD1 (Tdie)") else [46.9, 47.3])

    def test_fallback_to_formatted_value_when_raw_missing(self):
        sensors = parse_temperatures(fixture(
            ("CPU Package", None, "62.4 °C"),
            ("Core #1", "42,5 °C", "42,5 °C"),
        ))
        self.assertEqual({s.sensor_id: s.celsius for s in sensors},
                         {"/cpu/temp/0": 62.4, "/cpu/temp/1": 42.5})

    def test_fahrenheit_value_converted_to_celsius(self):
        sensors = parse_temperatures(fixture(
            ("CPU", "122 °F", "122 °F"),
        ))
        self.assertAlmostEqual(sensors[0].celsius, 50.0)

    def test_reject_invalid_or_unrealistic_readings(self):
        readings = [
            ("Missing", "N/A", "--"),
            ("Nonfinite", "NaN", "∞"),
            ("Outside", "500 °C", "500 °C"),
            ("Empty", None, None),
            ("Boolean", True, True),
        ]
        self.assertEqual(parse_temperatures(fixture(*readings)), [])

    def test_http_fetch_round_trip_parses_formatted_values(self):
        tree = fixture(("CPU Package", "46.9 °C", "46.9 °C"))
        body = json.dumps(tree).encode("utf-8")
        with patch("pc_app.monitor.urllib.request.urlopen", return_value=io.BytesIO(body)) as mocked:
            sensors = fetch_temperatures("http://127.0.0.1:8085/data.json", 0.8)
        self.assertEqual(sensors[0].celsius, 46.9)
        mocked.assert_called_once_with("http://127.0.0.1:8085/data.json", timeout=0.8)


if __name__ == "__main__":
    unittest.main()

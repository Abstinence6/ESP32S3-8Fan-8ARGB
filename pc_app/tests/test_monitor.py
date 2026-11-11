import unittest
from pc_app.monitor import MAX_ALL, parse_temperatures, resolve_temperature


class SensorParsingTests(unittest.TestCase):
    def test_walks_all_valid_temperatures_and_ignores_other_types(self):
        tree = {
            "Text": "PC", "Children": [
                {"Text": "CPU", "Children": [
                    {"Text": "Temperature", "Children": [
                        {"Text": "CPU Package", "Type": "Temperature", "SensorId": "/cpu/0/temp/0", "RawValue": 65.5},
                        {"Text": "Core", "Type": "Temperature", "SensorId": "/cpu/0/temp/1", "RawValue": None},
                    ]},
                    {"Text": "Load", "Type": "Load", "SensorId": "/cpu/0/load/0", "RawValue": 90},
                ]},
                {"Text": "GPU", "Children": [
                    {"Text": "Hotspot", "Type": "Temperature", "SensorId": "/gpu/0/temp/0", "RawValue": 77.2},
                ]},
            ],
        }
        sensors = parse_temperatures(tree)
        self.assertEqual(len(sensors), 2)
        self.assertEqual(resolve_temperature("/cpu/0/temp/0", sensors), 65.5)
        self.assertEqual(resolve_temperature(MAX_ALL, sensors), 77.2)
        self.assertIsNone(resolve_temperature("/missing", sensors))
        self.assertTrue(any("CPU Package" in sensor.name for sensor in sensors))


if __name__ == "__main__":
    unittest.main()

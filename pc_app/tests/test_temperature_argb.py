import unittest

from pc_app.monitor import TemperatureSensor, GROUP_AVG, GROUP_MAX
from pc_app.temperature_argb import (
    OFF, ZoneTemperatureConfig, zone_color, temperature_color, MISSING_RGB,
)


class TemperatureArgbTests(unittest.TestCase):
    def setUp(self):
        self.sensors = [
            TemperatureSensor("cpu", "CPU Package", 60.0),
            TemperatureSensor("gpu", "GPU Hotspot", 85.0),
        ]

    def test_single_sensor_and_independent_ranges(self):
        cool = ZoneTemperatureConfig(source="cpu", low_c=30, high_c=90)
        hot = ZoneTemperatureConfig(source="gpu", low_c=30, high_c=90)
        self.assertNotEqual(zone_color(cool, self.sensors, fresh=True),
                            zone_color(hot, self.sensors, fresh=True))

    def test_group_max_and_average_are_not_same(self):
        group = ("cpu", "gpu")
        peak = ZoneTemperatureConfig(source=GROUP_MAX, group_ids=group)
        average = ZoneTemperatureConfig(source=GROUP_AVG, group_ids=group)
        self.assertNotEqual(zone_color(peak, self.sensors, fresh=True),
                            zone_color(average, self.sensors, fresh=True))

    def test_missing_group_member_signals_unavailable_not_cool(self):
        cfg = ZoneTemperatureConfig(source=GROUP_MAX, group_ids=("cpu", "missing"))
        self.assertEqual(zone_color(cfg, self.sensors, fresh=True),
                         temperature_color(None, cfg))
        self.assertEqual(zone_color(cfg, self.sensors, fresh=False),
                         temperature_color(None, cfg))

    def test_hot_cold_and_missing_colors(self):
        cfg = ZoneTemperatureConfig(source="cpu", low_c=30, high_c=90, brightness=128)
        cold = temperature_color(30, cfg)
        hot = temperature_color(90, cfg)
        missing = temperature_color(None, cfg)
        self.assertGreater(cold[2], cold[0])
        self.assertGreater(hot[0], hot[2])
        self.assertGreater(missing[0], missing[2])
        self.assertEqual(missing, tuple(round(x * 128 / 255) for x in MISSING_RGB))

    def test_disabled_zone_and_bad_values(self):
        self.assertIsNone(zone_color(ZoneTemperatureConfig(), self.sensors, fresh=True))
        for value in (float("nan"), float("inf"), -1, 200):
            self.assertEqual(temperature_color(value, ZoneTemperatureConfig()),
                             temperature_color(None, ZoneTemperatureConfig()))

    def test_serializable_settings_and_validation(self):
        cfg = ZoneTemperatureConfig(source=GROUP_MAX, group_ids=("cpu", "gpu"),
                                    low_c=35, high_c=80, brightness=82)
        self.assertEqual(ZoneTemperatureConfig.from_dict(cfg.as_dict()), cfg)
        with self.assertRaises(ValueError):
            ZoneTemperatureConfig(source="cpu", low_c=100, high_c=30)
        with self.assertRaises(ValueError):
            ZoneTemperatureConfig(source="cpu", group_ids=("cpu", "cpu"))
        with self.assertRaises(ValueError):
            ZoneTemperatureConfig(brightness=255)
        with self.assertRaises(ValueError):
            ZoneTemperatureConfig(source="s" * 96)
        with self.assertRaises(ValueError):
            ZoneTemperatureConfig(group_ids=tuple(str(i) for i in range(9)))


if __name__ == "__main__":
    unittest.main()

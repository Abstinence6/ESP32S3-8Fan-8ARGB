import unittest
from pc_app.smart_control import SafeTemperatureFilter, AutoProfileSelector


class SafeCoolingTests(unittest.TestCase):
    def test_hot_spikes_are_immediate_and_falls_are_slow(self):
        f = SafeTemperatureFilter(hysteresis=1, hold_seconds=2, falling_celsius_per_second=2)
        self.assertEqual(f.update(1, 50, 1), 50)
        self.assertEqual(f.update(1, 94, 2), 94)
        self.assertEqual(f.update(1, 50, 3), 94)
        self.assertEqual(f.update(1, 50, 5), 90)
        self.assertEqual(f.update(1, None, 6), None)
        self.assertEqual(f.update(1, 45, 7), 45)

    def test_only_valid_sensors_are_transmitted(self):
        f = SafeTemperatureFilter()
        self.assertIsNone(f.update(2, float("nan"), 1))
        self.assertIsNone(f.update(2, 127, 2))
        with self.assertRaises(ValueError):
            f.update(9, 50, 3)

    def test_automatic_profile_dwell_and_minimum_nvs_interval(self):
        auto = AutoProfileSelector(dwell_seconds=30, min_change_seconds=600)
        self.assertIsNone(auto.consider(89, 12, 100))
        self.assertIsNone(auto.consider(80, 12, 120))
        self.assertEqual(auto.consider(87, 12, 131), "Performance")
        auto.applied("Performance", 131)
        self.assertIsNone(auto.consider(10, 12, 200))
        self.assertIsNone(auto.consider(10, 12, 270))
        self.assertIsNone(auto.consider(10, 12, 500))
        self.assertEqual(auto.consider(10, 12, 731), "Balanced")
        self.assertEqual(auto.recommend(5, 23), "Silent")


if __name__ == "__main__":
    unittest.main()

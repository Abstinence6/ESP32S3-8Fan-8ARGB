import unittest
from pc_app.pinmap_config import DEFAULTS, allowed_for_slot, default_map, validate_map


class GpioMappingTests(unittest.TestCase):
    def test_factory_mapping_is_valid(self):
        validate_map(default_map())
        self.assertTrue(allowed_for_slot(35, "PWM", 2))
        self.assertTrue(allowed_for_slot(46, "ARGB", 7))
        self.assertFalse(allowed_for_slot(46, "PWM", 2))

    def test_unavailable_or_reserved_pins_rejected(self):
        for pin in (0, 3, 19, 20, 22, 25, 27, 31, 35, 43, 44, 45, 46, 49):
            self.assertFalse(allowed_for_slot(pin, "PWM", 1))
        self.assertTrue(allowed_for_slot(18, "PWM", 1))

    def test_duplicates_and_invalid_channels_rejected(self):
        data = default_map()
        data["PWM"][0] = data["TACH"][0]
        with self.assertRaises(ValueError):
            validate_map(data)
        data = default_map()
        data["PWM"][0] = 22
        with self.assertRaises(ValueError):
            validate_map(data)
        data = default_map()
        data["PWM"][0] = 18
        validate_map(data)

    def test_all_24_signals_required(self):
        data = default_map()
        data["ARGB"].pop()
        with self.assertRaises(ValueError):
            validate_map(data)


if __name__ == "__main__":
    unittest.main()

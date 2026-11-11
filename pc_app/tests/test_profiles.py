import unittest
from pc_app.profiles import PRESETS, validate_profiles

class ProfilesTests(unittest.TestCase):
    def test_preset_curves_are_monotonic(self):
        for points in PRESETS.values():
            self.assertTrue(validate_profiles([points] * 8))
    def test_invalid_profiles_rejected(self):
        self.assertFalse(validate_profiles([[(-1, 20)] * 5] * 8))

if __name__ == "__main__":
    unittest.main()

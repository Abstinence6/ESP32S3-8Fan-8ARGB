"""Regression: ARGB-only scene presets never touch fan power or saved curves."""
import unittest
from pc_app.ui_dashboard_model import make_scene_commands


class DashboardSceneTests(unittest.TestCase):
    def test_solid_on_one_zone(self):
        self.assertEqual(
            make_scene_commands("Static warm", [3]),
            ["BRIGHT 3 64", "LED 3 255 110 30"],
        )

    def test_rainbow_all_zones(self):
        lines = make_scene_commands("Rainbow", range(1, 9))
        self.assertEqual(len(lines), 16)
        self.assertEqual(lines[0], "BRIGHT 1 64")
        self.assertEqual(lines[-1], "RAINBOW 8")
        self.assertFalse(any(s.startswith(("CURVE", "FAN", "TYPE")) for s in lines))

    def test_external_requires_live_frames(self):
        self.assertEqual(make_scene_commands("OpenRGB", [1, 2]), [])

    def test_off_only_selected(self):
        self.assertEqual(make_scene_commands("Off", [4, 7]), ["OFF 4", "OFF 7"])

    def test_invalid_channels_rejected(self):
        for channels in ([], [0], [9], [1, 1], ["1"], [True]):
            with self.subTest(channels=channels):
                with self.assertRaises(ValueError):
                    make_scene_commands("Off", channels)
        with self.assertRaises(ValueError):
            make_scene_commands("Missing scene", [1])


if __name__ == "__main__":
    unittest.main()

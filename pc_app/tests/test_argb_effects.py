import unittest
from pc_app.argb_effects import MODES, render_effect


class ArgbPatterns(unittest.TestCase):
    def test_every_mode_encodes_rgb_for_one_zone(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                frame = render_effect(mode, 25, 1.5, (255, 100, 0), (0, 40, 255))
                self.assertEqual(len(frame), 75)
                self.assertLessEqual(max(frame), 64)

    def test_brightness_zero_is_black(self):
        self.assertEqual(render_effect("Wave", 4, 9, (255,255,255), (200,200,200), 0),
                         bytes(12))

    def test_reject_overlarge_frame_or_invalid_color(self):
        for count in (0, 171):
            with self.assertRaises(ValueError):
                render_effect("Gradient", count, 0, (0,0,0), (255,255,255))
        with self.assertRaises(ValueError):
            render_effect("Rainbow", 1, 0, (0,0,0), (255,255,255))


if __name__ == "__main__":
    unittest.main()

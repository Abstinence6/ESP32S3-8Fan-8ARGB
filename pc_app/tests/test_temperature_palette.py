import unittest
from pc_app.temperature_palette import (
    DEFAULT_PALETTE, color_at, make_palette_command,
    parse_palette_reply, validate_palette,
)


class PaletteTests(unittest.TestCase):
    def test_defaults_and_linear_interpolation(self):
        self.assertEqual(color_at(0, DEFAULT_PALETTE), (0, 100, 255))
        self.assertEqual(color_at(200, DEFAULT_PALETTE), (255, 0, 0))
        pts = ((20, 0, 0, 0), (40, 100, 100, 100),
               (60, 200, 100, 0), (80, 250, 0, 0))
        self.assertEqual(color_at(30, pts), (50, 50, 50))

    def test_wire_round_trip_and_limits(self):
        pts = ((25, 0, 0, 255), (50, 0, 255, 0),
               (75, 255, 255, 0), (100, 255, 0, 0))
        line = make_palette_command(2, pts)
        self.assertEqual(line, "TPAL SET 2 4 25 0 0 255 50 0 255 0 75 255 255 0 100 255 0 0")
        data = ";".join(",".join(map(str, p)) for p in pts)
        self.assertEqual(parse_palette_reply(f"TPAL CH=2 COUNT=4 DATA={data}"), (2, pts))
        with self.assertRaises(ValueError):
            parse_palette_reply(f"TPAL CH=3 COUNT=5 DATA={data}")

    def test_bad_temperature_and_rgb_are_rejected(self):
        for bad in (
            ((20, 0, 0, 0), (20, 0, 0, 0), (60, 0, 0, 0), (80, 0, 0, 0)),
            ((20, 0, 0, 0), (40, 300, 0, 0), (60, 0, 0, 0), (80, 0, 0, 0)),
            ((20, 0, 0, 0), (40, 0, 0, 0), (60, 0, 0, 0)),
        ):
            with self.assertRaises(ValueError):
                validate_palette(bad)
        with self.assertRaises(ValueError):
            color_at(float("nan"), DEFAULT_PALETTE)


if __name__ == "__main__":
    unittest.main()

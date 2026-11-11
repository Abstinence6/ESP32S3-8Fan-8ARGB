import unittest
from pc_app.protocol import (
    DEFAULT_CURVE, make_curve_command, make_temperature_command,
    parse_curve, parse_status, validate_curve,
)


class ProtocolTests(unittest.TestCase):
    def test_curve_roundtrip(self):
        message = make_curve_command(3, DEFAULT_CURVE)
        self.assertEqual(parse_curve(message), (3, DEFAULT_CURVE))
        self.assertFalse(validate_curve([(40, 30), (35, 50), (55, 70), (65, 90), (80, 100)]))
        self.assertIsNone(parse_curve("CURVE 0 20 30 30 40 45 60 60 80 75 100"))

    def test_temp_validation(self):
        self.assertEqual(make_temperature_command(1, 43.25), "TEMP 1 432")
        with self.assertRaises(ValueError):
            make_temperature_command(4, 150)

    def test_status(self):
        status = parse_status("CH 2 FAN=55% RPM=1400 TEMP=487 MODE=auto SENSOR=ok")
        self.assertEqual((status.channel, status.pwm, status.rpm, status.deci_c), (2, 55, 1400, 487))
        self.assertTrue(status.fresh)
        self.assertIsNone(parse_status("ERR arguments"))


if __name__ == "__main__":
    unittest.main()

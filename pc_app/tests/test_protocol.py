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
        v4 = parse_status("CH 3 FAN=62% RPM=1460 TEMP=510 MODE=rpm SENSOR=ok TARGET=1500 FAULT=0 TYPE=3 RPM_OK=1")
        self.assertIsNotNone(v4)
        self.assertEqual((v4.mode, v4.target_rpm, v4.detected_type, v4.rpm_feedback),
                         ("rpm", 1500, 3, True))
        twowire = parse_status("CH 4 FAN=50% RPM=0 TEMP=440 MODE=auto SENSOR=ok TARGET=0 FAULT=0 TYPE=2 RPM_OK=0")
        self.assertFalse(twowire.rpm_feedback)
        self.assertIsNone(parse_status("CH 1 FAN=50% RPM=100 TEMP=450 MODE=auto SENSOR=ok TARGET=oops"))
        self.assertIsNone(parse_status("ERR arguments"))


if __name__ == "__main__":
    unittest.main()

import unittest
from pc_app.diagnostics import parse_health


class DiagnosisTests(unittest.TestCase):
    def test_detect_stale_fault_and_dc_guard(self):
        base = ("HEALTH 2 TYPE=3 DETECTED=255 PWM=100 RPM=1200 "
                "TACH=seen TACH_VALID=1 SENSOR=ok FAULT=0 DC_READY=0 MODE=auto")
        result = parse_health(base)
        self.assertEqual(result.channel, 2)
        self.assertIn("заблоковано", result.assessment)
        self.assertIn("Немає температури", parse_health(base.replace("SENSOR=ok", "SENSOR=stale")).assessment)
        self.assertEqual(parse_health(base.replace("FAULT=0", "FAULT=1")).assessment, "Аварія")
        self.assertIsNone(parse_health("HEALTH 22 PWM=0"))
        self.assertIsNone(parse_health(base.replace("PWM=100", "PWM=101")))


if __name__ == "__main__":
    unittest.main()

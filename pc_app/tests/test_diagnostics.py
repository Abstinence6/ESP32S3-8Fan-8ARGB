import unittest
from pc_app.diagnostics import parse_health


class DiagnosisTests(unittest.TestCase):
    def test_temperature_source_age_and_failsafe_diagnostics(self):
        line = ("HEALTH 4 TYPE=3 PWM=100 RPM=900 TACH=seen "
                "TACH_VALID=1 SENSOR=ok SOURCE=ds18b20 AGE_MS=150 "
                "FAILSAFE=overheat FAULT=0 DC_READY=0 MODE=auto")
        status = parse_health(line)
        self.assertEqual((status.source, status.age_ms, status.failsafe),
                         ("ds18b20", 150, "overheat"))
        self.assertIn("Перегрів", status.assessment)
        self.assertIsNone(parse_health(line.replace("AGE_MS=150", "AGE_MS=-2")))
        self.assertIsNone(parse_health(line.replace("SOURCE=ds18b20", "SOURCE=spoof")))
        self.assertEqual(parse_health(line.replace("AGE_MS=150", "AGE_MS=-")).age_ms, None)

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

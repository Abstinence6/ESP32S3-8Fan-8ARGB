import unittest
from pc_app.tach_health import TachHealthMonitor


class TachTests(unittest.TestCase):
    def test_only_reports_missing_tach_after_multiple_samples(self):
        m = TachHealthMonitor()
        self.assertIsNone(m.observe(1, pwm=100, rpm=0, has_feedback=True))
        self.assertIsNone(m.observe(1, pwm=100, rpm=0, has_feedback=True))
        self.assertIn("TACH", m.observe(1, pwm=100, rpm=0, has_feedback=True))
        self.assertIsNone(m.observe(1, pwm=100, rpm=0, has_feedback=True))
        m.observe(1, pwm=100, rpm=1700, has_feedback=True)
        self.assertIsNone(m.observe(1, pwm=100, rpm=1800, has_feedback=True))

    def test_two_pin_and_changing_pwm_ignore_noise(self):
        m = TachHealthMonitor()
        for _ in range(12):
            self.assertIsNone(m.observe(5, pwm=100, rpm=0, has_feedback=False))
        for pwm, rpm in [(20, 500), (30, 1500), (40, 700), (50, 1800)]:
            self.assertIsNone(m.observe(3, pwm=pwm, rpm=rpm, has_feedback=True))

    def test_stable_rpm_does_not_report_fault(self):
        m = TachHealthMonitor()
        for rpm in (1200, 1210, 1180, 1250, 1210, 1190, 1240, 1200):
            self.assertIsNone(m.observe(2, pwm=100, rpm=rpm, has_feedback=True))


if __name__ == "__main__":
    unittest.main()

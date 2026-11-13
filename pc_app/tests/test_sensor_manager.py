import unittest
from unittest.mock import patch
from pc_app.nwinfo_sensors import NwinfoSensorSampler


class ProviderManagerTests(unittest.TestCase):
    def test_disable_source_expires_values_and_backoff(self):
        with patch("pc_app.nwinfo_sensors.detect_cpu_vendor", return_value="intel"):
            sampler = NwinfoSensorSampler(executor=object())
        self.assertNotIn("ZEN", sampler.permitted_providers)
        sampler._latest["CPU"] = (1, ["stale"])
        sampler.set_enabled({"GPU", "SMART"})
        self.assertNotIn("CPU", sampler.active_providers)
        self.assertNotIn("CPU", sampler._latest)
        self.assertEqual(sampler._backoff("GPU"), 8)
        self.assertEqual(sampler._backoff("GPU"), 16)
        sampler.refresh_all()
        self.assertEqual(sampler._backoff("GPU"), 8)
        sampler.close()


if __name__ == "__main__":
    unittest.main()

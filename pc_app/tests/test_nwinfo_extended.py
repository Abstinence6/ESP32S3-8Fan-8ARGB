"""Additional NWinfo sensor provider and telemetry regression tests."""
from concurrent.futures import Future
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pc_app import nwinfo_sensors as ns


EXTENDED = {"Sensors": {
    "CPU": {"Intel Core i5": {"Package Temperature": 55, "Core Temperature": 53,
                               "Utilization": 28.5, "Frequency": 4300,
                               "Core Voltage": 1.12, "Package Power": 89}},
    "GPU": {"AMD Radeon": {"Temperature": 68.2, "Fan Speed": 1230,
                           "Utilization": 96, "Memory Usage": 50,
                           "Power": 215, "Voltage": 0.91,
                           "Frequency": 2680, "Memory Frequency": 1250}},
    "SMART": {"NVMe SSD": {"Temperature": 40, "Alarm Temperature": 83, "Life": 95}},
    "DIMM": {"Memory": {"DIMM A1": {"Temperature": 38.5}, "Load": 35}},
    "INTEL": {"Package Temperature": 56, "PCH Temperature": 47,
               "Tj Max": 100, "T-Control": 80, "Package Power": 92},
    "ZEN": {"Tctl": 62.1, "Tdie": 60.5, "Tccd1": 55.0,
            "GFX Temperature": 61, "Core Temperature 0": 58,
            "SoC Voltage": 1.05, "Socket Power": 85},
    "DISK": {"SSD 1": {"Read IOPS": 240.0, "Write IOPS": 39,
                       "Read Latency ms": 1.5, "Utilization": 12}},
}}


class MoreSensorsTests(unittest.TestCase):
    def test_new_live_temperature_names_with_strict_exclusions(self):
        readings = ns.parse_nwinfo_temperatures(EXTENDED)
        by_name = {s.name: s.celsius for s in readings}
        self.assertTrue(any("PCH Temperature" in k for k in by_name))
        self.assertTrue(any("Tdie" in k for k in by_name))
        self.assertTrue(any("Tccd1" in k for k in by_name))
        self.assertTrue(any("Core Temperature 0" in k for k in by_name))
        self.assertTrue(any("DIMM A1" in k for k in by_name))
        self.assertTrue(all("Alarm Temperature" not in k for k in by_name))
        self.assertTrue(all("Tj Max" not in k for k in by_name))
        self.assertTrue(all("T-Control" not in k for k in by_name))
        self.assertTrue(all(5 <= temp <= 125 for temp in by_name.values()))

    def test_live_metrics_have_explicit_units_and_are_not_temperatures(self):
        values = ns.parse_nwinfo_metrics(EXTENDED)
        by_name = {m.name: m for m in values}
        def find(fragment):
            return next(m for k, m in by_name.items() if fragment in k)
        self.assertEqual(find("Fan Speed").unit, "RPM")
        self.assertEqual(find("Package Power").unit, "W")
        self.assertEqual(find("Memory Frequency").unit, "MHz")
        self.assertEqual(find("Core Voltage").unit, "V")
        self.assertEqual(find("Utilization").unit, "%")
        self.assertEqual(find("Read IOPS").unit, "IOPS")
        self.assertEqual(find("Read Latency ms").unit, "ms")
        self.assertEqual(find("Life").unit, "%")
        self.assertFalse(any("Alarm Temperature" in m.name for m in values))
        self.assertFalse(any(m.value < 0 for m in values))
        self.assertFalse(any(m.unit == "°C" for m in values))

    def test_nwinfo_result_can_return_metrics_without_breaking_existing_fans(self):
        raw = json.dumps({"NWinfo": EXTENDED}).encode("utf-8")
        success = subprocess.CompletedProcess(args=[], returncode=0, stdout=raw, stderr=b"")
        with (
            patch.object(ns, "locate_nwinfo", return_value=Path("C:/nwinfo/nwinfo.exe")),
            patch.object(ns.subprocess, "run", return_value=success) as run,
        ):
            result = ns.fetch_temperatures(timeout=3.5, providers=("GPU",))
        self.assertIsInstance(result, list)
        self.assertTrue(result)
        self.assertTrue(result.metrics)
        self.assertEqual(run.call_args.kwargs["timeout"], 3.5)

    def test_extended_providers_schedule_independently(self):
        """A delayed DIMM/INTEL/ZEN probe never blocks initial GPU and CPU."""
        class ImmediateExecutor:
            def __init__(self):
                self.calls = []
            def submit(self, fn, *args):
                self.calls.append(args[1])
                f = Future()
                f.set_result(ns.SensorBatch([]))
                return f
        executor = ImmediateExecutor()
        sampler = ns.NwinfoSensorSampler(executor=executor)
        sampler.poll(now=10)
        self.assertIn(("GPU",), executor.calls)
        self.assertIn(("CPU",), executor.calls)
        self.assertNotIn(("INTEL",), executor.calls)
        sampler.poll(now=20)
        for name in ("DIMM", "INTEL", "ZEN", "DISK"):
            self.assertIn((name,), executor.calls)
        sampler.close()

    def test_metrics_expire_independently_of_temperature(self):
        from pc_app.monitor import TemperatureSensor
        metric = ns.HardwareMetric("nwinfo/gpu/x/power", "GPU / Power", 200, "W", "power")
        class ImmediateExecutor:
            def submit(self, fn, *args):
                f = Future()
                f.set_result(ns.SensorBatch(
                    [TemperatureSensor("nwinfo/gpu/x/temperature", "GPU / Temperature", 64)],
                    [metric],
                ))
                return f
        sampler = ns.NwinfoSensorSampler(executor=ImmediateExecutor())
        sampler.poll(now=0)
        sampler.poll(now=.1)
        self.assertTrue(sampler.metrics)
        self.assertEqual(sampler.metrics[0].unit, "W")
        sampler.poll(now=8)
        self.assertFalse(sampler.metrics)
        sampler.close()


if __name__ == "__main__":
    unittest.main()

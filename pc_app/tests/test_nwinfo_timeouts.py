"""Regression for real symptom: one hung NWinfo provider cannot block GPU updates."""
from concurrent.futures import Future
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pc_app import nwinfo_sensors


class ImmediateExecutor:
    """Deterministic single-threaded substitute for the sampler's background pool."""
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class ProviderIsolationTests(unittest.TestCase):
    def test_gpu_still_updates_if_cpu_provider_times_out(self):
        def read(timeout=4.0, providers=("CPU", "GPU", "SMART")):
            if providers == ("CPU",):
                raise RuntimeError("NWinfo [CPU] перевищив час очікування (7 с)")
            if providers == ("GPU",):
                return nwinfo_sensors.parse_nwinfo_temperatures(
                    {"Sensors": {"GPU": {"AMD RX 9070 XT": {"Temperature": 68.5}}}}
                )
            return []

        with patch.object(nwinfo_sensors, "fetch_temperatures", side_effect=read):
            sampler = nwinfo_sensors.NwinfoSensorSampler(executor=ImmediateExecutor())
            self.assertIsNone(sampler.poll(now=10.0))  # start probes
            sensors = sampler.poll(now=10.1)
            self.assertEqual(len(sensors), 1)
            self.assertEqual(sensors[0].celsius, 68.5)
            self.assertIn("CPU", sampler.problems)
            # Stale values must expire; ESP will revert to full-speed.
            self.assertEqual(sampler.poll(now=18.3), [])
            sampler.close()

    def test_gpu_does_not_load_privileged_cpu_driver(self):
        reply = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"Sensors": {"GPU": {"AMD": {"Temperature": 58.1}}}}).encode(),
            stderr=b"",
        )
        with (
            patch.object(nwinfo_sensors, "locate_nwinfo", return_value=Path("C:/nwinfo/nwinfo.exe")),
            patch.object(nwinfo_sensors.subprocess, "run", return_value=reply) as run,
        ):
            gpu = nwinfo_sensors.fetch_temperatures(timeout=6.5, providers=("GPU",))
        self.assertEqual(len(gpu), 1)
        self.assertIn("--sensors=GPU", run.call_args.args[0])
        self.assertIn("--driver=NONE", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["timeout"], 6.5)

    def test_smart_stall_does_not_hold_fan_telemetry(self):
        def read(timeout=4.0, providers=("CPU", "GPU", "SMART")):
            if providers == ("SMART",):
                raise RuntimeError("SMART timeout")
            if providers == ("CPU",):
                return nwinfo_sensors.parse_nwinfo_temperatures(
                    {"Sensors": {"CPU": {"Intel": {"Package Temperature": 56}}}}
                )
            return []
        with patch.object(nwinfo_sensors, "fetch_temperatures", side_effect=read):
            sampler = nwinfo_sensors.NwinfoSensorSampler(executor=ImmediateExecutor())
            sampler.poll(now=20)
            self.assertEqual([s.celsius for s in sampler.poll(now=20.1)], [56])
            sampler.poll(now=25.1)  # SMART starts later, separate background call
            self.assertEqual([s.celsius for s in sampler.poll(now=25.2)], [56])
            self.assertIn("SMART", sampler.problems)
            sampler.close()


if __name__ == "__main__":
    unittest.main()

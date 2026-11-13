"""Regression coverage for v6.1 safety and reliability hardening."""
import tempfile
from pathlib import Path
import unittest

from pc_app.firmware_update import flash_preflight, inspect_firmware
from pc_app.smart_control import AutoProfileSelector
from pc_app.tray_monitor import FaultNotificationGate


class SafetyUpgrades(unittest.TestCase):
    def test_unknown_or_disabled_pc_must_confirm_isolated_bench(self):
        for state in ("unknown", "disabled", "invalid", ""):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    flash_preflight(state, isolated_bench=False, is_proxy=False)
                flash_preflight(state, isolated_bench=True, is_proxy=False)

    def test_known_power_on_cannot_flash_even_if_bench_selected(self):
        with self.assertRaises(ValueError):
            flash_preflight("on", isolated_bench=True, is_proxy=False)
        flash_preflight("off", isolated_bench=False, is_proxy=False)
        with self.assertRaises(ValueError):
            flash_preflight("off", isolated_bench=True, is_proxy=True)

    def test_changed_firmware_image_does_not_match_selected_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            firmware = Path(temp) / "firmware.bin"
            firmware.write_bytes(bytes([0xE9, 3, 0, 0, 0, 0, 0, 0]) + bytes(2200))
            old, _ = inspect_firmware(str(firmware))
            firmware.write_bytes(bytes([0xE9, 3, 0, 0, 0, 0, 0, 0]) + bytes([2])*2200)
            new, _ = inspect_firmware(str(firmware))
            self.assertNotEqual(old, new)

    def test_missing_gpu_telemetry_does_not_write_a_silent_curve(self):
        selector = AutoProfileSelector(dwell_seconds=20)
        self.assertIsNone(selector.recommend(None, 23))
        self.assertIsNone(selector.consider(None, 23, 100))
        self.assertIsNone(selector.consider(None, 23, 200))
        self.assertIsNone(selector.recommend(float("nan"), 2))
        self.assertIsNone(selector.consider(85, 12, 210))  # valid again; start dwell
        self.assertEqual(selector.consider(85, 12, 235), "Performance")
        selector.applied("Performance", 235)
        self.assertIsNone(selector.consider(None, 23, 1000))

    def test_fan_fault_messages_once_per_transition_and_limited(self):
        gate = FaultNotificationGate(cooldown=60)
        self.assertIn("авар", gate.observe(2, fault=True, fresh=True, now=5).lower())
        self.assertIsNone(gate.observe(2, fault=True, fresh=True, now=6))
        self.assertIsNone(gate.observe(2, fault=False, fresh=True, now=7))
        self.assertIsNone(gate.observe(2, fault=True, fresh=True, now=8))  # rate limited
        self.assertIn("авар", gate.observe(2, fault=True, fresh=True, now=66).lower())
        self.assertIn("температур", gate.observe(2, fault=False, fresh=False, now=67).lower())


if __name__ == "__main__":
    unittest.main()

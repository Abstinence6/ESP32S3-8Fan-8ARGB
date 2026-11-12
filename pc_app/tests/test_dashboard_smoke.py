"""Windows/offscreen Qt smoke test: build the real dashboard without hardware.

Runs separately *after* installing the GUI requirements. The regular
stdlib-only unit suite intentionally skips this on build workers without Qt.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    import pyqtgraph  # noqa: F401
    import serial  # noqa: F401
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "GUI dependencies not yet installed")
class DashboardSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from main import FanArgbWindow
        self.window = FanArgbWindow()
        self.window.temperature_timer.stop()
        self.window.serial_timer.stop()
        self.window.sacn_timer.stop()
        self.window.aux_status_timer.stop()
        self.window.temperature_result_timer.stop()

    def tearDown(self):
        self.window.close()

    def test_render_preview(self):
        """Optional offscreen screenshots for visual QA of the actual Qt layout."""
        if os.environ.get("SAVE_DASHBOARD_PREVIEW") != "1":
            self.skipTest("Set SAVE_DASHBOARD_PREVIEW=1 to capture screenshots")
        from protocol import parse_status
        self.window.dashboard.set_connected(True, "DEMO")
        self.window.dashboard.set_sensor_count(7)
        for ch in range(1, 9):
            line = (
                f"CH {ch} FAN={28 + ch * 5}% RPM={760 + ch * 155} "
                f"TEMP={335 + ch * 23} MODE=auto SENSOR=ok TYPE=3 FAULT=0"
            )
            self.window.handle_line(line)
        self.window.dashboard.set_bridge_state(True, 128)
        self.window.dashboard.set_mqtt_state("ENABLED=1 CONNECTED=1")
        self.window.dashboard.update_pc_state("on BUSY=0")
        self.window.show()
        self.app.processEvents()
        output = Path("dist/ui-preview")
        output.mkdir(parents=True, exist_ok=True)
        for key in ("overview", "fans", "argb", "pc", "service", "logs"):
            self.window.dashboard.show_page(key)
            self.app.processEvents()
            target = output / f"{key}.png"
            self.assertTrue(self.window.grab().save(str(target), "PNG"))
            self.assertGreater(target.stat().st_size, 10_000)

    def test_navigation_and_existing_controls(self):
        shell = self.window.dashboard
        self.assertEqual(shell.stack.count(), 6)
        self.assertEqual(len(shell.fan_cards), 8)
        self.assertEqual(shell.page_index["overview"], shell.stack.currentIndex())
        shell.open_fan(6)
        self.assertEqual(self.window.current_fan, 6)
        self.assertEqual(shell.page_index["fans"], shell.stack.currentIndex())
        self.assertEqual(self.window.fan_box.currentIndex(), 5)
        shell.show_page("service")
        service = shell.stack.widget(shell.page_index["service"]).widget()
        self.assertTrue(service.isAncestorOf(self.window.cal_progress))
        self.assertTrue(service.isAncestorOf(self.window.sensor_table))
        shell.show_page("logs")
        logs = shell.stack.widget(shell.page_index["logs"]).widget()
        self.assertTrue(logs.isAncestorOf(self.window.log_text))

    def test_telemetry_updates_overview_and_pc_gates(self):
        self.window.handle_line(
            "CH 3 FAN=55% RPM=1200 TEMP=430 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        )
        card = self.window.dashboard.fan_cards[3]
        self.assertEqual(card["rpm"].text(), "1200 RPM")
        self.assertIn("55% PWM", card["metrics"].text())
        self.assertIn("43.0", card["metrics"].text())
        self.window.dashboard.set_connected(True, "COM7")
        self.window.handle_line("PC off BUSY=0")
        self.assertTrue(self.window.dashboard.pc_buttons["on"].isEnabled())
        self.assertFalse(self.window.dashboard.pc_buttons["off"].isEnabled())
        self.window.handle_line("PC on BUSY=1")
        self.assertFalse(self.window.dashboard.pc_buttons["force"].isEnabled())
        self.window.handle_line("PC on BUSY=0")
        self.assertTrue(self.window.dashboard.pc_buttons["force"].isEnabled())
        self.window.dashboard.set_connected(False)
        self.assertFalse(self.window.dashboard.pc_buttons["on"].isEnabled())
        self.assertFalse(self.window.dashboard.pc_buttons["force"].isEnabled())


if __name__ == "__main__":
    unittest.main()

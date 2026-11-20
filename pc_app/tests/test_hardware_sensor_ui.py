"""Offscreen Qt tests for the ESP32-S3 hardware temperature diagnostics."""
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAS_QT = False
else:
    HAS_QT = True


@unittest.skipUnless(HAS_QT, "GUI dependencies not yet installed")
class HardwareSensorPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        self.addCleanup(sys.path.pop, 0)
        from hardware_sensor_ui import HardwareSensorPanel

        self.sent: list[str] = []
        self.panel = HardwareSensorPanel(SimpleNamespace(send=self._send))
        self.addCleanup(self.panel.close)
        self.panel.show()

    def _send(self, command: str) -> bool:
        self.sent.append(command)
        return True

    def _open_source_dialog(self):
        from hardware_sensor_ui import FanTemperatureSourceDialog

        dialog = FanTemperatureSourceDialog(self.panel, self.panel)
        self.addCleanup(dialog.close)
        self.panel.handle_status("HTEMP ENABLED=1 VALID=0")
        dialog.open_for_channel(4)
        self.assertEqual(self.sent[-2:], ["HTMODE? 4", "HTMAP? 4"])
        self.assertFalse(dialog.save_mode.isEnabled())
        return dialog

    def test_late_replies_keep_unsaved_fan_source_and_rom(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        rom = "2800010203040506"
        for late_reply in ("HTLIST", "HTMODE", "HTMAP"):
            with self.subTest(late_reply=late_reply):
                dialog = self._open_source_dialog()
                self.panel.handle_sensor_line(f"1 ROM={rom} VALID=0")
                self.panel.handle_sensor_line("HTSENSOR_END COUNT=1")
                dialog.handle_mode("4 LOCAL")
                dialog.handle_map("4 ROM=AUTO")
                QTest.keyClick(dialog.mode, Qt.Key.Key_Down)
                QTest.keyClick(dialog.probe_box, Qt.Key.Key_Down)
                self.assertEqual(dialog.mode.currentData(), "BACKUP")
                self.assertEqual(dialog.probe_box.currentData(), rom)
                self.sent.clear()

                if late_reply == "HTLIST":
                    self.panel.handle_sensor_line("HTSENSOR_END COUNT=0")
                    self.assertIn("датчик відсутній", dialog.probe_box.currentText())
                    self.assertEqual(dialog.probe_box.currentData(), rom)
                    self.panel.handle_sensor_line(f"1 ROM={rom} VALID=1 TEMP=365")
                    self.panel.handle_sensor_line("HTSENSOR_END COUNT=1")
                    self.assertIn("36.5 °C", dialog.probe_box.currentText())
                elif late_reply == "HTMODE":
                    dialog.handle_mode("4 BACKUP")
                    dialog.handle_mode("4 PC")
                else:
                    dialog.handle_map(f"4 ROM={rom}")
                    dialog.handle_map("4 ROM=AUTO")

                self.assertEqual(dialog.mode.currentData(), "BACKUP")
                self.assertEqual(dialog.probe_box.currentData(), rom)
                self.assertTrue(dialog.save_map.isEnabled())
                self.assertEqual(self.sent, [])
                dialog.close()

                dialog.open_for_channel(7)
                self.assertIsNone(dialog.mode.currentData())
                self.assertIsNone(dialog.probe_box.currentData())
                dialog.handle_mode("4 BACKUP")
                dialog.handle_map(f"4 ROM={rom}")
                self.assertFalse(dialog.save_mode.isEnabled())
                dialog.handle_map("7 ROM=AUTO")
                dialog.handle_mode("7 PC")
                self.assertEqual(dialog.mode.currentData(), "PC")
                self.assertEqual(dialog.probe_box.currentData(), "AUTO")
                dialog.close()

    def test_only_matching_readback_releases_the_saved_fan_field(self):
        from unittest.mock import patch
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QMessageBox

        rom = "2800010203040506"
        dialog = self._open_source_dialog()
        self.panel.handle_sensor_line(f"1 ROM={rom} VALID=0")
        self.panel.handle_sensor_line("HTSENSOR_END COUNT=1")
        dialog.handle_mode("4 LOCAL")
        dialog.handle_map("4 ROM=AUTO")
        QTest.keyClick(dialog.mode, Qt.Key.Key_Down)
        QTest.keyClick(dialog.probe_box, Qt.Key.Key_Down)
        self.sent.clear()

        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            dialog.save_mode.click()
        self.assertEqual(self.sent, ["HTMODE 4 BACKUP", "HTMODE? 4"])
        dialog.handle_mode("4 LOCAL")
        self.assertEqual(dialog.mode.currentData(), "BACKUP")
        dialog.handle_mode("4 BACKUP")
        dialog.handle_mode("4 LOCAL")
        self.assertEqual(dialog.mode.currentData(), "LOCAL")
        dialog.handle_map("4 ROM=AUTO")
        self.assertEqual(dialog.probe_box.currentData(), rom)

        self.sent.clear()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.save_map.click()
        self.assertEqual(self.sent, [f"HTMAP 4 {rom}", "HTMAP? 4"])
        dialog.handle_map("4 ROM=AUTO")
        self.assertEqual(dialog.probe_box.currentData(), rom)
        dialog.handle_map(f"4 ROM={rom}")
        dialog.handle_map("4 ROM=AUTO")
        self.assertEqual(dialog.probe_box.currentData(), "AUTO")

    def test_discovery_requires_confirmed_support_not_a_valid_reading(self):
        from PySide6.QtWidgets import QPushButton

        query = next(button for button in self.panel.findChildren(QPushButton)
                     if button.text() == "Перевірити датчик")
        scan = self.panel.rescan
        self.assertIn("Не опитано", self.panel.status.text())
        self.assertFalse(scan.isVisible())
        self.assertTrue(query.isVisible())
        query.click()
        self.assertEqual(self.sent, ["HTEMP?", "HTLIST?"])

        self.panel.handle_status("HTEMP ENABLED=0 VALID=0")
        self.assertIn("вимкнено у прошивці", self.panel.status.text())
        self.assertFalse(scan.isVisible())
        self.assertTrue(query.isVisible())

        self.panel.handle_status("HTEMP ENABLED=1 VALID=0")
        self.assertIn("показання недійсні", self.panel.status.text())
        self.assertTrue(scan.isVisible())
        self.sent.clear()
        scan.click()
        self.assertEqual(self.sent, ["HTSCAN", "HTEMP?", "HTLIST?"])
        self.panel.handle_status("HTEMP ENABLED=1 VALID=1 TEMP=365 AGE_MS=4")
        self.assertIn("36.5", self.panel.status.text())

    def test_readings_update_on_complete_discovery_and_clear_on_disconnect(self):
        self.panel.handle_status("HTEMP ENABLED=1 VALID=0")
        rom = "2800010203040506"
        self.panel.handle_sensor_line(f"1 ROM={rom} VALID=1 TEMP=365")
        self.assertFalse(self.panel.readings.isVisible())
        self.panel.handle_sensor_line("HTSENSOR_END COUNT=1")
        self.assertIn(rom, self.panel.readings.text())
        self.assertIn("36.5 °C", self.panel.readings.text())
        self.assertTrue(self.panel.readings.isVisible())

        self.panel.handle_sensor_line("HTSENSOR_END COUNT=0")
        self.assertFalse(self.panel.readings.isVisible())
        self.panel.handle_sensor_line(f"1 ROM={rom} VALID=0")
        self.panel.handle_sensor_line("HTSENSOR_END COUNT=1")
        self.panel.reset_status()
        self.assertIn("Не опитано", self.panel.status.text())
        self.assertFalse(self.panel.rescan.isVisible())
        self.assertFalse(self.panel.readings.isVisible())
        self.assertEqual(self.sent, [])
        self.panel.handle_status("HTEMP ENABLED=1 VALID=0")
        self.assertFalse(self.panel.readings.isVisible())
        self.assertFalse(self.panel.probes)

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
    from PySide6.QtWidgets import QApplication, QPushButton
    import pyqtgraph  # noqa: F401
    import serial  # noqa: F401
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "GUI dependencies not yet installed")
class DashboardSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QFont, QFontDatabase
        # CI Windows offscreen occasionally runs without its system font cache:
        # register a real installed UI font so preview labels render as glyphs.
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "arial.ttf", "tahoma.ttf"):
            path = font_dir / filename
            if path.is_file():
                family_id = QFontDatabase.addApplicationFont(str(path))
                if family_id >= 0:
                    fonts = QFontDatabase.applicationFontFamilies(family_id)
                    if fonts:
                        cls.app.setFont(QFont(fonts[0], 10))
                        break
        else:
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
            font.setPointSize(10)
            cls.app.setFont(font)

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

    def test_n16r8_board_capability_disables_second_channel_in_view(self):
        shell = self.window.dashboard
        shell.set_connected(True, "COM7")
        self.window.handle_line("FW VERSION=8 SERIAL=7 N16R8=1 CHMASK=253 DC_READY=1")
        self.assertEqual(shell.available_channel_mask, 253)
        self.assertFalse(shell.is_channel_available(2))
        self.assertTrue(shell.is_channel_available(1))
        self.assertIn("7/8", shell.channel_availability.text())
        self.assertFalse(self.window.fan_box.model().item(1).isEnabled())
        self.assertFalse(shell.zone_box.model().item(1).isEnabled())
        shell.set_connected(False)
        self.assertTrue(self.window.fan_box.model().item(1).isEnabled())

    def test_one_fan_quick_presets_only_write_selected_channel(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        from protocol import make_curve_command, DEFAULT_CURVE
        shell = self.window.dashboard
        shell.set_connected(True, "COM5")
        shell.set_channel_mask(253)
        self.assertFalse(shell.fan_preset_buttons[2]["Maximum"].isEnabled())
        self.assertTrue(shell.fan_preset_buttons[3]["Silent"].isEnabled())
        self.window.port = object()
        with patch.object(self.window, "send", return_value=True) as send:
            with patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.StandardButton.No
            ):
                shell.fan_preset_buttons[3]["Default"].click()
            send.assert_not_called()
            with patch.object(
                QMessageBox, "question",
                return_value=QMessageBox.StandardButton.Yes
            ):
                shell.fan_preset_buttons[3]["Default"].click()
            send.assert_any_call(make_curve_command(3, list(DEFAULT_CURVE)))
            send.assert_any_call("AUTO 3")
            self.assertEqual(send.call_count, 2)
        self.window.port = None
        shell.set_connected(False)
        self.assertFalse(shell.fan_preset_buttons[3]["Silent"].isEnabled())

    def test_fan_rotor_responds_to_rpm_and_stops_on_expiration(self):
        shell = self.window.dashboard
        shell.set_connected(True, "COM5")
        shell.set_channel_mask(253)
        self.window.handle_line(
            "CH 1 FAN=55% RPM=1250 TEMP=440 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        )
        rotor = shell.fan_cards[1]["rotor"]
        self.assertEqual(rotor.rpm, 1250)
        rotor.advance(.05)
        self.assertGreater(rotor.angle, 0)
        shell._last_fan_update[1] -= 30
        shell.refresh_telemetry_freshness()
        self.assertEqual(rotor.rpm, 0)
        self.window.handle_line(
            "CH 1 FAN=55% RPM=2000 TEMP=440 MODE=auto SENSOR=ok TYPE=3 FAULT=0 RPM_OK=0"
        )
        self.assertEqual(rotor.rpm, 0)
        shell.set_connected(False)
        self.assertEqual(rotor.rpm, 0)

    def test_overview_status_and_four_metrics_are_one_row(self):
        shell = self.window.dashboard
        self.assertEqual(len(shell._summary_cards), 5)
        self.assertIs(shell._summary_cards[0], shell.system_banner)
        self.assertEqual(shell._summary_grid_columns, 5)
        self.assertTrue(shell.show_sources.isHidden())
        self.assertTrue(shell.attention_filter.isHidden())
        self.assertFalse(any(
            button.text() == "Усі канали"
            for button in shell.stack.widget(shell.page_index["overview"]).findChildren(QPushButton)
        ))
        for width in (1080, 1510):
            self.window.resize(width, 850)
            self.window.show()
            self.app.processEvents()
            for index in range(5):
                self.assertEqual(shell._summary_grid.itemAtPosition(0, index).widget(),
                                 shell._summary_cards[index])
            rows = {w.y() for w in shell._summary_cards}
            self.assertEqual(len(rows), 1)

    def test_argb_reduced_to_three_visible_tabs_no_mode_dropdown(self):
        shell = self.window.dashboard
        names = [shell.argb_workspace_tabs.tabText(i) for i in range(3)]
        self.assertEqual(names, ["Кольори", "Автоефекти", "OpenRGB"])
        self.assertFalse(shell.argb_workspace_tabs.tabBar().isHidden())
        self.assertFalse(hasattr(shell, "argb_mode_selector"))
        self.assertEqual(set(shell.argb_auto_sections),
                         {"native", "temperature", "sensors", "audio"})
        self.assertFalse(shell.argb_auto_sections["audio"].isChecked())
        self.window.show()
        shell.show_page("argb")
        shell.argb_workspace_tabs.setCurrentIndex(1)
        self.app.processEvents()
        shell.argb_auto_sections["audio"].setChecked(True)
        self.app.processEvents()
        self.assertTrue(shell.audio_reactive.isVisible())
        shell.argb_auto_sections["audio"].setChecked(False)
        self.app.processEvents()
        self.assertFalse(shell.audio_reactive.isVisible())
        shell.argb_workspace_tabs.setCurrentIndex(0)
        self.app.processEvents()
        shell.argb_studio_toggle.setChecked(True)
        self.app.processEvents()
        self.assertTrue(shell.studio.isVisible())
        shell.argb_studio_toggle.setChecked(False)
        self.app.processEvents()
        self.assertFalse(shell.studio.isVisible())

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
        self.window.statusBar().showMessage(
            "DEMO · тестові дані інтерфейсу · реальний контролер не підключено"
        )
        self.window.handle_line(
            "FW VERSION=8 SERIAL=7 N16R8=1 CHMASK=253 "
            "DC_READY=1 DS18B20=0 SENSORS=0"
        )
        self.window.handle_line(
            "WIFI_CONFIG ENABLED=1 CONNECTED=1 SSID_HEX=4D792057694669 "
            "PASSWORD_SET=1 IP=192.168.1.10"
        )
        self.window.handle_line(
            "MQTT_CONFIG ENABLED=1 CONNECTED=1 HOST_HEX=6D7174742E6C6F63616C "
            "PORT=1883 USER_HEX=- AUTH=0 DISCOVERY=1 TEMP_ALLOW=0 "
            "STORAGE_OK=1 TOPIC=esp32fan/demo"
        )
        self.window.handle_line("STRIPCFG CH=1 LEDS=30 REVERSE=0 BRIGHT=64")
        self.window.handle_line("ARGBSTATUS LIMIT_MA=2000 REQUESTED_MA=320")
        self.window.handle_line("CONFIG 1 TYPE=3 PPR=2 CRIT=90 STALL=0")
        self.window.show()
        self.app.processEvents()
        output = Path("dist/ui-preview")
        output.mkdir(parents=True, exist_ok=True)
        for key in ("overview", "fans", "sensors", "argb", "pc", "esp32", "service", "logs"):
            self.window.dashboard.show_page(key)
            self.app.processEvents()
            target = output / f"{key}.png"
            self.assertTrue(self.window.grab().save(str(target), "PNG"))
            self.assertGreater(target.stat().st_size, 10_000)
        panel = self.window.dashboard.device_settings
        self.window.dashboard.show_page("esp32")
        for tab_key in ("wifi", "mqtt", "argb", "fan"):
            self.assertTrue(panel.select_tab(tab_key))
            self.app.processEvents()
            target = output / f"esp32-{tab_key}.png"
            self.assertTrue(self.window.grab().save(str(target), "PNG"))
            self.assertGreater(target.stat().st_size, 10_000)
        for width, height in ((1080, 760), (1510, 930)):
            self.window.resize(width, height)
            self.app.processEvents()
            for key in ("overview", "fans", "argb", "service"):
                self.window.dashboard.show_page(key)
                self.app.processEvents()
                file = output / f"{key}-{width}.png"
                self.assertTrue(self.window.grab().save(str(file), "PNG"))
                self.assertGreater(file.stat().st_size, 10_000)
        self.window.resize(1510, 930)

    def test_workspaces_are_focused_and_responsive(self):
        shell = self.window.dashboard
        self.assertEqual(shell.fan_workspace_tabs.count(), 3)
        self.assertEqual(shell.sensor_workspace_tabs.count(), 3)
        self.assertEqual(shell.argb_workspace_tabs.count(), 3)
        self.assertEqual(shell.service_workspace_tabs.count(), 5)
        self.window.show()
        for width in (1080, 1510):
            self.window.resize(width, 850)
            self.app.processEvents()
            shell.show_page("overview")
            self.app.processEvents()
            self.assertIn(shell._fan_grid_columns, (2, 3, 4))
            card_widths = {frame.width() for frame in shell._fan_frames.values()}
            self.assertLessEqual(max(card_widths) - min(card_widths), 3)
            summary_widths = {card.width() for card in shell._summary_cards}
            self.assertLessEqual(max(summary_widths) - min(summary_widths), 3)
            if width == 1080:
                self.assertEqual(shell._fan_grid_columns, 3)
                self.assertEqual(shell._summary_grid_columns, 5)
            else:
                self.assertEqual(shell._fan_grid_columns, 4)
                self.assertEqual(shell._summary_grid_columns, 5)
            for key in ("overview", "fans", "sensors", "argb", "esp32", "service"):
                shell.show_page(key)
                self.app.processEvents()
                scroll = shell.stack.widget(shell.page_index[key])
                self.assertLessEqual(
                    scroll.widget().width(), scroll.viewport().width() + 3,
                    f"Horizontal clipping in {key} at {width}px",
                )

    def test_v3_fan_editor_has_balanced_curve_and_live_side_panel(self):
        shell = self.window.dashboard
        self.window.show()
        for width in (1080, 1510):
            self.window.resize(width, 850)
            shell.show_page("fans")
            self.app.processEvents()
            self.assertTrue(shell.fan_control_panel.isAncestorOf(self.window.save_button))
            self.assertTrue(shell.fan_control_panel.isAncestorOf(self.window.pid_checkbox))
            self.assertGreater(self.window.curve_plot.width(), 190)
            self.assertGreaterEqual(shell.fan_control_panel.width(), 270)
            self.assertLessEqual(shell.fan_control_panel.width(), 360)
            chart_parent = self.window.curve_plot.parentWidget()
            self.assertIsNotNone(chart_parent)

        self.window.dashboard.set_connected(True, "COM5")
        self.window.handle_line(
            "CH 4 FAN=62% RPM=1870 TEMP=482 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        )
        shell.open_fan(4)
        self.assertEqual(shell.fan_live_title.text(), "FAN 04")
        self.assertIn("1 870 RPM", shell.fan_live_rpm.text())
        self.assertIn("62%", shell.fan_live_metrics.text())
        self.window.handle_line(
            "CH 4 FAN=100% RPM=0 TEMP=482 MODE=auto SENSOR=stale TYPE=3 FAULT=1"
        )
        self.assertEqual(shell.fan_live_state.property("role"), "negative")
        shell.set_connected(False)
        self.assertIn("Немає", shell.fan_live_state.text())

    def test_gpio_esp_nvs_save_requires_readback_and_reboot(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        panel = self.window.dashboard.device_settings.gpio_dialog
        sent = []
        self.window.send = lambda command: sent.append(command) or True
        self.window.dashboard.set_connected(True, "COM9")
        panel.set_supported(True)
        self.assertEqual(sent[-1], "GPIO?")
        factory = {
            "PWM": "21 35 39 42 6 16 10 14",
            "TACH": "47 36 40 2 5 15 9 13",
            "ARGB": "48 37 41 1 4 7 46 12",
        }
        for kind, pins in factory.items():
            self.window.handle_line(f"GPIO {kind} {pins}")
        self.window.handle_line("GPIO_END REBOOT=0")
        self.assertTrue(panel._loaded)
        self.assertFalse(panel.reboot_required)
        target = panel.controls[("PWM", 1)]
        target.setCurrentIndex(target.findData(18))
        self.assertTrue(panel._dirty)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            panel.save()
        self.assertEqual(sent[-1], "GPIO BEGIN")
        self.window.handle_line("OK GPIO_BEGIN")
        self.assertEqual(sent[-1], "GPIO PWM 1 18")
        self.window.handle_line("OK GPIO_PIN")
        self.assertEqual(sent[-1], "GPIO COMMIT")
        self.window.handle_line("OK GPIO_SAVED REBOOT_REQUIRED")
        self.assertEqual(sent[-1], "GPIO?")
        self.window.handle_line("GPIO PWM 18 35 39 42 6 16 10 14")
        self.window.handle_line("GPIO TACH " + factory["TACH"])
        self.window.handle_line("GPIO ARGB " + factory["ARGB"])
        self.window.handle_line("GPIO_END REBOOT=1")
        self.assertFalse(panel._dirty)
        self.assertTrue(panel.reboot_required)
        self.assertIn("Перезавантаж", panel.status.text())
        self.assertEqual(panel._saved["PWM"][0], 18)

    def test_github_update_panel_does_not_auto_flash(self):
        from github_updates import APP_VERSION
        shell = self.window.dashboard
        panel = shell.maintenance_panel.github_updates
        self.assertIn("GitHub", panel.title())
        self.assertIn(APP_VERSION, panel.status.text())
        self.assertFalse(panel.windows_button.isEnabled())
        self.assertFalse(panel.firmware_button.isEnabled())
        self.assertFalse(panel.page_button.isEnabled())
        self.assertFalse(shell.maintenance_panel.firmware_path)

    def test_safe_pid_autotune_requires_verified_esp_reply(self):
        from main import time
        from protocol import parse_status
        from PySide6.QtWidgets import QMessageBox
        from unittest.mock import patch

        from unittest.mock import Mock
        self.window.pid_tune_supported = True
        self.window.port = Mock()
        sent = []
        self.window.send = lambda command: sent.append(command) or True
        self.window.dashboard.set_connected(True, "COM7")
        dialog = self.window.pid_tune_dialog = __import__(
            "pid_autotune_ui").PidAutotuneDialog(self.window, self.window)
        dialog.show_for_channel(1)
        self.assertEqual(sent[-1], "PIDGAINS? 1")
        self.window.handle_line("PIDGAINS CH=1 KP=30 KI=3 KD=4")
        self.assertEqual(dialog.current, (30, 3, 4))

        start = time.time() - 45
        series = [
            (0, 40, 1000, 45), (5, 40, 1000, 45),
            (10, 40, 1010, 45), (15, 40, 1005, 45),
            (20, 60, 1080, 45), (25, 60, 1230, 45),
            (30, 60, 1450, 45), (35, 60, 1600, 45),
            (40, 60, 1602, 45), (45, 60, 1598, 45),
        ]
        self.window.history[1].extend(
            (start + t, pwm, rpm, temp) for t, pwm, rpm, temp in series
        )
        self.window.fan_status[1] = parse_status(
            "CH 1 FAN=60% RPM=1600 TEMP=450 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        )
        dialog.analyze()
        self.assertIsNotNone(dialog.recommendation)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dialog.apply()
        self.assertTrue(sent[-1].startswith("PIDGAINS 1 "))
        self.window.handle_line("OK PIDGAINS_SAVED")
        self.assertEqual(sent[-1], "PIDGAINS? 1")
        kp, ki, kd = dialog.recommendation.gains
        self.window.handle_line(f"PIDGAINS CH=1 KP={kp} KI={ki} KD={kd}")
        self.assertEqual(dialog.current, (kp, ki, kd))
        self.assertIn("підтвердив", dialog.status.text())
        dialog.hide()

    def test_predictive_cooling_nvs_readback(self):
        panel = self.window.dashboard.device_settings.assist_dialog
        sent = []
        self.window.send = lambda msg: sent.append(msg) or True
        self.window.dashboard.set_connected(True, "COM5")
        panel.set_supported(True)
        self.assertEqual(sent[-1], "ASSIST?")
        line = ("ASSIST ENABLE=0 CPU_START=65 CPU_FULL=160 GPU_START=100 "
                "GPU_FULL=300 BOOST=15 BIAS=5 MAP=0:3,0:3,0:3,0:3,0:3,0:3,0:3,0:3")
        self.window.handle_line(line)
        self.assertIsNotNone(panel._saved)
        self.assertFalse(panel._busy)
        self.assertEqual(panel._saved.roles, (0,) * 8)
        panel.enabled.setChecked(True)
        panel.roles[0].setCurrentIndex(1)
        from PySide6.QtWidgets import QMessageBox
        from unittest.mock import patch
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            panel.save()
        self.assertTrue(sent[-1].startswith("ASSIST SET 1"))
        self.window.handle_line("OK ASSIST_SAVED")
        self.assertEqual(sent[-1], "ASSIST?")
        self.window.handle_line(line.replace("ENABLE=0", "ENABLE=1").
                                replace("MAP=0:3", "MAP=1:3", 1))
        self.assertFalse(panel._busy)
        self.assertEqual(panel._saved.roles[0], 1)
        self.assertTrue(panel._saved.enabled)

    def test_temperature_argb_esp_readback_save_and_reload(self):
        shell = self.window.dashboard
        panel = shell.temperature_argb
        sent = []
        self.window.send = lambda command: sent.append(command) or True
        shell.set_connected(True, "COM9")
        panel.set_version(8)
        self.assertEqual(sent[-1], "TARGB? 1")
        self.window.handle_line(
            "TARGB CH=1 SOURCE_HEX=6E77696E666F2F6370752F706B67 "
            "LOW=30 HIGH=85 BRIGHT=64 COUNT=0"
        )
        self.window.handle_line("TARGB_END CH=1")
        self.assertEqual(panel.configs[1].source, "nwinfo/cpu/pkg")
        self.assertEqual(sent[-1], "TARGB? 2")
        # Simulate completing the eight independent readback transactions.
        for ch in range(2, 9):
            self.window.handle_line(
                f"TARGB CH={ch} SOURCE_HEX=5F5F4F46465F5F "
                "LOW=30 HIGH=85 BRIGHT=64 COUNT=0"
            )
            self.window.handle_line(f"TARGB_END CH={ch}")
        self.assertTrue(panel.save_buttons[1].isEnabled() is False)
        panel.lows[1].setValue(35)
        self.assertIn(1, panel._dirty)
        panel.save_zone(1)
        self.assertEqual(sent[-1], "TARGB BEGIN 1")
        self.window.handle_line("OK TARGB_BEGIN")
        self.assertTrue(sent[-1].startswith("TARGB SOURCE "))
        self.window.handle_line("OK TARGB_SOURCE")
        self.assertEqual(sent[-1], "TARGB RANGE 35 85 64")
        self.window.handle_line("OK TARGB_RANGE")
        self.assertEqual(sent[-1], "TARGB COMMIT")
        self.window.handle_line("OK TARGB_SAVED")
        self.assertEqual(sent[-1], "TARGB? 1")
        self.window.handle_line(
            "TARGB CH=1 SOURCE_HEX=6E77696E666F2F6370752F706B67 "
            "LOW=35 HIGH=85 BRIGHT=64 COUNT=0"
        )
        self.window.handle_line("TARGB_END CH=1")
        self.assertIn("підтвердив", panel.status.text())
        self.assertEqual(panel.configs[1].low_c, 35)
        self.assertNotIn(1, panel._dirty)

    def test_v3_argb_zone_map_is_read_only_until_apply(self):
        shell = self.window.dashboard
        self.assertEqual(len(shell.argb_zone_tiles), 8)
        self.assertEqual(shell.argb_workspace_tabs.count(), 3)
        self.assertTrue(shell.argb_zone_tiles[1][0].property("selected"))
        shell.zone_box.setCurrentIndex(4)
        self.assertFalse(shell.argb_zone_tiles[1][0].property("selected"))
        self.assertTrue(shell.argb_zone_tiles[5][0].property("selected"))
        self.assertEqual(self.window.fan_box.currentIndex(), 4)
        shell.sync_zone(7)
        self.assertTrue(shell.argb_zone_tiles[8][0].property("selected"))
        shell.argb_workspace_tabs.setCurrentIndex(2)
        self.assertTrue(shell.native_checkbox.isVisible() or
                        not shell.isVisible())  # stored OpenRGB control still exists

    def test_v3_esp32_footer_and_responsive_help(self):
        shell = self.window.dashboard
        panel = shell.device_settings
        self.assertEqual(panel.action_stack.count(), 4)
        for tab_name, button in (
            ("wifi", panel.wifi_save), ("mqtt", panel.mqtt_save),
            ("argb", panel.rgb_save), ("fan", panel.fan_save),
        ):
            self.assertTrue(panel.select_tab(tab_name))
            self.assertTrue(panel.action_stack.currentWidget().isAncestorOf(button))
        self.window.show()
        shell.show_page("esp32")
        self.window.resize(1510, 930)
        self.app.processEvents()
        self.assertFalse(shell._esp_help_card.isHidden())
        self.window.resize(1080, 760)
        self.app.processEvents()
        self.assertTrue(shell._esp_help_card.isHidden())
        self.assertTrue(panel.action_footer.isAncestorOf(panel.fan_save))

    def test_quick_navigation_and_search_palette(self):
        shell = self.window.dashboard
        self.assertEqual(len(shell._shortcuts), 10)
        palette = shell.create_command_palette()
        palette.search.setText("Вентилятор 6")
        self.assertGreater(palette.results.count(), 0)
        palette.activate_selection()
        self.assertEqual(shell.stack.currentIndex(), shell.page_index["fans"])
        self.assertEqual(self.window.current_fan, 6)

        palette = shell.create_command_palette()
        palette.search.setText("Home Assistant")
        self.assertEqual(palette.results.count(), 1)
        palette.activate_selection()
        self.assertEqual(shell.stack.currentIndex(), shell.page_index["esp32"])
        self.assertEqual(shell.device_settings.tabs.currentIndex(), 1)

        palette = shell.create_command_palette()
        palette.search.setText("невідомий розділ")
        self.assertEqual(palette.results.count(), 0)
        palette.close()

    def test_expired_fan_status_is_not_shown_as_live_rpm(self):
        shell = self.window.dashboard
        shell.set_connected(True, "COM7")
        normal = "CH 1 FAN=55% RPM=1250 TEMP=440 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        self.window.handle_line(normal)
        self.assertIn("RPM", shell.fan_cards[1]["rpm"].text())
        shell._last_fan_update[1] -= 20.0
        shell.refresh_telemetry_freshness()
        self.assertEqual(shell.fan_cards[1]["rpm"].text(), "— RPM")
        self.assertIn("застарів", shell.fan_cards[1]["state"].text())
        self.assertIn("застаріла", shell.health_title.text())
        shell._toggle_attention_filter(True)
        self.assertIn(1, shell._fan_grid_visible)
        self.window.handle_line(normal)
        self.assertIn("1 250 RPM", shell.fan_cards[1]["rpm"].text())
        self.assertNotIn("застарів", shell.fan_cards[1]["state"].text())

    def test_overview_safety_hierarchy_and_detail_visibility(self):
        shell = self.window.dashboard
        self.assertIn("не підключено", shell.health_title.text().lower())
        shell.set_connected(True, "COM7")
        self.assertIn("Читаємо", shell.health_title.text())
        self.window.handle_line(
            "CH 1 FAN=100% RPM=1200 TEMP=450 MODE=auto SENSOR=stale TYPE=3 FAULT=0"
        )
        self.assertIn("Захисне", shell.health_title.text())
        self.assertEqual(shell.system_banner.property("state"), "warning")
        self.window.handle_line(
            "CH 1 FAN=55% RPM=1200 TEMP=450 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        )
        self.assertIn("Перевіряємо канали", shell.health_title.text())
        for channel in range(2, 9):
            self.window.handle_line(
                f"CH {channel} FAN=55% RPM=1200 TEMP=450 "
                "MODE=auto SENSOR=ok TYPE=3 FAULT=0"
            )
        self.assertIn("працює", shell.health_title.text())
        self.window.handle_line(
            "CH 1 FAN=100% RPM=1200 TEMP=980 MODE=auto SENSOR=ok TYPE=3 FAULT=1"
        )
        self.assertEqual(shell.system_banner.property("state"), "critical")
        self.assertIn("Потрібна увага", shell.health_title.text())
        shell.show_sources.setChecked(False)
        self.assertTrue(shell.fan_cards[1]["source"].isHidden())
        shell.show_sources.setChecked(True)
        self.assertFalse(shell.fan_cards[1]["source"].isHidden())
        shell.show_sources.setChecked(False)
        shell.set_connected(False)
        self.assertEqual(shell.system_banner.property("state"), "idle")

    def test_esp32_tabs_preserve_safe_readback_and_password_masking(self):
        panel = self.window.dashboard.device_settings
        self.assertEqual(panel.tabs.count(), 4)
        self.assertFalse(panel.tabs.tabBar().drawBase())
        self.assertTrue(panel.select_tab("mqtt"))
        self.assertFalse(panel.select_tab("unsupported"))
        self.assertFalse(panel.mqtt_host.isEnabled())
        panel.set_connected(True)
        panel.set_version(8, 7)
        self.window.handle_line(
            "WIFI_CONFIG ENABLED=0 CONNECTED=0 SSID_HEX=- PASSWORD_SET=0 IP=-"
        )
        self.assertTrue(panel.wifi_ssid.isEnabled())
        self.assertFalse(panel.mqtt_host.isEnabled())
        self.window.handle_line(
            "MQTT_CONFIG ENABLED=0 CONNECTED=0 HOST_HEX=- PORT=1883 "
            "USER_HEX=- AUTH=0 DISCOVERY=1 TEMP_ALLOW=0 TOPIC=esp32fan/demo"
        )
        self.assertTrue(panel.mqtt_host.isEnabled())
        self.assertIn("зчитано", panel.result.text())
        panel.mqtt_reveal.setChecked(True)
        from PySide6.QtWidgets import QLineEdit
        self.assertEqual(panel.mqtt_password.echoMode(), QLineEdit.EchoMode.Normal)
        panel.mqtt_reveal.setChecked(False)
        self.assertEqual(panel.mqtt_password.echoMode(), QLineEdit.EchoMode.Password)
        panel.mqtt_host.textEdited.emit("new.local")
        self.assertIn("•", panel.tabs.tabText(1))
        panel.set_connected(False)
        self.assertNotIn("•", panel.tabs.tabText(1))
        self.assertFalse(panel.mqtt_host.isEnabled())
        self.assertEqual(panel.mqtt_host.text(), "")

    def test_esp32_config_readback_and_acknowledged_save(self):
        panel = self.window.dashboard.device_settings
        sent = []
        self.window.send = lambda command: sent.append(command) or True
        panel.set_connected(True)
        panel.set_version(8)
        self.assertIn("WIFI CONFIG?", sent)
        self.assertIn("MQTT CONFIG?", sent)
        self.window.handle_line("WIFI_CONFIG ENABLED=0 CONNECTED=0 SSID_HEX=- PASSWORD_SET=0 IP=-")
        self.window.handle_line(
            "MQTT_CONFIG ENABLED=0 CONNECTED=0 HOST_HEX=- PORT=1883 "
            "USER_HEX=- AUTH=0 DISCOVERY=1 TOPIC=esp32fan/demo"
        )
        self.assertTrue(panel.wifi_save.isEnabled())
        self.assertTrue(panel.mqtt_save.isEnabled())
        self.assertEqual(panel.mqtt_host.text(), "")

        panel.wifi_ssid.setText("My home 5G")
        panel.wifi_password.setText("my strong password")
        panel.save_wifi()
        self.assertTrue(sent[-1].startswith("WIFI SETHEX "))
        self.assertNotIn("my strong password", sent[-1])
        self.assertEqual(panel.wifi_password.text(), "")
        self.assertFalse(panel.mqtt_save.isEnabled())  # busy, awaiting ESP ack
        self.window.handle_line("OK WIFI_SET")
        self.assertEqual(sent[-1], "WIFI CONFIG?")
        from device_config_protocol import encode_value
        self.window.handle_line(
            "WIFI_CONFIG ENABLED=1 CONNECTED=0 SSID_HEX="
            + encode_value("My home 5G", 32) + " PASSWORD_SET=1 IP=-"
        )
        self.assertIn("підтвердив", panel.result.text())
        self.assertTrue(panel.mqtt_save.isEnabled())

        panel.mqtt_host.setText("broker.local")
        panel.mqtt_user.setText("home assistant")
        panel.mqtt_password.setText("secret with spaces")
        panel.mqtt_enabled.setChecked(True)
        panel.save_mqtt()
        self.assertTrue(sent[-1].startswith("MQTT BROKER "))
        self.window.handle_line("OK MQTT_SAVED")
        self.assertTrue(sent[-1].startswith("MQTT AUTHHEX "))
        self.assertNotIn("secret with spaces", sent[-1])
        self.window.handle_line("OK MQTT_SAVED")
        self.assertEqual(sent[-1], "MQTT ON")
        self.window.handle_line("OK MQTT_SAVED")
        self.assertEqual(sent[-1], "MQTT CONFIG?")
        self.window.handle_line(
            "MQTT_CONFIG ENABLED=1 CONNECTED=0 HOST_HEX="
            + encode_value("broker.local", 63) + " PORT=1883 USER_HEX="
            + encode_value("home assistant", 31)
            + " AUTH=1 DISCOVERY=1 TOPIC=esp32fan/demo"
        )
        self.assertIn("підтвердив", panel.result.text())
        self.assertEqual(panel.mqtt_password.text(), "")

    def test_v7_atomic_mqtt_uses_one_commit_and_verified_readback(self):
        panel = self.window.dashboard.device_settings
        sent = []
        self.window.send = lambda command: sent.append(command) or True
        panel.set_connected(True)
        panel.set_version(8, 7)
        self.window.handle_line("WIFI_CONFIG ENABLED=0 CONNECTED=0 SSID_HEX=- PASSWORD_SET=0 IP=-")
        self.window.handle_line(
            "MQTT_CONFIG ENABLED=0 CONNECTED=0 HOST_HEX=- PORT=1883 "
            "USER_HEX=- AUTH=0 DISCOVERY=1 TEMP_ALLOW=0 STORAGE_OK=1 TOPIC=esp32fan/demo"
        )
        panel.mqtt_host.setText("broker.local")
        panel.mqtt_enabled.setChecked(True)
        panel.mqtt_temperature.setChecked(True)
        panel.save_mqtt()
        self.assertEqual(sent[-1], "MQTT TX START")
        self.window.handle_line("OK MQTT_TX")
        self.assertEqual(sent[-1], "MQTT TX BROKER broker.local 1883")
        self.window.handle_line("OK MQTT_TX")
        self.assertEqual(sent[-1], "MQTT TX FLAGS 1 1 1")
        self.window.handle_line("OK MQTT_TX")
        self.assertEqual(sent[-1], "MQTT TX COMMIT")
        self.window.handle_line("OK MQTT_TX")
        self.assertEqual(sent[-1], "MQTT CONFIG?")
        from device_config_protocol import encode_value
        self.window.handle_line(
            "MQTT_CONFIG ENABLED=1 CONNECTED=0 HOST_HEX="
            + encode_value("broker.local", 63)
            + " PORT=1883 USER_HEX=- AUTH=0 DISCOVERY=1 TEMP_ALLOW=1 "
              "STORAGE_OK=1 TOPIC=esp32fan/demo"
        )
        self.assertIn("підтвердив", panel.result.text())
        self.assertTrue(panel.mqtt_save.isEnabled())
        # Repeating identical settings must not begin a new NVS transaction.
        sent.clear()
        panel.save_mqtt()
        self.assertNotIn("MQTT TX START", sent)

    def test_unresponsive_usb_port_is_closed_for_identity_based_recovery(self):
        from time import monotonic

        class SilentPort:
            closed = False
            def close(self):
                self.closed = True

        port = SilentPort()
        self.window.port = port
        self.window._reconnect_armed = True
        self.window.heartbeat.ping(monotonic() - 25)
        self.window.refresh_aux_status()
        self.assertIsNone(self.window.port)
        self.assertTrue(port.closed)
        self.assertTrue(self.window._reconnect_armed)
        self.assertFalse(self.window.heartbeat.expired(monotonic()))

    def test_old_firmware_disables_unavailable_configuration(self):
        panel = self.window.dashboard.device_settings
        panel.set_connected(True)
        panel.set_version(7)
        self.assertFalse(panel.wifi_save.isEnabled())
        self.assertFalse(panel.mqtt_save.isEnabled())
        self.assertIn("v8+", panel.header.text())

    def test_navigation_and_existing_controls(self):
        shell = self.window.dashboard
        self.assertEqual(shell.stack.count(), 8)
        self.assertEqual(len(shell.fan_cards), 8)
        self.assertEqual(shell.page_index["overview"], shell.stack.currentIndex())
        shell.open_fan(6)
        self.assertEqual(self.window.current_fan, 6)
        self.assertEqual(shell.page_index["fans"], shell.stack.currentIndex())
        self.assertEqual(self.window.fan_box.currentIndex(), 5)
        shell.show_page("service")
        service = shell.stack.widget(shell.page_index["service"]).widget()
        self.assertTrue(service.isAncestorOf(self.window.cal_progress))
        shell.show_page("sensors")
        sensors = shell.stack.widget(shell.page_index["sensors"]).widget()
        self.assertTrue(sensors.isAncestorOf(self.window.sensor_table))
        self.assertTrue(sensors.isAncestorOf(self.window.metric_table))
        self.assertEqual(shell.stack.currentIndex(), shell.page_index["sensors"])
        shell.show_page("logs")
        logs = shell.stack.widget(shell.page_index["logs"]).widget()
        self.assertTrue(logs.isAncestorOf(self.window.log_text))

    def test_nwinfo_local_sensors_reach_gui_and_fan_choices(self):
        from concurrent.futures import Future
        from nwinfo_sensors import parse_nwinfo_temperatures
        from monitor import MAX_ALL
        report = {"Sensors": {
            "CPU": {"Intel Core": {"Package Temperature": 54}},
            "GPU": {"AMD Radeon": {"Temperature": 66}},
            "SMART": {"SSD": {"Temperature": 38}},
        }}
        completed = Future()
        completed.set_result(parse_nwinfo_temperatures(report))
        self.window.temperature_future = completed
        self.window.apply_temperature_result()
        self.assertEqual(self.window.sensor_table.rowCount(), 3)
        self.assertIn("3 температур", self.window.sensor_status.text())
        self.assertEqual(self.window.source_boxes[0].currentData(), MAX_ALL)
        names = [
            self.window.source_boxes[0].itemText(i)
            for i in range(self.window.source_boxes[0].count())
        ]
        self.assertTrue(any("Intel Core" in x for x in names))
        self.assertTrue(any("AMD Radeon" in x for x in names))

    def test_additional_metrics_are_display_only_and_searchable(self):
        from concurrent.futures import Future
        from monitor import TemperatureSensor
        from nwinfo_sensors import HardwareMetric
        metric = HardwareMetric(
            "nwinfo/gpu/radeon/fan%20speed",
            "GPU / Radeon / Fan Speed", 1450, "RPM", "fan",
        )
        sampler = self.window.sensor_sampler
        sampler._initialized = True
        sampler._last_poll_at = 100.0
        sampler._metric_latest = {"GPU": (100.0, [metric])}
        future = Future()
        future.set_result([
            TemperatureSensor("nwinfo/gpu/radeon/temperature", "GPU / Radeon / Temperature", 61.4),
        ])
        self.window.temperature_future = future
        self.window.apply_temperature_result()
        self.assertEqual(self.window.sensor_table.rowCount(), 1)
        self.assertEqual(self.window.metric_table.rowCount(), 1)
        self.assertEqual(self.window.metric_table.item(0, 2).text(), "RPM")
        self.assertIn("1 інших", self.window.dashboard.summary_temp.text())
        source_labels = [
            self.window.source_boxes[0].itemText(i)
            for i in range(self.window.source_boxes[0].count())
        ]
        self.assertTrue(any("Temperature" in item for item in source_labels))
        self.assertFalse(any("Fan Speed" in item for item in source_labels))
        self.window.sensor_search.setText("Fan Speed")
        self.assertTrue(self.window.sensor_table.isRowHidden(0))
        self.assertFalse(self.window.metric_table.isRowHidden(0))
        self.window.sensor_search.clear()
        self.assertFalse(self.window.sensor_table.isRowHidden(0))

    def test_nwinfo_timeout_does_not_discard_valid_gpu_telemetry(self):
        from concurrent.futures import Future
        from monitor import TemperatureSensor
        self.window.sensor_sampler.problems["CPU"] = "тайм-аут 7 с"
        result = Future()
        result.set_result([
            TemperatureSensor("nwinfo/gpu/amd/temperature", "GPU / AMD / Temperature", 65.4)
        ])
        self.window.temperature_future = result
        self.window.apply_temperature_result()
        self.assertEqual(self.window.sensor_table.rowCount(), 1)
        self.assertIn("частково", self.window.sensor_status.text())
        self.assertIn("CPU", self.window.sensor_status.toolTip())

    def test_v6_hardware_sensor_diagnostics_and_maintenance_panels(self):
        shell = self.window.dashboard
        self.assertIsNotNone(shell.hardware_sensor)
        self.assertIsNotNone(shell.settings_panel)
        self.assertIsNotNone(shell.maintenance_panel)
        self.assertIsNotNone(shell.diagnostics)
        self.assertIsNotNone(shell.sensor_manager)
        self.assertIsNotNone(shell.studio)
        self.assertIn("power", self.window.history_plots)
        self.window.handle_line("HTEMP ENABLED=1 VALID=1 TEMP=365 AGE_MS=4")
        self.assertIn("36.5", shell.hardware_sensor.status.text())
        self.window.handle_line("HTMODE 1 BACKUP")
        self.assertEqual(shell.hardware_sensor.current_modes[1], "BACKUP")
        self.window.handle_line("FW VERSION=6 SERIAL=4 DC_READY=0 DS18B20=1")
        self.assertIn("v6", shell.firmware_status.text())
        self.window.handle_line(
            "HEALTH 1 TYPE=3 DETECTED=255 PWM=100 RPM=900 "
            "TACH=seen TACH_VALID=1 SENSOR=ok FAULT=0 DC_READY=0 MODE=auto"
        )
        self.assertIn("заблоковано", shell.diagnostics.table.item(0, 7).text())

    def test_manual_curve_edits_disable_automatic_profiles(self):
        box = self.window.dashboard.settings_panel.auto_profiles
        box.blockSignals(True)
        box.setChecked(True)
        box.blockSignals(False)
        self.window._disable_auto_for_manual_change()
        self.assertFalse(box.isChecked())
        self.assertEqual(
            str(self.window.settings.value("autoProfiles", "")).lower(),
            "false",
        )

    def test_short_serial_write_is_not_reported_as_success(self):
        class ShortSerial:
            def __init__(self):
                self.closed = False
            def write(self, data):
                return len(data) - 1
            def close(self):
                self.closed = True
        port = ShortSerial()
        from serial_tx import SerialTransmitter
        self.window.port = port
        self.window.tx = SerialTransmitter(port)
        self.assertFalse(self.window.send("PING"))
        self.assertTrue(port.closed)
        self.assertIsNone(self.window.port)

    def test_telemetry_updates_overview_and_pc_gates(self):
        self.window.handle_line(
            "CH 3 FAN=55% RPM=1200 TEMP=430 MODE=auto SENSOR=ok TYPE=3 FAULT=0"
        )
        card = self.window.dashboard.fan_cards[3]
        self.assertEqual(card["rpm"].text(), "1 200 RPM")
        self.assertIn("PWM  55%", card["metrics"].text())
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

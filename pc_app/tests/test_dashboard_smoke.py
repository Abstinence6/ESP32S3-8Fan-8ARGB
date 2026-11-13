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
        self.window.handle_line("FW VERSION=8 SERIAL=7 DC_READY=0 DS18B20=0 SENSORS=0")
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
                self.assertEqual(shell._fan_grid_columns, 2)
                self.assertEqual(shell._summary_grid_columns, 2)
            else:
                self.assertEqual(shell._fan_grid_columns, 4)
                self.assertEqual(shell._summary_grid_columns, 4)
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
        shell.argb_workspace_tabs.setCurrentIndex(1)
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
        self.assertEqual(len(shell._shortcuts), 9)
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

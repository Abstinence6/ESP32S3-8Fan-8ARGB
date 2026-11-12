"""Windows desktop companion: ESP32 calibration, fan curves and PC temperatures.

Run: python pc_app/main.py (from repository root or from pc_app).
Requires a running LibreHardwareMonitor Remote Web Server on localhost:8085.
"""
from __future__ import annotations

import json
import csv
from collections import deque
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional

import pyqtgraph as pg
import serial
from serial.tools import list_ports
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QColorDialog, QCheckBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QFileDialog,
    QHeaderView, QAbstractItemView,
)

from monitor import (
    DEFAULT_LHM_URL, GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED, MAX_ALL,
    TemperatureSensor, fetch_temperatures, resolve_temperature,
)
from sacn_bridge import E131Listener, SACN_PORT, SERIAL_BAUD, encode_rgb_frame
from protocol import validate_curve, DEFAULT_CURVE, make_curve_command, make_temperature_command, parse_curve, parse_status
from serial_owner import SerialProxyClient
from profiles import PRESETS
from config_presets import (RGB_SCENES, FAN_CURVES, commands as preset_commands,
                            create_configuration, from_json as parse_configuration,
                            to_json as serialize_configuration, openrgb_e131_manifest)
from ui_dashboard_model import make_scene_commands
from ui_dashboard import DashboardShell


class FanArgbWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FanARGB · ESP32-S3")
        self.resize(1510, 930)
        self.setMinimumSize(1080, 700)
        self.settings = QSettings("FanARGB", "FanARGBControl")
        self._last_lhm_issue: str | None = None
        self.port: Optional[serial.Serial | SerialProxyClient] = None
        self.read_buffer = ""
        self.temperatures: list[TemperatureSensor] = []
        self.curves = {ch: list(DEFAULT_CURVE) for ch in range(1, 9)}
        self.secondary_curves = {ch: list(DEFAULT_CURVE) for ch in range(1, 9)}
        self.config_types: dict[int, int] = {}
        self.fan_pid_enabled = {ch: False for ch in range(1, 9)}
        self.fan_dual_enabled = {ch: False for ch in range(1, 9)}
        self.history: dict[int, deque] = {ch: deque(maxlen=3600) for ch in range(1, 9)}
        self.cal_points: dict[int, dict[int, int]] = {ch: {} for ch in range(1, 9)}
        self.current_fan = 1
        self.target_items: list[pg.TargetItem] = []
        self.updating_targets = False
        self.fan_status: dict[int, object] = {}
        self.source_boxes: list[QComboBox] = []
        self.sensor_groups: dict[int, list[str]] = {}
        self.sensor_weights: dict[int, dict[str, float]] = {}
        for ch in range(1, 9):
            try:
                raw_weights = json.loads(str(self.settings.value(f"groupWeights{ch}", "{}")))
                self.sensor_weights[ch] = {str(k): float(v) for k,v in raw_weights.items()} if isinstance(raw_weights, dict) else {}
            except (ValueError, TypeError):
                self.sensor_weights[ch] = {}
            try:
                value = json.loads(str(self.settings.value(f"groupSensors{ch}", "[]")))
                self.sensor_groups[ch] = list(dict.fromkeys(
                    item for item in value if isinstance(item, str)
                )) if isinstance(value, list) else []
            except (ValueError, TypeError):
                self.sensor_groups[ch] = []
        self.led_counts: list[int] | None = None  # do not stream until ESP confirms sizes
        self.temperature_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="LHM")
        self.temperature_future: Future | None = None
        self.sacn = E131Listener()
        self.sacn_pending: dict[int, bytes] = {}
        self.sacn_last_sent = 0.0
        self.sacn_forwarded = 0
        self._build_ui()
        self.refresh_ports()
        self._update_targets()

        self.serial_timer = QTimer(self)
        self.serial_timer.timeout.connect(self.poll_serial)
        self.serial_timer.start(80)
        self.temperature_timer = QTimer(self)
        self.temperature_timer.timeout.connect(self.refresh_temperatures)
        self.temperature_timer.start(2000)
        self.temperature_result_timer = QTimer(self)
        self.temperature_result_timer.timeout.connect(self.apply_temperature_result)
        self.temperature_result_timer.start(100)
        self.sacn_timer = QTimer(self)
        self.sacn_timer.timeout.connect(self.poll_sacn)
        self.sacn_timer.start(20)
        self.refresh_temperatures()
        self.aux_status_timer = QTimer(self)
        self.aux_status_timer.timeout.connect(self.refresh_aux_status)
        self.aux_status_timer.start(5000)
        if str(self.settings.value("sacnEnabled", "false")).lower() in ("true", "1"):
            self.bridge_checkbox.setChecked(True)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        connect_row = QHBoxLayout()
        connect_row.addWidget(QLabel("COM порт:"))
        self.port_box = QComboBox()
        self.port_box.setMinimumWidth(160)
        connect_row.addWidget(self.port_box)
        refresh_ports = QPushButton("↻ Порти")
        refresh_ports.clicked.connect(self.refresh_ports)
        connect_row.addWidget(refresh_ports)
        self.connect_button = QPushButton("Підключити")
        self.connect_button.clicked.connect(self.toggle_serial)
        connect_row.addWidget(self.connect_button)
        connect_row.addSpacing(18)
        connect_row.addWidget(QLabel("Libre Hardware Monitor:"))
        self.lhm_url = QLineEdit(self.settings.value("lhmUrl", DEFAULT_LHM_URL))
        self.lhm_url.setMinimumWidth(260)
        connect_row.addWidget(self.lhm_url)
        self.lhm_status = QLabel("Датчики: пошук…")
        connect_row.addWidget(self.lhm_status)
        connect_row.addStretch(1)
        layout.addLayout(connect_row)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        splitter.addWidget(left)
        table_box = QGroupBox("Вентилятори та джерела температури")
        table_layout = QVBoxLayout(table_box)
        self.fan_table = QTableWidget(8, 6)
        self.fan_table.setHorizontalHeaderLabels(["№", "PWM", "RPM", "Темп. °C", "Режим", "Датчик для кривої"])
        self.fan_table.verticalHeader().setVisible(False)
        self.fan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.fan_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.fan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fan_table.setMaximumHeight(335)
        for ch in range(1, 9):
            row = ch - 1
            for col, value in enumerate([str(ch), "100%", "—", "—", "авто · без датчика"]):
                self.fan_table.setItem(row, col, QTableWidgetItem(value))
            box = QComboBox()
            box.addItem("MAX усіх температур", MAX_ALL)
            box.addItem("AVG вибраної групи", GROUP_AVG)
            box.addItem("MAX вибраної групи", GROUP_MAX)
            box.addItem("Зважене AVG групи", GROUP_WEIGHTED)
            desired = str(self.settings.value(f"source{ch}", MAX_ALL))
            known = [MAX_ALL, GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED]
            if desired in known:
                box.setCurrentIndex(known.index(desired))
            else:
                box.addItem(f"Недоступний: {desired}", desired)
                box.setCurrentIndex(3)
            box.currentIndexChanged.connect(lambda _=0, number=ch: self.source_changed(number))
            self.fan_table.setCellWidget(row, 5, box)
            self.source_boxes.append(box)
        self.fan_table.itemSelectionChanged.connect(self.fan_row_selected)
        table_layout.addWidget(self.fan_table)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Профіль:"))
        self.profile_box = QComboBox()
        self.profile_box.addItems(["Silent", "Balanced", "Performance", "Custom"])
        profile_row.addWidget(self.profile_box)
        apply_profile = QPushButton("Застосувати до 8 вентиляторів")
        apply_profile.clicked.connect(self.apply_profile)
        profile_row.addWidget(apply_profile)
        save_custom = QPushButton("Зберегти Custom")
        save_custom.clicked.connect(self.save_custom_profile)
        profile_row.addWidget(save_custom)
        table_layout.addLayout(profile_row)
        controls = QHBoxLayout()
        override_button = QPushButton("PWM вручну…")
        override_button.clicked.connect(self.manual_override)
        controls.addWidget(override_button)
        auto_button = QPushButton("Авто для вибраного")
        auto_button.clicked.connect(lambda: self.send(f"AUTO {self.current_fan}"))
        controls.addWidget(auto_button)
        all_auto = QPushButton("Всі → Авто")
        all_auto.clicked.connect(lambda: self.send("ALLAUTO"))
        controls.addWidget(all_auto)
        table_layout.addLayout(controls)
        group_row = QHBoxLayout()
        group_edit = QPushButton("☑ Вибрати датчики групи для вентилятора…")
        group_edit.clicked.connect(self.edit_sensor_group)
        group_row.addWidget(group_edit)
        group_row.addWidget(QLabel("Режим AVG/MAX вибирається в таблиці вище"))
        table_layout.addLayout(group_row)
        left_layout.addWidget(table_box)

        sensors_box = QGroupBox("Усі доступні температурні датчики ПК")
        sensors_layout = QVBoxLayout(sensors_box)
        self.sensor_table = QTableWidget(0, 3)
        self.sensor_table.setHorizontalHeaderLabels(["Датчик / обладнання", "°C", "SensorId"])
        self.sensor_table.verticalHeader().setVisible(False)
        self.sensor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.sensor_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.sensor_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        sensors_layout.addWidget(self.sensor_table)
        left_layout.addWidget(sensors_box, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)
        splitter.setSizes([740, 740])
        choose_row = QHBoxLayout()
        choose_row.addWidget(QLabel("Редагувати криву вентилятора:"))
        self.fan_box = QComboBox()
        for ch in range(1, 9):
            self.fan_box.addItem(f"Вентилятор {ch}", ch)
        self.fan_box.currentIndexChanged.connect(self.fan_combo_selected)
        choose_row.addWidget(self.fan_box)
        choose_row.addWidget(QLabel("Тип:"))
        self.type_box = QComboBox()
        for name, wire in (("2-pin / ключ", 2), ("3-pin / ключ+TACH", 3)):
            self.type_box.addItem(name, wire)
        self.type_box.setCurrentIndex(1)
        choose_row.addWidget(self.type_box)
        type_button = QPushButton("Встановити тип")
        type_button.clicked.connect(self.apply_fan_type)
        choose_row.addWidget(type_button)
        choose_row.addStretch(1)
        right_layout.addLayout(choose_row)

        curve_box = QGroupBox("PWM від температури — перетягни 5 точок мишкою")
        curve_layout = QVBoxLayout(curve_box)
        self.curve_plot = pg.PlotWidget()
        self.curve_plot.setBackground("#151b24")
        self.curve_plot.setLabel("left", "PWM", units="%")
        self.curve_plot.setLabel("bottom", "Температура", units="°C")
        self.curve_plot.showGrid(x=True, y=True, alpha=0.3)
        self.curve_plot.setXRange(0, 100, padding=0)
        self.curve_plot.setYRange(0, 100, padding=0)
        self.curve_plot.setLimits(xMin=0, xMax=125, yMin=0, yMax=100)
        self.curve_line = self.curve_plot.plot([], [], pen=pg.mkPen("#4ed2e4", width=3))
        curve_layout.addWidget(self.curve_plot, 1)
        curve_actions = QHBoxLayout()
        self.save_button = QPushButton("Зберегти криву в ESP32 (NVS)")
        self.save_button.clicked.connect(self.save_curve)
        curve_actions.addWidget(self.save_button)
        reread_button = QPushButton("Прочитати з ESP")
        reread_button.clicked.connect(lambda: self.send(
            f"{'CURVE2?' if self.secondary_checkbox.isChecked() else 'CURVE?'} {self.current_fan}"))
        curve_actions.addWidget(reread_button)
        self.secondary_checkbox = QCheckBox("Крива 2")
        self.secondary_checkbox.toggled.connect(lambda _: self._update_targets())
        curve_actions.addWidget(self.secondary_checkbox)
        curve_layout.addLayout(curve_actions)
        regulation_actions = QHBoxLayout()
        self.pid_checkbox = QCheckBox("PID / підтримувати RPM")
        self.pid_checkbox.toggled.connect(self.toggle_pid)
        regulation_actions.addWidget(self.pid_checkbox)
        self.dual_checkbox = QCheckBox("Дві температурні криві")
        self.dual_checkbox.toggled.connect(self.toggle_dual)
        regulation_actions.addWidget(self.dual_checkbox)
        self.secondary_source_box = QComboBox()
        self.secondary_source_box.setMinimumWidth(160)
        self.secondary_source_box.currentIndexChanged.connect(self.secondary_source_changed)
        regulation_actions.addWidget(self.secondary_source_box)
        rpm_target_button = QPushButton("Цільові RPM…")
        rpm_target_button.clicked.connect(self.set_rpm_target)
        regulation_actions.addWidget(rpm_target_button)
        curve_layout.addLayout(regulation_actions)
        right_layout.addWidget(curve_box, 2)

        calibration_box = QGroupBox("Калібрування PWM → RPM (21 крок: 0–100%, по 5%)")
        calibration_layout = QVBoxLayout(calibration_box)
        cal_actions = QHBoxLayout()
        self.start_button = QPushButton("▶ Розумне калібрування")
        self.start_button.clicked.connect(self.start_calibration)
        cal_actions.addWidget(self.start_button)
        stop_button = QPushButton("■ Перервати")
        stop_button.clicked.connect(lambda: self.send("CAL CANCEL"))
        cal_actions.addWidget(stop_button)
        read_button = QPushButton("Завантажити RPM з ESP")
        read_button.clicked.connect(lambda: self.send(f"CAL GET {self.current_fan}"))
        cal_actions.addWidget(read_button)
        calibration_layout.addLayout(cal_actions)
        self.cal_progress = QProgressBar()
        self.cal_progress.setRange(0, 21)
        calibration_layout.addWidget(self.cal_progress)
        self.rpm_plot = pg.PlotWidget()
        self.rpm_plot.setBackground("#151b24")
        self.rpm_plot.setLabel("left", "RPM")
        self.rpm_plot.setLabel("bottom", "PWM", units="%")
        self.rpm_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rpm_curve = self.rpm_plot.plot([], [], pen=pg.mkPen("#86df93", width=2),
                                            symbol="o", symbolSize=7, symbolBrush="#86df93")
        calibration_layout.addWidget(self.rpm_plot, 1)
        right_layout.addWidget(calibration_box, 1)

        history_box = QGroupBox("Історія — PWM / RPM")
        history_layout = QVBoxLayout(history_box)
        self.history_plot = pg.PlotWidget()
        self.history_plot.setMaximumHeight(130)
        self.history_plot.setLabel("bottom", "Час", units="с")
        self.history_plot.showGrid(x=True, y=True, alpha=0.2)
        self.history_pwm_curve = self.history_plot.plot(pen=pg.mkPen("#6cbce5", width=2), name="PWM")
        history_layout.addWidget(self.history_plot)
        hist_row = QHBoxLayout()
        export_button = QPushButton("Зберегти історію CSV…")
        export_button.clicked.connect(self.export_history)
        hist_row.addWidget(export_button)
        hist_row.addStretch(1)
        history_layout.addLayout(hist_row)
        right_layout.addWidget(history_box)

        rgb_box = QGroupBox("ARGB · вибраний канал + OpenRGB / E1.31")
        rgb_layout = QVBoxLayout(rgb_box)
        rgb_actions = QHBoxLayout()
        color_button = QPushButton("Колір…")
        color_button.clicked.connect(self.pick_color)
        rgb_actions.addWidget(color_button)
        rainbow_button = QPushButton("Rainbow")
        rainbow_button.clicked.connect(lambda: self.send(f"RAINBOW {self.current_fan}"))
        rgb_actions.addWidget(rainbow_button)
        brightness_button = QPushButton("Яскравість…")
        brightness_button.clicked.connect(self.pick_brightness)
        rgb_actions.addWidget(brightness_button)
        off_button = QPushButton("Вимкнути ARGB")
        off_button.clicked.connect(lambda: self.send(f"OFF {self.current_fan}"))
        rgb_actions.addWidget(off_button)
        rgb_layout.addLayout(rgb_actions)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Конфігурація:"))
        self.config_cooling = QComboBox()
        self.config_cooling.addItems(FAN_CURVES.keys())
        self.config_cooling.setCurrentText("Balanced")
        preset_row.addWidget(self.config_cooling)
        self.config_lighting = QComboBox()
        self.config_lighting.addItems(RGB_SCENES.keys())
        preset_row.addWidget(self.config_lighting)
        apply_config = QPushButton("Застосувати")
        apply_config.clicked.connect(self.apply_configuration)
        preset_row.addWidget(apply_config)
        rgb_layout.addLayout(preset_row)
        config_files = QHBoxLayout()
        for label, handler in (
            ("Експорт конфігурації…", self.export_configuration),
            ("Імпорт конфігурації…", self.import_configuration),
            ("OpenRGB E1.31 налаштування…", self.export_openrgb_reference),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            config_files.addWidget(button)
        rgb_layout.addLayout(config_files)
        hardware_rgb = QHBoxLayout()
        strip_count_button = QPushButton("LED у каналі…")
        strip_count_button.clicked.connect(self.configure_led_count)
        hardware_rgb.addWidget(strip_count_button)
        reverse_button = QPushButton("Реверс стрічки…")
        reverse_button.clicked.connect(self.reverse_led_strip)
        hardware_rgb.addWidget(reverse_button)
        budget_button = QPushButton("Ліміт струму ARGB…")
        budget_button.clicked.connect(self.set_argb_budget)
        hardware_rgb.addWidget(budget_button)
        wifi_button = QPushButton("Wi-Fi / E1.31 / DDP…")
        wifi_button.clicked.connect(self.configure_wifi)
        hardware_rgb.addWidget(wifi_button)
        rgb_layout.addLayout(hardware_rgb)
        e131_row = QHBoxLayout()
        self.bridge_checkbox = QCheckBox("E1.31 → USB, 8 окремих зон")
        self.bridge_checkbox.toggled.connect(self.toggle_sacn)
        e131_row.addWidget(self.bridge_checkbox)
        self.bridge_status = QLabel("Вимкнено")
        e131_row.addWidget(self.bridge_status)
        rgb_layout.addLayout(e131_row)
        rgb_layout.addWidget(QLabel(
            "OpenRGB → Settings → E1.31 Devices: IP 127.0.0.1, Universe 1–8, "
            "DMX Start Channel 1, RGB, до 170 LED/зона"))
        pc_box = QGroupBox("Живлення ПК · PWR_SW (додаткове обладнання)")
        pc_layout = QHBoxLayout(pc_box)
        self.pc_power_status = QLabel("Стан ПК: невідомий")
        pc_layout.addWidget(self.pc_power_status)
        for label, command in (("Увімкнути ПК", "PC ON"), ("Вимкнути ПК", "PC OFF"),
                               ("Утримати Power 6 с", "PC FORCE")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, cmd=command: self.pc_power_action(cmd))
            pc_layout.addWidget(button)
        read_pc = QPushButton("Оновити стан")
        read_pc.clicked.connect(lambda: self.send("PC STATUS"))
        pc_layout.addWidget(read_pc)
        right_layout.addWidget(pc_box)
        right_layout.addWidget(rgb_box)

        log_box = QGroupBox("Serial / діагностика")
        log_layout = QVBoxLayout(log_box)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(180)
        log_layout.addWidget(self.log_text)
        raw_row = QHBoxLayout()
        self.raw_input = QLineEdit()
        self.raw_input.setPlaceholderText("Команда: STATUS, HELP, FAN 1 50…")
        self.raw_input.returnPressed.connect(self.send_raw)
        raw_row.addWidget(self.raw_input)
        send_button = QPushButton("Надіслати")
        send_button.clicked.connect(self.send_raw)
        raw_row.addWidget(send_button)
        log_layout.addLayout(raw_row)
        diagnostic_row = QHBoxLayout()
        health_button = QPushButton("Діагностика 8 вентиляторів")
        health_button.setToolTip("HEALTH: лише читає стан PWM/RPM/TACH; не змінює живлення")
        health_button.clicked.connect(lambda: self.send("HEALTH"))
        diagnostic_row.addWidget(health_button)
        faults_button = QPushButton("Журнал аварій")
        faults_button.clicked.connect(lambda: self.send("FAULTS"))
        diagnostic_row.addWidget(faults_button)
        test_button = QPushButton("Тест TACH (5 с)")
        test_button.setToolTip("Тільки спостерігає імпульси TACH, не змінює PWM чи живлення")
        test_button.clicked.connect(lambda: self.send("SELFTEST"))
        diagnostic_row.addWidget(test_button)
        mqtt_button = QPushButton("Налаштувати MQTT…")
        mqtt_button.clicked.connect(self.configure_mqtt)
        diagnostic_row.addWidget(mqtt_button)
        log_layout.addLayout(diagnostic_row)
        right_layout.addWidget(log_box)

        # Move the existing controls into focused pages. Widgets retain their
        # signals/slots: no firmware or serial behavior changes in the redesign.
        self.dashboard = DashboardShell(
            self,
            refresh_ports=refresh_ports,
            table_box=table_box,
            choose_row=choose_row,
            curve_box=curve_box,
            history_box=history_box,
            sensors_box=sensors_box,
            calibration_box=calibration_box,
            rgb_box=rgb_box,
            pc_box=pc_box,
            log_box=log_box,
            hardware_rgb=hardware_rgb,
            config_files=config_files,
            preset_row=preset_row,
            diagnostic_row=diagnostic_row,
            scenes=RGB_SCENES.keys(),
        )
        self.setCentralWidget(self.dashboard)
        self.dashboard.set_bridge_state(False)
        for ch, box in enumerate(self.source_boxes, start=1):
            self.dashboard.set_fan_source(ch, box.currentText())
        self.statusBar().showMessage(
            "ESP відключено · автоматичне охолодження переходить у fail-safe без телеметрії"
        )

    def refresh_ports(self) -> None:
        selected = self.port_box.currentData() or self.settings.value("port", "")
        self.port_box.clear()
        for port in list_ports.comports():
            self.port_box.addItem(f"{port.device} ({port.description})", port.device)
        for index in range(self.port_box.count()):
            if self.port_box.itemData(index) == selected:
                self.port_box.setCurrentIndex(index)
                break

    def toggle_serial(self) -> None:
        if self.port:
            self.disconnect()
            return
        port_name = self.port_box.currentData()
        if not port_name:
            QMessageBox.warning(self, "COM порт", "Підключи ESP32-S3 та вибери COM порт")
            return
        try:
            try:
                self.port = SerialProxyClient(port_name)
                using_agent = True
            except (OSError, ConnectionError):
                self.port = serial.Serial(port_name, SERIAL_BAUD, timeout=0, write_timeout=0.3)
                using_agent = False
            self.led_counts = None
            self.settings.setValue("port", port_name)
            self.connect_button.setText("Від'єднати")
            self.dashboard.set_connected(True, port_name)
            self.statusBar().showMessage(f"ESP: {port_name} підключено")
            self.log(f"Підключено до {port_name} ({'через фоновий агент' if using_agent else 'COM напряму'})")
            # Opening a serial port can reset an ESP board; wait for the boot message.
            QTimer.singleShot(2200, self.read_device_state)
        except (serial.SerialException, OSError) as exc:
            self.port = None
            QMessageBox.critical(self, "Serial", str(exc))

    def read_device_state(self) -> None:
        if not self.port:
            return
        self.send("PING")
        self.send("LEDS")
        self.send("STATUS")
        self.send("PC STATUS")
        self.send("MQTT?")
        for ch in range(1, 9):
            self.send(f"CURVE? {ch}")
            self.send(f"CURVE2? {ch}")
            self.send(f"TYPE? {ch}")
            self.send(f"CONFIG {ch}")

    def refresh_aux_status(self) -> None:
        if self.port:
            self.send("PC STATUS")
            self.send("MQTT?")

    def disconnect(self) -> None:
        if self.port:
            try:
                self.port.close()
            except OSError:
                pass
        self.port = None
        self.led_counts = None
        self.connect_button.setText("Підключити")
        self.dashboard.set_connected(False)
        self.statusBar().showMessage("ESP: відключено — автономний захист через 10 с без температур")
        self.log("ESP відключено")

    def send(self, message: str) -> bool:
        if not self.port:
            return False
        try:
            self.port.write((message + "\n").encode("ascii"))
            return True
        except (serial.SerialException, OSError) as exc:
            self.log(f"ПОМИЛКА Serial: {exc}")
            self.disconnect()
            return False

    def send_raw(self) -> None:
        raw = self.raw_input.text().strip()
        if raw and self.send(raw):
            self.log("> " + raw)
            self.raw_input.clear()

    def poll_serial(self) -> None:
        if not self.port:
            return
        try:
            chunk = self.port.read(self.port.in_waiting or 0)
        except (serial.SerialException, OSError) as exc:
            self.log(f"ПОМИЛКА: {exc}")
            self.disconnect()
            return
        if not chunk:
            return
        self.read_buffer += chunk.decode("utf-8", errors="replace")
        if len(self.read_buffer) > 4000:
            self.read_buffer = ""
            self.log("Переповнено буфер Serial")
        while "\n" in self.read_buffer:
            line, self.read_buffer = self.read_buffer.split("\n", 1)
            self.handle_line(line.strip())

    def handle_line(self, line: str) -> None:
        if not line:
            return
        status = parse_status(line)
        if status:
            self.fan_status[status.channel] = status
            self.dashboard.update_fan(status.channel, status)
            row = status.channel - 1
            self.fan_table.item(row, 1).setText(f"{status.pwm}%")
            self.fan_table.item(row, 2).setText(str(status.rpm) if status.rpm_feedback else "—")
            self.history[status.channel].append((time.time(), status.pwm, status.rpm,
                                                  status.deci_c / 10 if status.fresh else float("nan")))
            if status.channel == self.current_fan:
                self._refresh_history()
            self.fan_table.item(row, 3).setText(f"{status.deci_c / 10:.1f}" if status.fresh else "—")
            self.fan_table.item(row, 4).setText(
                f"{status.mode} · {'OK' if status.fresh else 'fail-safe'}"
                + (" · FAULT" if status.fault else "")
                + (f" · {status.detected_type}-pin" if status.detected_type in (2, 3) else "")
            )
            return
        if line.startswith("PC "):
            self.pc_power_status.setText("Стан ПК: " + line[3:])
            self.dashboard.update_pc_state(line[3:])
            return
        if line.startswith("MQTT ENABLED="):
            self.dashboard.set_mqtt_state(line[5:])
            return
        if line.startswith("TYPE ") or line.startswith("CONFIG "):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    channel = int(parts[1]); cfg = dict(part.split("=",1) for part in parts[2:] if "=" in part)
                    if "SET" in cfg:
                        self.config_types[channel] = int(cfg["SET"])
                    if "TYPE" in cfg:
                        self.config_types[channel] = int(cfg["TYPE"])
                    if "PID" in cfg: self.fan_pid_enabled[channel] = bool(int(cfg["PID"]))
                    if "DUAL" in cfg:
                        self.fan_dual_enabled[channel] = bool(int(cfg["DUAL"]))
                        self.settings.setValue(f"dualEnabled{channel}", self.fan_dual_enabled[channel])
                    if channel == self.current_fan: self._sync_mode_controls()
                except (KeyError, ValueError):
                    pass
            return
        if line.startswith("CURVE2 "):
            parsed = parse_curve(line.replace("CURVE2 ", "CURVE ", 1))
            if parsed:
                ch, pts = parsed
                self.secondary_curves[ch] = pts
                if ch == self.current_fan and self.secondary_checkbox.isChecked():
                    self._update_targets()
            return
        curve = parse_curve(line)
        if curve:
            ch, points = curve
            self.curves[ch] = points
            if ch == self.current_fan:
                self._update_targets()
            return
        tokens = line.split()
        if len(tokens) == 9 and tokens[0] == "LEDCOUNTS":
            try:
                counts = [int(item) for item in tokens[1:]]
            except ValueError:
                counts = []
            if len(counts) == 8 and all(1 <= number <= 170 for number in counts):
                self.led_counts = counts
                self.log("ARGB: " + ", ".join(f"{count} LED" for count in counts))
            return
        if len(tokens) == 4 and tokens[0] in ("CAL_POINT", "CAL_RESULT"):
            try:
                ch, pwm, rpm = map(int, tokens[1:])
            except ValueError:
                self.log(line)
                return
            if not (1 <= ch <= 8 and 0 <= pwm <= 100 and 0 <= rpm <= 65535):
                return
            self.cal_points[ch][pwm] = rpm
            if ch == self.current_fan:
                if tokens[0] == "CAL_POINT":
                    self.cal_progress.setValue(len(self.cal_points[ch]))
                self._update_rpm_plot()
            return
        if line.startswith("CAL_STARTED "):
            try:
                ch = int(tokens[1])
            except (IndexError, ValueError):
                return
            if 1 <= ch <= 8:
                self.cal_points[ch] = {}
                if ch == self.current_fan:
                    self.cal_progress.setValue(0)
                    self._update_rpm_plot()
        if line.startswith("CAL_SAVED "):
            self.log(line + " — збережено у flash ESP")
        elif line.startswith("CAL_ERROR "):
            self.log("КАЛІБРУВАННЯ НЕ ЗБЕРЕЖЕНО: " + line)
        elif not line.startswith("OK") or "SAVED" in line:
            self.log(line)

    def log(self, message: str) -> None:
        self.log_text.append(message)
        if self.log_text.document().blockCount() > 150:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()

    def refresh_temperatures(self) -> None:
        # Never block the Qt GUI thread while the sensor service responds or times out.
        url = self.lhm_url.text().strip()
        self.settings.setValue("lhmUrl", url)
        if self.temperature_future is None:
            self.temperature_future = self.temperature_executor.submit(fetch_temperatures, url, 0.8)

    def apply_temperature_result(self) -> None:
        future = self.temperature_future
        if future is None or not future.done():
            return
        self.temperature_future = None
        connected = False
        issue = None
        try:
            self.temperatures = future.result()
            connected = True
            if self.temperatures:
                self.lhm_status.setText(f"{len(self.temperatures)} температур")
                self.lhm_status.setStyleSheet("color: #70cda6")
                self.lhm_status.setToolTip("LHM: отримано температури з /data.json")
            else:
                issue = ("LHM відповідає, але температурних датчиків у /data.json немає. "
                         "Перевір, чи вони видимі у LibreHardwareMonitor.")
                self.lhm_status.setText("0 температур · перевір LHM")
                self.lhm_status.setStyleSheet("color: #edba6d")
                self.lhm_status.setToolTip(issue)
        except Exception as exc:
            self.temperatures = []
            issue = f"LHM недоступний: {type(exc).__name__}: {exc}"
            self.lhm_status.setText("LHM недоступний")
            self.lhm_status.setToolTip(issue + "\nУвімкни Options → Remote Web Server → Run")
            self.lhm_status.setStyleSheet("color: #f18b92")
        if issue != self._last_lhm_issue:
            if issue:
                self.log(issue)
            self._last_lhm_issue = issue
        self.dashboard.set_sensor_count(
            len(self.temperatures), available=connected
        )
        self._update_sensor_table()
        self._update_source_boxes()
        self._update_secondary_box()

        # All group sensors must be present; otherwise ESP's 10s stale watchdog
        # falls back to 100% PWM. Temperature traffic shares USB with RGB frames.
        for ch, box in enumerate(self.source_boxes, start=1):
            celsius = resolve_temperature(
                str(box.currentData()), self.temperatures, self.sensor_groups[ch], self.sensor_weights[ch]
            )
            if celsius is not None:
                try:
                    self.send(make_temperature_command(ch, celsius))
                except ValueError:
                    pass
            if self.fan_dual_enabled[ch]:
                second = str(self.settings.value(f"source2{ch}", MAX_ALL))
                celsius2 = resolve_temperature(second, self.temperatures, self.sensor_groups[ch], self.sensor_weights[ch])
                if celsius2 is not None:
                    try:
                        cmd = make_temperature_command(ch, celsius2).replace("TEMP ", "TEMP2 ", 1)
                        self.send(cmd)
                    except ValueError:
                        pass
        self.send("STATUS")

    def _update_sensor_table(self) -> None:
        self.sensor_table.setRowCount(len(self.temperatures))
        for row, sensor in enumerate(self.temperatures):
            for col, value in enumerate((sensor.name, f"{sensor.celsius:.1f}", sensor.sensor_id)):
                self.sensor_table.setItem(row, col, QTableWidgetItem(value))

    def _update_source_boxes(self) -> None:
        for ch, box in enumerate(self.source_boxes, start=1):
            saved_id = str(box.currentData() or self.settings.value(f"source{ch}", MAX_ALL))
            box.blockSignals(True)
            box.clear()
            box.addItem("MAX усіх температур", MAX_ALL)
            box.addItem(f"AVG групи ({len(self.sensor_groups[ch])})", GROUP_AVG)
            box.addItem(f"MAX групи ({len(self.sensor_groups[ch])})", GROUP_MAX)
            box.addItem(f"Зважене AVG групи ({len(self.sensor_groups[ch])})", GROUP_WEIGHTED)
            for sensor in self.temperatures:
                box.addItem(f"{sensor.name} ({sensor.celsius:.1f}°C)", sensor.sensor_id)
            ids = [box.itemData(i) for i in range(box.count())]
            if saved_id not in ids:
                box.addItem("Недоступний датчик: " + saved_id, saved_id)
            box.setCurrentIndex(next(i for i in range(box.count()) if box.itemData(i) == saved_id))
            box.blockSignals(False)
            self.dashboard.set_fan_source(ch, box.currentText())

    def source_changed(self, ch: int) -> None:
        box = self.source_boxes[ch - 1]
        self.settings.setValue(f"source{ch}", box.currentData())
        self.dashboard.set_fan_source(ch, box.currentText())

    def _update_secondary_box(self) -> None:
        if not hasattr(self, "secondary_source_box"):
            return
        ch = self.current_fan
        box = self.secondary_source_box
        desired = str(self.settings.value(f"source2{ch}", MAX_ALL))
        box.blockSignals(True)
        box.clear()
        box.addItem("MAX усіх", MAX_ALL)
        box.addItem("AVG групи", GROUP_AVG)
        box.addItem("MAX групи", GROUP_MAX)
        box.addItem("Зважене AVG", GROUP_WEIGHTED)
        for sensor in self.temperatures:
            box.addItem(sensor.name, sensor.sensor_id)
        idx = box.findData(desired)
        if idx == -1:
            box.addItem("Немає: " + desired, desired)
            idx = box.count() - 1
        box.setCurrentIndex(idx)
        box.blockSignals(False)

    def secondary_source_changed(self) -> None:
        if not hasattr(self, "secondary_source_box"):
            return
        self.settings.setValue(f"source2{self.current_fan}", self.secondary_source_box.currentData())

    def edit_sensor_group(self) -> None:
        ch = self.current_fan
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Датчики групи вентилятора {ch}")
        dialog.resize(650, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Обери датчики для AVG або MAX. Якщо хоч один недоступний, "
            "температура не надсилатиметься до ESP (fail-safe 100%)."
        ))
        lst = QListWidget(dialog)
        selected = set(self.sensor_groups[ch])
        for sensor in self.temperatures:
            item = QListWidgetItem(f"{sensor.name}   —   {sensor.celsius:.1f}°C", lst)
            item.setData(Qt.ItemDataRole.UserRole, sensor.sensor_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if sensor.sensor_id in selected
                               else Qt.CheckState.Unchecked)
        live_ids = {sensor.sensor_id for sensor in self.temperatures}
        for missing_id in sorted(selected - live_ids):
            item = QListWidgetItem(f"⚠ Недоступний: {missing_id}", lst)
            item.setData(Qt.ItemDataRole.UserRole, missing_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        layout.addWidget(lst)
        weight_row = QHBoxLayout()
        set_weight = QPushButton("Вага вибраного датчика…")
        def choose_weight():
            selected_item = lst.currentItem()
            if not selected_item:
                return
            identifier = str(selected_item.data(Qt.ItemDataRole.UserRole))
            old_weight = self.sensor_weights[ch].get(identifier, 1.0)
            value, ok = QInputDialog.getDouble(dialog, "Вага датчика", identifier,
                                               old_weight, 0.1, 100.0, 1)
            if ok:
                self.sensor_weights[ch][identifier] = value
                selected_item.setToolTip(f"Вага {value:g}")
        set_weight.clicked.connect(choose_weight)
        weight_row.addWidget(set_weight)
        weight_row.addWidget(QLabel("Лише для режиму Зважене AVG"))
        layout.addLayout(weight_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            group = [lst.item(i).data(Qt.ItemDataRole.UserRole)
                     for i in range(lst.count())
                     if lst.item(i).checkState() == Qt.CheckState.Checked]
            self.sensor_groups[ch] = group
            self.settings.setValue(f"groupSensors{ch}", json.dumps(group))
            self.settings.setValue(f"groupWeights{ch}", json.dumps(self.sensor_weights[ch]))
            if self.source_boxes[ch - 1].currentData() not in (GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED):
                self.source_boxes[ch - 1].setCurrentIndex(1)  # AVG group by default
            self._update_source_boxes()

    def fan_row_selected(self) -> None:
        row = self.fan_table.currentRow()
        if 0 <= row < 8 and row + 1 != self.current_fan:
            self.fan_box.setCurrentIndex(row)

    def fan_combo_selected(self, index: int) -> None:
        if not 0 <= index < 8:
            return
        self.current_fan = index + 1
        self.dashboard.sync_zone(index)
        self.fan_table.selectRow(index)
        self._update_targets()
        self._update_rpm_plot()
        self.cal_progress.setValue(len(self.cal_points[self.current_fan]))
        self._sync_mode_controls()
        self._refresh_history()
        self._update_secondary_box()

    def _active_curve(self) -> list[tuple[int, int]]:
        return self.secondary_curves[self.current_fan] if self.secondary_checkbox.isChecked() else self.curves[self.current_fan]

    def _sync_mode_controls(self) -> None:
        code = self.config_types.get(self.current_fan, 3)
        index = self.type_box.findData(code)
        if index >= 0:
            self.type_box.setCurrentIndex(index)
        for widget, state in ((self.pid_checkbox, self.fan_pid_enabled[self.current_fan]),
                              (self.dual_checkbox, self.fan_dual_enabled[self.current_fan])):
            widget.blockSignals(True)
            widget.setChecked(state)
            widget.blockSignals(False)

    def apply_fan_type(self) -> None:
        wire = int(self.type_box.currentData())
        confirm = QMessageBox.warning(
            self, "Перевір фізичну перемичку",
            "TYPE задає, чи доступний TACH (3-pin), або його немає (2-pin).\n"
            "Важливо: керування живленням дозволено лише після перевірки ключа.\n"
            "Підтверджуєш тип підключеного вентилятора?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes: return
        self.send(f"TYPE {self.current_fan} {wire}")
        self.send(f"TYPE? {self.current_fan}")
        self.send(f"CONFIG {self.current_fan}")

    def toggle_pid(self, enabled: bool) -> None:
        self.send(f"PID {self.current_fan} {1 if enabled else 0}")
        self.send(f"CONFIG {self.current_fan}")

    def toggle_dual(self, enabled: bool) -> None:
        self.send(f"DUAL {self.current_fan} {1 if enabled else 0}")
        self.send(f"CONFIG {self.current_fan}")

    def set_rpm_target(self) -> None:
        if self.config_types.get(self.current_fan, 3) == 2:
            QMessageBox.warning(self, "RPM", "2-pin не має TACH, тому RPM-регулювання неможливе")
            return
        rpm, ok = QInputDialog.getInt(self, "Підтримка RPM", "Цільові оберти:",
                                      1200, 0, 20000, 50)
        if ok: self.send(f"RPM {self.current_fan} {rpm}")

    def _refresh_history(self) -> None:
        hist = list(self.history[self.current_fan])
        if not hist: return
        origin = hist[0][0]
        self.history_pwm_curve.setData([ts-origin for ts, *_ in hist], [pwm for _,pwm,_,_ in hist])

    def export_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Експорт журналу", "fan_history.csv", "CSV (*.csv)")
        if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer=csv.writer(f)
            writer.writerow(["channel", "timestamp", "pwm_percent", "rpm", "temperature_c"])
            for ch, entries in self.history.items():
                for row in entries: writer.writerow((ch, *row))
        self.log(f"Історія збережена: {path}")

    def _update_targets(self) -> None:
        self.updating_targets = True
        for target in self.target_items:
            self.curve_plot.removeItem(target)
        self.target_items = []
        for index, (temp, pwm) in enumerate(self._active_curve()):
            target = pg.TargetItem(pos=(temp, pwm), size=16, symbol="o", movable=True,
                                   pen=pg.mkPen("#f2f6fa", width=2), brush=pg.mkBrush("#3abac8"))
            self.curve_plot.addItem(target)
            target.sigPositionChanged.connect(lambda *args, i=index: self.target_moved(i))
            self.target_items.append(target)
        self.updating_targets = False
        self._update_curve_line()

    def _update_curve_line(self) -> None:
        points = self._active_curve()
        self.curve_line.setData([t for t, _ in points], [p for _, p in points])

    def target_moved(self, index: int) -> None:
        if self.updating_targets or not self.target_items:
            return
        self.updating_targets = True
        points = list(self._active_curve())
        item = self.target_items[index]
        temp = int(round(item.pos().x()))
        pwm = int(round(item.pos().y()))
        left_t = 0 if index == 0 else points[index - 1][0] + 1
        right_t = 125 if index == 4 else points[index + 1][0] - 1
        left_p = 0 if index == 0 else points[index - 1][1]
        right_p = 100 if index == 4 else points[index + 1][1]
        temp = max(left_t, min(right_t, temp))
        pwm = max(left_p, min(right_p, pwm))
        item.setPos(temp, pwm)
        points[index] = (temp, pwm)
        if self.secondary_checkbox.isChecked():
            self.secondary_curves[self.current_fan] = points
        else:
            self.curves[self.current_fan] = points
        self._update_curve_line()
        self.updating_targets = False

    def save_curve(self) -> None:
        try:
            message = make_curve_command(self.current_fan, self._active_curve())
            if self.secondary_checkbox.isChecked(): message = message.replace("CURVE ", "CURVE2 ", 1)
        except ValueError as exc:
            QMessageBox.warning(self, "Крива PWM", str(exc))
            return
        if self.send(message):
            self.log(f"> {message.split()[0]} {self.current_fan} — запис у NVS запитано")
        else:
            QMessageBox.warning(self, "ESP", "Підключи ESP32 до збереження кривої")

    def save_custom_profile(self) -> None:
        data = [self.curves[ch] for ch in range(1,9)]
        self.settings.setValue("customCurves", json.dumps(data))
        self.log("Custom-профіль збережено на ПК")

    def apply_profile(self) -> None:
        name = self.profile_box.currentText()
        if name == "Custom":
            try:
                stored = json.loads(str(self.settings.value("customCurves", "[]")))
                curves = [[tuple(p) for p in fan] for fan in stored]
                if len(curves) != 8 or not all(validate_curve(c) for c in curves):
                    raise ValueError("Custom profile invalid")
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(self, "Custom", str(exc)); return
        else:
            curves = [list(PRESETS[name]) for _ in range(8)]
        if not self.port:
            QMessageBox.warning(self, "Профіль", "Підключи ESP32 перед застосуванням")
            return
        confirm = QMessageBox.question(self, "Профіль охолодження",
            f"Змінити всі 8 температурних кривих на {name} та записати в ESP32 NVS?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes: return
        for ch, points in enumerate(curves, start=1):
            if not self.send(make_curve_command(ch, points)):
                QMessageBox.warning(self, "Профіль", f"Не вдалося відправити Fan {ch}")
                return
            self.curves[ch] = points
        self._update_targets()
        self.log(f"Профіль {name}: відправлено 8 кривих на збереження в ESP")

    def apply_configuration(self, loaded: dict | None = None) -> None:
        if not self.port:
            QMessageBox.warning(self, "Конфігурація", "Підключи ESP32 перед застосуванням")
            return
        try:
            config = loaded if loaded is not None else create_configuration(
                self.config_cooling.currentText(), self.config_lighting.currentText())
            lines = preset_commands(config)
        except ValueError as exc:
            QMessageBox.warning(self, "Конфігурація", str(exc))
            return
        confirmed = QMessageBox.question(
            self, "Застосувати конфігурацію",
            "Замінити температурні криві восьми вентиляторів (запис у NVS) "
            "і застосувати режими ARGB? Тип вентиляторів та захист не змінюються.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        for line in lines:
            if not self.send(line):
                QMessageBox.warning(self, "Конфігурація",
                                    "З'єднання втрачено; конфігурацію застосовано частково")
                return
        for ch, curve in enumerate(config["fan_curves"], start=1):
            self.curves[ch] = [tuple(p) for p in curve]
        self._update_targets()
        self.log(f"Застосовано конфігурацію: {len(lines)} команд надіслано")
        if any(scene["mode"] == "external" for scene in config["argb"]):
            self.log("OpenRGB: очікування зовнішніх кадрів E1.31; увімкни міст або Wi-Fi")

    def export_configuration(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт конфігурації", "fan_argb_config.json", "JSON (*.json)")
        if not path:
            return
        try:
            data = create_configuration(self.config_cooling.currentText(),
                                        self.config_lighting.currentText())
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(serialize_configuration(data))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Експорт", str(exc))
            return
        self.log(f"Конфігурацію експортовано: {path}")

    def import_configuration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Імпорт конфігурації", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = parse_configuration(handle.read())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Імпорт", f"Невалідна конфігурація: {exc}")
            return
        self.apply_configuration(data)

    def export_openrgb_reference(self) -> None:
        if self.led_counts is None:
            QMessageBox.warning(self, "OpenRGB",
                                "Спочатку підключи ESP32 та дочекайся відповіді LEDCOUNTS")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Довідник E1.31 для OpenRGB",
            "openrgb_e131_reference.json", "JSON (*.json)")
        if not path:
            return
        ip = "127.0.0.1"
        if QMessageBox.question(
                self, "OpenRGB",
                "Використовувати пряме E1.31 через Wi-Fi замість USB-моста?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                ) == QMessageBox.StandardButton.Yes:
            ip, accepted = QInputDialog.getText(
                self, "ESP32 Wi-Fi IP", "IP-адреса ESP32 у локальній мережі:")
            if not accepted or not ip.strip():
                return
            import ipaddress
            try:
                ipaddress.IPv4Address(ip.strip())
            except ipaddress.AddressValueError:
                QMessageBox.warning(self, "OpenRGB", "Некоректна IPv4-адреса")
                return
            ip = ip.strip()
        try:
            reference = openrgb_e131_manifest(self.led_counts, ip)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(reference, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "OpenRGB", str(exc))
            return
        self.log(f"Довідник OpenRGB E1.31 збережено: {path} (налаштуй зони вручну)")

    def pc_power_action(self, command: str) -> None:
        if not self.port:
            QMessageBox.warning(self, "PC Power", "Спочатку підключи ESP32-S3")
            return
        warning = {
            "PC ON": "Натиснути кнопку Power на 300 мс для увімкнення ПК?",
            "PC OFF": "Натиснути Power на 300 мс? ОС може вимкнутись або перейти у сон.",
            "PC FORCE": "Утримувати Power 6 секунд? Це може призвести до втрати даних!",
        }.get(command)
        if not warning:
            return
        if QMessageBox.question(self, "Керування живленням ПК", warning,
                                QMessageBox.StandardButton.Yes |
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self.send(command):
                QTimer.singleShot(250, lambda: self.send("PC STATUS"))

    def manual_override(self) -> None:
        value, accepted = QInputDialog.getInt(self, "Ручний PWM", "Швидкість у %:",
                                               100, 0, 100, 1)
        if accepted:
            self.send(f"FAN {self.current_fan} {value}")

    def apply_argb_scene(self, scene_name: str, all_zones: bool = False) -> None:
        """Apply a lighting-only scene without modifying cooling NVS or fan duty."""
        if not self.port:
            QMessageBox.warning(self, "ARGB", "Спочатку підключи ESP32-S3")
            return
        channels = list(range(1, 9)) if all_zones else [self.current_fan]
        try:
            commands = make_scene_commands(scene_name, channels)
        except ValueError as exc:
            QMessageBox.warning(self, "ARGB", str(exc))
            return
        if scene_name == "OpenRGB":
            if not self.bridge_checkbox.isChecked():
                self.bridge_checkbox.setChecked(True)
            if not self.bridge_checkbox.isChecked():
                QMessageBox.warning(
                    self, "OpenRGB",
                    "Не вдалося увімкнути локальний міст E1.31. "
                    "Перевір порт UDP 5568 або налаштуй прямий Wi-Fi E1.31.",
                )
                return
            self.log("OpenRGB: міст E1.31 увімкнено; очікування кадрів із OpenRGB")
            self.dashboard.show_page("argb")
            return
        # Live E1.31 packets would immediately overwrite a selected static scene.
        if self.bridge_checkbox.isChecked():
            self.bridge_checkbox.setChecked(False)
        for command in commands:
            if not self.send(command):
                QMessageBox.warning(self, "ARGB", "З'єднання втрачено під час застосування сцени")
                return
        self.log(
            f"ARGB: {scene_name} → {'усі 8 зон' if all_zones else f'канал {self.current_fan}'}"
        )

    def pick_color(self) -> None:
        color = QColorDialog.getColor(parent=self, title="ARGB — колір стрічки")
        if color.isValid():
            self.send(f"LED {self.current_fan} {color.red()} {color.green()} {color.blue()}")

    def pick_brightness(self) -> None:
        value, accepted = QInputDialog.getInt(self, "Яскравість ARGB", "0..255:",
                                               64, 0, 255, 1)
        if accepted:
            self.send(f"BRIGHT {self.current_fan} {value}")

    def start_calibration(self) -> None:
        answer = QMessageBox.question(
            self, "Калібрування RPM",
            f"Вентилятор {self.current_fan} по черзі отримає PWM від 0 до 100%. "
            "Він може повністю зупинитися на низьких значеннях. "
            "Інші вентилятори продовжать керування за температурою. Почати?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cal_points[self.current_fan] = {}
            self.cal_progress.setValue(0)
            self._update_rpm_plot()
            self.send(f"CAL SMART {self.current_fan}")

    def _update_rpm_plot(self) -> None:
        samples = sorted(self.cal_points[self.current_fan].items())
        self.rpm_curve.setData([p for p, _ in samples], [rpm for _, rpm in samples])

    def configure_led_count(self) -> None:
        current = self.led_counts[self.current_fan - 1] if self.led_counts else 30
        count, ok = QInputDialog.getInt(self, "ARGB LED", "Кількість LED (1..170):", current, 1, 170)
        if ok and self.send(f"STRIP {self.current_fan} {count}"):
            QTimer.singleShot(400, lambda: self.send("LEDS"))

    def reverse_led_strip(self) -> None:
        direction, ok = QInputDialog.getItem(self, "ARGB напрямок", "Нумерація LED:",
                                            ["Прямий", "Зворотний"], 0, False)
        if ok: self.send(f"REVERSE {self.current_fan} {1 if direction == 'Зворотний' else 0}")

    def set_argb_budget(self) -> None:
        ma, ok = QInputDialog.getInt(self, "Максимальний струм", "Загальний ліміт 5В ARGB, мА:",
                                     2000, 100, 20000, 100)
        if ok: self.send(f"RGBBUDGET {ma}")

    def configure_mqtt(self) -> None:
        if not self.port:
            QMessageBox.warning(self, "MQTT", "Спочатку підключи ESP32-S3")
            return
        host, ok = QInputDialog.getText(self, "MQTT", "IP/hostname брокера:")
        if not ok or not host.strip(): return
        port, ok = QInputDialog.getInt(self, "MQTT", "Порт:", 1883, 1, 65535)
        if not ok: return
        user, ok = QInputDialog.getText(self, "MQTT", "Користувач (порожній = без авторизації):")
        if not ok: return
        password = ""
        if user:
            password, ok = QInputDialog.getText(self, "MQTT", "Пароль:", QLineEdit.EchoMode.Password)
            if not ok: return
        self.send(f"MQTT HOST {host.strip()} {port}")
        if user:
            self.send(f"MQTT AUTH {user} {password}")
        else:
            self.send("MQTT AUTH CLEAR")
        self.send("MQTT ON")
        self.send("MQTT?")
        QMessageBox.information(self, "MQTT", "Брокер збережено. ESP32 має бути підключено до Wi-Fi.\n"
                                 "Home Assistant Discovery активується після з'єднання з брокером.")

    def configure_wifi(self) -> None:
        ssid, ok = QInputDialog.getText(self, "Wi-Fi на ESP32", "SSID (без пробілів):")
        if not ok or not ssid: return
        password, ok = QInputDialog.getText(self, "Wi-Fi на ESP32", "Пароль (без пробілів):",
                                              QLineEdit.EchoMode.Password)
        if not ok: return
        if " " in ssid or " " in password:
            QMessageBox.warning(self, "Wi-Fi", "Цей протокол не підтримує пробіли у SSID/паролі")
            return
        # Do not log the password, and do not include it in GUI history.
        self.send(f"WIFI SET {ssid} {password}")

    def toggle_sacn(self, enabled: bool) -> None:
        if not enabled:
            self.sacn.stop()
            self.sacn_pending.clear()
            self.bridge_status.setText("Вимкнено")
            self.dashboard.set_bridge_state(False)
            self.settings.setValue("sacnEnabled", False)
            return
        try:
            self.sacn.start()
        except OSError as exc:
            self.bridge_status.setText("UDP 5568 зайнятий або заблокований")
            self.log(f"E1.31 ERROR: {exc}")
            self.bridge_checkbox.blockSignals(True)
            self.bridge_checkbox.setChecked(False)
            self.bridge_checkbox.blockSignals(False)
            self.settings.setValue("sacnEnabled", False)
            return
        self.settings.setValue("sacnEnabled", True)
        self.dashboard.set_bridge_state(True, self.sacn_forwarded)
        self.bridge_status.setText(f"Прийом: 127.0.0.1:{SACN_PORT} (0 кадрів)")

    def poll_sacn(self) -> None:
        if self.sacn.sock is None:
            return
        # Keep the last frame per strip; drop stale frames when effects run faster
        # than USB transfer. Fan temperatures and Serial commands stay responsive.
        self.sacn_pending.update(self.sacn.read_latest())
        now = time.monotonic()
        if not self.port or self.led_counts is None or now - self.sacn_last_sent < 0.04 or not self.sacn_pending:
            return
        self.sacn_last_sent = now
        frames = self.sacn_pending
        self.sacn_pending = {}
        for ch, rgb in sorted(frames.items()):
            count = min(self.led_counts[ch - 1], 170)
            rgb = rgb[:3 * count]
            if len(rgb) < 3:
                continue
            try:
                packet = encode_rgb_frame(ch, rgb)
                if self.port.write(packet) != len(packet):
                    raise serial.SerialTimeoutException("incomplete RGB frame")
                self.sacn_forwarded += 1
            except (ValueError, serial.SerialException, OSError) as exc:
                self.log(f"ARGB E1.31 → USB ERROR: {exc}")
                self.disconnect()
                return
        if self.sacn_forwarded % 50 < len(frames):
            self.bridge_status.setText(
                f"Прийом: 127.0.0.1:{SACN_PORT} ({self.sacn_forwarded} кадрів → ESP)"
            )
            self.dashboard.set_bridge_state(True, self.sacn_forwarded)

    def closeEvent(self, event) -> None:
        self.sacn.stop()
        self.temperature_executor.shutdown(wait=False, cancel_futures=True)
        self.disconnect()
        self.settings.sync()
        super().closeEvent(event)


def main() -> None:
    if "--headless" in sys.argv:
        from agent import run_agent
        sys.exit(run_agent())
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 10))  # Windows Cyrillic-capable system font
    window = FanArgbWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Windows desktop companion: ESP32 calibration, fan curves and PC temperatures.

Run: python pc_app/main.py (from repository root or from pc_app).
Uses bundled NWinfo and an optional local DS18B20 sensor on ESP32-S3.
"""
from __future__ import annotations

import json
import csv
from dataclasses import dataclass
from datetime import datetime
from collections import deque
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional

import pyqtgraph as pg
import serial
from serial.tools import list_ports
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QTextCursor, QFont, QAction, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QColorDialog, QCheckBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QFileDialog, QSystemTrayIcon, QMenu, QStyle,
    QHeaderView, QAbstractItemView, QStackedWidget, QTabWidget,
)

from monitor import (
    GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED, MAX_ALL, MAX_CPU_GPU,
    TemperatureSensor,
)
from nwinfo_sensors import NwinfoSensorSampler
from sacn_bridge import E131Listener, SACN_PORT, SERIAL_BAUD, encode_rgb_frame
from protocol import validate_curve, DEFAULT_CURVE, make_curve_command, parse_curve, parse_status
from serial_owner import SerialProxyClient
from serial_tx import SerialTransmitter
from rgb_stream import AdaptiveRgbStream
from openrgb_native import OpenRGBNativeServer
from port_recovery import PortRecovery, SerialHeartbeat
from profiles import PRESETS
from config_presets import (RGB_SCENES, FAN_CURVES, commands as preset_commands,
                            create_configuration, from_json as parse_configuration,
                            to_json as serialize_configuration, openrgb_e131_manifest)
from ui_dashboard_model import make_scene_commands
from ui_dashboard import DashboardShell
from smart_control import SafeTemperatureFilter, AutoProfileSelector
from tray_monitor import FaultNotificationGate
from tach_health import TachHealthMonitor, dump_references
from fan_groups_ui import FanGroupsDialog
from autonomy_ui import OfflineProfilesDialog, AirflowDialog
from reactive_argb import MAPPING_KEY, value_commands
from audio_capture import LoopbackAudioCapture, audio_command
from application_profiles import (
    ApplicationProfilePolicy, loads as load_application_rules,
    runtime_commands, scan_processes,
)
from application_profiles_ui import ApplicationProfilesDialog
from pid_autotune_ui import PidAutotuneDialog
from telemetry_store import TelemetryStore
from sensor_pipeline import (
    FanSensorRoute, plan_sensor_telemetry,
    choose_automatic_profile, automatic_profile_commands,
)


@dataclass
class _CurveReadback:
    expected: list[tuple[int, int]] | None
    saw_mismatch: bool = False


class FanArgbWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FanARGB · ESP32-S3")
        self.resize(1510, 930)
        self.setMinimumSize(1080, 700)
        self.settings = QSettings("FanARGB", "FanARGBControl")
        self.port: Optional[serial.Serial | SerialProxyClient] = None
        self.tx: SerialTransmitter | None = None
        self.recovery = PortRecovery()
        self.heartbeat = SerialHeartbeat(timeout_seconds=18.0)
        self._reconnect_armed = False
        self.read_buffer = ""
        self.temperatures: list[TemperatureSensor] = []
        self.last_temperature_sample_at = float("-inf")
        self.cooling_assist_supported = False
        self.pid_tune_supported = False
        self.pid_tune_dialog = None
        self.curves = {ch: list(DEFAULT_CURVE) for ch in range(1, 9)}
        self.secondary_curves = {ch: list(DEFAULT_CURVE) for ch in range(1, 9)}
        self._curve_dirty: set[tuple[int, bool]] = set()
        self._curve_pending: dict[tuple[int, bool], _CurveReadback] = {}
        self._curve_feedback: dict[tuple[int, bool], str] = {}
        self.config_types: dict[int, int] = {}
        self.fan_pid_enabled = {ch: False for ch in range(1, 9)}
        self.fan_dual_enabled = {ch: False for ch in range(1, 9)}
        self.history: dict[int, deque] = {ch: deque(maxlen=3600) for ch in range(1, 9)}
        self.power_history = deque(maxlen=3600)
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
        self.sensor_sampler = NwinfoSensorSampler()
        saved_providers = str(self.settings.value("nwinfoProviders", ""))
        if saved_providers:
            self.sensor_sampler.set_enabled(set(saved_providers.split(",")))
        self.temperature_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="NWinfoResults")
        self._last_sensor_issue: str | None = None
        self.safe_filter = SafeTemperatureFilter()
        self.auto_selector = AutoProfileSelector()
        self.runtime_curve_supported = False
        self.reactive_fx_supported = False
        self.audio_supported = False
        self.offline_supported = False
        self.airflow_supported = False
        self.offline_dialog = None
        self.airflow_dialog = None
        self.audio_capture = LoopbackAudioCapture()
        self._last_audio_error = ""
        self._reactive_error = ""
        self.app_policy = ApplicationProfilePolicy()
        self.app_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ApplicationProfiles")
        self.app_scan_future: Future | None = None
        self.app_active: str | None = None
        self.app_last_lease = 0.0
        self.fault_gate = FaultNotificationGate()
        self.tach_monitor = TachHealthMonitor()
        try:
            self.tach_monitor.import_references(str(self.settings.value("fanHealthRefsV1", "")))
        except ValueError:
            pass  # Do not overwrite a corrupt user backup.
        self.telemetry = TelemetryStore()
        self._quit_requested = False
        self._last_hwtemp_line = ""
        self.temperature_future: Future | None = None
        self.sacn = E131Listener()
        self.openrgb_native = OpenRGBNativeServer()
        self.rgb_stream = AdaptiveRgbStream()
        self.sacn_forwarded = 0
        self._build_ui()
        self._setup_tray()
        self.refresh_ports()
        self._update_targets()

        self.serial_timer = QTimer(self)
        self.serial_timer.timeout.connect(self.poll_serial)
        self.serial_timer.start(80)
        self.tx_timer = QTimer(self)
        self.tx_timer.timeout.connect(self.flush_serial_tx)
        self.tx_timer.start(15)
        self.audio_timer = QTimer(self)
        self.audio_timer.timeout.connect(self.poll_audio_levels)
        self.audio_timer.start(90)
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.timeout.connect(self._try_reconnect)
        self.reconnect_timer.start(5000)
        self.temperature_timer = QTimer(self)
        self.temperature_timer.timeout.connect(self.refresh_temperatures)
        self.temperature_timer.start(2000)
        self.temperature_result_timer = QTimer(self)
        self.temperature_result_timer.timeout.connect(self.apply_temperature_result)
        self.temperature_result_timer.start(100)
        self.sacn_timer = QTimer(self)
        self.sacn_timer.timeout.connect(self.poll_sacn)
        self.sacn_timer.start(20)
        self.openrgb_sdk_timer = QTimer(self)
        self.openrgb_sdk_timer.timeout.connect(self.poll_native_openrgb)
        self.openrgb_sdk_timer.start(25)
        self.refresh_temperatures()
        self.aux_status_timer = QTimer(self)
        self.aux_status_timer.timeout.connect(self.refresh_aux_status)
        self.aux_status_timer.start(5000)
        self.profile_timer = QTimer(self)
        self.profile_timer.timeout.connect(self._check_automatic_profile)
        self.profile_timer.start(6000)
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
        connect_row.addWidget(QLabel("Датчики Windows · NWinfo:"))
        self.sensor_status = QLabel("Пошук датчиків…")
        connect_row.addWidget(self.sensor_status)
        connect_row.addStretch(1)
        layout.addLayout(connect_row)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        splitter.addWidget(left)
        self.fan_source_stack = QStackedWidget()
        for ch in range(1, 9):
            box = QComboBox()
            box.setAccessibleName("Датчик Windows для кривої")
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(10)
            box.addItem("MAX усіх температур", MAX_ALL)
            box.addItem("MAX(CPU, GPU) — для корпусних вентиляторів", MAX_CPU_GPU)
            box.addItem("AVG вибраної групи", GROUP_AVG)
            box.addItem("MAX вибраної групи", GROUP_MAX)
            box.addItem("Зважене AVG групи", GROUP_WEIGHTED)
            desired = str(self.settings.value(f"source{ch}", MAX_ALL))
            known = [MAX_ALL, MAX_CPU_GPU, GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED]
            if desired in known:
                box.setCurrentIndex(known.index(desired))
            else:
                box.addItem(f"Недоступний: {desired}", desired)
                box.setCurrentIndex(box.count() - 1)
            box.setToolTip(box.currentText())
            box.currentIndexChanged.connect(lambda _=0, number=ch: self.source_changed(number))
            self.fan_source_stack.addWidget(box)
            self.source_boxes.append(box)

        all_fans = QWidget()
        all_fans_layout = QVBoxLayout(all_fans)
        all_fans_layout.setContentsMargins(0, 0, 0, 0)
        profile_row = QHBoxLayout()
        profile_label = QLabel("Профіль:")
        profile_row.addWidget(profile_label)
        self.profile_box = QComboBox()
        self.profile_box.addItems(["Silent", "Balanced", "Performance", "Custom"])
        profile_label.setBuddy(self.profile_box)
        profile_row.addWidget(self.profile_box, 1)
        apply_profile = QPushButton("Записати в ESP32")
        apply_profile.setToolTip("Замінює основні криві всіх 8 вентиляторів у пам’яті ESP32 (NVS) після підтвердження.")
        apply_profile.clicked.connect(self.apply_profile)
        profile_row.addWidget(apply_profile)
        all_fans_layout.addLayout(profile_row)
        save_custom = QPushButton("Зберегти Custom на ПК")
        save_custom.setToolTip("Копіює поточні основні криві всіх 8 вентиляторів у профіль Custom на ПК. Без запису в ESP32.")
        save_custom.clicked.connect(self.save_custom_profile)
        all_fans_layout.addWidget(save_custom, alignment=Qt.AlignmentFlag.AlignLeft)
        all_auto = QPushButton("Усі вентилятори → Авто")
        all_auto.setToolTip("Повертає всі вентилятори в автоматичний режим, не замінюючи їхні криві.")
        all_auto.clicked.connect(lambda: self.send("ALLAUTO"))
        all_fans_layout.addWidget(all_auto, alignment=Qt.AlignmentFlag.AlignLeft)
        fan_group_button = QPushButton("Групи вентиляторів…")
        fan_group_button.setToolTip("Об’єднати кілька вентиляторів для спільного керування.")
        fan_group_button.clicked.connect(self.open_fan_groups)
        all_fans_layout.addWidget(fan_group_button, alignment=Qt.AlignmentFlag.AlignLeft)

        selected_controls = QWidget()
        controls = QHBoxLayout(selected_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        override_button = QPushButton("Ручний PWM…")
        override_button.clicked.connect(self.manual_override)
        controls.addWidget(override_button)
        auto_button = QPushButton("Повернути в Авто")
        auto_button.clicked.connect(lambda: self.send(f"AUTO {self.current_fan}"))
        controls.addWidget(auto_button)
        source_label = QLabel("Windows:")
        source_label.setToolTip("Джерело температури для кривої, зокрема AVG або MAX групи.")
        controls.addWidget(source_label)
        controls.addWidget(self.fan_source_stack, 1)
        group_edit = QPushButton("Датчики для кривої…")
        group_edit.setToolTip("Вибрати датчики групи цього вентилятора для AVG, MAX або зваженого AVG.")
        group_edit.clicked.connect(self.edit_sensor_group)
        controls.addWidget(group_edit)

        cooling_tools = QWidget()
        tool_row = QHBoxLayout(cooling_tools)
        tool_row.setContentsMargins(0, 0, 0, 0)
        app_profiles_button = QPushButton("Профілі за програмами…")
        app_profiles_button.setToolTip("Правила на ПК; активні програми тимчасово змінюють криві ESP32 без запису в NVS.")
        app_profiles_button.clicked.connect(self.open_application_profiles)
        tool_row.addWidget(app_profiles_button)
        offline_button = QPushButton("Автономні профілі ESP32…")
        offline_button.setToolTip("Профілі в пам’яті ESP32 для роботи без застосунку на ПК.")
        offline_button.clicked.connect(self.open_offline_profiles)
        tool_row.addWidget(offline_button)
        airflow_button = QPushButton("Airflow Assistant…")
        airflow_button.setToolTip("Оцінка балансу припливу й витяжки, а не тиску в корпусі.")
        airflow_button.clicked.connect(self.open_airflow_assistant)
        tool_row.addWidget(airflow_button)
        tool_row.addStretch(1)

        sensors_box = QGroupBox("Усі доступні температурні датчики ПК")
        sensors_layout = QVBoxLayout(sensors_box)
        self.sensor_search = QLineEdit()
        self.sensor_search.setPlaceholderText("Пошук датчиків: CPU, GPU, NVMe, RAM, Power…")
        self.sensor_search.setClearButtonEnabled(True)
        self.sensor_search.textChanged.connect(self._filter_sensor_rows)
        sensors_layout.addWidget(self.sensor_search)
        self.sensor_tabs = QTabWidget()
        self.sensor_table = QTableWidget(0, 3)
        self.sensor_table.setHorizontalHeaderLabels(["Температурний датчик / пристрій", "°C", "SensorId"])
        self.sensor_table.verticalHeader().setVisible(False)
        self.sensor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.sensor_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.sensor_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sensor_tabs.addTab(self.sensor_table, "Температури")
        self.metric_table = QTableWidget(0, 4)
        self.metric_table.setHorizontalHeaderLabels(["Показник / пристрій", "Значення", "Одиниці", "Категорія"])
        self.metric_table.verticalHeader().setVisible(False)
        self.metric_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metric_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sensor_tabs.addTab(self.metric_table, "Інші показники")
        sensors_layout.addWidget(self.sensor_tabs)
        left_layout.addWidget(sensors_box, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)
        splitter.setSizes([740, 740])
        choose_row = QHBoxLayout()
        self.fan_box = QComboBox()
        for ch in range(1, 9):
            self.fan_box.addItem(f"Вентилятор {ch}", ch)
        self.fan_box.currentIndexChanged.connect(self.fan_combo_selected)
        choose_row.addWidget(self.fan_box)
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
        # The editor chart follows the same light/dark palette as native Windows.
        chart_background = self.palette().color(QPalette.ColorRole.Base).name()
        chart_foreground = self.palette().color(QPalette.ColorRole.Text).name()
        self.curve_plot.setBackground(chart_background)
        for axis_name in ("left", "bottom"):
            axis = self.curve_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(chart_foreground))
            axis.setTextPen(pg.mkPen(chart_foreground))
        self.curve_plot.setLabel("left", "PWM", units="%")
        self.curve_plot.setLabel("bottom", "Температура", units="°C")
        self.curve_plot.showGrid(x=True, y=True, alpha=0.3)
        self.curve_plot.setRange(xRange=(-4, 129), yRange=(-4, 104), padding=0)
        self.curve_plot.setMouseEnabled(x=False, y=False)
        self.curve_plot.setMenuEnabled(False)
        self.curve_plot.hideButtons()
        self.curve_line = self.curve_plot.plot([], [], pen=pg.mkPen("#4ed2e4", width=3))
        curve_layout.addWidget(self.curve_plot, 1)
        curve_actions = QHBoxLayout()
        self.save_button = QPushButton("Зберегти криву в ESP32 (NVS)")
        self.save_button.clicked.connect(self.save_curve)
        curve_actions.addWidget(self.save_button)
        self.reread_curve_button = QPushButton("Прочитати з ESP32")
        self.reread_curve_button.setToolTip("Оновити криву з ESP32, замінивши локальні зміни")
        self.reread_curve_button.clicked.connect(self.read_curve)
        curve_actions.addWidget(self.reread_curve_button)
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
        pid_row = QHBoxLayout()
        pid_tune = QPushButton("PID автонастроювання за TACH…")
        pid_tune.clicked.connect(self.show_pid_autotune)
        pid_row.addWidget(pid_tune)
        pid_row.addStretch(1)
        curve_layout.addLayout(pid_row)
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

        history_box = QGroupBox("Історія — PWM / RPM / температури / потужність")
        history_layout = QVBoxLayout(history_box)
        self.history_tabs = QTabWidget()
        self.history_plots = {}
        for key, label, unit in (
            ("pwm", "PWM", "%"), ("rpm", "RPM", "RPM"),
            ("temp", "Температура", "°C"), ("power", "Потужність", "Вт"),
        ):
            plot = pg.PlotWidget()
            plot.setMinimumHeight(190)
            plot.setLabel("bottom", "Час", units="с")
            plot.setLabel("left", label, units=unit)
            plot.showGrid(x=True, y=True, alpha=0.2)
            self.history_plots[key] = plot
            self.history_tabs.addTab(plot, label)
        self.history_plot = self.history_plots["pwm"]
        self.history_pwm_curve = self.history_plot.plot(
            pen=pg.mkPen("#6cbce5", width=2), name="PWM"
        )
        self.history_rpm_curve = self.history_plots["rpm"].plot(
            pen=pg.mkPen("#8cdb98", width=2)
        )
        self.history_temperature_curve = self.history_plots["temp"].plot(
            pen=pg.mkPen("#e6ae6d", width=2)
        )
        self.cpu_power_curve = self.history_plots["power"].plot(
            pen=pg.mkPen("#80b7eb", width=2), name="CPU W"
        )
        self.gpu_power_curve = self.history_plots["power"].plot(
            pen=pg.mkPen("#e8a073", width=2), name="GPU W"
        )
        self.history_plots["power"].addLegend()
        history_layout.addWidget(self.history_tabs)
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
        rainbow_button.clicked.connect(lambda: self._send_argb_quick("RAINBOW"))
        rgb_actions.addWidget(rainbow_button)
        brightness_button = QPushButton("Яскравість…")
        brightness_button.clicked.connect(self.pick_brightness)
        rgb_actions.addWidget(brightness_button)
        off_button = QPushButton("Вимкнути ARGB")
        off_button.clicked.connect(lambda: self._send_argb_quick("OFF"))
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
            all_fans=all_fans,
            selected_controls=selected_controls,
            cooling_tools=cooling_tools,
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
            self.disconnect(manual=True)
            return
        port_name = self.port_box.currentData()
        if not port_name:
            QMessageBox.warning(self, "COM порт", "Підключи ESP32-S3 та вибери COM порт")
            return
        self.connect_to_port(str(port_name))

    def connect_to_port(self, port_name: str, quiet: bool = False) -> bool:
        if self.port:
            return True
        try:
            try:
                self.port = SerialProxyClient(port_name)
                using_agent = True
            except (OSError, ConnectionError):
                self.port = serial.Serial(
                    port_name, SERIAL_BAUD, timeout=0, write_timeout=0.3
                )
                using_agent = False
            self.tx = SerialTransmitter(self.port)
            self.rgb_stream.reset()
            self.led_counts = None
            self.runtime_curve_supported = False
            self.reactive_fx_supported = False
            self.app_active = None
            self.app_policy.reset()
            self.heartbeat.reset()
            self.read_buffer = ""
            self.settings.setValue("port", port_name)
            self.connect_button.setText("Від'єднати")
            self.dashboard.set_connected(True, port_name)
            self.statusBar().showMessage(f"USB: {port_name} відкрито; очікуємо відповідь ESP32")
            self.log(
                f"Підключено до {port_name} "
                f"({'через агента' if using_agent else 'COM напряму'})"
            )
            if not quiet or self.recovery.identity is None:
                # Identity is recorded only after an explicit user-selected port.
                self.recovery.remember(list_ports.comports(), port_name)
            self._reconnect_armed = True
            QTimer.singleShot(2200, self.read_device_state)
            return True
        except (serial.SerialException, OSError) as exc:
            self.port = None
            self.tx = None
            if quiet:
                self.log(f"Перепідключення ESP не вдалося: {exc}")
            else:
                QMessageBox.warning(self, "Serial", str(exc))
            return False

    def _try_reconnect(self) -> None:
        if self.port or not self._reconnect_armed:
            return
        ports = list(list_ports.comports())
        target = self.recovery.find(ports)
        if not target:
            return
        self.refresh_ports()
        self.connect_to_port(target, quiet=True)

    def read_device_state(self) -> None:
        if not self.port:
            return
        if self.send("PING"):
            self.heartbeat.ping(time.monotonic())
        self.send("VERSION?")
        self.send("LEDS")
        self.send("STATUS")
        self.send("PC STATUS")
        self.send("MQTT?")
        self.send("HTEMP?")
        self.send("HTLIST?")
        for ch in range(1, 9):
            self.send(f"CURVE? {ch}")
            self.send(f"CURVE2? {ch}")
            self.send(f"TYPE? {ch}")
            self.send(f"CONFIG {ch}")

    def refresh_aux_status(self) -> None:
        if self.port:
            if self.heartbeat.expired(time.monotonic()):
                self.log("USB: немає відповіді PONG від ESP32; перепідключення за USB-ідентичністю")
                self.telemetry.record_alert("USB", "ESP32 не відповідає на PING")
                self.disconnect()
                return
            if self.send("PING"):
                self.heartbeat.ping(time.monotonic())
            if not self.port:
                return
            # PONG alone cannot prove the eight fan statuses are still current.
            self.send("STATUS")
            self.send("PC STATUS")
            self.send("MQTT?")
            self.send("HTEMP?")
            self.dashboard.device_settings.refresh_online()

    def set_audio_capture_enabled(self, enabled: bool) -> None:
        # Persistent opt-in; never access audio before the user activates it.
        self.settings.setValue("audioCaptureEnabled", bool(enabled))
        if enabled and self.port and self.audio_supported:
            self.audio_capture.start()
        else:
            self.audio_capture.stop()

    def poll_audio_levels(self) -> None:
        if not self.port or not self.audio_supported:
            return
        problem = self.audio_capture.error
        if problem and problem != self._last_audio_error:
            self.log("Audio loopback: " + problem)
            self.dashboard.audio_reactive.status.setText(
                "Помилка захоплення системного звуку: " + problem)
            self._last_audio_error = problem
        data = self.audio_capture.read_latest()
        if data is not None:
            self.send(audio_command(data))

    def disconnect(self, manual: bool = False) -> None:
        self.audio_capture.stop()
        self.audio_supported = False
        if manual:
            self._reconnect_armed = False
        if self.port:
            try:
                self.port.close()
            except OSError:
                pass
        if self.tx is not None:
            self.tx.clear()
        self.rgb_stream.reset()
        self.tx = None
        self.port = None
        self.heartbeat.reset()
        self.read_buffer = ""
        self.led_counts = None
        self.cooling_assist_supported = False
        self.pid_tune_supported = False
        self.runtime_curve_supported = False
        self.reactive_fx_supported = False
        self.app_active = None
        self.app_policy.reset()
        if self.pid_tune_dialog is not None:
            self.pid_tune_dialog.set_connected(False)
        self.dashboard.native_effects.set_supported(False)
        self.dashboard.reactive_argb.set_supported(False)
        self.dashboard.audio_reactive.set_supported(False)
        self._last_hwtemp_line = ""
        self.dashboard.hardware_sensor.reset_status()
        self.offline_supported = False
        self.airflow_supported = False
        if self.dashboard.native_checkbox.isChecked():
            self.dashboard.native_checkbox.setChecked(False)
        if self.dashboard.studio.active:
            self.dashboard.studio.stop()
        self.connect_button.setText("Підключити")
        self.reset_curve_feedback()
        self.dashboard.set_connected(False)
        self.fault_gate.reset()
        self.tach_monitor.reset()
        self._update_tray_tooltip()
        self.statusBar().showMessage("ESP: відключено — автономний захист через 10 с без температур")
        self.log("ESP відключено")

    def send(self, message: str) -> bool:
        if not self.port:
            return False
        try:
            if self.tx is None:
                return False
            self.tx.send_command(message)
            self.dashboard.note_argb_command(message)
            return True
        except (serial.SerialException, OSError, ValueError, UnicodeError) as exc:
            self.log(f"ПОМИЛКА Serial: {exc}")
            self.disconnect()
            return False

    def queue_rgb(self, channel: int, packet: bytes) -> bool:
        if not self.port or self.tx is None:
            return False
        try:
            self.tx.queue_rgb(channel, packet)
            self.dashboard.clear_argb_preview(channel)
            return True
        except ValueError as exc:
            self.log(f"RGB: {exc}")
            return False

    def flush_serial_tx(self) -> None:
        if self.tx is None:
            return
        try:
            self.tx.flush_rgb(max_frames=4)
        except (OSError, serial.SerialException) as exc:
            self.log(f"USB RGB: {exc}")
            self.disconnect()

    def send_raw(self) -> None:
        raw = self.raw_input.text().strip()
        if raw and self.send(raw):
            secret_command = raw.upper().startswith((
                "WIFI SET", "MQTT AUTH", "MQTT AUTHHEX", "MQTT TX AUTHHEX",
            ))
            self.log("> [приховано налаштування доступу]" if secret_command else "> " + raw)
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
        if line.startswith("PONG ") and line[5:].isdigit():
            self.heartbeat.pong()
            self.dashboard.note_esp_response()
            return
        if self.pid_tune_dialog is not None and self.pid_tune_dialog.handle_line(line):
            return
        if self.dashboard.temperature_argb.handle_line(line):
            return
        if self.dashboard.native_effects.handle_line(line):
            return
        if self.dashboard.reactive_argb.handle_line(line):
            return
        if self.dashboard.audio_reactive.handle_line(line):
            return
        if self.offline_dialog and self.offline_dialog.handle_line(line):
            return
        if self.airflow_dialog and self.airflow_dialog.handle_line(line):
            return
        if self.dashboard.device_settings.handle_line(line):
            return
        if self.dashboard.diagnostics.handle_line(line):
            return
        status = parse_status(line)
        if status:
            self.fan_status[status.channel] = status
            self.dashboard.update_fan(status.channel, status)
            alert = self.fault_gate.observe(
                status.channel, fault=status.fault,
                fresh=status.fresh, now=time.monotonic(),
            )
            if (alert and self.tray_icon is not None and
                    self.dashboard.settings_panel.notify_faults.isChecked()):
                self.tray_icon.showMessage(
                    "FanARGB · стан охолодження", alert,
                    QSystemTrayIcon.MessageIcon.Warning, 6500,
                )
            self._update_tray_tooltip()

            self.history[status.channel].append((time.time(), status.pwm, status.rpm,
                                                  status.deci_c / 10 if status.fresh else float("nan")))
            self.telemetry.record_fan(
                status.channel, pwm=status.pwm, rpm=status.rpm,
                temperature=status.deci_c / 10 if status.fresh else None,
                fresh=status.fresh, fault=status.fault,
            )
            tach_warning = self.tach_monitor.observe(
                status.channel, pwm=status.pwm, rpm=status.rpm,
                has_feedback=status.rpm_feedback, fault=status.fault,
            )
            if hasattr(self.dashboard.diagnostics, "update_fan_health"):
                self.dashboard.diagnostics.update_fan_health(
                    status.channel, self.tach_monitor.status(status.channel))
            if tach_warning:
                self.log("TACH: " + tach_warning)
                self.telemetry.record_alert("TACH", tach_warning)
                if (self.tray_icon is not None and
                        self.dashboard.settings_panel.notify_faults.isChecked()):
                    self.tray_icon.showMessage(
                        "FanARGB · діагностика TACH", tach_warning,
                        QSystemTrayIcon.MessageIcon.Warning, 6500,
                    )
            if status.channel == self.current_fan:
                self._refresh_history()
            return
        if line.startswith("FW VERSION="):
            fields = dict(x.split("=", 1) for x in line.split() if "=" in x)
            try:
                version = int(fields["VERSION"])
                dc_ready = {"0": False, "1": True}.get(fields.get("DC_READY", ""))
                self.dashboard.note_esp_response(dc_ready)
                self.dashboard.firmware_status.setText(
                    f"ESP32 firmware v{version} · "
                    + ("сумісна" if version >= 8 else "оновлення потрібне для налаштувань ESP32")
                    + f" · DC PWM {'дозволено' if fields.get('DC_READY') == '1' else 'заблоковано'}"
                    + f" · DS18B20 {'так' if fields.get('DS18B20') == '1' else 'ні'}"
                )
                channel_mask = fields.get("CHMASK")
                if channel_mask is not None:
                    self.dashboard.set_channel_mask(int(channel_mask))
                serial_version = int(fields.get("SERIAL", 5))
                self.dashboard.device_settings.set_version(version, serial_version)
                self.dashboard.temperature_argb.set_version(serial_version)
                self.dashboard.temperature_argb.set_palette_supported(fields.get("TPAL_NVS") == "1")
                self.dashboard.device_settings.gpio_dialog.set_supported(
                    fields.get("GPIO_NVS") == "1",
                    n16r8=(fields.get("N16R8") == "1" and fields.get("CHMASK") == "255"),
                )
                self.pid_tune_supported = fields.get("PIDTUNE_NVS") == "1"
                if self.pid_tune_dialog is not None:
                    self.pid_tune_dialog.set_supported(self.pid_tune_supported)
                self.cooling_assist_supported = fields.get("ASSIST_NVS") == "1"
                self.dashboard.device_settings.assist_dialog.set_supported(self.cooling_assist_supported)
                self.runtime_curve_supported = fields.get("RTCURVE") == "1"
                self.dashboard.native_effects.set_supported(fields.get("FX") == "1")
                self.offline_supported = fields.get("OFFLINE") == "1"
                self.airflow_supported = fields.get("AIRFLOW") == "1"
                self.audio_supported = fields.get("AUDIO") == "1"
                self.dashboard.audio_reactive.set_supported(self.audio_supported)
                if self.audio_supported:
                    self.dashboard.audio_reactive.readback()
                    if str(self.settings.value("audioCaptureEnabled","false")).lower() in ("true","1"):
                        self.audio_capture.start()
                self.reactive_fx_supported = fields.get("RFX") == "1"
                self.dashboard.reactive_argb.set_supported(self.reactive_fx_supported)
                if self.reactive_fx_supported:
                    self.dashboard.reactive_argb.readback()
            except (ValueError, KeyError):
                self.log("Невалідна відповідь VERSION?")
            return
        if line.startswith("HTSENSOR_END"):
            self.dashboard.hardware_sensor.handle_sensor_line(line)
            return
        if line.startswith("HTSENSOR "):
            self.dashboard.hardware_sensor.handle_sensor_line(line[9:])
            return
        if line.startswith("HTMAP "):
            self.dashboard.temperature_source_dialog.handle_map(line[6:])
            return
        if line.startswith("HTEMP "):
            self._last_hwtemp_line = line
            self.dashboard.hardware_sensor.handle_status(line)
            return
        if line.startswith("HTMODE "):
            self.dashboard.temperature_source_dialog.handle_mode(line[7:])
            return
        if line.startswith("PC "):
            self.pc_power_status.setText("Стан ПК: " + line[3:])
            self.dashboard.update_pc_state(line[3:])
            return
        if line.startswith("MQTT ENABLED="):
            self.dashboard.set_mqtt_state(line[5:])
            return
        if line.startswith("TYPE ") or line.startswith("CONFIG "):
            if line.startswith("CONFIG "):
                self.dashboard.device_settings.on_fan_config(line)
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
                self._accept_curve_readback(*parsed, secondary=True)
            return
        curve = parse_curve(line)
        if curve:
            self._accept_curve_readback(*curve, secondary=False)
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
        # A separate worker runs bundled NWinfo; the Qt GUI stays responsive.
        if self.temperature_future is None:
            self.temperature_future = self.temperature_executor.submit(self.sensor_sampler.poll)

    def apply_temperature_result(self) -> None:
        future = self.temperature_future
        if future is None or not future.done():
            return
        self.temperature_future = None
        ready = False
        issue: str | None = None
        try:
            sample = future.result()
            if sample is None:
                self.sensor_status.setText("NWinfo · опитування CPU / GPU…")
                self.sensor_status.setStyleSheet("color: #edba6d")
                return
            self.temperatures = sample
            self.last_temperature_sample_at = time.monotonic()
            ready = True
            provider_issues = self.sensor_sampler.problems
            details = "; ".join(f"{p}: {v}" for p, v in sorted(provider_issues.items()))
            if self.temperatures:
                self.sensor_status.setText(
                    f"NWinfo · {len(self.temperatures)} температур" +
                    (" · частково" if provider_issues else "")
                )
                self.sensor_status.setStyleSheet(
                    "color: #edba6d" if provider_issues else "color: #70cda6"
                )
                self.sensor_status.setToolTip(
                    details or "Локальне читання CPU / GPU / SSD без вебсервера"
                )
                if provider_issues:
                    issue = "Недоступні окремі датчики: " + details
            else:
                issue = (
                    "NWinfo не надав справних температур. " +
                    (details or "Перевір драйвери CPU/GPU та права доступу.")
                )
                self.sensor_status.setText("NWinfo · немає температур")
                self.sensor_status.setStyleSheet("color: #edba6d")
                self.sensor_status.setToolTip(issue)
        except Exception as exc:
            self.temperatures = []
            issue = f"NWinfo: {type(exc).__name__}: {exc}"
            self.sensor_status.setText("NWinfo · помилка датчиків")
            self.sensor_status.setStyleSheet("color: #f18b92")
            self.sensor_status.setToolTip(issue)
        if issue != self._last_sensor_issue:
            if issue:
                self.log(issue)
            self._last_sensor_issue = issue
        self.dashboard.set_sensor_count(
            len(self.temperatures), available=ready,
            metric_count=len(self.sensor_sampler.metrics),
        )
        self._update_sensor_table()
        self._update_metric_table()
        watts = self.sensor_sampler.metrics
        for metric in watts:
            self.telemetry.record_metric(
                metric.sensor_id, metric.name, metric.value, metric.unit
            )
        self._update_source_boxes()
        self._update_secondary_box()
        self.dashboard.temperature_argb.refresh_sensors()
        self.dashboard.reactive_argb.refresh_sensors()

        # Use the same safety-checked sensor routing as the headless agent.
        # GUI selection is live; the agent reads the corresponding QSettings.
        routes = tuple(
            FanSensorRoute(
                primary=str(box.currentData()),
                secondary=str(self.settings.value(f"source2{ch}", MAX_ALL)),
                group_ids=tuple(self.sensor_groups[ch]),
                weights=self.sensor_weights[ch],
                dual=self.fan_dual_enabled[ch],
            )
            for ch, box in enumerate(self.source_boxes, start=1)
        )
        plan = plan_sensor_telemetry(
            routes, self.temperatures, watts, filter_engine=self.safe_filter,
            smoothing=self.dashboard.settings_panel.smoothing.isChecked(),
            now=time.monotonic(), include_power=self.cooling_assist_supported,
        )
        self.power_history.append((
            time.time(),
            plan.cpu_watts if plan.cpu_watts is not None else float("nan"),
            plan.gpu_watts if plan.gpu_watts is not None else float("nan"),
        ))
        self._refresh_history()
        self._update_tray_tooltip()
        for command in plan.commands:
            self.send(command)
        if self.port and self.reactive_fx_supported:
            try:
                host_commands = value_commands(
                    str(self.settings.value(MAPPING_KEY,"")),
                    self.temperatures, self.sensor_sampler.metrics,
                )
            except ValueError as exc:
                message = str(exc)
                if message != self._reactive_error:
                    self.log("ARGB датчики: " + message)
                self._reactive_error = message
            else:
                self._reactive_error = ""
                for command in host_commands:
                    self.send(command)
        self.send("STATUS")

    def _check_automatic_profile(self) -> None:
        if not self.port:
            return
        now = time.monotonic()
        opt_in = str(self.settings.value("appProfilesEnabled", "false")).lower() in ("true", "1")
        if opt_in and self.runtime_curve_supported:
            if self.app_scan_future is None:
                self.app_scan_future = self.app_executor.submit(scan_processes)
            if self.app_scan_future.done():
                future = self.app_scan_future
                self.app_scan_future = self.app_executor.submit(scan_processes)
                try:
                    running = future.result()
                    rules = load_application_rules(str(self.settings.value("appProfileRulesV1", "")))
                    decision = self.app_policy.consider(rules, running, now=now)
                except (ValueError, ImportError, OSError) as exc:
                    self.log(f"Профілі програм: {exc}")
                    # Recover to the saved cooling policy rather than renewing
                    # a process decision that is no longer trustworthy.
                    if self.app_active:
                        self.send("RTCURVE CLEAR")
                    self.app_active = None
                    self.app_policy.reset()
                else:
                    if decision.ready and decision.profile != self.app_active:
                        actions = (runtime_commands(decision.profile) if decision.profile
                                   else ("RTCURVE CLEAR",))
                        if all(self.send(cmd) for cmd in actions):
                            self.app_active = decision.profile
                            self.app_last_lease = now
                            self.log("Профіль застосунку: " + (decision.profile or "базовий"))
                    elif decision.ready and self.app_active and now - self.app_last_lease > 6.0:
                        if self.send("RTCURVE KEEPALIVE"):
                            self.app_last_lease = now
            if self.app_active:
                return # Prevent lower-priority GPU automation from changing the base curve.
        elif self.app_active is not None:
            self.send("RTCURVE CLEAR")
            self.app_active = None
            self.app_policy.reset()
        if not self.dashboard.settings_panel.auto_profiles.isChecked():
            return
        desired = choose_automatic_profile(
            self.sensor_sampler.metrics, self.auto_selector,
            hour=datetime.now().hour, now=now,
        )
        if desired:
            try:
                for command in automatic_profile_commands(desired):
                    if not self.send(command):
                        self.log("Автопрофіль: COM недоступний, зміни не завершено")
                        return
            except ValueError as exc:
                self.log(f"Автопрофіль: {exc}")
                return
            for ch in range(1, 9):
                self.curves[ch] = list(PRESETS[desired])
            self.auto_selector.applied(desired, time.monotonic())
            self.profile_box.setCurrentText(desired)
            self._update_targets()
            self.log(f"Автопрофіль {desired}: надіслано 8 кривих, без зміни захисту")

    def _setup_tray(self) -> None:
        self.tray_icon = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self)
        tray.setToolTip("FanARGBControl · ESP32-S3")
        menu = QMenu(self)
        show_action = QAction("Відкрити FanARGBControl", self)
        show_action.triggered.connect(self._restore_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        for preset in ("Silent", "Balanced", "Performance"):
            action = QAction(f"Профіль: {preset}", self)
            action.triggered.connect(lambda _=False, name=preset: self._tray_profile(name))
            menu.addAction(action)
        menu.addSeparator()
        quit_action = QAction("Вийти", self)
        quit_action.triggered.connect(self._exit_from_tray)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self._restore_from_tray()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        self.tray_icon = tray

    def _update_tray_tooltip(self) -> None:
        if self.tray_icon is None:
            return
        connected = "підключено" if self.port else "відключено"
        recent = len(self.temperatures)
        problems = sum(1 for fan in self.fan_status.values()
                       if fan.fault or not fan.fresh)
        self.tray_icon.setToolTip(
            f"FanARGB · ESP {connected}\n"
            f"Температурних датчиків: {recent}\n"
            f"Проблемні вентилятори: {problems}"
        )

    def _disable_auto_for_manual_change(self) -> None:
        """Manual fan-curve edits take precedence over future auto profiles."""
        box = self.dashboard.settings_panel.auto_profiles
        if box.isChecked():
            box.setChecked(False)
            self.log("Автопрофілі вимкнено: застосовано ручне налаштування кривих")
        if str(self.settings.value("appProfilesEnabled", "false")).lower() in ("true", "1"):
            self.settings.setValue("appProfilesEnabled", False)
            self._application_rules_changed()
            self.log("Профілі програм вимкнено: ручні налаштування мають пріоритет")

    def _tray_profile(self, profile: str) -> None:
        self.profile_box.setCurrentText(profile)
        self._restore_from_tray()
        self.apply_profile()  # requires the existing explicit confirmation

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _exit_from_tray(self) -> None:
        self._quit_requested = True
        self.close()

    def _update_sensor_table(self) -> None:
        self.sensor_table.setRowCount(len(self.temperatures))
        for row, sensor in enumerate(self.temperatures):
            for col, value in enumerate((sensor.name, f"{sensor.celsius:.1f}", sensor.sensor_id)):
                self.sensor_table.setItem(row, col, QTableWidgetItem(value))

    def _update_metric_table(self) -> None:
        """Show power, clocks, voltage, RPM and load as read-only telemetry."""
        metrics = self.sensor_sampler.metrics
        self.metric_table.setRowCount(len(metrics))
        for row, metric in enumerate(metrics):
            columns = (
                metric.name, f"{metric.value:.1f}", metric.unit, metric.kind,
            )
            for col, value in enumerate(columns):
                self.metric_table.setItem(row, col, QTableWidgetItem(value))
        self.sensor_tabs.setTabText(0, f"Температури · {len(self.temperatures)}")
        self.sensor_tabs.setTabText(1, f"Інші показники · {len(metrics)}")
        self._filter_sensor_rows()

    def _filter_sensor_rows(self, _text: str = "") -> None:
        query = self.sensor_search.text().strip().casefold()
        for table in (self.sensor_table, self.metric_table):
            for row in range(table.rowCount()):
                searchable = " ".join(
                    table.item(row, col).text() if table.item(row, col) else ""
                    for col in range(table.columnCount())
                ).casefold()
                table.setRowHidden(row, bool(query and query not in searchable))

    def _update_source_boxes(self) -> None:
        for ch, box in enumerate(self.source_boxes, start=1):
            saved_id = str(box.currentData() or self.settings.value(f"source{ch}", MAX_ALL))
            box.blockSignals(True)
            box.clear()
            box.addItem("MAX усіх температур", MAX_ALL)
            box.addItem("MAX(CPU, GPU)", MAX_CPU_GPU)
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
            box.setToolTip(box.currentText())
            self.dashboard.set_fan_source(ch, box.currentText())

    def source_changed(self, ch: int) -> None:
        box = self.source_boxes[ch - 1]
        box.setToolTip(box.currentText())
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
        self.refresh_curve_feedback()

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

    def fan_combo_selected(self, index: int) -> None:
        if not 0 <= index < 8:
            return
        self.current_fan = index + 1
        self.dashboard.sync_zone(index)
        self.fan_source_stack.setCurrentIndex(index)
        self._update_targets()
        self._update_rpm_plot()
        self.cal_progress.setValue(len(self.cal_points[self.current_fan]))
        self._sync_mode_controls()
        self._refresh_history()
        self._update_secondary_box()
        self.refresh_curve_feedback()

    def _active_curve(self) -> list[tuple[int, int]]:
        return self.secondary_curves[self.current_fan] if self.secondary_checkbox.isChecked() else self.curves[self.current_fan]

    def _active_curve_key(self) -> tuple[int, bool]:
        return self.current_fan, self.secondary_checkbox.isChecked()

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

    def show_pid_autotune(self) -> None:
        if self.pid_tune_dialog is None:
            self.pid_tune_dialog = PidAutotuneDialog(self, self)
        self.pid_tune_dialog.show_for_channel(self.current_fan)

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
        if hist:
            origin = hist[0][0]
            times = [row[0] - origin for row in hist]
            self.history_pwm_curve.setData(times, [row[1] for row in hist])
            self.history_rpm_curve.setData(times, [row[2] for row in hist])
            self.history_temperature_curve.setData(times, [row[3] for row in hist])
        else:
            self.history_pwm_curve.clear()
            self.history_rpm_curve.clear()
            self.history_temperature_curve.clear()
        power = list(self.power_history)
        if power:
            origin = power[0][0]
            xs = [row[0] - origin for row in power]
            self.cpu_power_curve.setData(xs, [row[1] for row in power])
            self.gpu_power_curve.setData(xs, [row[2] for row in power])

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

    def refresh_curve_feedback(self) -> None:
        key = self._active_curve_key()
        fallback = ("Локальні зміни · не збережено в ESP32" if key in self._curve_dirty
                    else "Локальна крива · ще не прочитано з ESP32")
        status = self._curve_feedback.get(key, fallback)
        self.dashboard.fan_curve_status.setText(status)
        ch, secondary = key
        curve_number = 2 if secondary else 1
        self.save_button.setText(f"Записати криву {curve_number} · FAN {ch:02d}")
        source = self.secondary_source_box if secondary else self.source_boxes[ch - 1]
        self.dashboard.fan_curve_source.setText(f"Датчик Windows · крива {curve_number}: {source.currentText()}")
        self.dashboard.fan_curve_source.setToolTip(source.currentText())
        enabled = (self.dashboard.is_connected and not self.dashboard._demo
                   and self.dashboard.is_channel_available(ch) and key not in self._curve_pending)
        self.save_button.setEnabled(enabled)
        self.reread_curve_button.setEnabled(enabled)

    def reset_curve_feedback(self) -> None:
        self._curve_pending.clear()
        self._curve_feedback.clear()

    def _update_curve_line(self) -> None:
        points = self._active_curve()
        self.curve_line.setData([t for t, _ in points], [p for _, p in points])
        self.refresh_curve_feedback()

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
        if points[index] == (temp, pwm):
            self.updating_targets = False
            return
        points[index] = (temp, pwm)
        if self.secondary_checkbox.isChecked():
            self.secondary_curves[self.current_fan] = points
        else:
            self.curves[self.current_fan] = points
        key = self._active_curve_key()
        self._curve_dirty.add(key)
        if key not in self._curve_pending:
            self._curve_feedback[key] = "Локальні зміни · не збережено в ESP32"
        self._update_curve_line()
        self.updating_targets = False

    def _request_curve_readback(self, key: tuple[int, bool], expected: list[tuple[int, int]] | None = None) -> None:
        ch, secondary = key
        if not self.send(f"{'CURVE2?' if secondary else 'CURVE?'} {ch}"):
            self._curve_feedback[key] = "Не вдалося запросити криву з ESP32"
            self.refresh_curve_feedback()
            return
        pending = _CurveReadback(expected)
        self._curve_pending[key] = pending
        self._curve_feedback[key] = "Очікуємо зчитування з ESP32…"
        self.refresh_curve_feedback()

        def expire() -> None:
            if self._curve_pending.get(key) is pending:
                del self._curve_pending[key]
                self._curve_feedback[key] = (
                    "Крива з ESP32 не збігається · запис не підтверджено" if pending.saw_mismatch
                    else "Немає відповіді · криву не підтверджено"
                )
                self.refresh_curve_feedback()

        QTimer.singleShot(3000, self, expire)

    def _accept_curve_readback(self, ch: int, points: list[tuple[int, int]], *, secondary: bool) -> None:
        key = ch, secondary
        curves = self.secondary_curves if secondary else self.curves
        pending = self._curve_pending.get(key)
        expected = pending.expected if pending is not None else None
        if pending is not None:
            if expected is not None and expected != points:
                # Startup and save replies have no request ID; this may be the startup reply.
                pending.saw_mismatch = True
                return
            del self._curve_pending[key]
        elif key in self._curve_dirty:
            return

        if expected is not None and key in self._curve_dirty and expected != curves[ch]:
            self._curve_feedback[key] = "Нові локальні зміни · не збережено в ESP32"
        else:
            curves[ch] = points
            self._curve_dirty.discard(key)
            self._curve_feedback[key] = (
                "Зчитування з ESP32: крива збігається" if expected is not None else "Прочитано з ESP32"
            )
        if key == self._active_curve_key():
            self._update_targets()

    def read_curve(self) -> None:
        if self.reread_curve_button.isEnabled():
            self._request_curve_readback(self._active_curve_key())

    def save_curve(self) -> None:
        if not self.save_button.isEnabled():
            return
        key = self._active_curve_key()
        ch, secondary = key
        points = list(self._active_curve())
        try:
            message = make_curve_command(ch, points)
            if secondary:
                message = message.replace("CURVE ", "CURVE2 ", 1)
        except ValueError as exc:
            QMessageBox.warning(self, "Крива PWM", str(exc))
            return
        if self.send(message):
            self._curve_dirty.add(key)
            self._disable_auto_for_manual_change()
            self.log(f"> {message.split()[0]} {ch} — запис у NVS запитано")
            self._request_curve_readback(key, points)
        else:
            QMessageBox.warning(self, "ESP", "Підключи ESP32 до збереження кривої")

    def apply_fan_quick_preset(self, channel: int, preset: str) -> None:
        """One explicit, independently confirmed, NVS-backed fan profile change."""
        if not 1 <= channel <= 8 or preset not in (
            "Silent", "Default", "Maximum", "Custom"
        ):
            return
        if not self.port or not self.dashboard._channel_mask_known:
            QMessageBox.information(
                self, "Профіль вентилятора",
                "Підключи ESP32 і дочекайся інформації про доступні канали."
            )
            return
        if not self.dashboard.is_channel_available(channel):
            QMessageBox.warning(
                self, "Недоступний канал",
                f"FAN {channel:02d} вимкнено у конфігурації цієї плати."
            )
            return
        if preset == "Silent":
            curve = list(PRESETS["Silent"])
        elif preset == "Default":
            curve = list(DEFAULT_CURVE)
        elif preset == "Maximum":
            curve = [(25, 100), (35, 100), (50, 100), (65, 100), (80, 100)]
        else:
            try:
                stored = json.loads(str(self.settings.value("customCurves", "[]")))
                if not isinstance(stored, list) or len(stored) != 8:
                    raise ValueError("Missing custom profile")
                curve = [tuple(point) for point in stored[channel - 1]]
                if not validate_curve(curve):
                    raise ValueError("Invalid custom profile")
            except (TypeError, ValueError, IndexError, KeyError):
                QMessageBox.information(
                    self, "Custom",
                    "Немає збереженої власної кривої. Відредагуй криву "
                    "цього вентилятора і збережи Custom-профіль."
                )
                self.dashboard.open_fan(channel)
                return
        command = make_curve_command(channel, curve)
        answer = QMessageBox.question(
            self, f"FAN {channel:02d} · {preset}",
            f"Змінити тільки FAN {channel:02d} на {preset}?\n\n"
            "Крива буде записана в NVS контролера. "
            "Для каналу буде відновлено автоматичне керування. "
            "Аварійні та температурні захисти залишаться активними.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        key = channel, False
        if key in self._curve_pending:
            return
        if not self.send(command):
            QMessageBox.warning(self, "Профіль", "Не вдалося надіслати CURVE.")
            return
        if not self.send(f"AUTO {channel}"):
            QMessageBox.warning(
                self, "Профіль",
                "CURVE надіслана, але AUTO не надіслано. "
                "Перевір стан ESP32 — зміни могли застосуватися частково."
            )
            return
        self._disable_auto_for_manual_change()
        self.curves[channel] = curve
        self._curve_dirty.add(key)
        self._request_curve_readback(key, list(curve))
        if self.current_fan == channel:
            self._update_targets()
        self.log(
            f"FAN {channel:02d}: {preset} — CURVE/AUTO надіслано; "
            "чекаємо відповіді контролера"
        )

    def save_custom_profile(self) -> None:
        data = [self.curves[ch] for ch in range(1,9)]
        self.settings.setValue("customCurves", json.dumps(data))
        self.log("Custom-профіль збережено на ПК")

    def capture_fan_reference(self) -> None:
        reference = self.tach_monitor.candidate_reference(self.current_fan)
        if reference is None:
            QMessageBox.warning(self, "Fan Health",
                                "Для еталона потрібні щонайменше 4 стабільні вимірювання TACH при PWM ≥35%.")
            return
        pwm, rpm = reference
        choice = QMessageBox.question(
            self, "Fan Health",
            f"Зберегти еталон для FAN {self.current_fan}: {rpm} RPM при {pwm}% PWM?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        self.tach_monitor.set_reference(self.current_fan, pwm, rpm)
        self.settings.setValue("fanHealthRefsV1", self.tach_monitor.export_references())
        self.log(f"Fan Health FAN {self.current_fan}: еталон {rpm} RPM @ {pwm}%")

    def forget_fan_reference(self) -> None:
        self.tach_monitor.clear_reference(self.current_fan)
        self.settings.setValue("fanHealthRefsV1", self.tach_monitor.export_references())
        self.log(f"Fan Health FAN {self.current_fan}: еталон скинуто")

    def open_application_profiles(self) -> None:
        ApplicationProfilesDialog(self.settings, self._application_rules_changed, self).exec()

    def _application_rules_changed(self) -> None:
        if self.app_active and self.port:
            self.send("RTCURVE CLEAR")
        self.app_active = None
        self.app_policy.reset()

    def open_offline_profiles(self) -> None:
        if not self.port or not self.offline_supported:
            QMessageBox.warning(self, "Автономні профілі",
                "Підключи ESP32 з підтримкою OFFLINE=1")
            return
        if self.offline_dialog is None:
            self.offline_dialog = OfflineProfilesDialog(self)
        self.offline_dialog.exec()

    def open_airflow_assistant(self) -> None:
        if not self.port or not self.airflow_supported:
            QMessageBox.warning(self, "Airflow Assistant",
                "Підключи ESP32 з підтримкою AIRFLOW=1")
            return
        if self.airflow_dialog is None:
            self.airflow_dialog = AirflowDialog(self)
        self.airflow_dialog.exec()

    def open_fan_groups(self) -> None:
        FanGroupsDialog(self.settings, self.send, self, self._disable_auto_for_manual_change).exec()

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
        self._disable_auto_for_manual_change()
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
        self._disable_auto_for_manual_change()
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
        channels = self.dashboard.argb_targets(all_zones)
        if not channels:
            return
        if self.dashboard.studio.active:
            self.dashboard.studio.stop()
        if self.dashboard.temperature_argb.active:
            self.dashboard.temperature_argb.stop()
        if self.dashboard.native_checkbox.isChecked():
            self.dashboard.native_checkbox.setChecked(False)
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
            f"ARGB: {scene_name} → " + ", ".join(f"{ch:02d}" for ch in channels)
        )

    def _send_argb_quick(self, mode: str) -> None:
        targets = self.dashboard.argb_targets(False)
        if targets:
            self.send(f"{mode} {targets[0]}")

    def pick_color(self) -> None:
        targets = self.dashboard.argb_targets(False)
        if not targets:
            return
        channel = targets[0]
        if self.dashboard.temperature_argb.active:
            self.dashboard.temperature_argb.stop()
        color = QColorDialog.getColor(parent=self, title=f"ARGB {channel:02d} — колір стрічки")
        if color.isValid() and self.dashboard.is_channel_available(channel):
            self.send(f"LED {channel} {color.red()} {color.green()} {color.blue()}")

    def pick_brightness(self) -> None:
        targets = self.dashboard.argb_targets(False)
        if not targets:
            return
        channel = targets[0]
        value, accepted = QInputDialog.getInt(self, f"Яскравість ARGB {channel:02d}", "0..255:",
                                               64, 0, 255, 1)
        if accepted and self.dashboard.is_channel_available(channel):
            self.send(f"BRIGHT {channel} {value}")

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
        # Single source of truth: read/apply/verify the actual ESP32 config.
        self.dashboard.show_page("esp32")
        self.dashboard.device_settings.mqtt_host.setFocus()

    def configure_wifi(self) -> None:
        self.dashboard.show_page("esp32")
        self.dashboard.device_settings.wifi_ssid.setFocus()

    def toggle_native_openrgb(self, enabled: bool) -> None:
        self.rgb_stream.reset()
        if enabled and self.dashboard.temperature_argb.active:
            self.dashboard.temperature_argb.stop()
        if not enabled:
            self.openrgb_native.stop()
            return
        if not self.port or self.led_counts is None:
            self.log("Native OpenRGB: підключи ESP та дочекайся LEDCOUNTS")
            box = self.dashboard.native_checkbox
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
            return
        if self.bridge_checkbox.isChecked():
            self.bridge_checkbox.setChecked(False)
        if self.dashboard.studio.active:
            self.dashboard.studio.stop()
        try:
            self.openrgb_native.start(self.led_counts)
            self.dashboard.clear_argb_preview()
            self.log("OpenRGB SDK: 127.0.0.1:6743, один контролер із 8 зонами")
        except (OSError, ValueError) as exc:
            self.log(f"OpenRGB SDK: {exc}")
            box = self.dashboard.native_checkbox
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)

    def poll_native_openrgb(self) -> None:
        frames = self.openrgb_native.read_latest()
        if (not self.port or self.led_counts is None or
                not self.dashboard.native_checkbox.isChecked()):
            return
        now = time.monotonic()
        try:
            self.rgb_stream.offer(frames, self.led_counts, now=now)
            self.rgb_stream.dispatch(self.queue_rgb, now=now)
        except (ValueError, OSError, serial.SerialException) as exc:
            self.log(f"OpenRGB SDK кадр відхилено: {exc}")
            self.disconnect()

    def toggle_sacn(self, enabled: bool) -> None:
        self.rgb_stream.reset()
        if enabled and self.dashboard.temperature_argb.active:
            self.dashboard.temperature_argb.stop()
        if enabled and self.dashboard.native_checkbox.isChecked():
            self.dashboard.native_checkbox.setChecked(False)
        if enabled and self.dashboard.studio.active:
            self.dashboard.studio.stop()
        if not enabled:
            self.sacn.stop()
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
        frames = self.sacn.read_latest()
        if not self.port or self.led_counts is None:
            self.rgb_stream.reset()  # no stale replay after reconnect
            return
        now = time.monotonic()
        try:
            self.rgb_stream.offer(frames, self.led_counts, now=now)
            queued = self.rgb_stream.dispatch(self.queue_rgb, now=now)
        except (ValueError, serial.SerialException, OSError) as exc:
            self.log(f"ARGB E1.31 → USB ERROR: {exc}")
            self.disconnect()
            return
        if queued and self.tx is not None:
            self.sacn_forwarded = self.tx.frames_sent
            self.bridge_status.setText(
                f"Прийом: 127.0.0.1:{SACN_PORT} "
                f"({self.sacn_forwarded} кадрів → ESP · "
                f"ліміт ≈{self.rgb_stream.target_fps(now=now):.1f} FPS/зону)"
            )
            self.dashboard.set_bridge_state(True, self.sacn_forwarded)

    def export_history_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт історії вентиляторів", "fanargb-history.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            count = self.telemetry.export_csv(path)
            QMessageBox.information(
                self, "Історія FanARGB",
                f"Експортовано {count} вимірювань за останні 7 діб.",
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Історія", str(exc))

    def closeEvent(self, event) -> None:
        worker = getattr(self.dashboard.maintenance_panel, "worker", None)
        if worker is not None and worker.isRunning():
            QMessageBox.warning(
                self, "ESP32-S3",
                "Прошивання триває. Не закривай програму та не відключай USB.",
            )
            event.ignore()
            return
        if (not self._quit_requested and self.tray_icon is not None and
                self.dashboard.settings_panel.minimize_tray.isChecked()):
            self.hide()
            event.ignore()
            return
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.dashboard.studio.stop()
        self.audio_capture.stop()
        self.openrgb_native.stop()
        self.sacn.stop()
        self.temperature_executor.shutdown(wait=False, cancel_futures=True)
        self.app_executor.shutdown(wait=False, cancel_futures=True)
        self.sensor_sampler.close()
        self.telemetry.close()
        self.disconnect(manual=True)
        self.settings.sync()
        super().closeEvent(event)


def main() -> None:
    if "--headless" in sys.argv:
        from agent import run_agent
        sys.exit(run_agent())
    app = QApplication(sys.argv)
    # Keep native Windows controls, fonts, system theme and accessibility.
    app.setApplicationName("FanARGBControl")
    app.setOrganizationName("FanARGB")
    window = FanArgbWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

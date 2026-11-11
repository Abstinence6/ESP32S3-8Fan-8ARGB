"""Windows desktop companion: ESP32 calibration, fan curves and PC temperatures.

Run: python pc_app/main.py (from repository root or from pc_app).
Requires a running LibreHardwareMonitor Remote Web Server on localhost:8085.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional

import pyqtgraph as pg
import serial
from serial.tools import list_ports
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QColorDialog, QCheckBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QHeaderView, QAbstractItemView,
)

from monitor import (
    DEFAULT_LHM_URL, GROUP_AVG, GROUP_MAX, MAX_ALL,
    TemperatureSensor, fetch_temperatures, resolve_temperature,
)
from sacn_bridge import E131Listener, SACN_PORT, SERIAL_BAUD, encode_rgb_frame
from protocol import DEFAULT_CURVE, make_curve_command, make_temperature_command, parse_curve, parse_status


class FanArgbWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ESP32-S3 · Fan & ARGB Controller")
        self.resize(1480, 890)
        self.settings = QSettings("FanARGB", "FanARGBControl")
        self.port: Optional[serial.Serial] = None
        self.read_buffer = ""
        self.temperatures: list[TemperatureSensor] = []
        self.curves = {ch: list(DEFAULT_CURVE) for ch in range(1, 9)}
        self.cal_points: dict[int, dict[int, int]] = {ch: {} for ch in range(1, 9)}
        self.current_fan = 1
        self.target_items: list[pg.TargetItem] = []
        self.updating_targets = False
        self.fan_status: dict[int, object] = {}
        self.source_boxes: list[QComboBox] = []
        self.sensor_groups: dict[int, list[str]] = {}
        for ch in range(1, 9):
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
            desired = str(self.settings.value(f"source{ch}", MAX_ALL))
            known = [MAX_ALL, GROUP_AVG, GROUP_MAX]
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
        reread_button.clicked.connect(lambda: self.send(f"CURVE? {self.current_fan}"))
        curve_actions.addWidget(reread_button)
        curve_layout.addLayout(curve_actions)
        right_layout.addWidget(curve_box, 2)

        calibration_box = QGroupBox("Калібрування PWM → RPM (21 крок: 0–100%, по 5%)")
        calibration_layout = QVBoxLayout(calibration_box)
        cal_actions = QHBoxLayout()
        self.start_button = QPushButton("▶ Калібрувати вибраний")
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
        right_layout.addWidget(rgb_box)

        log_box = QGroupBox("Serial / діагностика")
        log_layout = QVBoxLayout(log_box)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(105)
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
        right_layout.addWidget(log_box)
        self.statusBar().showMessage("ESP: відключено — до підключення вентилятори повинні бути в fail-safe 100%")

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
            self.port = serial.Serial(port_name, SERIAL_BAUD, timeout=0, write_timeout=0.3)
            self.led_counts = None
            self.settings.setValue("port", port_name)
            self.connect_button.setText("Від'єднати")
            self.statusBar().showMessage(f"ESP: {port_name} підключено")
            self.log(f"Підключено до {port_name} ({SERIAL_BAUD} бод)")
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
        for ch in range(1, 9):
            self.send(f"CURVE? {ch}")

    def disconnect(self) -> None:
        if self.port:
            try:
                self.port.close()
            except OSError:
                pass
        self.port = None
        self.led_counts = None
        self.connect_button.setText("Підключити")
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
            row = status.channel - 1
            self.fan_table.item(row, 1).setText(f"{status.pwm}%")
            self.fan_table.item(row, 2).setText(str(status.rpm))
            self.fan_table.item(row, 3).setText(f"{status.deci_c / 10:.1f}" if status.fresh else "—")
            self.fan_table.item(row, 4).setText(
                f"{status.mode} · {'OK' if status.fresh else 'fail-safe'}"
            )
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
        try:
            self.temperatures = future.result()
            self.lhm_status.setText(f"{len(self.temperatures)} температур")
            self.lhm_status.setStyleSheet("color: #3c9c57")
        except Exception as exc:
            self.temperatures = []
            self.lhm_status.setText("Немає зв'язку з LHM")
            self.lhm_status.setToolTip(str(exc))
            self.lhm_status.setStyleSheet("color: #d05555")
        self._update_sensor_table()
        self._update_source_boxes()

        # All group sensors must be present; otherwise ESP's 10s stale watchdog
        # falls back to 100% PWM. Temperature traffic shares USB with RGB frames.
        for ch, box in enumerate(self.source_boxes, start=1):
            celsius = resolve_temperature(
                str(box.currentData()), self.temperatures, self.sensor_groups[ch]
            )
            if celsius is not None:
                try:
                    self.send(make_temperature_command(ch, celsius))
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
            for sensor in self.temperatures:
                box.addItem(f"{sensor.name} ({sensor.celsius:.1f}°C)", sensor.sensor_id)
            ids = [box.itemData(i) for i in range(box.count())]
            if saved_id not in ids:
                box.addItem("Недоступний датчик: " + saved_id, saved_id)
            box.setCurrentIndex(next(i for i in range(box.count()) if box.itemData(i) == saved_id))
            box.blockSignals(False)

    def source_changed(self, ch: int) -> None:
        box = self.source_boxes[ch - 1]
        self.settings.setValue(f"source{ch}", box.currentData())

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
            if self.source_boxes[ch - 1].currentData() not in (GROUP_AVG, GROUP_MAX):
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
        self.fan_table.selectRow(index)
        self._update_targets()
        self._update_rpm_plot()
        self.cal_progress.setValue(len(self.cal_points[self.current_fan]))

    def _update_targets(self) -> None:
        self.updating_targets = True
        for target in self.target_items:
            self.curve_plot.removeItem(target)
        self.target_items = []
        for index, (temp, pwm) in enumerate(self.curves[self.current_fan]):
            target = pg.TargetItem(pos=(temp, pwm), size=16, symbol="o", movable=True,
                                   pen=pg.mkPen("#f2f6fa", width=2), brush=pg.mkBrush("#3abac8"))
            self.curve_plot.addItem(target)
            target.sigPositionChanged.connect(lambda *args, i=index: self.target_moved(i))
            self.target_items.append(target)
        self.updating_targets = False
        self._update_curve_line()

    def _update_curve_line(self) -> None:
        points = self.curves[self.current_fan]
        self.curve_line.setData([t for t, _ in points], [p for _, p in points])

    def target_moved(self, index: int) -> None:
        if self.updating_targets or not self.target_items:
            return
        self.updating_targets = True
        points = list(self.curves[self.current_fan])
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
        self.curves[self.current_fan] = points
        self._update_curve_line()
        self.updating_targets = False

    def save_curve(self) -> None:
        try:
            message = make_curve_command(self.current_fan, self.curves[self.current_fan])
        except ValueError as exc:
            QMessageBox.warning(self, "Крива PWM", str(exc))
            return
        if self.send(message):
            self.log(f"> CURVE {self.current_fan} — запис у NVS запитано")
        else:
            QMessageBox.warning(self, "ESP", "Підключи ESP32 до збереження кривої")

    def manual_override(self) -> None:
        value, accepted = QInputDialog.getInt(self, "Ручний PWM", "Швидкість у %:",
                                               100, 0, 100, 1)
        if accepted:
            self.send(f"FAN {self.current_fan} {value}")

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
            self.send(f"CAL START {self.current_fan}")

    def _update_rpm_plot(self) -> None:
        samples = sorted(self.cal_points[self.current_fan].items())
        self.rpm_curve.setData([p for p, _ in samples], [rpm for _, rpm in samples])

    def toggle_sacn(self, enabled: bool) -> None:
        if not enabled:
            self.sacn.stop()
            self.sacn_pending.clear()
            self.bridge_status.setText("Вимкнено")
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
                self.port.write(encode_rgb_frame(ch, rgb))
                self.sacn_forwarded += 1
            except (ValueError, serial.SerialException, OSError) as exc:
                self.log(f"ARGB E1.31 → USB ERROR: {exc}")
                self.disconnect()
                return
        if self.sacn_forwarded % 50 < len(frames):
            self.bridge_status.setText(
                f"Прийом: 127.0.0.1:{SACN_PORT} ({self.sacn_forwarded} кадрів → ESP)"
            )

    def closeEvent(self, event) -> None:
        self.sacn.stop()
        self.temperature_executor.shutdown(wait=False, cancel_futures=True)
        self.disconnect()
        self.settings.sync()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FanArgbWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

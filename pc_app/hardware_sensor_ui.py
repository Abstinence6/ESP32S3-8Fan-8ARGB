"""UI for an opt-in physical DS18B20 attached directly to ESP32-S3."""
from __future__ import annotations
import re
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
)


class HardwareSensorPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Датчик ESP32-S3 · DS18B20")
        self.controller = controller
        self.available = False
        self.current_modes: dict[int, str] = {}
        self.current_maps: dict[int, str] = {}
        self.probes: dict[str, str] = {}
        layout = QVBoxLayout(self)
        self.status = QLabel("Не опитано — датчик вимкнений у стандартній прошивці")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(QLabel("Вентилятор:"))
        self.channel = QComboBox()
        for ch in range(1, 9):
            self.channel.addItem(f"Fan {ch}", ch)
        self.channel.currentIndexChanged.connect(self._query_mode)
        row.addWidget(self.channel)
        row.addWidget(QLabel("Джерело:"))
        self.mode = QComboBox()
        self.mode.addItem("Температура Windows", "PC")
        self.mode.addItem("DS18B20 локальний", "LOCAL")
        self.mode.addItem("DS18B20 резервний", "BACKUP")
        row.addWidget(self.mode)
        apply = QPushButton("Зберегти режим у ESP")
        apply.clicked.connect(self._apply)
        row.addStretch(1)
        layout.addLayout(row)
        actions = QHBoxLayout()
        actions.addWidget(apply)
        query = QPushButton("Перевірити")
        query.clicked.connect(self.refresh)
        actions.addWidget(query)
        actions.addStretch(1)
        layout.addLayout(actions)
        mapping_row = QHBoxLayout()
        mapping_row.addWidget(QLabel("Датчик (ROM):"))
        self.probe_box = QComboBox()
        self.probe_box.addItem("AUTO · лише один DS18B20 на шині", "AUTO")
        mapping_row.addWidget(self.probe_box, 1)
        save_map = QPushButton("Прив'язати до вентилятора")
        save_map.clicked.connect(self._apply_map)
        layout.addLayout(mapping_row)
        mapping_actions = QHBoxLayout()
        mapping_actions.addWidget(save_map)
        rescan = QPushButton("Сканувати 1-Wire")
        rescan.clicked.connect(self.scan)
        mapping_actions.addWidget(rescan)
        mapping_actions.addStretch(1)
        layout.addLayout(mapping_actions)
        note = QLabel(
            "LOCAL працює без Windows; BACKUP активується після 6 с без "
            "температури ПК. При втраті обох джерел PWM повертається до "
            "100%. Потрібне окреме живлення та GPIO з підтяжкою 4,7 кОм."
        )
        note.setWordWrap(True)
        note.setMinimumWidth(0)
        layout.addWidget(note)

    def refresh(self) -> None:
        self.controller.send("HTEMP?")
        self.probes.clear()
        self.controller.send("HTLIST?")
        self._query_mode()

    def scan(self) -> None:
        if not self.available:
            QMessageBox.warning(self, "DS18B20", "Апаратний датчик вимкнено у прошивці.")
            return
        self.controller.send("HTSCAN")
        self.refresh()

    def _apply_map(self) -> None:
        channel = self.channel.currentData()
        address = self.probe_box.currentData()
        if not self.available or not address or not channel:
            return
        if QMessageBox.question(
            self, "Призначення DS18B20",
            "Зберегти 64-бітну адресу термодатчика для цього вентилятора? "
            "При відключенні датчика його значення не буде підмінено іншим.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.controller.send(f"HTMAP {channel} {address}")
        self.controller.send(f"HTMAP? {channel}")

    def _query_mode(self, *_args) -> None:
        channel = self.channel.currentData()
        if channel:
            self.controller.send(f"HTMODE? {channel}")
            self.controller.send(f"HTMAP? {channel}")
            self._select_rom(int(channel))
            saved = self.current_modes.get(int(channel), "PC")
            self.mode.setCurrentIndex(max(0, self.mode.findData(saved)))

    def _apply(self) -> None:
        mode = self.mode.currentData()
        if not self.available and mode != "PC":
            QMessageBox.warning(self, "DS18B20", "Потрібна прошивка з HARDWARE_TEMP_ENABLED=1 і перевіреним GPIO.")
            return
        if mode in ("LOCAL", "BACKUP"):
            if QMessageBox.warning(
                self, "Змінити температурне джерело",
                "Якщо DS18B20 відключений, ESP32 перейде на 100% потужності вентиляторів. "
                "У режимі LOCAL для повністю автономної роботи відключи DUAL. "
                "Зберегти режим в ESP32 NVS?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
        self.controller.send(f"HTMODE {self.channel.currentData()} {mode}")
        self._query_mode()

    def _select_rom(self, channel: int) -> None:
        address = self.current_maps.get(channel, "AUTO")
        ix = self.probe_box.findData(address)
        if ix < 0 and address != "AUTO":
            self.probe_box.addItem(f"{address} · датчик відсутній", address)
            ix = self.probe_box.findData(address)
        self.probe_box.setCurrentIndex(max(0, ix))

    def handle_sensor_line(self, text: str) -> None:
        if text.startswith("HTSENSOR_END"):
            self.probe_box.blockSignals(True)
            selected_ch = int(self.channel.currentData() or 1)
            self.probe_box.clear()
            self.probe_box.addItem("AUTO · лише один DS18B20 на шині", "AUTO")
            for rom, label in sorted(self.probes.items()):
                self.probe_box.addItem(label, rom)
            self._select_rom(selected_ch)
            self.probe_box.blockSignals(False)
            return
        match = re.match(r"^\d+ ROM=([0-9A-Fa-f]{16}) VALID=([01])", text.strip())
        if not match:
            return
        rom = match.group(1).upper()
        fields = dict(x.split("=", 1) for x in text.split() if "=" in x)
        label = f"{rom} · " + (
            f"{int(fields.get('TEMP', '0')) / 10:.1f} °C" if match.group(2) == "1"
            else "немає свіжого значення"
        )
        self.probes[rom] = label

    def handle_map(self, text: str) -> None:
        match = re.fullmatch(r"(\d+) ROM=(AUTO|[0-9A-Fa-f]{16})", text.strip())
        if not match:
            return
        channel = int(match.group(1))
        if 1 <= channel <= 8:
            self.current_maps[channel] = match.group(2).upper()
            if channel == self.channel.currentData():
                self._select_rom(channel)

    def handle_status(self, text: str) -> None:
        flags = dict(x.split("=", 1) for x in text.split() if "=" in x)
        self.available = flags.get("ENABLED") == "1"
        if not self.available:
            self.status.setText("DS18B20 вимкнено у прошивці — GPIO не призначено")
        elif flags.get("VALID") != "1":
            self.status.setText("DS18B20 увімкнений, але датчик відсутній або показання недійсні")
        else:
            try:
                temp = int(flags["TEMP"]) / 10
            except (KeyError, ValueError):
                self.status.setText("Некоректна відповідь датчика")
                return
            self.status.setText(f"DS18B20: {temp:.1f} °C · свіжий вимір")

    def handle_mode(self, text: str) -> None:
        match = re.fullmatch(r"(\d+) (PC|LOCAL|BACKUP)", text.strip())
        if not match:
            return
        channel = int(match.group(1))
        if 1 <= channel <= 8:
            mode = match.group(2)
            self.current_modes[channel] = mode
            if channel == self.channel.currentData():
                index = self.mode.findData(mode)
                if index >= 0:
                    self.mode.setCurrentIndex(index)

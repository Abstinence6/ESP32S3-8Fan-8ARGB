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
        row.addWidget(apply)
        query = QPushButton("Перевірити")
        query.clicked.connect(self.refresh)
        row.addWidget(query)
        layout.addLayout(row)
        layout.addWidget(QLabel(
            "LOCAL працює без Windows; BACKUP активується після 6 с без "
            "температури ПК. При втраті обох джерел PWM повертається до "
            "100%. Потрібне окреме живлення та GPIO з підтяжкою 4,7 кОм."
        ))

    def refresh(self) -> None:
        self.controller.send("HTEMP?")
        self._query_mode()

    def _query_mode(self, *_args) -> None:
        channel = self.channel.currentData()
        if channel:
            self.controller.send(f"HTMODE? {channel}")
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

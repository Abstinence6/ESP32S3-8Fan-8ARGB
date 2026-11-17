"""Windows editor for ESP32 persistent power prediction and airflow groups."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

try:
    from .cooling_assist import (
        CoolingAssistConfig, ROLES, SOURCES, make_assist_command, parse_assist_reply,
    )
except ImportError:
    from cooling_assist import (
        CoolingAssistConfig, ROLES, SOURCES, make_assist_command, parse_assist_reply,
    )


class CoolingAssistDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("CPU/GPU Power · Intake / Exhaust")
        self.resize(780, 620)
        self.connected = False
        self.supported = False
        self._loading = False
        self._busy = False
        self._awaiting_ack = False
        self._expected: CoolingAssistConfig | None = None
        self._saved: CoolingAssistConfig | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        root = QVBoxLayout(self)
        desc = QLabel(
            "Випереджальне охолодження: ESP32 додає PWM, коли NWinfo показує "
            "високу потужність CPU/GPU. Intake може отримати додатковий PWM для "
            "переважання впуску. Exhaust ніколи не сповільнюється. "
            "Це НЕ вимірювання тиску й НЕ обходить тепловий fail-safe. "
            "Усі параметри зберігаються в NVS ESP32."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)
        form = QFormLayout()
        self.enabled = QCheckBox("Увімкнути випередження та групи")
        form.addRow("", self.enabled)
        self.cpu_start = self._spin(10, 2999, 65)
        self.cpu_full = self._spin(11, 3000, 160)
        self.gpu_start = self._spin(10, 2999, 100)
        self.gpu_full = self._spin(11, 3000, 300)
        self.boost = self._spin(0, 25, 15)
        self.bias = self._spin(0, 15, 5)
        for label, field in (
            ("CPU boost початок, W", self.cpu_start),
            ("CPU максимум, W", self.cpu_full),
            ("GPU boost початок, W", self.gpu_start),
            ("GPU максимум, W", self.gpu_full),
            ("Макс. приріст від потужності, %", self.boost),
            ("Додатково для Intake, %", self.bias),
        ):
            form.addRow(label, field)
        root.addLayout(form)
        grid = QGridLayout()
        grid.addWidget(QLabel("Канал"), 0, 0)
        grid.addWidget(QLabel("Група"), 0, 1)
        grid.addWidget(QLabel("Джерело потужності"), 0, 2)
        self.roles: list[QComboBox] = []
        self.sources: list[QComboBox] = []
        for ch in range(1, 9):
            grid.addWidget(QLabel(f"FAN {ch:02d}"), ch, 0)
            role = QComboBox()
            role.addItems(ROLES)
            grid.addWidget(role, ch, 1)
            self.roles.append(role)
            source = QComboBox()
            source.addItems(SOURCES)
            source.setCurrentIndex(3)
            grid.addWidget(source, ch, 2)
            self.sources.append(source)
        grid.setColumnStretch(2, 1)
        root.addLayout(grid)
        buttons = QHBoxLayout()
        self.read_button = QPushButton("Прочитати з ESP")
        self.read_button.clicked.connect(self.refresh)
        buttons.addWidget(self.read_button)
        self.save_button = QPushButton("Зберегти в ESP")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)
        self.status = QLabel("Підключи ESP32 з ASSIST_NVS=1")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._update_buttons()

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box

    def _update_buttons(self) -> None:
        idle = self.connected and self.supported and not self._busy
        self.read_button.setEnabled(idle)
        self.save_button.setEnabled(idle and self._saved is not None)

    def set_connected(self, value: bool) -> None:
        self.connected = bool(value)
        if not value:
            self._busy = False
            self._awaiting_ack = False
            self._timer.stop()
            self._saved = None
            self.supported = False
            self.status.setText("Відключено: налаштування збережені в ESP32 NVS")
        self._update_buttons()

    def set_supported(self, supported: bool) -> None:
        self.supported = bool(supported)
        if self.connected and self.supported:
            self.refresh()
        else:
            self.status.setText("Потрібна прошивка з ASSIST_NVS=1")
        self._update_buttons()

    def refresh(self) -> None:
        if self._busy or not self.connected or not self.supported:
            return
        self._busy = True
        if not self.controller.send("ASSIST?"):
            self._timeout()
            return
        self._timer.start(5000)
        self._update_buttons()

    def _timeout(self) -> None:
        self._busy = False
        self._awaiting_ack = False
        self._expected = None
        self._timer.stop()
        self.status.setText("⚠ ESP32 не підтвердив ASSIST; перечитай налаштування")
        self._update_buttons()

    def _load(self, config: CoolingAssistConfig) -> None:
        self._loading = True
        try:
            self.enabled.setChecked(config.enabled)
            for name, value in (
                ("cpu_start", config.cpu_start), ("cpu_full", config.cpu_full),
                ("gpu_start", config.gpu_start), ("gpu_full", config.gpu_full),
                ("boost", config.boost), ("bias", config.bias),
            ):
                getattr(self, name).setValue(value)
            for i in range(8):
                self.roles[i].setCurrentIndex(config.roles[i])
                self.sources[i].setCurrentIndex(config.sources[i])
        finally:
            self._loading = False
        self._saved = config

    def _current(self) -> CoolingAssistConfig:
        return CoolingAssistConfig(
            enabled=self.enabled.isChecked(), cpu_start=self.cpu_start.value(),
            cpu_full=self.cpu_full.value(), gpu_start=self.gpu_start.value(),
            gpu_full=self.gpu_full.value(), boost=self.boost.value(),
            bias=self.bias.value(), roles=tuple(x.currentIndex() for x in self.roles),
            sources=tuple(x.currentIndex() for x in self.sources),
        ).validate()

    def save(self) -> None:
        if self._busy or self._saved is None or not self.connected or not self.supported:
            return
        try:
            proposed = self._current()
            command = make_assist_command(proposed)
        except ValueError as exc:
            QMessageBox.warning(self, "Випереджальне охолодження", str(exc))
            return
        if proposed == self._saved:
            self.status.setText("Без змін; поточний NVS вже збігається")
            return
        if QMessageBox.question(
            self, "Запис параметрів охолодження",
            "Це змінить цільовий PWM у режимі Auto після отримання свіжої "
            "потужності CPU/GPU. Перевір тип вентиляторів, апаратний fail-ON "
            "і відповідність зовнішніх драйверів. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        self._expected = proposed
        self._awaiting_ack = True
        self._busy = True
        self._update_buttons()
        if not self.controller.send(command):
            self._timeout()
            return
        self._timer.start(5000)

    def handle_line(self, line: str) -> bool:
        if line.startswith("ERR ASSIST"):
            if self._busy:
                self._timeout()
            return True
        if line == "OK ASSIST_SAVED":
            if self._busy and self._awaiting_ack:
                self._awaiting_ack = False
                self._timer.stop()
                if not self.controller.send("ASSIST?"):
                    self._timeout()
                else:
                    self._timer.start(5000)
            return True
        if not line.startswith("ASSIST ENABLE="):
            return False
        if not self._busy or self._awaiting_ack:
            return True
        try:
            actual = parse_assist_reply(line)
            if self._expected is not None and self._expected != actual:
                raise ValueError("ESP32 повернув інше значення після NVS-запису")
        except ValueError as exc:
            self._timeout()
            self.status.setText("⚠ ASSIST: " + str(exc))
            return True
        self._timer.stop()
        self._busy = False
        self._awaiting_ack = False
        self._expected = None
        self._load(actual)
        self.status.setText("✓ Параметри Intake/Exhaust та CPU/GPU Power підтверджені ESP32 NVS")
        self._update_buttons()
        return True

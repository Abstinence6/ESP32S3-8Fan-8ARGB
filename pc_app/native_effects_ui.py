"""Native ESP32 scene editor; hardware limits and warnings remain in firmware."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSlider, QVBoxLayout,
)
try:
    from .native_effects_protocol import MODES, make_fx_set, parse_fx_line
except ImportError:
    from native_effects_protocol import MODES, make_fx_set, parse_fx_line

class NativeEffectsPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Автономні ефекти ESP32")
        self.controller = controller
        self.supported = False
        self.colors = ((20,160,255),(255,50,140))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Ефекти працюють без ПК. Аварійна індикація має пріоритет."))
        row = QHBoxLayout()
        self.channel = QComboBox()
        for i in range(1,9):
            self.channel.addItem(f"ARGB {i}",i)
        row.addWidget(self.channel)
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        row.addWidget(self.mode)
        self.direction = QCheckBox("Реверс")
        row.addWidget(self.direction)
        layout.addLayout(row)
        colors = QHBoxLayout()
        for i in range(2):
            btn = QPushButton(f"Колір {i+1}…")
            btn.clicked.connect(lambda _=False,j=i:self._pick(j))
            colors.addWidget(btn)
        layout.addLayout(colors)
        row = QHBoxLayout()
        row.addWidget(QLabel("Швидкість"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(1,10)
        self.speed.setValue(3)
        row.addWidget(self.speed)
        row.addWidget(QLabel("Яскравість"))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0,255)
        self.brightness.setValue(64)
        row.addWidget(self.brightness)
        layout.addLayout(row)
        self.boot = QCheckBox("Відтворювати при запуску ESP32 після збереження")
        layout.addWidget(self.boot)
        row = QHBoxLayout()
        self.buttons = []
        for title,fn in (("▶ Перегляд",self.preview),("■ Вимкнути",self.stop),
                         ("Зчитати",self.readback),("Зберегти у NVS",self.save)):
            button = QPushButton(title)
            button.clicked.connect(fn)
            row.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.channel.currentIndexChanged.connect(lambda *_:self.readback())
        self.set_supported(False)

    def set_supported(self, value: bool):
        self.supported = value
        for button in self.buttons:
            button.setEnabled(value)
        self.status.setText("Готово" if value else "Потрібен ESP32 з FX=1")

    def _pick(self,index):
        c = QColorDialog.getColor(QColor(*self.colors[index]),self,"Колір ARGB")
        if c.isValid():
            colors = list(self.colors)
            colors[index] = (c.red(),c.green(),c.blue())
            self.colors = tuple(colors)

    def _send(self,command):
        return bool(self.supported and self.controller.port and self.controller.send(command))

    def preview(self):
        try:
            cmd = make_fx_set(self.channel.currentData(),self.mode.currentIndex()+1,
                              *self.colors,self.speed.value(),self.brightness.value(),
                              int(self.direction.isChecked()))
        except ValueError as exc:
            QMessageBox.warning(self,"ARGB ESP32",str(exc))
            return False
        shell = self.controller.dashboard
        if shell.studio.active: shell.studio.stop()
        if shell.temperature_argb.active: shell.temperature_argb.stop()
        if shell.native_checkbox.isChecked(): shell.native_checkbox.setChecked(False)
        if self.controller.bridge_checkbox.isChecked(): self.controller.bridge_checkbox.setChecked(False)
        ok = self._send(cmd)
        self.status.setText("Сцену надіслано; NVS не змінено" if ok else "COM недоступний")
        return ok

    def save(self):
        if not self.preview(): return
        ch = self.channel.currentData()
        if self._send(f"FX BOOT {ch} {int(self.boot.isChecked())}") and self._send("FX SAVE"):
            self.status.setText("Очікування підтвердження FX_SAVED")

    def stop(self):
        if self._send(f"FX STOP {self.channel.currentData()}"):
            self.status.setText("FX STOP надіслано")

    def readback(self):
        self._send(f"FX? {self.channel.currentData()}")

    def handle_line(self,line):
        if line == "OK FX_SAVED":
            self.status.setText("ESP32 підтвердив збереження сцен у NVS")
            return True
        if line.startswith("ERR FX"):
            self.status.setText("ESP32 відхилив команду: " + line)
            return True
        state = parse_fx_line(line)
        if state is None: return False
        if state.channel == self.channel.currentData():
            self.mode.setCurrentIndex(state.mode-1)
            self.colors = (state.primary,state.secondary)
            self.speed.setValue(state.speed)
            self.brightness.setValue(state.brightness)
            self.direction.setChecked(bool(state.direction))
            self.boot.setChecked(state.boot)
            self.status.setText("Ефект активний" if state.active else "Ефект вимкнений")
        return True

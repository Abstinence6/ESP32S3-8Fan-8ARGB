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
        self._channel = 1
        self._channel_available = True
        self._drafts = {}
        self._configs = {}
        self._read_intent = {}
        self.colors = ((20,160,255),(255,50,140))
        self._default = (0, self.colors, 3, 64, False, False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Ефекти працюють без ПК. Аварійна індикація має пріоритет."))
        row = QHBoxLayout()
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
                         ("Зчитати",lambda: self.readback(replace_draft=True)),
                         ("Зберегти у NVS",self.save)):
            button = QPushButton(title)
            button.clicked.connect(fn)
            row.addWidget(button)
            self.buttons.append(button)
        self.buttons[-1].setToolTip("ESP32 зберігає всі поточні автономні сцени в NVS.")
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_supported(False)

    def set_channel(self, channel: int, available: bool):
        if channel != self._channel:
            self._remember_draft()
            self._channel = channel
            self._fill(*self._drafts.get(channel, self._configs.get(channel, self._default)))
            self.set_supported(self.supported)
        self._channel_available = available
        self._update_buttons()

    def _remember_draft(self):
        ch = self._channel
        values = (self.mode.currentIndex(), self.colors, self.speed.value(),
                  self.brightness.value(), self.direction.isChecked(), self.boot.isChecked())
        # A known draft may match the defaults after a disconnect clears the cache.
        if values == self._drafts.get(ch):
            return values
        requested = self._read_intent.get(ch)
        # A post-request edit is a draft even when it matches the old cache.
        if (values != self._configs.get(ch, self._default)
                or (requested is not None and values != requested)):
            self._drafts[ch] = values
        else:
            self._drafts.pop(ch, None)
        return values

    def _fill(self, mode, colors, speed, brightness, direction, boot):
        self.mode.setCurrentIndex(mode)
        self.colors = colors
        self.speed.setValue(speed)
        self.brightness.setValue(brightness)
        self.direction.setChecked(direction)
        self.boot.setChecked(boot)

    def set_supported(self, value: bool):
        if self.supported and not value:
            self._remember_draft()
            self._configs.clear()
            self._read_intent.clear()
            self._fill(*self._drafts.get(self._channel, self._default))
        self.supported = value
        self._update_buttons()
        if value and self._channel in self._drafts and self._channel in self._configs:
            self._show_draft_status()
        elif value and self._channel in self._configs:
            self.status.setText("Налаштування зчитано з ESP32")
        else:
            self.status.setText("Готово" if value else "Потрібен ESP32 з FX=1")

    def _show_draft_status(self):
        self.status.setText("Незбережена чернетка · «Зчитати» замінить її даними ESP32")

    def _update_buttons(self):
        for button in self.buttons:
            button.setEnabled(self.supported and self._channel_available)

    def _pick(self,index):
        c = QColorDialog.getColor(QColor(*self.colors[index]),self,"Колір ARGB")
        if c.isValid():
            colors = list(self.colors)
            colors[index] = (c.red(),c.green(),c.blue())
            self.colors = tuple(colors)

    def _ready(self):
        return self.supported and self._channel_available and self.controller.port is not None

    def _send(self,command):
        return self._ready() and self.controller.send(command)

    def preview(self):
        if not self._ready():
            return False
        try:
            cmd = make_fx_set(self._channel,self.mode.currentIndex()+1,
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
        ch = self._channel
        if self._send(f"FX BOOT {ch} {int(self.boot.isChecked())}") and self._send("FX SAVE"):
            self.status.setText("Очікування підтвердження FX_SAVED")

    def stop(self):
        if self._send(f"FX STOP {self._channel}"):
            self.status.setText("FX STOP надіслано")

    def readback(self, *, replace_draft=False):
        ch = self._channel
        requested = self._remember_draft()
        if self._send(f"FX? {ch}") and replace_draft:
            self._read_intent[ch] = requested

    def handle_line(self,line):
        if line == "OK FX_SAVED":
            self.status.setText("ESP32 підтвердив збереження сцен у NVS")
            return True
        if line.startswith("ERR FX"):
            self.status.setText("ESP32 відхилив команду: " + line)
            return True
        state = parse_fx_line(line)
        if state is None: return False
        if not self.supported: return True
        ch = state.channel
        self.controller.dashboard.note_argb_readback(ch, "FX", state.active)
        visible = ch == self._channel
        if visible:
            self._remember_draft()
        values = (state.mode-1, (state.primary,state.secondary), state.speed,
                  state.brightness, bool(state.direction), state.boot)
        self._configs[ch] = values
        draft = self._drafts.get(ch)
        expected = self._read_intent.pop(ch, None)
        if draft is not None and draft != expected and draft != values:
            if visible:
                self._show_draft_status()
            return True
        self._drafts.pop(ch, None)
        if visible:
            self._fill(*values)
            self.status.setText("Ефект активний" if state.active else "Ефект вимкнений")
        return True

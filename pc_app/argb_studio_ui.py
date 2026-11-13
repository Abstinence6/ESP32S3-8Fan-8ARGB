"""Interactive ARGB Studio: rendered effects streamed via existing safe RGB frames."""
from __future__ import annotations
import json
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSlider, QVBoxLayout,
)

try:
    from .argb_effects import MODES, render_effect
    from .sacn_bridge import encode_rgb_frame
except ImportError:
    from argb_effects import MODES, render_effect
    from sacn_bridge import encode_rgb_frame


class ArgbStudioPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("ARGB Studio · власні ефекти")
        self.controller = controller
        self.colors = ((20, 160, 255), (255, 50, 140))
        self.active = False
        self.started = 0.0
        self.next_zone = 1
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        row.addWidget(QLabel("Ефект:"))
        row.addWidget(self.mode)
        self.scope_all = QCheckBox("Усі 8 зон")
        row.addWidget(self.scope_all)
        self.color_a = QPushButton("Колір A…")
        self.color_b = QPushButton("Колір B…")
        self.color_a.clicked.connect(lambda: self._select_color(0))
        self.color_b.clicked.connect(lambda: self._select_color(1))
        row.addWidget(self.color_a)
        row.addWidget(self.color_b)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Яскравість"))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 128)  # conservative default limit; HW enforces current
        self.brightness.setValue(64)
        row2.addWidget(self.brightness)
        row2.addWidget(QLabel("Швидкість"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(10, 250)  # speed 0.2..5.0
        self.speed.setValue(50)
        row2.addWidget(self.speed)
        layout.addLayout(row2)
        actions = QHBoxLayout()
        self.start_button = QPushButton("▶ Запустити")
        self.start_button.clicked.connect(self.start)
        actions.addWidget(self.start_button)
        stop = QPushButton("■ Зупинити")
        stop.clicked.connect(self.stop)
        actions.addWidget(stop)
        save = QPushButton("Зберегти пресет")
        save.clicked.connect(self.save_preset)
        actions.addWidget(save)
        load = QPushButton("Завантажити пресет")
        load.clicked.connect(self.load_preset)
        actions.addWidget(load)
        self.status = QLabel("Очікування · передавання RGB кадрів через USB")
        actions.addWidget(self.status)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(40)

    def _select_color(self, index: int) -> None:
        from PySide6.QtGui import QColor
        current = QColor(*self.colors[index])
        chosen = QColorDialog.getColor(current, self, f"Колір {index + 1}")
        if chosen.isValid():
            colors = list(self.colors)
            colors[index] = (chosen.red(), chosen.green(), chosen.blue())
            self.colors = tuple(colors)

    def start(self) -> None:
        if not self.controller.port or not self.controller.led_counts:
            QMessageBox.warning(self, "ARGB Studio",
                                "Підключи ESP32 та дочекайся LEDCOUNTS")
            return
        if self.controller.bridge_checkbox.isChecked():
            self.controller.bridge_checkbox.setChecked(False)
        if self.controller.dashboard.native_checkbox.isChecked():
            self.controller.dashboard.native_checkbox.setChecked(False)
        self.started = time.monotonic()
        self.next_zone = 1
        self.active = True
        self.timer.start()
        self.status.setText("Активний · USB кадри")

    def stop(self) -> None:
        self.timer.stop()
        self.active = False
        self.status.setText("Зупинено · останній кадр залишається на стрічці")

    def _tick(self) -> None:
        if not self.active or not self.controller.port or not self.controller.led_counts:
            self.stop()
            return
        if self.controller.bridge_checkbox.isChecked():  # external OpenRGB owns LEDs
            self.stop()
            return
        channel = self.next_zone if self.scope_all.isChecked() else self.controller.current_fan
        if self.scope_all.isChecked():
            self.next_zone = self.next_zone % 8 + 1
        count = min(170, self.controller.led_counts[channel - 1])
        try:
            frame = render_effect(
                self.mode.currentText(), count, time.monotonic() - self.started,
                *self.colors, self.brightness.value(), self.speed.value() / 50.0,
            )
            packet = encode_rgb_frame(channel, frame)
            if not self.controller.queue_rgb(channel, packet):
                raise IOError("ARGB queue rejected frame")
        except (ValueError, OSError) as exc:
            self.stop()
            self.controller.log(f"ARGB Studio: {exc}")
            self.controller.disconnect()

    def save_preset(self) -> None:
        data = dict(version=1, mode=self.mode.currentText(), colors=self.colors,
                    brightness=self.brightness.value(), speed=self.speed.value(),
                    all_zones=self.scope_all.isChecked())
        self.controller.settings.setValue("argbStudioPreset", json.dumps(data))
        self.status.setText("Пресет збережено")

    def load_preset(self) -> None:
        try:
            data = json.loads(str(self.controller.settings.value("argbStudioPreset", "")))
            colors = data["colors"]
            if (data["version"] != 1 or data["mode"] not in MODES or
                len(colors) != 2 or any(len(c) != 3 or
                any(type(v) is not int or not 0 <= v <= 255 for v in c)
                for c in colors)):
                raise ValueError("Invalid preset")
            self.colors = tuple(tuple(c) for c in colors)
            self.mode.setCurrentText(data["mode"])
            self.brightness.setValue(max(0, min(128, int(data["brightness"]))))
            self.speed.setValue(max(10, min(250, int(data["speed"]))))
            self.scope_all.setChecked(bool(data["all_zones"]))
            self.status.setText("Пресет завантажено")
        except (ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "ARGB Studio", f"Непридатний пресет: {exc}")

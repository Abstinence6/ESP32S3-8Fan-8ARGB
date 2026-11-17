"""Eight independent ARGB zones colored by one PC sensor or a sensor group."""
from __future__ import annotations
import json
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

try:
    from .temperature_argb import (
        ASSIGNMENTS, OFF, ZoneTemperatureConfig, zone_color,
        MAX_ALL, MAX_CPU_GPU, GROUP_MAX, GROUP_AVG, GROUP_WEIGHTED,
    )
    from .sacn_bridge import encode_rgb_frame
except ImportError:
    from temperature_argb import (
        ASSIGNMENTS, OFF, ZoneTemperatureConfig, zone_color,
        MAX_ALL, MAX_CPU_GPU, GROUP_MAX, GROUP_AVG, GROUP_WEIGHTED,
    )
    from sacn_bridge import encode_rgb_frame


SOURCES = (
    (OFF, "Вимкнено"),
    (MAX_ALL, "Максимум усіх температур"),
    (MAX_CPU_GPU, "Максимум CPU/GPU"),
    (GROUP_MAX, "Максимум обраної групи"),
    (GROUP_AVG, "Середнє обраної групи"),
    (GROUP_WEIGHTED, "Зважене середнє групи (ваги = 1)"),
)


class TemperatureArgbPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("ARGB · колір за температурою")
        self.controller = controller
        self.active = False
        self._last_rgb: dict[int, tuple[int, int, int]] = {}
        self.sources: dict[int, QComboBox] = {}
        self.lows: dict[int, QSpinBox] = {}
        self.highs: dict[int, QSpinBox] = {}
        self.groups: dict[int, tuple[str, ...]] = {}
        self.labels: dict[int, QLabel] = {}
        self.configs: dict[int, ZoneTemperatureConfig] = {}
        try:
            raw = json.loads(str(controller.settings.value("temperatureArgbZones", "{}")))
            if not isinstance(raw, dict):
                raw = {}
        except (ValueError, TypeError):
            raw = {}
        for ch in range(1, 9):
            try:
                cfg = ZoneTemperatureConfig.from_dict(raw.get(str(ch), {}))
            except (ValueError, TypeError):
                cfg = ZoneTemperatureConfig()
            self.configs[ch] = cfg
            self.groups[ch] = cfg.group_ids

        root = QVBoxLayout(self)
        help_text = QLabel(
            "Кожен вихід ARGB має власний датчик або групу. "
            "Низька температура — синій/зелений, висока — жовтий/червоний. "
            "Втрачений датчик — помаранчевий. Потрібні працюючі NWinfo, USB і ПК. "
            "ESP автоматично вимкне зовнішній режим після втрати кадрів."
        )
        help_text.setWordWrap(True)
        root.addWidget(help_text)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        for col, label in enumerate(("Вихід", "Датчик / група", "Група", "Синій від °C", "Червоний від °C", "Стан")):
            grid.addWidget(QLabel(label), 0, col)
        for ch in range(1, 9):
            cfg = self.configs[ch]
            grid.addWidget(QLabel(f"ARGB {ch:02d}"), ch, 0)
            source = QComboBox()
            self.sources[ch] = source
            source.setMinimumWidth(210)
            grid.addWidget(source, ch, 1)
            group_button = QPushButton("Датчики…")
            group_button.clicked.connect(lambda _=False, index=ch: self.edit_group(index))
            grid.addWidget(group_button, ch, 2)
            low = QSpinBox()
            low.setRange(0, 124)
            low.setValue(cfg.low_c)
            self.lows[ch] = low
            grid.addWidget(low, ch, 3)
            high = QSpinBox()
            high.setRange(1, 125)
            high.setValue(cfg.high_c)
            self.highs[ch] = high
            grid.addWidget(high, ch, 4)
            status = QLabel("—")
            status.setMinimumWidth(100)
            self.labels[ch] = status
            grid.addWidget(status, ch, 5)
            source.currentIndexChanged.connect(lambda _=0, index=ch: self.save_zone(index))
            low.valueChanged.connect(lambda _=0, index=ch: self.save_zone(index))
            high.valueChanged.connect(lambda _=0, index=ch: self.save_zone(index))
        grid.setColumnStretch(1, 2)
        scroll.setWidget(content)
        root.addWidget(scroll)

        row = QHBoxLayout()
        row.addWidget(QLabel("Яскравість (обмежена):"))
        self.brightness = QSpinBox()
        self.brightness.setRange(0, 128)
        self.brightness.setValue(self.configs[1].brightness)
        self.brightness.valueChanged.connect(self._save_brightness)
        row.addWidget(self.brightness)
        start = QPushButton("▶ Запустити термо-ARGB")
        start.clicked.connect(self.start)
        row.addWidget(start)
        stop = QPushButton("■ Зупинити")
        stop.clicked.connect(self.stop)
        row.addWidget(stop)
        root.addLayout(row)
        self.status = QLabel("Очікування. Обери джерела для потрібних зон.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._tick)
        self.refresh_sensors()

    def refresh_sensors(self) -> None:
        actual = sorted(self.controller.temperatures, key=lambda s: s.name.casefold())
        for ch, combo in self.sources.items():
            selected = str(combo.currentData() or self.configs[ch].source)
            combo.blockSignals(True)
            combo.clear()
            for key, label in SOURCES:
                combo.addItem(label, key)
            for s in actual:
                combo.addItem(s.name, s.sensor_id)
            idx = combo.findData(selected)
            if idx < 0 and selected not in ASSIGNMENTS:
                combo.addItem("Недоступний: " + selected, selected)
                idx = combo.count() - 1
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)

    def save_zone(self, ch: int) -> None:
        source = str(self.sources[ch].currentData() or OFF)
        low = self.lows[ch].value()
        high = self.highs[ch].value()
        if low >= high:
            self.labels[ch].setText("Пороги: низ ≥ верх")
            return
        cfg = ZoneTemperatureConfig(
            source=source, group_ids=self.groups[ch], low_c=low, high_c=high,
            brightness=self.brightness.value(),
        )
        self.configs[ch] = cfg
        self._store()

    def _save_brightness(self) -> None:
        for ch in range(1, 9):
            cfg = self.configs[ch]
            self.configs[ch] = ZoneTemperatureConfig(
                source=cfg.source, group_ids=cfg.group_ids, low_c=cfg.low_c,
                high_c=cfg.high_c, brightness=self.brightness.value(),
            )
        self._store()

    def _store(self) -> None:
        self.controller.settings.setValue(
            "temperatureArgbZones",
            json.dumps({str(ch): cfg.as_dict() for ch, cfg in self.configs.items()},
                       ensure_ascii=False),
        )

    def edit_group(self, ch: int) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"ARGB {ch} · датчики групи")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Обери всі датчики, що входять до групи:"))
        listing = QListWidget()
        saved = set(self.groups[ch])
        for sensor in sorted(self.controller.temperatures, key=lambda s: s.name.casefold()):
            item = QListWidgetItem(sensor.name)
            item.setData(Qt.ItemDataRole.UserRole, sensor.sensor_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if sensor.sensor_id in saved else Qt.CheckState.Unchecked)
            listing.addItem(item)
        for sid in sorted(saved - {s.sensor_id for s in self.controller.temperatures}):
            item = QListWidgetItem("Недоступний: " + sid)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            listing.addItem(item)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.groups[ch] = tuple(
            str(listing.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(listing.count())
            if listing.item(i).checkState() == Qt.CheckState.Checked
        )
        self.save_zone(ch)

    def start(self) -> None:
        if not self.controller.port or not self.controller.led_counts:
            QMessageBox.warning(self, "ARGB температура",
                                "Підключи ESP32 і дочекайся LEDCOUNTS")
            return
        if all(cfg.source == OFF for cfg in self.configs.values()):
            QMessageBox.warning(self, "ARGB температура", "Признач хоча б один ARGB вихід")
            return
        if self.controller.dashboard.studio.active:
            self.controller.dashboard.studio.stop()
        if self.controller.dashboard.native_checkbox.isChecked():
            self.controller.dashboard.native_checkbox.setChecked(False)
        if self.controller.bridge_checkbox.isChecked():
            self.controller.bridge_checkbox.setChecked(False)
        self.active = True
        self._last_rgb.clear()
        self.timer.start()
        self._tick()

    def stop(self) -> None:
        self.timer.stop()
        self.active = False
        self.status.setText("Зупинено · зовнішні кадри згаснуть після 3 с")

    def _tick(self) -> None:
        if not self.active:
            return
        if not self.controller.port or not self.controller.led_counts or (
            self.controller.bridge_checkbox.isChecked()
            or self.controller.dashboard.native_checkbox.isChecked()
            or self.controller.dashboard.studio.active
        ):
            self.stop()
            return
        fresh = (
            time.monotonic() - self.controller.last_temperature_sample_at <= 7.0
            and bool(self.controller.temperatures)
        )
        count = 0
        for ch, cfg in self.configs.items():
            if cfg.source == OFF:
                self.labels[ch].setText("Вимкнено")
                continue
            color = zone_color(cfg, self.controller.temperatures, fresh=fresh)
            if color is None:
                continue
            num_leds = min(170, self.controller.led_counts[ch - 1])
            try:
                packet = encode_rgb_frame(ch, bytes(color) * num_leds)
                if not self.controller.queue_rgb(ch, packet):
                    raise OSError("Unable to queue ARGB frame")
            except (OSError, ValueError) as exc:
                self.stop()
                self.controller.log(f"ARGB температура: {exc}")
                return
            self.labels[ch].setText(
                "● Датчик втрачено" if not fresh or color == zone_color(
                    cfg, [], fresh=False) else "● Активно"
            )
            count += 1
        self.status.setText(
            f"Термо-ARGB: {count} зон · " + (
                "датчики актуальні" if fresh else "неактуальні; помаранчевий сигнал"
            )
        )

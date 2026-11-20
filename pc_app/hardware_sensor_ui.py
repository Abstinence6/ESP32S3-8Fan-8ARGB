"""UI for an opt-in physical DS18B20 attached directly to ESP32-S3."""
from __future__ import annotations
import re
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


_UNCHECKED = "Не опитано — підключіть ESP32-S3 і перевірте підтримку DS18B20."


class HardwareSensorPanel(QGroupBox):
    support_changed = Signal(bool)
    probes_changed = Signal()

    def __init__(self, controller):
        super().__init__("Датчик ESP32-S3 · DS18B20")
        self.controller = controller
        self.available = False
        self.probes: dict[str, str] = {}
        self._pending_probes: dict[str, str] = {}
        layout = QVBoxLayout(self)
        self.status = QLabel(_UNCHECKED)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        query = QPushButton("Перевірити датчик")
        query.clicked.connect(self.refresh)
        actions.addWidget(query)
        self.rescan = QPushButton("Сканувати 1-Wire")
        self.rescan.clicked.connect(self.scan)
        self.rescan.hide()
        actions.addWidget(self.rescan)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.readings = QLabel()
        self.readings.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.readings.setWordWrap(True)
        self.readings.hide()
        layout.addWidget(self.readings)
        hint = QLabel("Призначення: Охолодження → вибраний FAN → Джерело температури.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _set_available(self, available: bool) -> None:
        if self.available == available:
            return
        self.available = available
        self.rescan.setVisible(available)
        self.readings.setVisible(available and bool(self.probes))
        self.support_changed.emit(available)

    def reset_status(self) -> None:
        self._set_available(False)
        self.probes.clear()
        self._pending_probes.clear()
        self.readings.clear()
        self.probes_changed.emit()
        self.status.setText(_UNCHECKED)

    def refresh(self) -> None:
        self.controller.send("HTEMP?")
        self.controller.send("HTLIST?")

    def scan(self) -> None:
        if self.available:
            self.controller.send("HTSCAN")
            self.refresh()

    def handle_sensor_line(self, text: str) -> None:
        if text.startswith("HTSENSOR_END"):
            self.probes = self._pending_probes
            self._pending_probes = {}
            self.readings.setText("\n".join(self.probes.values()))
            self.readings.setVisible(self.available and bool(self.probes))
            self.probes_changed.emit()
            return
        match = re.match(r"^\d+ ROM=([0-9A-Fa-f]{16}) VALID=([01])", text.strip())
        if not match:
            return
        rom = match.group(1).upper()
        fields = dict(x.split("=", 1) for x in text.split() if "=" in x)
        reading = "немає свіжого значення"
        if match.group(2) == "1":
            try:
                reading = f"{int(fields['TEMP']) / 10:.1f} °C"
            except (KeyError, ValueError):
                pass
        self._pending_probes[rom] = f"{rom} · {reading}"

    def handle_status(self, text: str) -> None:
        flags = dict(x.split("=", 1) for x in text.split() if "=" in x)
        self._set_available(flags.get("ENABLED") == "1")
        if flags.get("ENABLED") == "0":
            self.status.setText("DS18B20 вимкнено у прошивці — призначення недоступні.")
        elif not self.available:
            self.status.setText("Не вдалося перевірити підтримку DS18B20.")
        elif flags.get("VALID") != "1":
            self.status.setText("DS18B20 увімкнений, але датчик відсутній або показання недійсні")
        else:
            try:
                temp = int(flags["TEMP"]) / 10
            except (KeyError, ValueError):
                self.status.setText("Некоректна відповідь датчика")
                return
            self.status.setText(f"DS18B20: {temp:.1f} °C · свіжий вимір")


class FanTemperatureSourceDialog(QDialog):
    def __init__(self, sensor: HardwareSensorPanel, parent: QWidget):
        super().__init__(parent)
        self.sensor = sensor
        self.channel: int | None = None
        self._mapped_rom: str | None = None
        self._draft_mode: str | None = None
        self._draft_rom: str | None = None
        self._pending_mode: str | None = None
        self._pending_rom: str | None = None
        layout = QVBoxLayout(self)
        note = QLabel(
            "Налаштування основної кривої ESP32. Датчик Windows вибирається окремо; "
            "друга крива (DUAL) не змінюється.\n"
            "Основний DS18B20 працює без Windows; резервний — після 6 с без даних ПК."
        )
        note.setWordWrap(True)
        note.setMinimumWidth(410)
        note.setMinimumHeight(note.heightForWidth(note.minimumWidth()))
        layout.addWidget(note)
        self.mode = QComboBox()
        self.mode.setPlaceholderText("Очікуємо режим з ESP32…")
        self.mode.setAccessibleName("Джерело температури для основної кривої")
        self.mode.addItem("Температура Windows", "PC")
        self.mode.addItem("DS18B20 · основне джерело", "LOCAL")
        self.mode.addItem("DS18B20 · резервне джерело", "BACKUP")
        layout.addWidget(self.mode)
        self.save_mode = QPushButton("Зберегти джерело в ESP32")
        self.save_mode.clicked.connect(self._apply_mode)
        layout.addWidget(self.save_mode, alignment=Qt.AlignmentFlag.AlignLeft)

        self.mapping = QGroupBox("Прив’язка DS18B20 (ROM)")
        mapping_layout = QVBoxLayout(self.mapping)
        self.probe_box = QComboBox()
        self.probe_box.setPlaceholderText("Очікуємо прив’язку з ESP32…")
        self.probe_box.setAccessibleName("ROM датчика DS18B20")
        mapping_layout.addWidget(self.probe_box)
        self.save_map = QPushButton("Зберегти прив’язку в ESP32")
        self.save_map.clicked.connect(self._apply_map)
        mapping_layout.addWidget(self.save_map, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.mapping)
        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.button(QDialogButtonBox.StandardButton.Close).setText("Закрити")
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)
        self.mode.currentIndexChanged.connect(self._update_controls)
        self.mode.activated.connect(self._edit_mode)
        self.probe_box.activated.connect(self._edit_rom)
        self.sensor.probes_changed.connect(self._populate_probe_box)
        self.finished.connect(self._clear)
        self.resize(450, self.sizeHint().height())
        self._clear()

    def _clear(self) -> None:
        self.channel = None
        self._mapped_rom = None
        self._draft_mode = self._draft_rom = None
        self._pending_mode = self._pending_rom = None
        self.mode.setCurrentIndex(-1)
        self._populate_probe_box()

    def open_for_channel(self, channel: int) -> None:
        self.channel = channel
        self.setWindowTitle(f"Джерело температури · FAN {channel:02d}")
        self.open()
        self.sensor.controller.send(f"HTMODE? {channel}")
        self.sensor.controller.send(f"HTMAP? {channel}")

    def _edit_mode(self) -> None:
        self._draft_mode = self.mode.currentData()
        self._pending_mode = None

    def _edit_rom(self) -> None:
        self._draft_rom = self.probe_box.currentData()
        self._pending_rom = None

    def _update_controls(self) -> None:
        has_mode = self.mode.currentIndex() >= 0
        self.mode.setEnabled(has_mode)
        self.save_mode.setEnabled(has_mode)
        self.mapping.setVisible(self.mode.currentData() in ("LOCAL", "BACKUP"))
        self.mapping.setEnabled(self._mapped_rom is not None)

    def _populate_probe_box(self) -> None:
        self.probe_box.clear()
        self.probe_box.addItem("AUTO · лише один DS18B20 на шині", "AUTO")
        for rom, label in sorted(self.sensor.probes.items()):
            self.probe_box.addItem(label, rom)
        for rom in (self._mapped_rom, self._draft_rom):
            if rom is not None and self.probe_box.findData(rom) < 0:
                self.probe_box.addItem(f"{rom} · датчик відсутній", rom)
        self.probe_box.setCurrentIndex(self.probe_box.findData(self._draft_rom or self._mapped_rom))
        self._update_controls()

    def _apply_mode(self) -> None:
        channel = self.channel
        mode = self.mode.currentData()
        if channel is None or not self.sensor.available or mode is None:
            return
        if mode in ("LOCAL", "BACKUP") and QMessageBox.warning(
            self, "Змінити температурне джерело",
            "Якщо крива охолодження не отримує свіжої температури, спрацьовує захисний режим. "
            "У режимі LOCAL для повністю автономної роботи відключіть DUAL. "
            "Зберегти режим в ESP32 NVS?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.channel != channel or not self.sensor.available:
            return
        if self.sensor.controller.send(f"HTMODE {channel} {mode}"):
            self._pending_mode = mode
            self.sensor.controller.send(f"HTMODE? {channel}")

    def _apply_map(self) -> None:
        channel = self.channel
        address = self.probe_box.currentData()
        if (channel is None or not self.sensor.available or not address
                or self.mode.currentData() not in ("LOCAL", "BACKUP")):
            return
        if QMessageBox.question(
            self, "Призначення DS18B20",
            "Зберегти прив’язку DS18B20 для цього вентилятора? "
            "AUTO працює лише з одним датчиком на шині. Вказаний ROM не підміняється іншим датчиком.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.channel != channel or not self.sensor.available:
            return
        if self.sensor.controller.send(f"HTMAP {channel} {address}"):
            self._pending_rom = address
            self.sensor.controller.send(f"HTMAP? {channel}")

    def handle_mode(self, text: str) -> None:
        match = re.fullmatch(r"(\d+) (PC|LOCAL|BACKUP)", text.strip())
        if not match or int(match.group(1)) != self.channel:
            return
        mode = match.group(2)
        # Only a matching readback after Save can release the draft.
        if mode == self._pending_mode:
            self._draft_mode = self._pending_mode = None
        if self._draft_mode is None:
            self.mode.setCurrentIndex(self.mode.findData(mode))

    def handle_map(self, text: str) -> None:
        match = re.fullmatch(r"(\d+) ROM=(AUTO|[0-9A-Fa-f]{16})", text.strip())
        if not match or int(match.group(1)) != self.channel:
            return
        self._mapped_rom = match.group(2).upper()
        if self._mapped_rom == self._pending_rom:
            self._draft_rom = self._pending_rom = None
        self._populate_probe_box()

"""Interactive ESP32-S3 GPIO mapping; changes live only after reboot."""
from __future__ import annotations
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

try:
    from .pinmap_config import TYPES, DEFAULTS, default_map, validate_map, allowed_for_slot
except ImportError:
    from pinmap_config import TYPES, DEFAULTS, default_map, validate_map, allowed_for_slot


class GpioSettingsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ESP32-S3 · GPIO PWM / TACH / ARGB")
        self.resize(800, 655)
        self.controller = controller
        self.connected = False
        self.supported = False
        self._n16r8 = False
        self._loaded = False
        self._loading = False
        self._dirty = False
        self._reading = False
        self._reply: dict[str, list[int]] = {}
        self._saved = default_map()
        self._expected: dict[str, list[int]] | None = None
        self._operations: deque[tuple[str, str]] = deque()
        self._waiting_ack: str | None = None
        self._verify = False
        self.reboot_required = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        root = QVBoxLayout(self)
        hint = QLabel(
            "ESP32 зберігає GPIO у NVS. Нове призначення набуває чинності "
            "ЛИШЕ ПІСЛЯ ПЕРЕЗАВАНТАЖЕННЯ. Підтверди фізичну розводку PWM, "
            "TACH, ARGB та апаратний fail-ON вентиляторів. Службові GPIO "
            "заблоковані, а старі винятки PSRAM/bootstrapping збережені "
            "тільки на заводських місцях."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.addWidget(QLabel("Канал"), 0, 0)
        for col, kind in enumerate(TYPES, 1):
            grid.addWidget(QLabel(kind), 0, col)
        self.controls: dict[tuple[str, int], QComboBox] = {}
        for ch in range(1, 9):
            grid.addWidget(QLabel(str(ch)), ch, 0)
            for col, kind in enumerate(TYPES, 1):
                box = QComboBox()
                for pin in range(49):
                    if allowed_for_slot(pin, kind, ch):
                        suffix = " · заводський ризик" if pin in (33, 34, 35, 36, 37, 46) else ""
                        box.addItem(f"GPIO{pin}{suffix}", pin)
                box.setCurrentIndex(box.findData(DEFAULTS[kind][ch - 1]))
                box.currentIndexChanged.connect(self._changed)
                grid.addWidget(box, ch, col)
                self.controls[(kind, ch)] = box
        scroller.setWidget(holder)
        root.addWidget(scroller)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Прочитати з ESP")
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_button)
        self.save_button = QPushButton("Зберегти GPIO в ESP")
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        self.factory_button = QPushButton("Заводська розкладка")
        self.factory_button.clicked.connect(self.factory)
        actions.addWidget(self.factory_button)
        root.addLayout(actions)
        self.status = QLabel("Налаштування GPIO недоступні до підключення ESP32.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._update_buttons()

    def _busy(self) -> bool:
        return self._reading or self._waiting_ack is not None or self._verify

    def _update_buttons(self) -> None:
        ready = self.connected and self.supported and not self._busy()
        self.refresh_button.setEnabled(ready)
        self.save_button.setEnabled(ready and self._loaded and self._dirty)
        self.factory_button.setEnabled(ready and self._loaded)
        for box in self.controls.values():
            box.setEnabled(ready and self._loaded)

    def set_connected(self, value: bool) -> None:
        self.connected = bool(value)
        if not value:
            self._timer.stop()
            self._reading = False
            self._waiting_ack = None
            self._operations.clear()
            self._verify = False
            self._loaded = False
            self.supported = False
            self._n16r8 = False
            self._dirty = False
            self.status.setText("ESP32 відключено — GPIO залишились у NVS.")
        self._update_buttons()

    def set_supported(self, value: bool, *, n16r8: bool = False) -> None:
        self.supported = bool(value)
        self._n16r8 = bool(n16r8)
        if self.supported and self.connected:
            self.refresh()
        else:
            self.status.setText("Потрібна прошивка із GPIO_NVS=1.")
            self._update_buttons()

    def _changed(self, *_args) -> None:
        if not self._loading:
            self._dirty = True
            self.status.setText("Незбережені зміни; застосування після reboot ESP32.")
            self._update_buttons()

    def _map_from_controls(self) -> dict[str, list[int]]:
        return {kind: [int(self.controls[(kind, ch)].currentData())
                       for ch in range(1, 9)] for kind in TYPES}

    def _load_controls(self, pins: dict[str, list[int]]) -> None:
        self._loading = True
        try:
            for kind in TYPES:
                for ch in range(1, 9):
                    box = self.controls[(kind, ch)]
                    index = box.findData(pins[kind][ch - 1])
                    if index < 0:
                        raise ValueError("Заборонений GPIO у відповіді ESP")
                    box.setCurrentIndex(index)
        finally:
            self._loading = False
        self._dirty = False
        self._loaded = True
        self._update_buttons()

    def refresh(self) -> None:
        if self.connected and self.supported and not self._busy():
            self._request_readback()

    def _request_readback(self) -> None:
        self._reply = {}
        self._reading = True
        self._update_buttons()
        if not self.controller.send("GPIO?"):
            self._fail("Не вдалося прочитати GPIO через USB")
            return
        self._timer.start(5000)

    def _timeout(self) -> None:
        self._fail("ESP32 не відповів на GPIO-команду")

    def _fail(self, message: str) -> None:
        self._timer.stop()
        if self._waiting_ack is not None and self.connected:
            self.controller.send("GPIO CANCEL")
        self._reading = False
        self._waiting_ack = None
        self._operations.clear()
        self._verify = False
        self._expected = None
        self.status.setText("Помилка: " + message)
        self._update_buttons()

    def save(self) -> None:
        if not (self.connected and self.supported and self._loaded) or self._busy():
            return
        desired = self._map_from_controls()
        try:
            validate_map(desired)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if desired == self._saved:
            self._dirty = False
            self._update_buttons()
            return
        if QMessageBox.question(
            self, "Підтвердження фізичної GPIO-розводки",
            "Перевір: PWM відповідає розводці плати, драйвер забезпечує "
            "fail-ON, TACH і ARGB не конфліктують. Помилкові GPIO можуть "
            "зупинити вентилятори! Після запису потрібен reboot. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        commands = [("GPIO BEGIN", "OK GPIO_BEGIN")]
        for kind in TYPES:
            for ch in range(1, 9):
                pin = desired[kind][ch - 1]
                if pin != self._saved[kind][ch - 1]:
                    commands.append((f"GPIO {kind} {ch} {pin}", "OK GPIO_PIN"))
        commands.append(("GPIO COMMIT", "OK GPIO_SAVED REBOOT_REQUIRED"))
        self._expected = desired
        self._operations = deque(commands)
        self.status.setText("Запис і перевірка GPIO в NVS ESP32…")
        self._send_next()

    def factory(self) -> None:
        if not self.connected or not self.supported or self._busy():
            return
        if QMessageBox.question(
            self, "Заводська розкладка",
            "Відновити заводські GPIO з NVS (потрібне перезавантаження)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        # GPIO FACTORY restores firmware defaults, which differ on N16R8.
        self._expected = default_map(n16r8=self._n16r8)
        self._operations = deque([("GPIO FACTORY", "OK GPIO_FACTORY REBOOT_REQUIRED")])
        self._send_next()

    def _send_next(self) -> None:
        self._timer.stop()
        self._waiting_ack = None
        if not self._operations:
            self._verify = True
            self._request_readback()
            return
        command, ack = self._operations.popleft()
        self._waiting_ack = ack
        self._update_buttons()
        if not self.controller.send(command):
            self._fail("USB запис GPIO не вдався")
            return
        self._timer.start(5000)

    def handle_line(self, line: str) -> bool:
        if self._waiting_ack is not None:
            if line == self._waiting_ack:
                self._send_next()
                return True
            if line.startswith("ERR "):
                self._fail("Контролер відхилив GPIO команду: " + line)
                return True
        if line.startswith("GPIO_END "):
            if not self._reading:
                return True
            try:
                if set(self._reply) != set(TYPES):
                    raise ValueError("Неповна відповідь ESP")
                validate_map(self._reply)
                marker = line.split("REBOOT=", 1)[1].strip()
                if marker not in ("0", "1"):
                    raise ValueError("Некоректний reboot статус")
                self.reboot_required = marker == "1"
                result = {kind: list(self._reply[kind]) for kind in TYPES}
                if self._verify and result != self._expected:
                    raise ValueError("Прочитані GPIO не збігаються із записаними")
            except (ValueError, IndexError, KeyError) as exc:
                self._fail(str(exc))
                return True
            self._timer.stop()
            self._reading = False
            self._saved = result
            self._verify = False
            self._expected = None
            try:
                self._load_controls(result)
            except ValueError as exc:
                self._fail(str(exc))
                return True
            self.status.setText("GPIO збережено в ESP32. " +
                ("Перезавантаж ESP32 для застосування!" if self.reboot_required
                 else "Застосовано."))
            self._update_buttons()
            return True
        if line.startswith("GPIO "):
            if not self._reading:
                return True
            parts = line.split()
            if len(parts) != 10 or parts[1] not in TYPES:
                self._fail("Некоректна відповідь GPIO")
                return True
            try:
                self._reply[parts[1]] = [int(s) for s in parts[2:]]
            except ValueError:
                self._fail("Неправильне число GPIO")
            return True
        return False

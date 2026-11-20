"""PC UI for per-zone ARGB temperature settings stored in ESP32 NVS.

All writes are explicit, one zone at a time, ACK-checked and verified by a
fresh controller readback. QSettings is deliberately not used for this config.
"""
from __future__ import annotations

from collections import deque
import math
import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

try:
    from .device_config_protocol import decode_value, encode_value, fields
    from .monitor import resolve_temperature
    from .temperature_argb import (
        ASSIGNMENTS, OFF, ZoneTemperatureConfig, zone_color,
        MAX_ALL, MAX_CPU_GPU, GROUP_MAX, GROUP_AVG, GROUP_WEIGHTED,
        TEMPERATURE_GRADIENT, TEMPERATURE_SAMPLE_TTL, temperature_color,
    )
    from .sacn_bridge import encode_rgb_frame
    from .temperature_palette import DEFAULT_PALETTE, Palette, make_palette_command, parse_palette_reply
    from .temperature_palette_ui import TemperaturePaletteDialog
except ImportError:
    from device_config_protocol import decode_value, encode_value, fields
    from monitor import resolve_temperature
    from temperature_argb import (
        ASSIGNMENTS, OFF, ZoneTemperatureConfig, zone_color,
        MAX_ALL, MAX_CPU_GPU, GROUP_MAX, GROUP_AVG, GROUP_WEIGHTED,
        TEMPERATURE_GRADIENT, TEMPERATURE_SAMPLE_TTL, temperature_color,
    )
    from sacn_bridge import encode_rgb_frame
    from temperature_palette import DEFAULT_PALETTE, Palette, make_palette_command, parse_palette_reply
    from temperature_palette_ui import TemperaturePaletteDialog

SOURCES = (
    (OFF, "Вимкнено"),
    (MAX_ALL, "Максимум усіх температур"),
    (MAX_CPU_GPU, "Максимум CPU/GPU"),
    (GROUP_MAX, "Максимум обраної групи"),
    (GROUP_AVG, "Середнє обраної групи"),
    (GROUP_WEIGHTED, "Зважене середнє групи (рівні ваги)"),
)


class TemperatureGradient(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(16)
        self.stops = ()
        self.marker: float | None = None

    def set_scale(self, stops, marker: float | None) -> None:
        if (self.stops, self.marker) != (stops, marker):
            self.stops, self.marker = stops, marker
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        bar = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.stops:
            gradient = QLinearGradient(bar.left(), 0, bar.right(), 0)
            for position, rgb in self.stops:
                gradient.setColorAt(position, QColor(*rgb))
            painter.fillRect(bar, gradient)
        else:
            painter.fillRect(bar, self.palette().mid())
        if self.marker is not None:
            x = bar.left() + self.marker * bar.width()
            painter.fillRect(QRectF(x - 2, 0, 4, self.height()), QColor("black"))
            painter.fillRect(QRectF(x - 1, 0, 2, self.height()), QColor("white"))


class TemperatureArgbPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("ARGB · колір за температурою")
        self.controller = controller
        self.connected = False
        self.supported = False
        self.active = False
        self._channel = 1
        self._channel_mask = 0xFF
        self._loading = False
        self._loaded: set[int] = set()
        self._dirty: set[int] = set()
        self.sources: dict[int, QComboBox] = {}
        self.lows: dict[int, QSpinBox] = {}
        self.highs: dict[int, QSpinBox] = {}
        self.brightness: dict[int, QSpinBox] = {}
        self.groups: dict[int, tuple[str, ...]] = {ch: () for ch in range(1, 9)}
        self.labels: dict[int, QLabel] = {}
        self.save_buttons: dict[int, QPushButton] = {}
        self.configs = {ch: ZoneTemperatureConfig() for ch in range(1, 9)}
        self.palette_supported = False
        self.palettes: dict[int, Palette] = {}
        self.palette_buttons: dict[int, QPushButton] = {}
        self._palette_queue: deque[int] = deque()
        self._palette_pending: int | None = None
        self._palette_expected: Palette | None = None
        self._palette_ack = False
        self._palette_timer = QTimer(self)
        self._palette_timer.setSingleShot(True)
        self._palette_timer.timeout.connect(self._palette_failed)

        # Exactly one command or readback transaction at a time. UI never
        # reports successful flash persistence until the ESP echoes its data.
        self._read_queue: deque[int] = deque()
        self._reading_ch: int | None = None
        self._read_value: dict | None = None
        self._write_queue: deque[tuple[str, str]] = deque()
        self._await_ack: str | None = None
        self._write_ch: int | None = None
        self._expected: ZoneTemperatureConfig | None = None
        self._verify = False
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._timeout)

        root = QVBoxLayout(self)
        help_label = QLabel(
            "Призначення датчиків, групи й пороги записуються до NVS ESP32 "
            "та відновлюються після перезапуску. Потрібні ПК, NWinfo й USB, "
            "щоб передавати поточні температури. "
            "Синій → зелений → жовтий → червоний. "
            "Якщо датчик втрачено — помаранчевий колір."
        )
        help_label.setWordWrap(True)
        root.addWidget(help_label)
        content = QWidget()
        self._grid = grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        headers = (
            "Зона", "Датчик / група", "Група", "Низ, °C", "Верх, °C",
            "Яскр.", "Стан", "NVS", "Кольори"
        )
        for col, caption in enumerate(headers):
            grid.addWidget(QLabel(caption), 0, col)
        for ch in range(1, 9):
            grid.addWidget(QLabel(f"ARGB {ch:02d}"), ch, 0)
            source = QComboBox()
            source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            source.setMinimumWidth(130)
            self.sources[ch] = source
            grid.addWidget(source, ch, 1)
            group = QPushButton("Датчики…")
            group.clicked.connect(lambda _=False, channel=ch: self.edit_group(channel))
            grid.addWidget(group, ch, 2)
            low = QSpinBox()
            low.setRange(0, 124)
            low.setValue(30)
            self.lows[ch] = low
            grid.addWidget(low, ch, 3)
            high = QSpinBox()
            high.setRange(1, 125)
            high.setValue(85)
            self.highs[ch] = high
            grid.addWidget(high, ch, 4)
            bright = QSpinBox()
            bright.setRange(0, 128)
            bright.setValue(64)
            self.brightness[ch] = bright
            grid.addWidget(bright, ch, 5)
            status = QLabel("Немає відповіді ESP")
            status.setWordWrap(True)
            status.setMinimumWidth(80)
            self.labels[ch] = status
            grid.addWidget(status, ch, 6)
            save = QPushButton("Зберегти")
            save.setToolTip("Зберегти в ESP")
            save.setAccessibleName("Зберегти в ESP")
            save.clicked.connect(lambda _=False, channel=ch: self.save_zone(channel))
            self.save_buttons[ch] = save
            grid.addWidget(save, ch, 7)
            palette_button = QPushButton("Палітра…")
            palette_button.clicked.connect(lambda _=False, channel=ch: self.edit_palette(channel))
            self.palette_buttons[ch] = palette_button
            grid.addWidget(palette_button, ch, 8)
            source.currentIndexChanged.connect(lambda _=0, channel=ch: self._mark_dirty(channel))
            low.valueChanged.connect(lambda _=0, channel=ch: self._mark_dirty(channel))
            high.valueChanged.connect(lambda _=0, channel=ch: self._mark_dirty(channel))
            bright.valueChanged.connect(lambda _=0, channel=ch: self._mark_dirty(channel))
        grid.setColumnStretch(1, 2)
        root.addWidget(content)
        self.gradient_status = QLabel()
        self.gradient_status.setWordWrap(True)
        root.addWidget(self.gradient_status)
        self.gradient = TemperatureGradient()
        self.gradient.setAccessibleName("Чернетка температурної шкали ARGB")
        root.addWidget(self.gradient)
        self.draft_color: tuple[int, int, int] | None = None
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("↻ Зчитати вибрану зону")
        self.refresh_button.clicked.connect(self.refresh_selected)
        actions.addWidget(self.refresh_button)
        self.start_button = QPushButton("▶ Запустити всі налаштовані зони")
        self.start_button.clicked.connect(self.start)
        actions.addWidget(self.start_button)
        self.stop_button = QPushButton("■ Зупинити всі термо-зони")
        self.stop_button.clicked.connect(self.stop)
        actions.addWidget(self.stop_button)
        root.addLayout(actions)
        self.status = QLabel("Підключи ESP32 з підтримкою TARGB (serial v8+).")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._tick)
        self.refresh_sensors()
        self.set_channel(1, 0xFF)

    def set_channel(self, channel: int, mask: int) -> None:
        self._channel = channel
        self._channel_mask = mask
        for ch in self.sources:
            for col in range(self._grid.columnCount()):
                widget = self._grid.itemAtPosition(ch, col).widget()
                widget.setVisible(ch == channel)
            self._grid.itemAtPosition(ch, 2).widget().setEnabled(self._available(ch))
        self._update_buttons()
        self.refresh_gradient()

    def refresh_gradient(self) -> None:
        ch = self._channel
        self.draft_color = None
        stops, marker = (), None
        if not self._available(ch):
            text = "Канал недоступний"
        elif self.lows[ch].value() >= self.highs[ch].value():
            text = "Нижній поріг має бути меншим за верхній"
        else:
            try:
                cfg = self._edited_config(ch)
            except ValueError:
                self.gradient.set_scale((), None)
                self.gradient_status.setText("Чернетка · некоректне джерело або група")
                return
            palette = self.palettes.get(ch) if self.palette_supported else None
            low, high = (palette[0][0], palette[-1][0]) if palette else (cfg.low_c, cfg.high_c)
            stops = tuple(((t - low) / (high - low), (r, g, b)) for t, r, g, b in palette) if palette else TEMPERATURE_GRADIENT
            reading = None
            source = self.sources[ch].currentText()
            if cfg.source == OFF:
                text = "Джерело вимкнено"
            elif not self.connected:
                text = f"ПК · {source} · ESP32 не підключено"
            elif time.monotonic() - self.controller.last_temperature_sample_at > TEMPERATURE_SAMPLE_TTL:
                text = f"ПК · {source} · дані відсутні або застаріли"
            else:
                reading = resolve_temperature(cfg.source, self.controller.temperatures, cfg.group_ids)
                if reading is None or not math.isfinite(reading) or not 0 <= reading <= 125:
                    reading = None
                    text = f"ПК · {source} · немає температури"
                else:
                    marker = max(0.0, min(1.0, (reading - low) / (high - low)))
                    text = f"ПК · {source} · {reading:.1f} °C"
            if cfg.source != OFF and self.connected:
                self.draft_color = temperature_color(reading, cfg, palette)
            text = f"{low}–{high} °C · {text}"
        self.gradient.set_scale(stops, marker)
        text = "Шкала чернетки · " + text
        if self.gradient_status.text() != text:
            self.gradient_status.setText(text)
            self.gradient.setAccessibleDescription(text)

    def _available(self, ch: int) -> bool:
        return bool(self._channel_mask & (1 << (ch - 1)))

    def _busy(self) -> bool:
        return (self._reading_ch is not None or self._write_ch is not None or
                self._palette_pending is not None or self._palette_ack)

    def _update_buttons(self) -> None:
        ready = self.connected and self.supported
        self.refresh_button.setEnabled(ready and self._available(self._channel) and not self._busy())
        self.start_button.setEnabled(ready and any(map(self._available, self._loaded)) and not self._busy())
        for ch, palette_button in self.palette_buttons.items():
            palette_button.setEnabled(ready and self._available(ch) and self.palette_supported and
                                      ch in self.palettes and not self._busy())
        for ch, button in self.save_buttons.items():
            button.setEnabled(
                ready and self._available(ch) and not self._busy() and ch in self._loaded and ch in self._dirty
            )

    def set_connected(self, connected: bool) -> None:
        self.connected = bool(connected)
        if not connected:
            self.stop()
            self.supported = False
            self.palette_supported = False
            self.palettes.clear()
            self._palette_queue.clear()
            self._palette_pending = None
            self._palette_expected = None
            self._palette_ack = False
            self._palette_timer.stop()
            self._loaded.clear()
            self._dirty.clear()
            self._read_queue.clear()
            self._reading_ch = None
            self._write_ch = None
            self._read_value = None
            self._await_ack = None
            self._verify = False
            self._timeout_timer.stop()
            self.configs = {ch: ZoneTemperatureConfig() for ch in range(1, 9)}
            self.groups = {ch: () for ch in range(1, 9)}
            for label in self.labels.values():
                label.setText("Немає даних")
            self.status.setText("ESP32 відключено — налаштування залишаються у NVS.")
        self._update_buttons()
        self.refresh_gradient()

    def set_version(self, serial_version: int) -> None:
        supported = serial_version >= 8
        self.supported = supported
        if supported and self.connected:
            self.refresh_all()
        elif not supported:
            self.status.setText("Потрібна прошивка з протоколом TARGB (serial v8+).")
            self._update_buttons()

    def set_palette_supported(self, enabled: bool) -> None:
        self.palette_supported = bool(enabled)
        self.refresh_gradient()
        if self.palette_supported and self.connected:
            self._palette_queue = deque(range(1, 9))
            self._palette_read_next()
        self._update_buttons()

    def _palette_read_next(self) -> None:
        if self._palette_pending is not None or self._palette_ack:
            return
        if not self._palette_queue:
            self._update_buttons()
            return
        ch = self._palette_queue.popleft()
        self._palette_pending = ch
        if not self.controller.send(f"TPAL? {ch}"):
            self._palette_failed()
        else:
            self._palette_timer.start(5000)
        self._update_buttons()

    def _palette_failed(self) -> None:
        self._palette_timer.stop()
        self._palette_queue.clear()
        self._palette_pending = None
        self._palette_expected = None
        self._palette_ack = False
        self.status.setText("Палітра: немає підтвердження запису або читання з ESP32.")
        self._update_buttons()

    def edit_palette(self, ch: int) -> None:
        if (not self.connected or not self._available(ch) or not self.palette_supported
                or ch not in self.palettes or self._busy()):
            return
        editor = TemperaturePaletteDialog(ch, self.palettes[ch], self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        points = editor.points
        if points == self.palettes[ch]:
            return
        try:
            command = make_palette_command(ch, points)
        except ValueError as exc:
            self.status.setText(f"Помилка палітри: {exc}")
            return
        self._palette_expected = points
        self._palette_pending = ch
        self._palette_ack = True
        self.status.setText(f"Запис палітри ARGB {ch} у NVS ESP32…")
        if not self.controller.send(command):
            self._palette_failed()
            return
        self._palette_timer.start(5000)
        self._update_buttons()

    def _handle_palette(self, line: str) -> bool:
        if line.startswith("ERR TPAL"):
            if self._palette_pending is not None:
                self._palette_failed()
            return True
        if line == "OK TPAL_SAVED":
            if self._palette_pending is not None and self._palette_ack:
                self._palette_ack = False
                self._palette_timer.stop()
                if not self.controller.send(f"TPAL? {self._palette_pending}"):
                    self._palette_failed()
                    return True
                self._palette_timer.start(5000)
            return True
        if not line.startswith("TPAL CH="):
            return False
        if self._palette_pending is None or self._palette_ack:
            return True
        try:
            channel, points = parse_palette_reply(line)
            if channel != self._palette_pending:
                raise ValueError("Неочікуваний канал")
            if self._palette_expected is not None and points != self._palette_expected:
                raise ValueError("Відповідь ESP32 не збігається з новою палітрою")
        except ValueError:
            self._palette_failed()
            return True
        self.palettes[channel] = points
        if channel == self._channel:
            self.refresh_gradient()
        self._palette_timer.stop()
        self._palette_pending = None
        if self._palette_expected is not None:
            self.status.setText(f"✓ ESP32 підтвердив палітру ARGB {channel} у NVS.")
            self._palette_expected = None
        else:
            self._palette_read_next()
        self._update_buttons()
        return True

    def refresh_sensors(self) -> None:
        actual = sorted(self.controller.temperatures, key=lambda s: s.name.casefold())
        for ch, box in self.sources.items():
            selected = str(box.currentData() or self.configs[ch].source)
            box.blockSignals(True)
            box.clear()
            for key, label in SOURCES:
                box.addItem(label, key)
            for s in actual:
                box.addItem(s.name, s.sensor_id)
            idx = box.findData(selected)
            if idx < 0 and selected not in ASSIGNMENTS:
                box.addItem("Недоступний: " + selected, selected)
                idx = box.count() - 1
            box.setCurrentIndex(max(idx, 0))
            box.blockSignals(False)
        self.refresh_gradient()

    def refresh_selected(self) -> None:
        if not self.connected or not self.supported or not self._available(self._channel) or self._busy():
            return
        self.status.setText(f"Читаю ARGB {self._channel:02d} із NVS ESP32…")
        self._send_read(self._channel)

    def refresh_all(self) -> None:
        if not self.connected or not self.supported or self._busy():
            return
        self._read_queue = deque(range(1, 9))
        self.status.setText("Читаю налаштування восьми ARGB-зон із NVS ESP32…")
        self._read_next()

    def _read_next(self) -> None:
        if self._reading_ch is not None or self._write_ch is not None:
            return
        if not self._read_queue:
            self.status.setText(
                f"Зчитано {len(self._loaded)}/8 зон із NVS ESP32."
            )
            self._update_buttons()
            return
        ch = self._read_queue.popleft()
        self._send_read(ch)

    def _send_read(self, ch: int) -> None:
        self._reading_ch = ch
        self._read_value = None
        self._update_buttons()
        if not self.controller.send(f"TARGB? {ch}"):
            self._fail(f"Немає USB-з’єднання для читання ARGB {ch}.")
            return
        self._timeout_timer.start(5000)

    def _timeout(self) -> None:
        self._fail("Час очікування TARGB вичерпано; запис не підтверджений.")

    def _fail(self, error: str) -> None:
        self._timeout_timer.stop()
        old = self._write_ch
        if old is not None and self.connected:
            self.controller.send("TARGB CANCEL")
        self._read_queue.clear()
        self._reading_ch = None
        self._read_value = None
        self._await_ack = None
        self._write_queue.clear()
        self._write_ch = None
        self._expected = None
        self._verify = False
        self.status.setText("⚠ " + error)
        if old is not None:
            self.labels[old].setText("⚠ Не збережено")
        self._update_buttons()

    def _mark_dirty(self, ch: int) -> None:
        if self._loading:
            return
        self._dirty.add(ch)
        self.labels[ch].setText("Змінено · не збережено")
        self._update_buttons()
        if ch == self._channel:
            self.refresh_gradient()

    def edit_group(self, ch: int) -> None:
        if not self._available(ch):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"ARGB {ch} · група датчиків")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Оберіть до 8 датчиків для цієї ARGB-зони:"))
        listing = QListWidget()
        chosen = set(self.groups[ch])
        for sensor in sorted(self.controller.temperatures, key=lambda s: s.name.casefold()):
            item = QListWidgetItem(sensor.name)
            item.setData(Qt.ItemDataRole.UserRole, sensor.sensor_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if sensor.sensor_id in chosen
                else Qt.CheckState.Unchecked
            )
            listing.addItem(item)
        for ident in sorted(chosen - {s.sensor_id for s in self.controller.temperatures}):
            item = QListWidgetItem("Недоступний: " + ident)
            item.setData(Qt.ItemDataRole.UserRole, ident)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            listing.addItem(item)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ids = tuple(
            str(listing.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(listing.count())
            if listing.item(i).checkState() == Qt.CheckState.Checked
        )
        if len(ids) > 8:
            QMessageBox.warning(self, "ARGB", "Не більше восьми датчиків у групі.")
            return
        self.groups[ch] = ids
        self._mark_dirty(ch)

    def _edited_config(self, ch: int) -> ZoneTemperatureConfig:
        return ZoneTemperatureConfig(
            source=str(self.sources[ch].currentData() or OFF),
            group_ids=self.groups[ch],
            low_c=self.lows[ch].value(),
            high_c=self.highs[ch].value(),
            brightness=self.brightness[ch].value(),
        )

    def save_zone(self, ch: int) -> None:
        if not (self.connected and self.supported and self._available(ch) and ch in self._loaded) or self._busy():
            return
        try:
            cfg = self._edited_config(ch)
            if cfg.source in (GROUP_AVG, GROUP_MAX, GROUP_WEIGHTED) and not cfg.group_ids:
                raise ValueError("Обери хоча б один датчик для групи.")
            commands = [("TARGB BEGIN " + str(ch), "OK TARGB_BEGIN")]
            commands.append(("TARGB SOURCE " + encode_value(cfg.source, 95), "OK TARGB_SOURCE"))
            commands.extend(
                ("TARGB GROUP " + encode_value(ident, 95), "OK TARGB_GROUP")
                for ident in cfg.group_ids
            )
            commands.append((f"TARGB RANGE {cfg.low_c} {cfg.high_c} {cfg.brightness}",
                             "OK TARGB_RANGE"))
            commands.append(("TARGB COMMIT", "OK TARGB_SAVED"))
        except (ValueError, TypeError) as exc:
            self.status.setText("⚠ " + str(exc))
            return
        self._write_ch = ch
        self._expected = cfg
        self._write_queue = deque(commands)
        self._read_queue.clear()
        self.status.setText(f"Запис ARGB {ch} до NVS ESP32…")
        self._write_next()

    def _write_next(self) -> None:
        self._timeout_timer.stop()
        self._await_ack = None
        if not self._write_queue:
            self._verify = True
            self._send_read(self._write_ch)
            return
        command, expected_ack = self._write_queue.popleft()
        self._await_ack = expected_ack
        self._update_buttons()
        if not self.controller.send(command):
            self._fail("Не вдалося надіслати команду налаштування.")
            return
        self._timeout_timer.start(5000)

    def _load_readback(self, ch: int, cfg: ZoneTemperatureConfig) -> None:
        self.configs[ch] = cfg
        self.groups[ch] = cfg.group_ids
        self._loaded.add(ch)
        self._loading = True
        try:
            box = self.sources[ch]
            index = box.findData(cfg.source)
            if index < 0:
                box.addItem("Недоступний: " + cfg.source, cfg.source)
                index = box.count() - 1
            box.setCurrentIndex(index)
            self.lows[ch].setValue(cfg.low_c)
            self.highs[ch].setValue(cfg.high_c)
            self.brightness[ch].setValue(cfg.brightness)
        finally:
            self._loading = False
        self._dirty.discard(ch)
        self.labels[ch].setText("✓ Збережено в ESP")
        self._update_buttons()
        if ch == self._channel:
            self.refresh_gradient()

    def handle_line(self, line: str) -> bool:
        if self._handle_palette(line):
            return True
        if self._await_ack is not None:
            if line == self._await_ack:
                self._write_next()
                return True
            if line.startswith("ERR "):
                self._fail("ESP відхилив команду: " + line)
                return True
        if line.startswith("TARGB CH="):
            if self._reading_ch is None:
                return True
            try:
                data = fields(line, "TARGB")
                ch = int(data["CH"])
                if ch != self._reading_ch:
                    raise ValueError("Unexpected zone")
                group_count = int(data["COUNT"])
                if not 0 <= group_count <= 8:
                    raise ValueError("Invalid group count")
                self._read_value = {
                    "source": decode_value(data["SOURCE_HEX"], 95),
                    "low_c": int(data["LOW"]),
                    "high_c": int(data["HIGH"]),
                    "brightness": int(data["BRIGHT"]),
                    "group_count": group_count,
                    "group_ids": [],
                }
            except (ValueError, KeyError) as exc:
                self._fail(f"Некоректна конфігурація ESP: {exc}")
            return True
        if line.startswith("TARGB_GROUP "):
            if self._reading_ch is None:
                return True
            try:
                data = fields(line, "TARGB_GROUP")
                if int(data["CH"]) != self._reading_ch or self._read_value is None:
                    raise ValueError("Unexpected group entry")
                members = self._read_value["group_ids"]
                if len(members) >= 8:
                    raise ValueError("Too many group entries")
                members.append(decode_value(data["ID_HEX"], 95))
            except (KeyError, ValueError) as exc:
                self._fail(f"Некоректна група ESP: {exc}")
            return True
        if line.startswith("TARGB_END "):
            if self._reading_ch is None:
                return True
            try:
                data = fields(line, "TARGB_END")
                ch = int(data["CH"])
                if ch != self._reading_ch or self._read_value is None:
                    raise ValueError("Unexpected end-of-zone")
                info = self._read_value
                if len(info["group_ids"]) != info["group_count"]:
                    raise ValueError("Incomplete group readback")
                cfg = ZoneTemperatureConfig(
                    source=info["source"], group_ids=tuple(info["group_ids"]),
                    low_c=info["low_c"], high_c=info["high_c"],
                    brightness=info["brightness"],
                )
            except (ValueError, KeyError, TypeError) as exc:
                self._fail(f"Неповний або некоректний TARGB readback: {exc}")
                return True
            self._timeout_timer.stop()
            self._reading_ch = None
            self._read_value = None
            if self._verify:
                if cfg != self._expected:
                    self._fail(f"Налаштування ARGB {ch} відрізняються після запису.")
                    return True
                self._verify = False
                self._write_ch = None
                self._expected = None
                self._load_readback(ch, cfg)
                self.status.setText(f"✓ ESP32 підтвердив запис і зчитування ARGB {ch} з NVS.")
            else:
                # Never silently discard unsaved edits during unrelated refresh.
                if ch not in self._dirty:
                    self._load_readback(ch, cfg)
                self._read_next()
            self._update_buttons()
            return True
        return False

    def start(self) -> None:
        if not self.connected or not self.supported or not self.controller.led_counts:
            QMessageBox.warning(self, "ARGB температура",
                                "Підключи ESP32 із firmware v9 та дочекайся LEDCOUNTS.")
            return
        if not any(self._available(ch) and ch in self._loaded and cfg.source != OFF
                   for ch, cfg in self.configs.items()):
            QMessageBox.warning(self, "ARGB температура",
                                "Спочатку збережи джерело хоча б однієї зони в ESP32.")
            return
        if self.controller.dashboard.studio.active:
            self.controller.dashboard.studio.stop()
        if self.controller.dashboard.native_checkbox.isChecked():
            self.controller.dashboard.native_checkbox.setChecked(False)
        if self.controller.bridge_checkbox.isChecked():
            self.controller.bridge_checkbox.setChecked(False)
        self.active = True
        self.timer.start()
        self._tick()

    def stop(self) -> None:
        self.timer.stop()
        self.active = False
        self.status.setText("Зупинено · останні USB-кадри згаснуть через 3 с")

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
        fresh = time.monotonic() - self.controller.last_temperature_sample_at <= TEMPERATURE_SAMPLE_TTL
        sent = 0
        for ch, cfg in self.configs.items():
            if not self._available(ch) or ch not in self._loaded or cfg.source == OFF:
                continue
            color = zone_color(cfg, self.controller.temperatures, fresh=fresh,
                               palette=self.palettes.get(ch) if self.palette_supported else None)
            if color is None:
                continue
            num_leds = min(170, self.controller.led_counts[ch - 1])
            try:
                if not self.controller.queue_rgb(
                    ch, encode_rgb_frame(ch, bytes(color) * num_leds), source="Температура ПК"
                ):
                    raise OSError("ARGB command queue unavailable")
            except (ValueError, OSError) as exc:
                self.stop()
                self.controller.log("ARGB температура: " + str(exc))
                return
            self.labels[ch].setText("● Датчик втрачено" if color ==
                                    zone_color(cfg, [], fresh=False) else "● Активно")
            sent += 1
        self.status.setText(
            f"Термо-ARGB: {sent} зон · "
            + ("температури актуальні" if fresh else "немає даних; помаранчевий колір")
        )

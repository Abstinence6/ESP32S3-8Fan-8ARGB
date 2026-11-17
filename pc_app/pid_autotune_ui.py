"""Human-confirmed, passive PID auto-tune using already recorded RPM steps."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout,
)

try:
    from .pid_autotune import (
        PidRecommendation, gains_command, parse_pid_gains, recommend_pid,
    )
except ImportError:
    from pid_autotune import (
        PidRecommendation, gains_command, parse_pid_gains, recommend_pid,
    )


class PidAutotuneDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.channel = 1
        self.supported = False
        self.phase = ""
        self.current: tuple[int, int, int] | None = None
        self.recommendation: PidRecommendation | None = None
        self.expected: tuple[int, int, int] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        self.setWindowTitle("PID · безпечне автонастроювання за TACH")
        self.resize(530, 350)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Аналізує раніше записану реакцію RPM на стрибок PWM "
            "і пропонує консервативні коефіцієнти. "
            "Не проводить експериментів із живленням або самостійних "
            "розгонів вентиляторів. Для застосування потрібні калібрування, "
            "дійсний TACH, свіжа температура і перевірений драйвер DC PWM. "
            "Усі коефіцієнти зберігаються в NVS ESP32."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.label = QLabel("FAN 1")
        layout.addWidget(self.label)
        self.current_label = QLabel("Коефіцієнти ESP32: невідомо")
        layout.addWidget(self.current_label)
        self.proposed_label = QLabel("Рекомендація: немає")
        self.proposed_label.setWordWrap(True)
        layout.addWidget(self.proposed_label)
        buttons = QHBoxLayout()
        self.read_button = QPushButton("Прочитати PID з ESP")
        self.read_button.clicked.connect(self.read)
        buttons.addWidget(self.read_button)
        self.analyze_button = QPushButton("Аналізувати історію")
        self.analyze_button.clicked.connect(self.analyze)
        buttons.addWidget(self.analyze_button)
        self.apply_button = QPushButton("Зберегти PID в ESP")
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.status = QLabel("Очікування підключення.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._update_buttons()

    def _update_buttons(self) -> None:
        ready = bool(self.controller.port) and self.supported and not self.phase
        self.read_button.setEnabled(ready)
        self.analyze_button.setEnabled(ready)
        self.apply_button.setEnabled(
            ready and self.recommendation is not None and
            self.current is not None
        )

    def set_supported(self, enabled: bool) -> None:
        self.supported = bool(enabled)
        self._update_buttons()

    def set_connected(self, connected: bool) -> None:
        if not connected:
            self._timer.stop()
            self.phase = ""
            self.current = None
            self.recommendation = None
            self.expected = None
            self.supported = False
            self.status.setText("ESP32 відключено. Налаштування залишились у NVS.")
        self._update_buttons()

    def show_for_channel(self, ch: int) -> None:
        if self.phase:
            return
        self.channel = ch
        self.current = None
        self.recommendation = None
        self.expected = None
        self.label.setText(f"FAN {ch:02d}")
        self.current_label.setText("Коефіцієнти ESP32: очікування читання")
        self.proposed_label.setText("Рекомендація: спочатку аналізувати історію")
        self.set_supported(self.controller.pid_tune_supported)
        self.show()
        if self.supported and self.controller.port:
            self.read()
        else:
            self.status.setText("Потрібна прошивка з PIDTUNE_NVS=1 й активне з'єднання.")

    def read(self) -> None:
        if self.phase or not self.controller.port or not self.supported:
            return
        self.phase = "read"
        if not self.controller.send(f"PIDGAINS? {self.channel}"):
            self._timeout()
            return
        self._timer.start(5000)
        self._update_buttons()

    def _timeout(self) -> None:
        self._timer.stop()
        self.phase = ""
        self.expected = None
        self.status.setText("⚠ Немає підтвердження PID від ESP32. Перечитай налаштування.")
        self._update_buttons()

    def analyze(self) -> None:
        self.recommendation = None
        if self.controller.config_types.get(self.channel, 3) == 2:
            self.status.setText("Для 2-pin вентилятора немає TACH.")
            self._update_buttons()
            return
        status = self.controller.fan_status.get(self.channel)
        if status is None or not status.rpm_feedback or status.fault or not status.fresh:
            self.status.setText("Потрібен свіжий, справний сигнал TACH без аварії.")
            self._update_buttons()
            return
        try:
            rec = recommend_pid(list(self.controller.history[self.channel]))
        except ValueError as exc:
            self.status.setText(str(exc))
            self._update_buttons()
            return
        self.recommendation = rec
        self.proposed_label.setText(
            f"Kp={rec.kp_milli / 1000:.3f} / Ki={rec.ki_milli / 1000:.3f} / "
            f"Kd={rec.kd_milli / 1000:.3f}\n"
            f"Доказ: ΔPWM={rec.pwm_delta:+.0f}% / ΔRPM={rec.rpm_delta:+.0f}, "
            f"τ≈{rec.response_seconds:.1f} с, {rec.sample_count} вимірювань."
        )
        self.status.setText("Консервативна рекомендація готова. Нічого не застосовано.")
        self._update_buttons()

    def apply(self) -> None:
        if (not self.controller.port or not self.supported or self.phase or
            self.current is None or self.recommendation is None):
            return
        if QMessageBox.question(
            self, "Підтвердити PID NVS",
            "Записати запропоновані коефіцієнти в ESP32? "
            "Прошивка відмовить без коректного калібрування, актуальних "
            "температури і TACH та перевіреного драйвера. "
            "Значення застосовуються лише після підтвердження NVS.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.expected = self.recommendation.gains
        try:
            command = gains_command(self.channel, self.expected)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.phase = "write"
        self._update_buttons()
        if not self.controller.send(command):
            self._timeout()
            return
        self._timer.start(5000)

    def handle_line(self, line: str) -> bool:
        if line.startswith("ERR PIDGAINS"):
            if self.phase:
                self._timeout()
                self.status.setText("⚠ ESP32 відхилив PID: апаратна перевірка, TACH або калібрування.")
            return True
        if line == "OK PIDGAINS_SAVED":
            if self.phase == "write":
                self.phase = "verify"
                self._timer.stop()
                if not self.controller.send(f"PIDGAINS? {self.channel}"):
                    self._timeout()
                else:
                    self._timer.start(5000)
            return True
        if not line.startswith("PIDGAINS CH="):
            return False
        if self.phase not in ("read", "verify"):
            return True
        try:
            ch, gains = parse_pid_gains(line)
            if ch != self.channel:
                raise ValueError("Відповідь іншого вентилятора")
            if self.phase == "verify" and gains != self.expected:
                raise ValueError("ESP32 повернув інші PID після запису")
        except ValueError as exc:
            self._timeout()
            self.status.setText("⚠ " + str(exc))
            return True
        was_verify = self.phase == "verify"
        self._timer.stop()
        self.phase = ""
        self.current = gains
        self.expected = None
        self.current_label.setText(
            f"Збережені PID ESP32: Kp={gains[0]/1000:.3f}, "
            f"Ki={gains[1]/1000:.3f}, Kd={gains[2]/1000:.3f}"
        )
        self.status.setText(
            "✓ ESP32 підтвердив запис PID у NVS та повторне читання."
            if was_verify else "Зчитано чинні коефіцієнти PID ESP32."
        )
        self._update_buttons()
        return True

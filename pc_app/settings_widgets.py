"""Desktop preferences for opt-in elevated autostart and cooling automation."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout,
)

try:
    from .autostart import (
        build_install_script, build_remove_script, current_task,
        invoke_uac, packaged_executable,
    )
except ImportError:
    from autostart import (
        build_install_script, build_remove_script, current_task,
        invoke_uac, packaged_executable,
    )


def _enabled(value) -> bool:
    return str(value).lower() in ("true", "1", "yes")


class DesktopSettingsPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Автоматизація Windows")
        self.controller = controller
        layout = QVBoxLayout(self)
        self.smoothing = QCheckBox("Згладжувати зниження температури (підвищення — негайно)")
        self.smoothing.setChecked(_enabled(controller.settings.value("smoothTemperatures", "true")))
        self.smoothing.toggled.connect(
            lambda v: controller.settings.setValue("smoothTemperatures", v))
        layout.addWidget(self.smoothing)

        self.auto_profiles = QCheckBox("Автоматичні профілі: Gaming / Work / Night")
        self.auto_profiles.setChecked(_enabled(controller.settings.value("autoProfiles", "false")))
        self.auto_profiles.toggled.connect(self._toggle_profiles)
        self.auto_profiles.setToolTip(
            "GPU ≥70% → Performance; звичайна робота → Balanced; 23:00–07:00 → Silent. "
            "Профіль записується в ESP NVS лише після 40 секунд стабільності "
            "та не частіше ніж раз на 15 хвилин.")
        layout.addWidget(self.auto_profiles)

        self.minimize_tray = QCheckBox("Під час закриття згортати в трей замість виходу")
        self.minimize_tray.setChecked(_enabled(controller.settings.value("minimizeToTray", "false")))
        self.minimize_tray.toggled.connect(
            lambda v: controller.settings.setValue("minimizeToTray", v))
        layout.addWidget(self.minimize_tray)
        self.notify_faults = QCheckBox("Сповіщати у треї про аварії та втрату температури")
        self.notify_faults.setChecked(_enabled(controller.settings.value("notifyFanFaults", "true")))
        self.notify_faults.toggled.connect(
            lambda value: controller.settings.setValue("notifyFanFaults", value))
        layout.addWidget(self.notify_faults)

        layout.addWidget(QLabel(
            "Автозапуск із правами адміністратора (Windows Task Scheduler). "
            "Потрібне підтвердження UAC під час встановлення; пароль не зберігається."
        ))
        row = QHBoxLayout()
        self.start_mode = QComboBox()
        self.start_mode.addItem("Інтерфейс (GUI)", "gui")
        self.start_mode.addItem("Фоновий агент (без вікна)", "agent")
        row.addWidget(self.start_mode)
        install = QPushButton("Увімкнути автозапуск (адмін)…")
        install.clicked.connect(self._install)
        row.addWidget(install)
        remove = QPushButton("Вимкнути автозапуск…")
        remove.clicked.connect(self._remove)
        row.addWidget(remove)
        layout.addLayout(row)
        state_row = QHBoxLayout()
        self.start_status = QLabel("Статус не перевірено")
        state_row.addWidget(self.start_status)
        check = QPushButton("Перевірити")
        check.clicked.connect(self._refresh)
        state_row.addWidget(check)
        layout.addLayout(state_row)

    def _toggle_profiles(self, enabled: bool) -> None:
        if enabled:
            answer = QMessageBox.warning(
                self, "Автоматичне охолодження",
                "Автоматичні профілі можуть змінювати криві 8 вентиляторів "
                "і записувати їх в ESP32 NVS. Програмний захист PWM залишається. "
                "Увімкнути цю функцію?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.auto_profiles.blockSignals(True)
                self.auto_profiles.setChecked(False)
                self.auto_profiles.blockSignals(False)
                return
        self.controller.settings.setValue("autoProfiles", enabled)

    def _install(self) -> None:
        try:
            exe = packaged_executable()
            if QMessageBox.question(
                self, "Автозапуск із правами адміністратора",
                "Створити завдання для поточного користувача з найвищими правами "
                "при вході у Windows?\n\n"
                "Шлях EXE має бути постійним і захищеним від заміни. "
                "На екрані з'явиться стандартний запит UAC.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            script = build_install_script(exe, self.start_mode.currentData())
            invoke_uac(script)
            self.start_status.setText("Запит UAC відкрито; перевір статус після підтвердження")
            QTimer.singleShot(4500, self._refresh)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Автозапуск", str(exc))

    def _remove(self) -> None:
        if QMessageBox.question(
            self, "Вимкнути автозапуск",
            "Видалити лише завдання автозапуску FanARGBControl?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            invoke_uac(build_remove_script())
            self.start_status.setText("Запит UAC відкрито; перевір статус після підтвердження")
            QTimer.singleShot(4500, self._refresh)
        except OSError as exc:
            QMessageBox.warning(self, "Автозапуск", str(exc))

    def _refresh(self) -> None:
        try:
            self.start_status.setText(current_task())
        except (OSError, ValueError) as exc:
            self.start_status.setText(f"Статус недоступний: {exc}")

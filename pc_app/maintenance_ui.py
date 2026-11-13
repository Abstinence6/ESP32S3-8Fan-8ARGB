"""Maintenance UI: portable settings backup and guarded firmware upgrade."""
from __future__ import annotations
import os
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)

try:
    from .config_backup import to_json, from_json, restore_settings
    from .firmware_update import inspect_firmware, flash_firmware, flash_preflight
    from .serial_owner import SerialProxyClient
except ImportError:
    from config_backup import to_json, from_json, restore_settings
    from firmware_update import inspect_firmware, flash_firmware, flash_preflight
    from serial_owner import SerialProxyClient


class FlashWorker(QThread):
    outcome = Signal(bool, str)

    def __init__(self, port: str, firmware_path: str, image_sha256: str, parent=None):
        super().__init__(parent)
        self.port = port
        self.firmware_path = firmware_path
        self.image_sha256 = image_sha256

    def run(self) -> None:
        try:
            flash_firmware(self.port, self.firmware_path, expected_sha256=self.image_sha256)
        except (Exception, SystemExit) as exc:
            # An explicit esptool zero SystemExit is success.
            if isinstance(exc, SystemExit) and exc.code in (0, None):
                self.outcome.emit(True, "Прошивку записано")
            else:
                self.outcome.emit(False, f"Помилка прошивання: {exc}")
        else:
            self.outcome.emit(True, "Прошивку записано")


class MaintenancePanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Резервні копії та прошивка ESP32-S3")
        self.controller = controller
        self.worker = None
        self.firmware_path = ""
        self.selected_sha256 = ""
        layout = QVBoxLayout(self)
        backup_row = QHBoxLayout()
        export = QPushButton("Експорт налаштувань ПК…")
        export.clicked.connect(self.export_settings)
        backup_row.addWidget(export)
        restore = QPushButton("Імпорт налаштувань ПК…")
        restore.clicked.connect(self.import_settings)
        backup_row.addWidget(restore)
        backup_row.addStretch(1)
        history_button = QPushButton("Експорт історії вентиляторів за 7 днів (CSV)…")
        history_button.clicked.connect(self.controller.export_history_csv)
        backup_row.addWidget(history_button)
        layout.addLayout(backup_row)

        flash_row = QHBoxLayout()
        choose = QPushButton("Вибрати firmware.bin…")
        choose.clicked.connect(self.choose_firmware)
        flash_row.addWidget(choose)
        self.status = QLabel("Прошивка не вибрана")
        flash_row.addWidget(self.status, 1)
        self.flash_button = QPushButton("Прошити ESP32 через USB…")
        self.flash_button.clicked.connect(self.flash)
        flash_row.addWidget(self.flash_button)
        layout.addLayout(flash_row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        info = QLabel(
            "Прошивання на COM перепідключає ESP і може перервати живлення "
            "вентиляторів, якщо апаратний ключ не має перевіреного fail-ON. "
            "Дозволено лише на безпечно відключеному стенді/ПК. "
            "Для цієї збірки адреса firmware.bin — 0x10000."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.isolated_bench = QCheckBox(
            "Підтверджую незалежний стенд: ПК вимкнено, вентилятори "
            "живляться без ESP32, кабель PWR_SW ізольовано"
        )
        self.isolated_bench.setToolTip(
            "Використовуй лише коли датчик стану ПК недоступний. "
            "Позначка не замінює фізичної перевірки живлення."
        )
        layout.addWidget(self.isolated_bench)

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт налаштувань", "fanargb-settings.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            target = Path(path)
            temp = target.with_suffix(".tmp")
            temp.write_text(to_json(self.controller.settings), encoding="utf-8")
            os.replace(temp, target)
            self.controller.log(f"Налаштування ПК експортовано: {path} (без паролів)")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Експорт", str(exc))

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Імпорт налаштувань", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = from_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Імпорт", str(exc))
            return
        if QMessageBox.question(
            self, "Відновити налаштування",
            "Перезаписати вибір датчиків, профілі й налаштування GUI з файлу?\n"
            "Секрети Wi-Fi/MQTT не імпортуються. Після відновлення перезапусти програму.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            count = restore_settings(self.controller.settings, data)
            QMessageBox.information(self, "Налаштування", f"Відновлено {count} параметрів. Перезапусти програму.")
        except ValueError as exc:
            QMessageBox.warning(self, "Імпорт", str(exc))

    def choose_firmware(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Оновлення ESP32-S3", "", "ESP32 firmware (*.bin)"
        )
        if not path:
            return
        self.firmware_path = ""
        self.selected_sha256 = ""
        try:
            digest, length = inspect_firmware(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Прошивка", str(exc))
            return
        self.firmware_path = path
        self.selected_sha256 = digest
        self.status.setText(f"{length//1024} КБ · SHA256 {digest[:12]}…")
        self.status.setToolTip(digest)

    def flash(self) -> None:
        if not self.firmware_path or not self.controller.port:
            QMessageBox.warning(self, "Прошивання", "Вибери firmware.bin і підключи ESP32")
            return
        proxy = isinstance(self.controller.port, SerialProxyClient)
        dashboard = self.controller.dashboard
        state = str(getattr(dashboard, "current_pc_state", "unknown"))
        last_seen = float(getattr(dashboard, "pc_state_updated_at", 0.0))
        # A stale "off" is not evidence that the machine is still off.
        if state == "off" and time.monotonic() - last_seen > 15:
            state = "unknown"
        isolated = self.isolated_bench.isChecked()
        try:
            flash_preflight(state, isolated_bench=isolated, is_proxy=proxy)
            actual_digest, _size = inspect_firmware(self.firmware_path)
            if actual_digest != self.selected_sha256:
                raise ValueError("Файл прошивки змінився після вибору. Вибери його ще раз.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Прошивання заблоковано", str(exc))
            return

        if state != "off":
            phrase, accepted = QInputDialog.getText(
                self, "Незалежний стенд — додаткова перевірка",
                "Датчик живлення ПК не підтверджує OFF. "
                "Прошивання дозволено лише на перевіреному ізольованому стенді. "
                "Введи СТЕНД для підтвердження:",
            )
            if not accepted or phrase.strip().upper() != "СТЕНД":
                return

        if QMessageBox.warning(
            self, "НЕБЕЗПЕКА: ESP32 перезавантажиться",
            "Фізично перевір: вентилятори не залежать від ESP32, "
            "комп'ютер вимкнено, а firmware.bin відповідає ESP32-S3 "
            "та app-розділу 0x10000. "
            "Запис перериває живлення/температурну телеметрію.\n\n"
            "Почати запис? Стирання всього чипа не виконується.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        port = str(self.controller.port_box.currentData())
        if not port or port == "None":
            QMessageBox.warning(self, "Прошивання", "Не визначено COM-порт")
            return
        self.controller.disconnect(manual=True)
        self.flash_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.status.setText("Прошивання… не відключай USB")
        self.worker = FlashWorker(port, self.firmware_path, actual_digest, self)
        self.worker.outcome.connect(self._finished)
        self.worker.start()

    def _finished(self, success: bool, message: str) -> None:
        self.progress.setVisible(False)
        self.flash_button.setEnabled(True)
        self.status.setText(message)
        if success:
            QMessageBox.information(self, "ESP32-S3", message + ". Підключися до COM повторно.")
        else:
            QMessageBox.warning(self, "ESP32-S3", message)

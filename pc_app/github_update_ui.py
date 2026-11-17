"""Explicit GitHub Releases discovery and safe download UI (no auto-install)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout,
)

try:
    from .github_updates import (
        APP_VERSION, PACKAGES, Release, download_release, latest_release,
    )
except ImportError:
    from github_updates import (
        APP_VERSION, PACKAGES, Release, download_release, latest_release,
    )


class ReleaseCheckWorker(QThread):
    outcome = Signal(object, str)

    def run(self) -> None:
        try:
            release = latest_release()
        except (ValueError, TypeError, KeyError) as exc:
            self.outcome.emit(None, str(exc))
        else:
            self.outcome.emit(release, "")


class ReleaseDownloadWorker(QThread):
    outcome = Signal(str, str, str, int)

    def __init__(self, release: Release, component: str, destination: str, parent=None):
        super().__init__(parent)
        self.release = release
        self.component = component
        self.destination = destination

    def run(self) -> None:
        try:
            digest, size = download_release(
                self.release, self.component, self.destination
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.outcome.emit(self.component, str(exc), "", 0)
        else:
            self.outcome.emit(self.component, "", digest, size)


class GitHubUpdatePanel(QGroupBox):
    def __init__(self, maintenance):
        super().__init__("Оновлення через GitHub Releases")
        self.maintenance = maintenance
        self.release: Release | None = None
        self.worker: QThread | None = None
        self._last_destination = ""
        layout = QVBoxLayout(self)
        self.description = QLabel(
            "Перевірка стабільних релізів GitHub: Windows EXE і прошивка ESP32-S3. "
            "Файли перевіряються за SHA-256 з релізного маніфесту. "
            "Нічого не встановлюється або прошивається автоматично."
        )
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.status = QLabel(f"Встановлена програма: {APP_VERSION} · реліз не перевірявся")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("Перевірити GitHub")
        self.check_button.clicked.connect(self.check)
        buttons.addWidget(self.check_button)
        self.windows_button = QPushButton("Завантажити Windows EXE…")
        self.windows_button.clicked.connect(lambda: self.download("windows"))
        buttons.addWidget(self.windows_button)
        self.firmware_button = QPushButton("Завантажити ESP32 BIN…")
        self.firmware_button.clicked.connect(lambda: self.download("firmware"))
        buttons.addWidget(self.firmware_button)
        self.page_button = QPushButton("Сторінка релізу")
        self.page_button.clicked.connect(self.open_release_page)
        buttons.addWidget(self.page_button)
        layout.addLayout(buttons)
        self._update_buttons()

    def _update_buttons(self) -> None:
        idle = self.worker is None or not self.worker.isRunning()
        self.check_button.setEnabled(idle)
        ready = idle and self.release is not None
        self.windows_button.setEnabled(ready)
        self.firmware_button.setEnabled(ready)
        self.page_button.setEnabled(ready)

    def check(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.release = None
        self.status.setText("Перевіряю стабільний реліз на GitHub…")
        self.worker = ReleaseCheckWorker(self)
        self.worker.outcome.connect(self._checked)
        self.worker.finished.connect(self._update_buttons)
        self._update_buttons()
        self.worker.start()

    def _checked(self, release: object, error: str) -> None:
        if error or not isinstance(release, Release):
            self.status.setText("GitHub: " + (error or "Некоректний реліз"))
            return
        self.release = release
        self.status.setText(
            f"GitHub: {release.tag} · локальна програма: {APP_VERSION}. "
            "Обери пакет для перевіреного завантаження."
        )
        self._update_buttons()

    def open_release_page(self) -> None:
        if self.release:
            QDesktopServices.openUrl(QUrl(self.release.page))

    def download(self, component: str) -> None:
        if self.release is None or self.worker is not None and self.worker.isRunning():
            return
        name, filename = PACKAGES[component]
        try:
            asset = self.release.package(component)
        except ValueError as exc:
            QMessageBox.warning(self, "GitHub Release", str(exc))
            return
        title = ("Windows-програма" if component == "windows"
                 else "Прошивка ESP32-S3")
        if QMessageBox.question(
            self, f"Завантажити {title} з GitHub",
            f"Реліз {self.release.tag} · {name} · {asset.size // 1024} КБ.\n"
            "Буде перевірено ZIP, маніфест і SHA-256 файлів. "
            + ("EXE не запуститься автоматично. "
               "Закрий стару версію перед запуском завантаженого EXE."
               if component == "windows" else
               "BIN лише буде вибрано для ручного прошивання. "
               "Вимоги до відключення ПК і fail-ON залишаються обов'язковими."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        suffix = ("Windows EXE (*.exe)" if component == "windows"
                  else "ESP32 firmware (*.bin)")
        path, _ = QFileDialog.getSaveFileName(
            self, f"Зберегти {title}", filename, suffix
        )
        if not path:
            return
        self._last_destination = path
        self.worker = ReleaseDownloadWorker(self.release, component, path, self)
        self.worker.outcome.connect(self._downloaded)
        self.worker.finished.connect(self._update_buttons)
        self.status.setText("Завантажую та перевіряю GitHub Release…")
        self._update_buttons()
        self.worker.start()

    def _downloaded(self, component: str, error: str, sha: str, size: int) -> None:
        if error:
            self.status.setText("Помилка перевірки GitHub Release: " + error)
            QMessageBox.warning(self, "Оновлення з GitHub", error)
            return
        name = Path(self._last_destination).name
        self.status.setText(
            f"Перевірено: {name} · {size // 1024} КБ · SHA-256 {sha[:12]}…"
        )
        if component == "firmware":
            self.maintenance.firmware_path = self._last_destination
            self.maintenance.selected_sha256 = sha
            self.maintenance.status.setText(
                f"BIN із GitHub перевірено · SHA256 {sha[:12]}… "
                "· прошивання тільки вручну"
            )
            self.maintenance.status.setToolTip(sha)
            QMessageBox.information(
                self, "Прошивка завантажена",
                "Файл перевірено та вибрано у блоці прошивання. "
                "ESP32 не перепрошивався. Перед прошиванням перевір "
                "плату, fail-ON та стан ПК."
            )
        else:
            QMessageBox.information(
                self, "Windows-програму завантажено",
                f"Перевірений EXE збережено: {self._last_destination}\n"
                "Програму не було запущено або замінено автоматично."
            )

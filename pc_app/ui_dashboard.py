"""Modern, task-based PySide6 shell for the existing 8Fan/8ARGB controller.

The original controls are *moved*, not recreated. Their signal connections and
the firmware/serial/safety behaviour stay in main.py.
"""
from __future__ import annotations

from collections.abc import Iterable
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from settings_widgets import DesktopSettingsPanel
from hardware_sensor_ui import HardwareSensorPanel
from argb_studio_ui import ArgbStudioPanel
from maintenance_ui import MaintenancePanel
from device_settings_ui import DeviceSettingsPanel
from diagnostics_ui import DiagnosticPanel
from sensor_manager_ui import SensorManagerPanel
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLayout, QPushButton, QRadioButton, QScrollArea, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget, QDialog, QLineEdit, QListWidget,
    QListWidgetItem,
)


PAGES = (
    ("overview", "Огляд", "Огляд системи", "Поточний стан охолодження"),
    ("fans", "Вентилятори", "Вентилятори", "Криві, швидкість, режими"),
    ("sensors", "Датчики", "Датчики обладнання", "Температури та телеметрія"),
    ("argb", "Підсвітка", "Підсвітка ARGB", "Сцени та OpenRGB"),
    ("pc", "Живлення ПК", "Живлення ПК", "Керування PWR_SW"),
    ("esp32", "Контролер ESP32", "Налаштування ESP32", "Wi-Fi, MQTT і TACH"),
    ("service", "Сервіс", "Сервіс", "Діагностика й калібрування"),
    ("logs", "Журнал", "Журнал подій", "Повідомлення й консоль"),
)

# Restrained slate/teal design system. All information remains real hardware data.
STYLE = """
QMainWindow, QWidget#dashboardRoot, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #0d141d; color: #e8edf4;
}
QWidget { color: #e8edf4; font-family: "Segoe UI"; font-size: 10pt; }
QFrame#sidebar { background: #121d28; border-right: 1px solid #263646; }
QFrame#topbar { background: #111a25; border-bottom: 1px solid #263646; }
QFrame#summaryCard, QFrame#fanCard, QFrame#quietCard {
    background: #172332; border: 1px solid #2b3d4f; border-radius: 12px;
}
QFrame#fanCard:hover { border-color: #5b8792; background: #192939; }
QFrame#systemBanner {
    background: #152c33; border: 1px solid #37616a; border-radius: 14px;
}
QFrame#systemBanner[state="warning"] {
    background: #30291e; border-color: #80673c;
}
QFrame#systemBanner[state="critical"] {
    background: #35222a; border-color: #995b69;
}
QFrame#systemBanner[state="idle"] {
    background: #1a2532; border-color: #415263;
}
QLabel[role="brand"] { font-size: 19pt; font-weight: 700; color: #f4f9fb; }
QLabel[role="pageTitle"] { font-size: 20pt; font-weight: 700; color: #f4f8fc; }
QLabel[role="bannerTitle"] { font-size: 18pt; font-weight: 700; color: #eef8fa; }
QLabel[role="bigNumber"] { font-size: 20pt; font-weight: 700; color: #f4f9fc; }
QLabel[role="minor"] { font-size: 9pt; color: #a9bacb; }
QLabel[role="sectionLabel"] { font-size: 9pt; font-weight: 650; color: #849aaf; }
QLabel[role="labelTitle"] { font-size: 10pt; font-weight: 650; color: #edf4f9; }
QLabel[role="positive"] { color: #79d7b6; font-weight: 650; }
QLabel[role="caution"] { color: #f1c47a; font-weight: 650; }
QLabel[role="negative"] { color: #ff9ba8; font-weight: 650; }
QGroupBox {
    background: #172332; border: 1px solid #2b3d4f; border-radius: 12px;
    margin-top: 18px; padding-top: 13px; font-weight: 650;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 16px; top: 1px; padding: 0 5px;
    color: #e4eef5;
}
QPushButton {
    background: #253648; color: #e9f1f6; border: 1px solid #3b5266;
    border-radius: 8px; padding: 7px 12px; min-height: 23px;
}
QPushButton:hover { background: #32495d; border-color: #6a91a3; }
QPushButton:pressed { background: #20313e; }
QPushButton:focus { border-color: #74ced1; }
QPushButton:disabled {
    background: #202b36; color: #8b9ba9; border-color: #313e4b;
}
QPushButton[role="primary"] {
    background: #147a80; border-color: #299da1; color: #ffffff; font-weight: 650;
}
QPushButton[role="primary"]:hover { background: #228d94; }
QPushButton[role="danger"] {
    background: #512e39; border-color: #925560; color: #ffd8dd;
}
QPushButton[role="danger"]:hover { background: #70414d; }
QPushButton[role="nav"] {
    background: transparent; border: 1px solid transparent;
    border-radius: 8px; padding: 10px 13px;
    text-align: left; font-weight: 500; color: #b6c7d5;
}
QPushButton[role="nav"]:hover { background: #203242; color: #ffffff; }
QPushButton[role="nav"]:checked {
    background: #19404b; color: #c2f5f0; font-weight: 700;
    border-left: 3px solid #6bd3d0;
}
QComboBox, QLineEdit, QSpinBox {
    background: #111e2b; color: #eaf2f8; border: 1px solid #3a5165;
    border-radius: 8px; padding: 6px 9px; min-height: 23px;
    selection-background-color: #296d75;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
    border-color: #70d0d2;
}
QComboBox QAbstractItemView {
    background: #1c2c3b; color: #eaf2f8;
    selection-background-color: #235966;
}
QSpinBox::up-button, QSpinBox::down-button {
    background: #26394b; border: 1px solid #3e5366; width: 17px;
}
QTableWidget, QTextEdit, QListWidget {
    background: #111e2b; alternate-background-color: #1a2938;
    color: #eaf2f8; gridline-color: #273b4f;
    border: 1px solid #304457; border-radius: 8px;
    selection-background-color: #245b67;
}
QHeaderView::section {
    background: #1f3041; color: #cbdce8; padding: 8px;
    border: 0; border-right: 1px solid #33485b;
}
QCheckBox, QRadioButton { spacing: 8px; }
QStatusBar {
    background: #111a25; color: #aebfce; border-top: 1px solid #283848;
}
QScrollBar:vertical { background: #121f2d; width: 11px; border: 0; }
QScrollBar::handle:vertical {
    background: #476176; border-radius: 5px; min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #243646; width: 5px; }
QTabWidget::pane {
    border: 1px solid #304457; border-radius: 9px; background: #172332;
}
QTabBar::tab {
    padding: 10px 16px; border-radius: 7px 7px 0 0;
    background: #1c2a39; color: #afc4d2;
}
QTabBar::tab:hover { background: #274151; }
QTabBar::tab:selected { background: #216270; color: #ffffff; font-weight: 650; }
QDialog { background: #14202e; }
"""


def _move_controls(source: QLayout, destination: QLayout) -> None:
    """Take existing widgets from a nested layout; keep their signal wiring."""
    while source.count():
        item = source.takeAt(0)
        if item.widget() is not None:
            destination.addWidget(item.widget())
        elif item.layout() is not None:
            _move_controls(item.layout(), destination)


def _label(text: str, role: str = "minor", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def _page_header(title: str, subtitle: str) -> QWidget:
    frame = QWidget()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 15)
    layout.setSpacing(4)
    layout.addWidget(_label(title, "pageTitle"))
    layout.addWidget(_label(subtitle, "minor", True))
    return frame


def _wrap_scroll(page: QWidget) -> QScrollArea:
    scroller = QScrollArea()
    scroller.setWidgetResizable(True)
    scroller.setFrameShape(QFrame.Shape.NoFrame)
    scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroller.setWidget(page)
    return scroller


class DashboardShell(QWidget):
    """Layout adapter around existing functionality; no serial side effects."""

    def __init__(
        self,
        controller,
        *,
        refresh_ports: QPushButton,
        table_box: QGroupBox,
        choose_row: QLayout,
        curve_box: QGroupBox,
        history_box: QGroupBox,
        sensors_box: QGroupBox,
        calibration_box: QGroupBox,
        rgb_box: QGroupBox,
        pc_box: QGroupBox,
        log_box: QGroupBox,
        hardware_rgb: QLayout,
        config_files: QLayout,
        preset_row: QLayout,
        diagnostic_row: QLayout,
        scenes: Iterable[str],
    ) -> None:
        super().__init__()
        self.controller = controller
        self.setObjectName("dashboardRoot")
        self.nav: dict[str, QPushButton] = {}
        self.page_index: dict[str, int] = {}
        self.fan_cards: dict[int, dict[str, QLabel]] = {}
        self.pc_buttons: dict[str, QPushButton] = {}
        self.is_connected = False
        self.current_pc_state = "unknown"
        self.current_pc_busy = False
        self.pc_state_updated_at = 0.0
        self._fan_statuses: dict[int, object] = {}
        self._fan_grid_columns = 0
        self._fan_frames: dict[int, QFrame] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        workspace = QWidget()
        right = QVBoxLayout(workspace)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._topbar(refresh_ports))
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        root.addWidget(workspace, 1)

        self._create_overview()
        self._create_fans(table_box, choose_row, curve_box, history_box)
        self._create_sensors(sensors_box)
        self._create_argb(rgb_box, scenes)
        self._create_pc(pc_box)
        self._create_device_settings()
        self._create_service(
            calibration_box, hardware_rgb, config_files,
            preset_row, diagnostic_row,
        )
        self._create_logs(log_box)
        self.show_page("overview")
        self.set_connected(False)
        self.controller.setStyleSheet(STYLE)
        self._shortcuts: list[QShortcut] = []
        for index, (key, _caption, _title, _hint) in enumerate(PAGES, 1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda selected=key: self.show_page(selected))
            self._shortcuts.append(shortcut)
        palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        palette_shortcut.activated.connect(self.open_command_palette)
        self._shortcuts.append(palette_shortcut)
        self._reflow_fan_cards()

    def create_command_palette(self) -> QDialog:
        """Read-only quick navigation. Commands never write to hardware."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Швидкий перехід · FanARGB")
        dialog.setMinimumWidth(470)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 17)
        layout.setSpacing(12)
        layout.addWidget(_label("Куди перейти?", "bannerTitle"))
        search = QLineEdit()
        search.setPlaceholderText("Введи розділ, номер вентилятора або MQTT…")
        search.setClearButtonEnabled(True)
        search.setAccessibleName("Пошук розділів FanARGB")
        layout.addWidget(search)
        results = QListWidget()
        results.setAlternatingRowColors(True)
        results.setMinimumHeight(260)
        results.setAccessibleName("Результати швидкого переходу")
        layout.addWidget(results)
        layout.addWidget(_label("Enter — перейти  ·  Esc — закрити  ·  Ctrl+1…8 — розділи", "minor"))
        choices = []
        for key, caption, _title, hint in PAGES:
            choices.append((caption, hint, lambda destination=key: self.show_page(destination)))
        for channel in range(1, 9):
            choices.append((
                f"Вентилятор {channel}", "Відкрити криву й керування",
                lambda ch=channel: self.open_fan(ch),
            ))
        for key, caption in (
            ("wifi", "Wi-Fi ESP32"), ("mqtt", "MQTT і Home Assistant"),
            ("argb", "ARGB у ESP32"), ("fan", "TACH і пороги"),
        ):
            choices.append((
                caption, "Конфігурація контролера",
                lambda section=key: self._open_device_tab(section),
            ))

        visible_actions: list[object] = []

        def refill(query: str) -> None:
            results.clear()
            visible_actions.clear()
            tokens = query.casefold().split()
            for caption, hint, action in choices:
                haystack = f"{caption} {hint}".casefold()
                if not all(token in haystack for token in tokens):
                    continue
                results.addItem(f"{caption}     ·     {hint}")
                visible_actions.append(action)
            if results.count():
                results.setCurrentRow(0)

        def activate() -> None:
            index = results.currentRow()
            if 0 <= index < len(visible_actions):
                visible_actions[index]()
                dialog.accept()

        search.textChanged.connect(refill)
        search.returnPressed.connect(activate)
        results.itemActivated.connect(lambda _item: activate())
        dialog.search = search
        dialog.results = results
        dialog.activate_selection = activate
        refill("")
        return dialog

    def open_command_palette(self) -> None:
        palette = self.create_command_palette()
        palette.search.setFocus()
        palette.exec()

    def _open_device_tab(self, key: str) -> None:
        self.show_page("esp32")
        self.device_settings.select_tab(key)

    def _sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(202)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 25, 15, 19)
        layout.setSpacing(5)
        layout.addWidget(_label("FanARGB", "brand"))
        layout.addWidget(_label("COOLING  /  LIGHTING", "sectionLabel"))
        layout.addSpacing(21)
        sections = {
            "overview": "РОБОЧИЙ ПРОСТІР",
            "pc": "КОНТРОЛЕР",
            "service": "ІНСТРУМЕНТИ",
        }
        for index, (key, caption, title, _subtitle) in enumerate(PAGES, 1):
            if key in sections:
                layout.addSpacing(15 if key != "overview" else 2)
                layout.addWidget(_label(sections[key], "sectionLabel"))
            button = QPushButton(caption)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.setMinimumHeight(41)
            button.setToolTip(f"{title}  ·  Ctrl+{index}")
            button.setAccessibleName(title)
            button.clicked.connect(
                lambda checked=False, selected=key: self.show_page(selected)
            )
            layout.addWidget(button)
            self.nav[key] = button
        layout.addStretch(1)
        layout.addWidget(_label("Ctrl+K  ·  швидкий перехід", "minor"))
        layout.addWidget(_label("Керування тільки локально", "minor"))
        return panel

    def _topbar(self, refresh_ports: QPushButton) -> QWidget:
        panel = QFrame()
        panel.setObjectName("topbar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(23, 11, 23, 11)
        layout.setSpacing(9)
        self.connection_text = _label("●  Не підключено", "caution")
        self.connection_text.setToolTip("ESP32-S3 через USB. При втраті температур діє fail-safe.")
        layout.addWidget(self.connection_text)
        layout.addStretch(1)
        search = QPushButton("Перейти…  Ctrl+K")
        search.setToolTip("Знайти розділ, вентилятор або сторінку налаштувань")
        search.clicked.connect(self.open_command_palette)
        layout.addWidget(search)
        self.controller.port_box.setMinimumWidth(130)
        self.controller.port_box.setMaximumWidth(225)
        self.controller.port_box.setToolTip("Оберіть фізичний порт ESP32-S3")
        layout.addWidget(self.controller.port_box)
        refresh_ports.setText("Оновити")
        refresh_ports.setToolTip("Оновити список доступних USB/COM-портів")
        layout.addWidget(refresh_ports)
        self.controller.connect_button.setProperty("role", "primary")
        layout.addWidget(self.controller.connect_button)
        return panel

    def _add_page(self, key: str, widget: QWidget) -> None:
        self.page_index[key] = self.stack.addWidget(_wrap_scroll(widget))

    @staticmethod
    def _content(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(25, 22, 27, 30)
        layout.setSpacing(17)
        layout.addWidget(_page_header(title, subtitle))
        return page, layout

    @staticmethod
    def _summary_card(title: str, initial: str, subtitle: str) -> tuple[QWidget, QLabel]:
        card = QFrame()
        card.setObjectName("summaryCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(17, 14, 17, 15)
        lay.setSpacing(8)
        lay.addWidget(_label(title, "minor"))
        value = _label(initial, "labelTitle", True)
        lay.addWidget(value)
        lay.addWidget(_label(subtitle, "minor"))
        return card, value

    def _create_overview(self) -> None:
        page, layout = self._content(
            "Огляд",
            "Стан охолодження в реальному часі. Для редагування відкрий потрібний вентилятор.",
        )
        banner = QFrame()
        banner.setObjectName("systemBanner")
        banner.setProperty("state", "idle")
        self.system_banner = banner
        info = QHBoxLayout(banner)
        info.setContentsMargins(23, 17, 23, 18)
        info.setSpacing(17)
        left = QVBoxLayout()
        left.setSpacing(5)
        self.health_title = _label("Контролер не підключено", "bannerTitle")
        self.health_description = _label(
            "Вибери USB/COM-порт і підключи ESP32 для перегляду стану.", "minor", True
        )
        left.addWidget(self.health_title)
        left.addWidget(self.health_description)
        info.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(5)
        right.addWidget(_label("КОНТРОЛЕР", "sectionLabel"))
        self.summary_esp = _label("Не підключено", "labelTitle", True)
        self.summary_esp.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.summary_esp)
        info.addLayout(right)
        layout.addWidget(banner)

        summary = QGridLayout()
        summary.setHorizontalSpacing(11)
        summary.setVerticalSpacing(11)
        for card_index, (key, title, hint) in enumerate((
            ("temp", "Датчики", "Температури ПК · NWinfo"),
            ("rgb", "Підсвітка", "ARGB / OpenRGB"),
            ("mqtt", "MQTT", "Home Assistant"),
            ("pc", "Живлення ПК", "PWR_SW"),
        )):
            card, value = self._summary_card(title, "—", hint)
            setattr(self, f"summary_{key}", value)
            summary.addWidget(card, 0, card_index)
            summary.setColumnStretch(card_index, 1)
        layout.addLayout(summary)

        heading = QHBoxLayout()
        heading.addWidget(_label("8 вентиляторів", "labelTitle"))
        heading.addStretch(1)
        details = QCheckBox("Показати джерела")
        details.setToolTip("Показати під кожним вентилятором джерело температури")
        self.show_sources = details
        details.setChecked(
            str(self.controller.settings.value("showFanSources", "false")).lower()
            in ("true", "1")
        )
        details.toggled.connect(self._toggle_sources)
        heading.addWidget(details)
        shortcut = QPushButton("Усі налаштування")
        shortcut.clicked.connect(lambda: self.show_page("fans"))
        heading.addWidget(shortcut)
        layout.addLayout(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(11)
        grid.setVerticalSpacing(11)
        self._fan_grid = grid
        for ch in range(1, 9):
            frame = QFrame()
            frame.setObjectName("fanCard")
            frame.setToolTip(f"Вентилятор {ch} · відкрий налаштування для деталей")
            box = QVBoxLayout(frame)
            box.setContentsMargins(16, 13, 16, 13)
            box.setSpacing(7)
            title = QHBoxLayout()
            title.addWidget(_label(f"FAN {ch:02d}", "labelTitle"))
            title.addStretch(1)
            state = _label("Очікування", "minor")
            title.addWidget(state)
            box.addLayout(title)
            rpm = _label("— RPM", "bigNumber")
            box.addWidget(rpm)
            metrics = _label("— %  ·  — °C", "minor")
            box.addWidget(metrics)
            source = _label("Джерело: не вибрано", "minor", True)
            source.setVisible(details.isChecked())
            source.setToolTip("Джерело температури цього вентилятора")
            box.addWidget(source)
            action = QPushButton("Відкрити налаштування")
            action.setToolTip(f"Редагувати криву, TACH і PWM вентилятора {ch}")
            action.clicked.connect(
                lambda checked=False, channel=ch: self.open_fan(channel)
            )
            box.addWidget(action)
            self._fan_frames[ch] = frame
            self.fan_cards[ch] = {
                "rpm": rpm, "metrics": metrics, "source": source, "state": state,
            }
        layout.addLayout(grid)
        safety = _label(
            "Без актуальної температури контролер перемикається на захисне охолодження. "
            "Робота силового ключа при скиданні ESP32 потребує апаратної перевірки.",
            "minor", True,
        )
        safety.setToolTip("Програмний fail-safe не гарантує живлення вентилятора при знеструмленні MCU")
        layout.addWidget(safety)
        layout.addStretch(1)
        self._add_page("overview", page)
        self._reflow_fan_cards()

    def _toggle_sources(self, checked: bool) -> None:
        for labels in self.fan_cards.values():
            labels["source"].setVisible(checked)
        self.controller.settings.setValue("showFanSources", checked)

    def _reflow_fan_cards(self) -> None:
        if not hasattr(self, "_fan_grid"):
            return
        # Width includes the 202px sidebar and 50px workspace margins.
        available = max(0, self.width() - 260)
        columns = 4 if available >= 1080 else 3 if available >= 680 else 2
        if columns == self._fan_grid_columns:
            return
        self._fan_grid_columns = columns
        for frame in self._fan_frames.values():
            self._fan_grid.removeWidget(frame)
        for ch, frame in self._fan_frames.items():
            self._fan_grid.addWidget(frame, (ch - 1) // columns, (ch - 1) % columns)
        for col in range(4):
            self._fan_grid.setColumnStretch(col, 1 if col < columns else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_fan_cards()

    def _update_cooling_health(self) -> None:
        if not self.is_connected:
            title = "Контролер не підключено"
            detail = "Підключи ESP32 через USB. Без температур ПК контролер використовує захисний режим."
            state = "idle"
        elif not self._fan_statuses:
            title = "Читаємо стан охолодження…"
            detail = "З'єднання встановлено. Очікуємо перші дані від вентилятора."
            state = "idle"
        else:
            faults = sum(bool(s.fault) for s in self._fan_statuses.values())
            stale = sum(not bool(s.fresh) for s in self._fan_statuses.values())
            count = len(self._fan_statuses)
            if faults:
                title = f"Потрібна увага · {faults} каналів"
                detail = "Виявлено аварійні стани. Відкрий Сервіс → Діагностика для перевірки."
                state = "critical"
            elif stale:
                title = f"Захисне охолодження · {stale} каналів"
                detail = "Немає свіжої температури на частині каналів — застосовується fail-safe."
                state = "warning"
            else:
                title = "Охолодження працює"
                detail = f"Отримано дані {count} із 8 каналів · налаштування доступні в розділі «Вентилятори»."
                state = "normal"
        self.health_title.setText(title)
        self.health_description.setText(detail)
        if self.system_banner.property("state") != state:
            self.system_banner.setProperty("state", state)
            self.system_banner.style().unpolish(self.system_banner)
            self.system_banner.style().polish(self.system_banner)

    def _create_fans(self, table_box, choose_row, curve_box, history_box) -> None:
        page, layout = self._content(
            "Вентилятори",
            "Спочатку вибери канал, потім редагуй криву й режим керування.",
        )
        # A vertical editor avoids clipped curve buttons and horizontal scrolling
        # on standard 1366px and 1080px displays.
        table_box.setTitle("8 каналів · швидкість, RPM та джерело температури")
        table_box.setMinimumHeight(380)
        layout.addWidget(table_box)
        row_holder = QFrame()
        row_holder.setObjectName("quietCard")
        row_layout = QHBoxLayout(row_holder)
        row_layout.setContentsMargins(15, 11, 15, 11)
        row_layout.setSpacing(10)
        _move_controls(choose_row, row_layout)
        layout.addWidget(row_holder)
        curve_box.setTitle("Крива PWM · перетягни п'ять точок")
        curve_box.setMinimumHeight(430)
        layout.addWidget(curve_box)
        history_box.setTitle("Історія вибраного вентилятора")
        layout.addWidget(history_box)
        layout.addStretch(1)
        self._add_page("fans", page)

    def _create_argb(self, rgb_box, scenes: Iterable[str]) -> None:
        page, layout = self._content(
            "ARGB-підсвітка",
            "Швидкі світлові сцени не змінюють профілі вентиляторів або їхню безпеку.",
        )
        select = QFrame()
        select.setObjectName("quietCard")
        bar = QHBoxLayout(select)
        bar.setContentsMargins(17, 14, 17, 14)
        bar.addWidget(_label("Зона:", "labelTitle"))
        self.zone_box = QComboBox()
        for ch in range(1, 9):
            self.zone_box.addItem(f"ARGB {ch}", ch)
        self.zone_box.currentIndexChanged.connect(self._zone_changed)
        bar.addWidget(self.zone_box)
        bar.addSpacing(12)
        bar.addWidget(_label("Сцена:", "labelTitle"))
        self.scene_box = QComboBox()
        self.scene_box.addItems(list(scenes))
        self.scene_box.setMinimumWidth(145)
        bar.addWidget(self.scene_box)
        self.scope_one = QRadioButton("Ця зона")
        self.scope_all = QRadioButton("Усі 8")
        self.scope_one.setChecked(True)
        bar.addWidget(self.scope_one)
        bar.addWidget(self.scope_all)
        bar.addStretch(1)
        apply_button = QPushButton("Застосувати сцену")
        apply_button.setProperty("role", "primary")
        apply_button.clicked.connect(self._apply_scene)
        bar.addWidget(apply_button)
        layout.addWidget(select)

        rgb_box.setTitle("Колір, яскравість та OpenRGB")
        layout.addWidget(rgb_box)
        native_row = QFrame()
        native_row.setObjectName("quietCard")
        native_layout = QHBoxLayout(native_row)
        self.native_checkbox = QCheckBox(
            "Native OpenRGB SDK · 8 зон · 127.0.0.1:6743"
        )
        self.native_checkbox.toggled.connect(self.controller.toggle_native_openrgb)
        native_layout.addWidget(self.native_checkbox)
        native_layout.addWidget(_label(
            "Додай Remote SDK server у OpenRGB: 127.0.0.1, порт 6743",
            "minor", True,
        ))
        layout.addWidget(native_row)
        self.studio = ArgbStudioPanel(self.controller)
        layout.addWidget(self.studio)
        note = QFrame()
        note.setObjectName("quietCard")
        foot = QVBoxLayout(note)
        foot.setContentsMargins(17, 13, 17, 13)
        foot.addWidget(_label(
            "OpenRGB → E1.31 Devices → 127.0.0.1, Universes 1–8 "
            "(для USB-моста). Прямий Wi-Fi E1.31 налаштовується окремо.",
            "minor", True,
        ))
        layout.addWidget(note)
        layout.addStretch(1)
        self._add_page("argb", page)

    def _create_pc(self, pc_box: QGroupBox) -> None:
        page, layout = self._content(
            "Живлення ПК",
            "Керування апаратною кнопкою ввімкнення. Потрібні окремі безпечні GPIO.",
        )
        status_card = QFrame()
        status_card.setObjectName("quietCard")
        top = QVBoxLayout(status_card)
        top.setContentsMargins(19, 16, 19, 16)
        top.addWidget(_label("ПОТОЧНИЙ СТАН", "minor"))
        self.pc_state_detail = _label("Невідомо", "bigNumber")
        top.addWidget(self.pc_state_detail)
        top.addWidget(_label(
            "PC Power працює лише за наявності перевіреного датчика стану "
            "і ввімкненої функції в прошивці.", "minor", True,
        ))
        layout.addWidget(status_card)
        pc_box.setTitle("Керування")
        pc_box.setMinimumHeight(110)
        layout.addWidget(pc_box)
        for i in range(pc_box.layout().count()):
            control = pc_box.layout().itemAt(i).widget()
            if isinstance(control, QPushButton):
                command = {
                    "Увімкнути ПК": "on",
                    "Вимкнути ПК": "off",
                    "Утримати Power 6 с": "force",
                }.get(control.text())
                if command:
                    self.pc_buttons[command] = control
                    if command == "force":
                        control.setProperty("role", "danger")
                elif control.text() == "Оновити стан":
                    self.pc_refresh_button = control
        warn = QFrame()
        warn.setObjectName("quietCard")
        wlay = QVBoxLayout(warn)
        wlay.setContentsMargins(17, 12, 17, 12)
        wlay.addWidget(_label(
            "Утримання Power 6 секунд вимикає комп'ютер примусово "
            "та може спричинити втрату незбережених даних.", "minor", True,
        ))
        layout.addWidget(warn)
        layout.addStretch(1)
        self._add_page("pc", page)

    def _service_group(self, title: str, *rows: QLayout) -> QGroupBox:
        group = QGroupBox(title)
        box = QVBoxLayout(group)
        box.setContentsMargins(15, 23, 15, 12)
        for row in rows:
            target = QHBoxLayout()
            target.setSpacing(8)
            _move_controls(row, target)
            box.addLayout(target)
        return group

    def _create_sensors(self, sensors_box) -> None:
        page, layout = self._content(
            "Датчики обладнання",
            "Усі доступні дані NWinfo. Температури можна використовувати для кривих; "
            "інші параметри наведено лише для моніторингу.",
        )
        sensors_box.setTitle("Температури та інші показники")
        sensors_box.setMinimumHeight(460)
        layout.addWidget(sensors_box, 1)
        endpoint = QGroupBox("Локальне опитування NWinfo")
        ep = QHBoxLayout(endpoint)
        ep.setContentsMargins(16, 20, 16, 12)
        ep.addWidget(_label(
            "CPU · GPU · RAM · SSD · Intel / AMD · без LHM", "minor"
        ), 1)
        scan = QPushButton("Оновити датчики")
        scan.clicked.connect(self.controller.refresh_temperatures)
        ep.addWidget(scan)
        ep.addWidget(self.controller.sensor_status)
        layout.addWidget(endpoint)
        self.hardware_sensor = HardwareSensorPanel(self.controller)
        layout.addWidget(self.hardware_sensor)
        self.sensor_manager = SensorManagerPanel(self.controller)
        layout.addWidget(self.sensor_manager)
        self._add_page("sensors", page)

    def _create_device_settings(self) -> None:
        page, layout = self._content(
            "Налаштування ESP32-S3",
            "Усі змінювані параметри зчитуються й записуються через USB до NVS "
            "контролера. Паролі не зберігаються на ПК.",
        )
        self.device_settings = DeviceSettingsPanel(self.controller)
        layout.addWidget(self.device_settings)
        self._add_page("esp32", page)

    def _create_service(
        self, calibration_box, hardware_rgb, config_files,
        preset_row, diagnostic_row,
    ) -> None:
        page, layout = self._content(
            "Сервіс і розширені налаштування",
            "Параметри, які зазвичай не потрібно змінювати щодня.",
        )
        warning = QFrame()
        warning.setObjectName("quietCard")
        wl = QVBoxLayout(warning)
        wl.setContentsMargins(17, 13, 17, 13)
        wl.addWidget(_label(
            "Калібрування та запис профілів змінюють стан ESP32. "
            "Перед зміною типу вентилятора перевір фізичне підключення.",
            "minor", True,
        ))
        layout.addWidget(warning)
        self.firmware_status = _label("Прошивка: версію ще не прочитано", "minor")
        layout.addWidget(self.firmware_status)
        layout.addWidget(calibration_box)
        network = self._service_group("Налаштування ARGB, Wi-Fi та живлення стрічок", hardware_rgb)
        layout.addWidget(network)
        combined = self._service_group("Профіль усієї системи · 8 вентиляторів + ARGB", preset_row, config_files)
        layout.addWidget(combined)
        advanced = self._service_group("Діагностика та MQTT / Home Assistant", diagnostic_row)
        layout.addWidget(advanced)
        self.diagnostics = DiagnosticPanel(self.controller)
        layout.addWidget(self.diagnostics)
        self.settings_panel = DesktopSettingsPanel(self.controller)
        layout.addWidget(self.settings_panel)
        self.maintenance_panel = MaintenancePanel(self.controller)
        layout.addWidget(self.maintenance_panel)

        layout.addStretch(1)
        self._add_page("service", page)

    def _create_logs(self, log_box: QGroupBox) -> None:
        page, layout = self._content(
            "Журнал та консоль",
            "Події Serial. Ручні команди призначені для діагностики.",
        )
        log_box.setTitle("Обмін із ESP32")
        self.controller.log_text.setMaximumHeight(16777215)
        self.controller.log_text.setMinimumHeight(410)
        layout.addWidget(log_box, 1)
        clear = QPushButton("Очистити журнал")
        clear.clicked.connect(self.controller.log_text.clear)
        tools = QHBoxLayout()
        tools.addWidget(clear)
        tools.addStretch(1)
        layout.addLayout(tools)
        self._add_page("logs", page)

    def show_page(self, key: str) -> None:
        if key not in self.page_index:
            raise KeyError(f"Unknown page: {key}")
        self.stack.setCurrentIndex(self.page_index[key])
        self.stack.widget(self.page_index[key]).verticalScrollBar().setValue(0)
        for name, button in self.nav.items():
            button.setChecked(name == key)

    def open_fan(self, channel: int) -> None:
        if not 1 <= channel <= 8:
            return
        self.controller.fan_box.setCurrentIndex(channel - 1)
        self.show_page("fans")

    def sync_zone(self, index: int) -> None:
        if self.zone_box.currentIndex() != index and 0 <= index < 8:
            self.zone_box.blockSignals(True)
            self.zone_box.setCurrentIndex(index)
            self.zone_box.blockSignals(False)

    def _zone_changed(self, index: int) -> None:
        if 0 <= index < 8:
            self.controller.fan_box.setCurrentIndex(index)

    def _apply_scene(self) -> None:
        self.controller.apply_argb_scene(
            self.scene_box.currentText(), self.scope_all.isChecked()
        )

    def set_connected(self, connected: bool, port_name: str = "") -> None:
        self.is_connected = bool(connected)
        if connected:
            self.connection_text.setText(f"●  ESP32 · {port_name}")
            self.connection_text.setProperty("role", "positive")
            self.summary_esp.setText(port_name or "Підключено")
        else:
            self._fan_statuses.clear()
            self.connection_text.setText("●  ESP32 не підключено")
            self.connection_text.setProperty("role", "caution")
            self.summary_esp.setText("Не підключено")
            self.update_pc_state("unknown")
            self.summary_mqtt.setText("Не підключено")
            for labels in self.fan_cards.values():
                labels["rpm"].setText("— RPM")
                labels["metrics"].setText("— %  ·  — °C")
                labels["state"].setText("Немає даних")
                labels["state"].setProperty("role", "minor")
                labels["state"].style().unpolish(labels["state"])
                labels["state"].style().polish(labels["state"])
        self._update_cooling_health()
        self._update_pc_buttons()
        self.device_settings.set_connected(connected)
        self.connection_text.style().unpolish(self.connection_text)
        self.connection_text.style().polish(self.connection_text)

    def set_sensor_count(self, count: int, available: bool = True, metric_count: int = 0) -> None:
        self.summary_temp.setText(
            f"{count} температур · {metric_count} інших" if count else
            f"0 температур · {metric_count} інших" if available else "Датчики недоступні"
        )

    def set_bridge_state(self, enabled: bool, frames: int = 0) -> None:
        if enabled:
            self.summary_rgb.setText(f"E1.31 · {frames} кадрів")
        else:
            self.summary_rgb.setText("Міст вимкнений")

    def set_mqtt_state(self, response: str) -> None:
        tokens = dict(
            item.split("=", 1) for item in response.split()
            if "=" in item
        )
        enabled = tokens.get("ENABLED") == "1"
        online = tokens.get("CONNECTED") == "1"
        self.summary_mqtt.setText(
            "Підключено" if online else "Налаштовано" if enabled else "Вимкнено"
        )

    def update_fan(self, channel: int, status) -> None:
        labels = self.fan_cards.get(channel)
        if labels is None:
            return
        self._fan_statuses[channel] = status
        labels["rpm"].setText(f"{status.rpm} RPM" if status.rpm_feedback else "— RPM")
        temp = f"{status.deci_c / 10:.1f} °C" if status.fresh else "— °C"
        labels["metrics"].setText(f"{status.pwm}% PWM  ·  {temp}")
        if status.fault:
            labels["state"].setText("Аварія")
            labels["state"].setProperty("role", "negative")
        elif not status.fresh:
            labels["state"].setText("Захист")
            labels["state"].setProperty("role", "caution")
        else:
            labels["state"].setText("Авто" if status.mode.lower() == "auto" else "Вручну")
            labels["state"].setProperty("role", "positive")
        state = labels["state"]
        state.style().unpolish(state)
        state.style().polish(state)
        self._update_cooling_health()

    def set_fan_source(self, channel: int, source_name: str) -> None:
        labels = self.fan_cards.get(channel)
        if labels:
            labels["source"].setText(f"Джерело: {source_name}")
            labels["source"].setToolTip(source_name)
            self._fan_frames[channel].setToolTip(
                f"Вентилятор {channel} · {source_name}"
            )

    def update_pc_state(self, status: str) -> None:
        self.pc_state_updated_at = time.monotonic()
        tokens = status.lower().split()
        self.current_pc_state = tokens[0] if tokens else "unknown"
        self.current_pc_busy = "busy=1" in tokens
        name = {
            "on": "Комп'ютер увімкнений",
            "off": "Комп'ютер вимкнений",
            "unknown": "Стан невідомий",
            "disabled": "Функцію вимкнено",
        }.get(self.current_pc_state, "Стан невідомий")
        self.pc_state_detail.setText(name + (" · натискання" if self.current_pc_busy else ""))
        self.summary_pc.setText(name)
        self._update_pc_buttons()

    def _update_pc_buttons(self) -> None:
        for action, button in self.pc_buttons.items():
            allowed = self.is_connected and not self.current_pc_busy and (
                (action == "on" and self.current_pc_state == "off") or
                (action in ("off", "force") and self.current_pc_state == "on")
            )
            button.setEnabled(allowed)
        if hasattr(self, "pc_refresh_button"):
            self.pc_refresh_button.setEnabled(self.is_connected)

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
    QListWidgetItem, QSizePolicy, QTabWidget,
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
/* Quiet, consistent surfaces; typography comes from the system Qt font,
   avoiding broken glyph fallback in offscreen Windows screenshots. */
QMainWindow, QWidget#dashboardRoot, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #0c111a; color: #e8edf4;
}
QWidget { color: #e8edf4; font-size: 10pt; }
QFrame#sidebar { background: #101924; border-right: 1px solid #253240; }
QFrame#topbar { background: #101823; border-bottom: 1px solid #253240; }
QFrame#metricsStrip, QFrame#fanCard, QFrame#quietCard, QFrame#systemBanner {
    background: #141f2c; border: 1px solid #293a4b; border-radius: 11px;
}
QFrame#metricSlot { background: transparent; border: none; }
QFrame#fanCard:hover { border-color: #4e8e91; background: #192836; }
QFrame#systemBanner { background: #102a30; border-color: #2e6a69; }
QFrame#systemBanner[state="warning"] { background: #292518; border-color: #8b7441; }
QFrame#systemBanner[state="critical"] { background: #30202a; border-color: #a75b69; }
QFrame#systemBanner[state="idle"] { background: #18212d; border-color: #3c4c5d; }
QLabel[role="brand"] { color: #ecf6f7; font-size: 17pt; font-weight: 750; }
QLabel[role="pageTitle"] { color: #f3f6fa; font-size: 18pt; font-weight: 700; }
QLabel[role="bannerTitle"] { color: #f1f8f8; font-size: 16pt; font-weight: 700; }
QLabel[role="bigNumber"] { color: #f6fafc; font-size: 20pt; font-weight: 700; }
QLabel[role="minor"] { color: #a1b1c2; font-size: 9pt; }
QLabel[role="sectionLabel"] { color: #849baa; font-size: 9pt; font-weight: 650; }
QLabel[role="labelTitle"] { color: #eaf0f5; font-size: 10pt; font-weight: 650; }
QLabel[role="positive"] { color: #70d2b3; font-weight: 600; }
QLabel[role="caution"] { color: #e6bd77; font-weight: 600; }
QLabel[role="negative"] { color: #ee969f; font-weight: 600; }
QLabel[role="metricValue"] { color: #eaf4f8; font-size: 12pt; font-weight: 650; }
QGroupBox {
    background: #141f2c; border: 1px solid #293a4b;
    border-radius: 11px; margin-top: 19px; padding-top: 12px; font-weight: 650;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 15px; top: 1px; padding: 0 5px;
    color: #e6edf2;
}
QPushButton {
    background: #253546; color: #e7eef4; border: 1px solid #364a5c;
    border-radius: 7px; padding: 6px 11px; min-height: 25px;
}
QPushButton:hover { background: #30485a; border-color: #5e8b98; }
QPushButton:pressed { background: #1e2b38; }
QPushButton:focus { border: 1px solid #75d2cd; }
QPushButton:disabled { background: #1c2834; color: #8394a2; border-color: #2a3845; }
QPushButton[role="primary"] {
    background: #137e83; border-color: #178d91; color: #f5ffff; font-weight: 650;
}
QPushButton[role="primary"]:hover { background: #209096; }
QPushButton[role="danger"] {
    background: #4b2d37; border-color: #80515e; color: #f9d8dd;
}
QPushButton[role="ghost"] {
    background: transparent; color: #8dd5d3; border: none;
    text-align: left; padding: 3px 0; min-height: 20px;
}
QPushButton[role="ghost"]:hover { color: #c6fcf9; background: transparent; }
QPushButton[role="nav"] {
    background: transparent; border: none; border-radius: 7px;
    text-align: left; color: #aab9c6; padding: 8px 12px;
}
QPushButton[role="nav"]:hover { color: #f2f9fa; background: #1d303d; }
QPushButton[role="nav"]:checked {
    background: #183a42; color: #c0f4f0; border-left: 3px solid #63ccc4;
    font-weight: 650;
}
QComboBox, QLineEdit, QSpinBox {
    background: #111d2a; color: #eef4f8; border: 1px solid #394d5e;
    border-radius: 7px; padding: 5px 9px; min-height: 25px;
    selection-background-color: #236572;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color: #6ccecc; }
QComboBox QAbstractItemView {
    background: #1a2b3b; color: #eaf2f8; selection-background-color: #205a66;
}
QSpinBox::up-button, QSpinBox::down-button {
    background: #263848; border: 1px solid #3b4e5f; width: 17px;
}
QTableWidget, QTextEdit, QListWidget {
    background: #101b28; alternate-background-color: #192838;
    color: #e8f0f6; gridline-color: #273949;
    border: 1px solid #2c3d4d; border-radius: 7px;
    selection-background-color: #225b65;
}
QHeaderView::section {
    background: #1b2b3a; color: #c8d8e4; padding: 8px;
    border: 0; border-right: 1px solid #304455;
}
QCheckBox, QRadioButton { spacing: 7px; }
QStatusBar { background: #101823; color: #9eafbd; border-top: 1px solid #263543; }
QScrollBar:vertical { background: #111c29; width: 10px; border: 0; }
QScrollBar::handle:vertical { background: #486275; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #273846; width: 5px; }
QTabWidget::pane { border: 0; background: transparent; top: 0; }
QTabBar::base { border: 0; background: transparent; }
QTabBar::tab {
    padding: 10px 15px; margin-right: 5px; border-radius: 7px;
    background: #192634; color: #aebdca;
}
QTabBar::tab:hover { background: #243a4a; }
QTabBar::tab:selected { background: #22515c; color: #f6ffff; font-weight: 650; }
QDialog { background: #121d2b; }
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
    if wrap:
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return widget


def _page_header(title: str, subtitle: str) -> QWidget:
    frame = QWidget()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 13)
    layout.setSpacing(4)
    layout.addWidget(_label(title, "pageTitle"))
    layout.addWidget(_label(subtitle, "minor", True))
    return frame


def _wrap_scroll(page: QWidget) -> QScrollArea:
    scroller = QScrollArea()
    scroller.setWidgetResizable(True)
    scroller.setFrameShape(QFrame.Shape.NoFrame)
    scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        panel.setFixedWidth(190)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(13, 20, 13, 16)
        layout.setSpacing(3)
        layout.addWidget(_label("FanARGB", "brand"))
        layout.addWidget(_label("8 FAN  /  8 ARGB", "sectionLabel"))
        layout.addSpacing(14)
        sections = {
            "overview": "РОБОЧИЙ ПРОСТІР",
            "pc": "КОНТРОЛЕР",
            "service": "ІНСТРУМЕНТИ",
        }
        for index, (key, caption, title, _subtitle) in enumerate(PAGES, 1):
            if key in sections:
                layout.addSpacing(12 if key != "overview" else 3)
                layout.addWidget(_label(sections[key], "sectionLabel"))
            button = QPushButton(caption)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.setMinimumHeight(39)
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
        layout.setContentsMargins(22, 10, 22, 10)
        layout.setSpacing(8)
        self.connection_text = _label("●  Не підключено", "caution")
        self.connection_text.setToolTip("ESP32-S3 через USB. При втраті температур діє fail-safe.")
        layout.addWidget(self.connection_text)
        layout.addStretch(1)
        search = QPushButton("Пошук  Ctrl+K")
        search.setToolTip("Знайти розділ, вентилятор або сторінку налаштувань")
        search.clicked.connect(self.open_command_palette)
        layout.addWidget(search)
        self.controller.port_box.setMinimumWidth(117)
        self.controller.port_box.setMaximumWidth(185)
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
        layout.setContentsMargins(27, 21, 27, 26)
        layout.setSpacing(14)
        layout.addWidget(_page_header(title, subtitle))
        return page, layout

    @staticmethod
    def _summary_card(title: str, initial: str, subtitle: str) -> tuple[QWidget, QLabel]:
        slot = QFrame()
        slot.setObjectName("metricSlot")
        lay = QVBoxLayout(slot)
        lay.setContentsMargins(11, 11, 11, 11)
        lay.setSpacing(5)
        lay.addWidget(_label(title.upper(), "sectionLabel"))
        value = _label(initial, "metricValue", True)
        lay.addWidget(value)
        lay.addWidget(_label(subtitle, "minor", True))
        slot.setMinimumHeight(88)
        slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return slot, value

    def _create_overview(self) -> None:
        page, layout = self._content(
            "Огляд системи",
            "Вісім незалежних каналів охолодження · поточні показники з ESP32-S3.",
        )
        banner = QFrame()
        banner.setObjectName("systemBanner")
        banner.setProperty("state", "idle")
        banner.setMinimumHeight(92)
        self.system_banner = banner
        info = QHBoxLayout(banner)
        info.setContentsMargins(19, 14, 19, 14)
        info.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(_label("ЗАГАЛЬНИЙ СТАН", "sectionLabel"))
        self.health_title = _label("Контролер не підключено", "bannerTitle", True)
        self.health_description = _label(
            "Обери COM-порт у верхній панелі, щоб переглянути охолодження.",
            "minor", True,
        )
        left.addWidget(self.health_title)
        left.addWidget(self.health_description)
        info.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(_label("ESP32-S3", "sectionLabel"))
        self.summary_esp = _label("Не підключено", "labelTitle", True)
        self.summary_esp.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self.summary_esp)
        info.addLayout(right, 0)
        layout.addWidget(banner)

        telemetry = QFrame()
        telemetry.setObjectName("metricsStrip")
        strip_layout = QVBoxLayout(telemetry)
        strip_layout.setContentsMargins(9, 4, 9, 4)
        strip_layout.setSpacing(0)
        summary = QGridLayout()
        summary.setHorizontalSpacing(8)
        summary.setVerticalSpacing(1)
        self._summary_grid = summary
        self._summary_cards: list[QWidget] = []
        self._summary_grid_columns = 0
        for key, title, hint in (
            ("temp", "Датчики", "NWinfo · температури ПК"),
            ("rgb", "ARGB", "OpenRGB · 8 каналів"),
            ("mqtt", "MQTT", "Home Assistant"),
            ("pc", "Живлення ПК", "Контроль PWR_SW"),
        ):
            card, value = self._summary_card(title, "—", hint)
            self._summary_cards.append(card)
            setattr(self, f"summary_{key}", value)
        strip_layout.addLayout(summary)
        layout.addWidget(telemetry)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(_label("ВЕНТИЛЯТОРИ", "sectionLabel"))
        heading.addWidget(_label("01–08", "minor"))
        heading.addStretch(1)
        details = QCheckBox("Джерела температур")
        details.setToolTip("Показувати джерело температури під RPM")
        self.show_sources = details
        details.setChecked(
            str(self.controller.settings.value("showFanSources", "false")).lower()
            in ("true", "1")
        )
        details.toggled.connect(self._toggle_sources)
        heading.addWidget(details)
        shortcut = QPushButton("Усі канали")
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
            frame.setMinimumHeight(142)
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            frame.setToolTip(f"Вентилятор {ch} · відкрий налаштування для деталей")
            box = QVBoxLayout(frame)
            box.setContentsMargins(16, 12, 16, 11)
            box.setSpacing(5)
            heading_row = QHBoxLayout()
            heading_row.addWidget(_label(f"FAN {ch:02d}", "labelTitle"))
            heading_row.addStretch(1)
            state = _label("Очікування", "minor")
            heading_row.addWidget(state)
            box.addLayout(heading_row)
            rpm = _label("— RPM", "bigNumber", True)
            box.addWidget(rpm)
            metrics = _label("— %   ·   — °C", "minor", True)
            box.addWidget(metrics)
            source = _label("Джерело: не вибрано", "minor", True)
            source.setVisible(details.isChecked())
            source.setToolTip("Джерело температури цього вентилятора")
            box.addWidget(source)
            action = QPushButton("Налаштувати")
            action.setProperty("role", "ghost")
            action.setToolTip(f"Крива, TACH і PWM вентилятора {ch}")
            action.clicked.connect(lambda _=False, channel=ch: self.open_fan(channel))
            box.addWidget(action)
            self._fan_frames[ch] = frame
            self.fan_cards[ch] = {
                "rpm": rpm, "metrics": metrics, "source": source, "state": state,
            }
        layout.addLayout(grid)
        info_text = _label(
            "За втрати актуальної температури прошивка переходить у fail-safe. "
            "Гарантоване живлення вентиляторів під час reset залежить від схеми ключів.",
            "minor", True,
        )
        layout.addWidget(info_text)
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
        available = max(0, self.width() - 252)
        columns = 4 if available >= 1000 else 3 if available >= 870 else 2
        if columns != self._fan_grid_columns:
            self._fan_grid_columns = columns
            for frame in self._fan_frames.values():
                self._fan_grid.removeWidget(frame)
            for ch, frame in self._fan_frames.items():
                self._fan_grid.addWidget(frame, (ch - 1) // columns, (ch - 1) % columns)
            for col in range(4):
                self._fan_grid.setColumnStretch(col, 1 if col < columns else 0)
        metrics_columns = 4 if available >= 850 else 2
        if metrics_columns != self._summary_grid_columns:
            self._summary_grid_columns = metrics_columns
            for card in self._summary_cards:
                self._summary_grid.removeWidget(card)
            for index, card in enumerate(self._summary_cards):
                self._summary_grid.addWidget(card, index // metrics_columns, index % metrics_columns)
            for col in range(4):
                self._summary_grid.setColumnStretch(col, 1 if col < metrics_columns else 0)

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
            elif count < 8:
                title = f"Перевіряємо канали · {count}/8"
                detail = "Стан решти вентиляторів ще не отримано. Оцінка охолодження неповна."
                state = "idle"
            else:
                title = "Охолодження працює"
                detail = "Усі 8 каналів передають актуальний стан · параметри доступні в «Вентиляторах»."
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
            "Налаштовуй вибраний канал. Загальний список та графіки винесені в окремі вкладки.",
        )
        controls = QFrame()
        controls.setObjectName("quietCard")
        bar = QHBoxLayout(controls)
        bar.setContentsMargins(16, 12, 16, 12)
        bar.setSpacing(10)
        _move_controls(choose_row, bar)
        for label in controls.findChildren(QLabel):
            if label.text().startswith("Редагувати криву"):
                label.setText("Канал")
        self.controller.fan_box.setMinimumWidth(155)
        self.controller.fan_box.setMaximumWidth(220)
        self.controller.type_box.setMaximumWidth(210)
        layout.addWidget(controls)

        self.fan_workspace_tabs = QTabWidget()
        self.fan_workspace_tabs.setObjectName("fanWorkspaceTabs")
        self.fan_workspace_tabs.setDocumentMode(True)

        curve_page = QWidget()
        curve_layout = QVBoxLayout(curve_page)
        curve_layout.setContentsMargins(0, 12, 0, 0)
        curve_layout.setSpacing(10)
        curve_box.setTitle("Температурна крива")
        curve_box.setMinimumHeight(440)
        self.controller.curve_plot.setMinimumHeight(250)
        curve_layout.addWidget(curve_box)
        curve_layout.addStretch(1)
        self.fan_workspace_tabs.addTab(curve_page, "Крива та PID")

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 12, 0, 0)
        list_layout.setSpacing(10)
        table_box.setTitle("Вісім каналів · RPM, PWM та джерела")
        table_box.setMinimumHeight(400)
        self.controller.fan_table.setMaximumHeight(16777215)
        list_layout.addWidget(table_box)
        list_layout.addStretch(1)
        self.fan_workspace_tabs.addTab(list_page, "Усі канали")

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(0, 12, 0, 0)
        history_box.setTitle("Історія вибраного вентилятора")
        history_box.setMinimumHeight(390)
        history_layout.addWidget(history_box)
        history_layout.addStretch(1)
        self.fan_workspace_tabs.addTab(history_page, "Графіки")

        layout.addWidget(self.fan_workspace_tabs, 1)
        layout.addStretch(1)
        self._add_page("fans", page)

    def _create_argb(self, rgb_box, scenes: Iterable[str]) -> None:
        page, layout = self._content(
            "ARGB",
            "Ефекти, інтеграція OpenRGB і редактор сцен — без змішування з охолодженням.",
        )
        self.argb_workspace_tabs = QTabWidget()
        self.argb_workspace_tabs.setObjectName("argbWorkspaceTabs")
        self.argb_workspace_tabs.setDocumentMode(True)

        scenes_page = QWidget()
        scenes_layout = QVBoxLayout(scenes_page)
        scenes_layout.setContentsMargins(0, 12, 0, 0)
        scenes_layout.setSpacing(12)

        select = QFrame()
        select.setObjectName("quietCard")
        bar = QVBoxLayout(select)
        bar.setContentsMargins(17, 13, 17, 13)
        bar.setSpacing(11)
        fields = QHBoxLayout()
        fields.setSpacing(12)
        fields.addWidget(_label("Канал", "labelTitle"))
        self.zone_box = QComboBox()
        self.zone_box.setMinimumWidth(110)
        for ch in range(1, 9):
            self.zone_box.addItem(f"ARGB {ch}", ch)
        self.zone_box.currentIndexChanged.connect(self._zone_changed)
        fields.addWidget(self.zone_box)
        fields.addSpacing(12)
        fields.addWidget(_label("Ефект", "labelTitle"))
        self.scene_box = QComboBox()
        self.scene_box.addItems(list(scenes))
        self.scene_box.setMinimumWidth(170)
        fields.addWidget(self.scene_box, 1)
        bar.addLayout(fields)
        actions = QHBoxLayout()
        self.scope_one = QRadioButton("Лише ця зона")
        self.scope_all = QRadioButton("Усі 8 зон")
        self.scope_one.setChecked(True)
        actions.addWidget(self.scope_one)
        actions.addWidget(self.scope_all)
        actions.addStretch(1)
        apply_button = QPushButton("Застосувати")
        apply_button.setProperty("role", "primary")
        apply_button.clicked.connect(self._apply_scene)
        actions.addWidget(apply_button)
        bar.addLayout(actions)
        scenes_layout.addWidget(select)

        rgb_box.setTitle("Ручне керування кольором")
        for label in rgb_box.findChildren(QLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        scenes_layout.addWidget(rgb_box)
        scenes_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(scenes_page, "Ефекти")

        openrgb_page = QWidget()
        openrgb_layout = QVBoxLayout(openrgb_page)
        openrgb_layout.setContentsMargins(0, 12, 0, 0)
        openrgb_layout.setSpacing(12)
        native_row = QFrame()
        native_row.setObjectName("quietCard")
        native_layout = QVBoxLayout(native_row)
        native_layout.setContentsMargins(17, 13, 17, 13)
        native_layout.setSpacing(7)
        self.native_checkbox = QCheckBox("Native OpenRGB SDK · 8 зон")
        self.native_checkbox.toggled.connect(self.controller.toggle_native_openrgb)
        native_layout.addWidget(self.native_checkbox)
        native_layout.addWidget(_label(
            "Локальний OpenRGB SDK: 127.0.0.1, порт 6743. "
            "Додай Remote SDK server у налаштуваннях OpenRGB.",
            "minor", True,
        ))
        openrgb_layout.addWidget(native_row)
        note = QFrame()
        note.setObjectName("quietCard")
        foot = QVBoxLayout(note)
        foot.setContentsMargins(17, 13, 17, 13)
        foot.addWidget(_label(
            "USB-місцева передача OpenRGB через E1.31: 127.0.0.1, Universes 1–8. "
            "Прямий Wi-Fi E1.31/DDP налаштовується у вкладці ESP32.",
            "minor", True,
        ))
        openrgb_layout.addWidget(note)
        openrgb_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(openrgb_page, "OpenRGB")

        studio_page = QWidget()
        studio_layout = QVBoxLayout(studio_page)
        studio_layout.setContentsMargins(0, 12, 0, 0)
        self.studio = ArgbStudioPanel(self.controller)
        studio_layout.addWidget(self.studio)
        studio_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(studio_page, "Студія")

        layout.addWidget(self.argb_workspace_tabs, 1)
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
        box.setSpacing(10)
        for row in rows:
            grid = QGridLayout()
            grid.setSpacing(9)
            column = 0
            while row.count():
                item = row.takeAt(0)
                widget = item.widget()
                if widget is None:
                    continue
                widget.setMinimumWidth(0)
                grid.addWidget(widget, column // 2, column % 2)
                column += 1
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            box.addLayout(grid)
        return group

    def _create_sensors(self, sensors_box) -> None:
        page, layout = self._content(
            "Датчики",
            "Температури NWinfo, фізичні DS18B20 та джерела для кривих вентиляторів.",
        )
        self.sensor_workspace_tabs = QTabWidget()
        self.sensor_workspace_tabs.setObjectName("sensorWorkspaceTabs")
        self.sensor_workspace_tabs.setDocumentMode(True)

        system_page = QWidget()
        system_layout = QVBoxLayout(system_page)
        system_layout.setContentsMargins(0, 12, 0, 0)
        system_layout.setSpacing(10)
        sensors_box.setTitle("Сенсори Windows · NWinfo")
        sensors_box.setMinimumHeight(440)
        system_layout.addWidget(sensors_box)
        endpoint = QFrame()
        endpoint.setObjectName("quietCard")
        ep = QHBoxLayout(endpoint)
        ep.setContentsMargins(15, 12, 15, 12)
        ep.addWidget(_label("CPU · GPU · SSD · RAM", "minor"), 1)
        scan = QPushButton("Оновити")
        scan.clicked.connect(self.controller.refresh_temperatures)
        ep.addWidget(scan)
        ep.addWidget(self.controller.sensor_status)
        system_layout.addWidget(endpoint)
        system_layout.addStretch(1)
        self.sensor_workspace_tabs.addTab(system_page, "Датчики ПК")

        hw_page = QWidget()
        hw_layout = QVBoxLayout(hw_page)
        hw_layout.setContentsMargins(0, 12, 0, 0)
        self.hardware_sensor = HardwareSensorPanel(self.controller)
        hw_layout.addWidget(self.hardware_sensor)
        hw_layout.addStretch(1)
        self.sensor_workspace_tabs.addTab(hw_page, "DS18B20")

        source_page = QWidget()
        source_layout = QVBoxLayout(source_page)
        source_layout.setContentsMargins(0, 12, 0, 0)
        self.sensor_manager = SensorManagerPanel(self.controller)
        source_layout.addWidget(self.sensor_manager)
        source_layout.addStretch(1)
        self.sensor_workspace_tabs.addTab(source_page, "Джерела")
        layout.addWidget(self.sensor_workspace_tabs, 1)
        layout.addStretch(1)
        self._add_page("sensors", page)

    def _create_device_settings(self) -> None:
        page, layout = self._content(
            "Налаштування ESP32-S3",
            "Усі змінювані параметри зчитуються й записуються через USB до NVS "
            "контролера. Паролі не зберігаються на ПК.",
        )
        self.device_settings = DeviceSettingsPanel(self.controller)
        self.device_settings.setMaximumWidth(925)
        layout.addWidget(self.device_settings, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._add_page("esp32", page)

    def _create_service(
        self, calibration_box, hardware_rgb, config_files,
        preset_row, diagnostic_row,
    ) -> None:
        page, layout = self._content(
            "Сервіс",
            "Калібрування, перевірка, профілі й оновлення — кожен сценарій окремо.",
        )
        self.service_workspace_tabs = QTabWidget()
        self.service_workspace_tabs.setObjectName("serviceWorkspaceTabs")
        self.service_workspace_tabs.setDocumentMode(True)

        check_page = QWidget()
        check = QVBoxLayout(check_page)
        check.setContentsMargins(0, 12, 0, 0)
        check.setSpacing(10)
        self.firmware_status = _label("Прошивка: версію ще не прочитано", "minor", True)
        check.addWidget(self.firmware_status)
        actions = self._service_group("Команди діагностики", diagnostic_row)
        check.addWidget(actions)
        self.diagnostics = DiagnosticPanel(self.controller)
        check.addWidget(self.diagnostics)
        check.addStretch(1)
        self.service_workspace_tabs.addTab(check_page, "Діагностика")

        cal_page = QWidget()
        cal = QVBoxLayout(cal_page)
        cal.setContentsMargins(0, 12, 0, 0)
        cal.setSpacing(12)
        warning = QFrame()
        warning.setObjectName("quietCard")
        wl = QVBoxLayout(warning)
        wl.setContentsMargins(16, 12, 16, 12)
        wl.addWidget(_label(
            "Калібрування змінює швидкість вентилятора. Проводь його лише "
            "за перевіреного силового керування та без ризику перегріву.",
            "minor", True,
        ))
        cal.addWidget(warning)
        cal.addWidget(calibration_box)
        cal.addWidget(self._service_group("Налаштування ARGB на ESP32", hardware_rgb))
        cal.addStretch(1)
        self.service_workspace_tabs.addTab(cal_page, "Калібрування")

        profiles_page = QWidget()
        profiles = QVBoxLayout(profiles_page)
        profiles.setContentsMargins(0, 12, 0, 0)
        profiles.setSpacing(12)
        profiles.addWidget(self._service_group(
            "Профіль системи · вентилятори та підсвітка", preset_row, config_files
        ))
        profiles.addStretch(1)
        self.service_workspace_tabs.addTab(profiles_page, "Профілі")

        update_page = QWidget()
        update = QVBoxLayout(update_page)
        update.setContentsMargins(0, 12, 0, 0)
        self.maintenance_panel = MaintenancePanel(self.controller)
        update.addWidget(self.maintenance_panel)
        update.addStretch(1)
        self.service_workspace_tabs.addTab(update_page, "Прошивка / копії")

        desktop_page = QWidget()
        desktop = QVBoxLayout(desktop_page)
        desktop.setContentsMargins(0, 12, 0, 0)
        self.settings_panel = DesktopSettingsPanel(self.controller)
        desktop.addWidget(self.settings_panel)
        desktop.addStretch(1)
        self.service_workspace_tabs.addTab(desktop_page, "Windows")

        layout.addWidget(self.service_workspace_tabs, 1)
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

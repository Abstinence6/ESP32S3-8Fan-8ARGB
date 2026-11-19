"""Modern, task-based PySide6 shell for the existing 8Fan/8ARGB controller.

The original controls are *moved*, not recreated. Their signal connections and
the firmware/serial/safety behaviour stay in main.py.
"""
from __future__ import annotations

from collections.abc import Iterable
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from settings_widgets import DesktopSettingsPanel
from hardware_sensor_ui import HardwareSensorPanel
from argb_studio_ui import ArgbStudioPanel
from native_effects_ui import NativeEffectsPanel
from reactive_argb_ui import ReactiveArgbPanel
from audio_reactive_ui import AudioReactivePanel
from temperature_argb_ui import TemperatureArgbPanel
from maintenance_ui import MaintenancePanel
from device_settings_ui import DeviceSettingsPanel
from diagnostics_ui import DiagnosticPanel
from sensor_manager_ui import SensorManagerPanel
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLayout, QPushButton, QProgressBar, QRadioButton, QScrollArea, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget, QDialog, QLineEdit, QListWidget,
    QListWidgetItem, QSizePolicy, QTabWidget, QToolButton, QStyle,
)


FAN_TELEMETRY_TTL = 15.0  # > two 5 s STATUS polls, tolerant of USB jitter

PAGES = (
    ("overview", "Головна", "Головна", "Стан контролера та швидкі дії"),
    ("fans", "Охолодження", "Охолодження", "Швидкість, криві та режими"),
    ("sensors", "Температури", "Температури", "Джерела й датчики"),
    ("argb", "Підсвітка", "Підсвітка", "Кольори, ефекти й синхронізація"),
    ("pc", "Живлення ПК", "Живлення ПК", "Керування кнопкою живлення"),
    ("esp32", "Налаштування ESP32", "Налаштування ESP32", "Wi-Fi, MQTT та периферія"),
    ("service", "Інструменти", "Інструменти", "Діагностика, оновлення та профілі"),
    ("logs", "Консоль", "Консоль", "Журнал подій і команди"),
)
ADVANCED_PAGES = frozenset(("pc", "esp32", "service", "logs"))

# Native Windows/Qt theme: platform controls keep their OS appearance.
# Only dashboard panels and status indicators have scoped decoration.
STYLE = """
QFrame#sidebar { background-color: palette(window); border-right: 1px solid palette(mid); }
QFrame#topbar { background-color: palette(window); border-bottom: 1px solid palette(mid); }
QFrame#metricsStrip, QFrame#fanCard, QFrame#quietCard, QFrame#systemBanner,
QFrame#nativeQuickStart, QFrame#nativeActions {
    background-color: palette(base); border: 1px solid palette(mid); border-radius: 8px;
}
QFrame#metricSlot { border: none; background: transparent; }
QFrame#fanCard:hover { border: 1px solid palette(highlight); }
QFrame#fanCard[state="warning"], QFrame#systemBanner[state="warning"] { border-color: #b68745; }
QFrame#fanCard[state="critical"], QFrame#systemBanner[state="critical"] { border-color: #bb5561; }
QFrame#fanCard[state="disabled"], QFrame#zoneTile[disabled="true"] { background-color: palette(window); }
QFrame#zoneTile { background-color: palette(base); border: 1px solid palette(mid); border-radius: 6px; }
QFrame#zoneTile[selected="true"], QFrame#systemBanner[state="normal"] { border-color: palette(highlight); }
QFrame#zonePixels { background-color: palette(midlight); border: none; border-radius: 3px; }
QFrame#zonePixels[selected="true"] { background-color: palette(highlight); }
QFrame#settingsActionFooter { background-color: palette(base); border: 1px solid palette(mid); }
QLabel[role="brand"] { font-size: 17pt; font-weight: 700; }
QLabel[role="pageTitle"] { font-size: 18pt; font-weight: 650; }
QLabel[role="bannerTitle"] { font-size: 15pt; font-weight: 650; }
QLabel[role="bigNumber"] { font-size: 19pt; font-weight: 650; }
QLabel[role="metricValue"] { font-size: 12pt; font-weight: 600; }
QLabel[role="labelTitle"] { font-weight: 600; }
QLabel[role="sectionLabel"] { font-size: 9pt; font-weight: 600; }
QLabel[role="minor"] { font-size: 9pt; }
QLabel[role="positive"] { color: #259363; font-weight: 600; }
QLabel[role="caution"] { color: #bb863f; font-weight: 600; }
QLabel[role="negative"] { color: #cd6571; font-weight: 600; }
QPushButton[role="nav"] { text-align: left; border: none; padding: 8px 10px; }
QPushButton[role="nav"]:hover { background-color: palette(midlight); }
QPushButton[role="nav"]:checked { border-left: 3px solid palette(highlight); background-color: palette(midlight); font-weight: 600; }
QPushButton[role="ghost"] { color: palette(highlight); background: transparent; border: none; text-align: left; padding: 3px 1px; }
QPushButton[role="ghost"]:hover { text-decoration: underline; }
QPushButton[role="filter"]:checked { border: 1px solid palette(highlight); }
QPushButton[role="danger"] { border: 1px solid #bb5561; }
QProgressBar#fanDuty { border: 0; background-color: palette(midlight); min-height: 7px; max-height: 7px; }
QProgressBar#fanDuty::chunk { background-color: palette(highlight); }
QProgressBar#fanDuty[state="warning"]::chunk { background-color: #b68745; }
QProgressBar#fanDuty[state="critical"]::chunk { background-color: #bb5561; }
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
        self.fan_cards: dict[int, dict[str, QWidget]] = {}
        self.pc_buttons: dict[str, QPushButton] = {}
        self.is_connected = False
        self.current_pc_state = "unknown"
        self.current_pc_busy = False
        self.pc_state_updated_at = 0.0
        self._fan_statuses: dict[int, object] = {}
        self.available_channel_mask = 0xFF  # unknown firmware -> legacy 8-channel behavior
        self._channel_mask_known = False
        self._last_fan_update: dict[int, float] = {}
        self._expired_fan_channels: set[int] = set()
        self._fan_grid_columns = 0
        self._fan_grid_visible: tuple[int, ...] = ()
        self._attention_only = False
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
        overview_shortcut = QShortcut(QKeySequence("Alt+Home"), self)
        overview_shortcut.activated.connect(lambda: self.show_page("overview"))
        self._shortcuts.append(overview_shortcut)
        palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        palette_shortcut.activated.connect(self.open_command_palette)
        self._shortcuts.append(palette_shortcut)
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.timeout.connect(self.refresh_telemetry_freshness)
        self._telemetry_timer.start(1000)
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
        panel.setFixedWidth(216)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 20, 14, 16)
        layout.setSpacing(5)
        layout.addWidget(_label("FanARGB", "brand"))
        layout.addWidget(_label("ESP32-S3 · керування", "minor"))
        layout.addSpacing(18)
        layout.addWidget(_label("ОСНОВНЕ", "sectionLabel"))

        icons = {
            "overview": QStyle.StandardPixmap.SP_DirHomeIcon,
            "fans": QStyle.StandardPixmap.SP_ComputerIcon,
            "sensors": QStyle.StandardPixmap.SP_DriveHDIcon,
            "argb": QStyle.StandardPixmap.SP_DialogApplyButton,
            "pc": QStyle.StandardPixmap.SP_DesktopIcon,
            "esp32": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "service": QStyle.StandardPixmap.SP_DialogHelpButton,
            "logs": QStyle.StandardPixmap.SP_FileIcon,
        }
        self.advanced_container = QWidget()
        advanced = QVBoxLayout(self.advanced_container)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(5)
        for index, (key, caption, title, _hint) in enumerate(PAGES, 1):
            button = QPushButton(caption)
            button.setProperty("role", "nav")
            button.setFlat(True)
            button.setIcon(self.style().standardIcon(icons[key]))
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.setAccessibleName(title)
            button.setToolTip(f"{title} · Ctrl+{index}")
            button.clicked.connect(
                lambda checked=False, selected=key: self.show_page(selected)
            )
            (advanced if key in ADVANCED_PAGES else layout).addWidget(button)
            self.nav[key] = button

        layout.addSpacing(16)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setText("Додатково")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        )
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced_container)
        self.advanced_toggle.setChecked(
            str(self.controller.settings.value("showAdvancedNavigation", "false")).lower()
            in ("true", "1")
        )
        self._toggle_advanced(self.advanced_toggle.isChecked())
        layout.addStretch(1)
        layout.addWidget(_label("Ctrl+K — швидкий пошук", "minor", True))
        self.sidebar_connection_hint = _label("ESP32 не підключено", "minor", True)
        layout.addWidget(self.sidebar_connection_hint)
        return panel

    def _toggle_advanced(self, visible: bool) -> None:
        self.advanced_container.setVisible(visible)
        self.controller.settings.setValue("showAdvancedNavigation", visible)

    def _topbar(self, refresh_ports: QPushButton) -> QWidget:
        panel = QFrame()
        panel.setObjectName("topbar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(22, 10, 22, 10)
        layout.setSpacing(8)
        self.connection_text = _label("ESP32 · не підключено", "caution")
        self.connection_text.setToolTip("ESP32-S3 через USB. При втраті температур діє fail-safe.")
        layout.addWidget(self.connection_text)
        layout.addStretch(1)
        search = QPushButton("Знайти…")
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
        page.setMinimumWidth(0)
        outside = QVBoxLayout(page)
        outside.setContentsMargins(18, 0, 18, 0)
        outside.setSpacing(0)
        # Never stretch a fan card to 700px on ultrawide monitors.
        # All pages share this same centered readable canvas.
        body = QWidget(page)
        body.setObjectName("pageCanvas")
        body.setMinimumWidth(0)
        body.setMaximumWidth(1280)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(7, 21, 7, 26)
        layout.setSpacing(14)
        layout.addWidget(_page_header(title, subtitle))
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        center.addStretch(1)
        center.addWidget(body, 100)
        center.addStretch(1)
        outside.addLayout(center)
        outside.addStretch(1)
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
            "Головна",
            "Стан ESP32 і керування вентиляторами.",
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
        diagnostics_button = QPushButton("Діагностика")
        diagnostics_button.setProperty("role", "ghost")
        diagnostics_button.setToolTip("Відкрити діагностику контролера")
        diagnostics_button.clicked.connect(lambda: self.show_page("service"))
        right.addWidget(diagnostics_button)
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
        self.channel_availability = _label("01–08", "minor", True)
        heading.addWidget(self.channel_availability)
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
        self.attention_filter = QPushButton("Проблемні")
        self.attention_filter.setCheckable(True)
        self.attention_filter.setProperty("role", "filter")
        self.attention_filter.setToolTip(
            "Залишити на екрані канали з аварією, застарілою температурою "
            "або ще не отриманим статусом. Фільтр не змінює керування."
        )
        self.attention_filter.setAccessibleName("Показати тільки проблемні вентилятори")
        self.attention_filter.toggled.connect(self._toggle_attention_filter)
        heading.addWidget(self.attention_filter)
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
            frame.setMinimumHeight(132)
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            frame.setToolTip(f"Вентилятор {ch} · відкрий налаштування для деталей")
            box = QVBoxLayout(frame)
            box.setContentsMargins(14, 11, 14, 10)
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
            duty = QProgressBar()
            duty.setObjectName("fanDuty")
            duty.setRange(0, 100)
            duty.setValue(0)
            duty.setTextVisible(False)
            duty.setProperty("state", "idle")
            duty.setToolTip("PWM: немає даних")
            duty.setAccessibleName(f"PWM вентилятора {ch}")
            duty.setAccessibleDescription("Поточний відсоток PWM, тільки для перегляду")
            box.addWidget(duty)
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
                "bar": duty,
            }
        layout.addLayout(grid)
        self.attention_empty_card = QFrame()
        self.attention_empty_card.setObjectName("quietCard")
        empty_box = QVBoxLayout(self.attention_empty_card)
        empty_box.setContentsMargins(18, 17, 18, 17)
        empty_box.setSpacing(4)
        empty_box.addWidget(_label("Немає каналів для перегляду", "labelTitle"))
        self.attention_empty_text = _label(
            "Дані ще не отримано. Перевір підключення контролера.", "minor", True
        )
        empty_box.addWidget(self.attention_empty_text)
        self.attention_empty_card.setVisible(False)
        layout.addWidget(self.attention_empty_card)
        layout.addStretch(1)
        self._add_page("overview", page)
        self._reflow_fan_cards()

    def _toggle_sources(self, checked: bool) -> None:
        for labels in self.fan_cards.values():
            labels["source"].setVisible(checked)
        self.controller.settings.setValue("showFanSources", checked)

    def _toggle_attention_filter(self, checked: bool) -> None:
        """Local display filter; never sends commands to a fan."""
        self._attention_only = bool(checked)
        self._reflow_fan_cards()

    def _fan_telemetry_stale(self, channel: int, now: float | None = None) -> bool:
        stamp = self._last_fan_update.get(channel)
        if stamp is None:
            return True
        return (time.monotonic() if now is None else now) - stamp > FAN_TELEMETRY_TTL

    def refresh_telemetry_freshness(self) -> None:
        """Expire individual card values even while PONG/USB stays connected."""
        if not self.is_connected:
            return
        now = time.monotonic()
        expired = {
            ch for ch in self._fan_statuses
            if self._fan_telemetry_stale(ch, now)
        }
        new_expired = expired - self._expired_fan_channels
        if not new_expired:
            return
        self._expired_fan_channels.update(new_expired)
        for ch in new_expired:
            labels = self.fan_cards.get(ch)
            if not labels or not self.is_channel_available(ch):
                continue
            age = max(0, int(now - self._last_fan_update[ch]))
            labels["rpm"].setText("— RPM")
            labels["metrics"].setText("PWM — %  ·  — °C")
            labels["state"].setText(f"Статус застарів · {age} с")
            labels["state"].setProperty("role", "caution")
            labels["state"].style().unpolish(labels["state"])
            labels["state"].style().polish(labels["state"])
            bar = labels["bar"]
            bar.setToolTip("Немає актуальної телеметрії PWM")
            bar.setProperty("state", "warning")
            bar.style().unpolish(bar)
            bar.style().polish(bar)
            frame = self._fan_frames[ch]
            frame.setProperty("state", "warning")
            frame.setToolTip(f"FAN {ch:02d}: немає телеметрії {age} с")
            frame.style().unpolish(frame)
            frame.style().polish(frame)
        self._update_cooling_health()
        self._refresh_attention_count()
        self._reflow_fan_cards()
        self._refresh_fan_detail()

    def _refresh_attention_count(self) -> None:
        count = sum(
            bool(status.fault) or not bool(status.fresh)
            or self._fan_telemetry_stale(channel)
            for channel, status in self._fan_statuses.items()
            if self.is_channel_available(channel)
        )
        self.attention_filter.setText(
            f"Проблемні · {count}" if count else "Проблемні · 0"
        )
        self.attention_filter.setToolTip(
            f"Зафіксовано {count} проблемних каналів. "
            "Непрочитані канали також відображаються у фільтрі."
        )

    def _reflow_fan_cards(self) -> None:
        if not hasattr(self, "_fan_grid"):
            return
        available = max(0, self.width() - 252)
        columns = 4 if available >= 1000 else 3 if available >= 765 else 2
        visible = tuple(
            ch for ch in self._fan_frames
            if not self._attention_only or (
                self.is_channel_available(ch) and (
                    not self.is_connected
                    or ch not in self._fan_statuses
                    or bool(self._fan_statuses[ch].fault)
                    or not bool(self._fan_statuses[ch].fresh)
                    or self._fan_telemetry_stale(ch)
                )
            )
        )
        if columns != self._fan_grid_columns or visible != self._fan_grid_visible:
            self._fan_grid_columns = columns
            self._fan_grid_visible = visible
            for frame in self._fan_frames.values():
                self._fan_grid.removeWidget(frame)
                frame.hide()
            for index, ch in enumerate(visible):
                frame = self._fan_frames[ch]
                self._fan_grid.addWidget(frame, index // columns, index % columns)
                frame.show()
            for col in range(4):
                self._fan_grid.setColumnStretch(col, 1 if col < columns else 0)
        self.attention_empty_card.setVisible(self._attention_only and not visible)
        if self._attention_only and not visible:
            self.attention_empty_text.setText(
                f"Усі {self.available_channel_mask.bit_count()} доступних вентиляторів передають актуальний стан без аварій. "
                "Повернись до «Усі канали», щоб побачити їхні параметри."
            )
        metrics_columns = 4  # always one compact row
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
        self._reflow_device_settings()

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
            active = {
                ch: status for ch, status in self._fan_statuses.items()
                if self.is_channel_available(ch)
            }
            faults = sum(bool(s.fault) for s in active.values())
            stale = sum(not bool(s.fresh) for s in active.values())
            expired = sum(self._fan_telemetry_stale(ch) for ch in active)
            count = len(active)
            expected = self.available_channel_mask.bit_count()
            if faults:
                title = f"Потрібна увага · {faults} каналів"
                detail = "Виявлено аварійні стани. Відкрий Інструменти → Діагностика для перевірки."
                state = "critical"
            elif expired:
                title = f"Телеметрія застаріла · {expired} каналів"
                detail = "ESP32 підключена, але немає свіжих статусів вентиляторів. Значення RPM/PWM приховано."
                state = "warning"
            elif stale:
                title = f"Захисне охолодження · {stale} каналів"
                detail = "Немає свіжої температури на частині каналів — застосовується fail-safe."
                state = "warning"
            elif count < expected:
                title = f"Перевіряємо канали · {count}/{expected}"
                detail = "Стан решти вентиляторів ще не отримано. Оцінка охолодження неповна."
                state = "idle"
            else:
                title = "Охолодження працює"
                detail = f"Усі {expected} доступних каналів передають актуальний стан."
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
            "Крива ліворуч, керування і поточний стан вибраного каналу праворуч.",
        )
        toolbar = QFrame()
        toolbar.setObjectName("quietCard")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(16, 11, 16, 11)
        bar.setSpacing(10)
        _move_controls(choose_row, bar)
        for label in toolbar.findChildren(QLabel):
            if label.text().startswith("Редагувати криву"):
                label.setText("Канал")
        self.controller.fan_box.setMinimumWidth(150)
        self.controller.fan_box.setMaximumWidth(235)
        self.controller.type_box.setMaximumWidth(220)
        layout.addWidget(toolbar)

        self.fan_workspace_tabs = QTabWidget()
        self.fan_workspace_tabs.setObjectName("fanWorkspaceTabs")
        self.fan_workspace_tabs.setDocumentMode(True)
        self.fan_workspace_tabs.tabBar().setDrawBase(False)

        curve_page = QWidget()
        curve_layout = QVBoxLayout(curve_page)
        curve_layout.setContentsMargins(0, 12, 0, 0)
        curve_layout.setSpacing(12)

        # Retain all original Qt widgets and signals. Only move their layouts
        # from below the enormous chart into a readable adjacent editor.
        original_layout = curve_box.layout()
        curve_actions = original_layout.takeAt(1).layout()
        regulation_actions = original_layout.takeAt(1).layout()
        if curve_actions is None or regulation_actions is None:
            raise RuntimeError("Fan editor controls were not found")
        curve_box.setTitle("Крива PWM · температура")
        curve_box.setMinimumHeight(370)
        self.controller.curve_plot.setMinimumHeight(300)
        curve_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.fan_live_card = QFrame()
        self.fan_live_card.setObjectName("quietCard")
        live = QVBoxLayout(self.fan_live_card)
        live.setContentsMargins(17, 14, 17, 14)
        live.setSpacing(6)
        live.addWidget(_label("ПОТОЧНИЙ КАНАЛ", "sectionLabel"))
        self.fan_live_title = _label("FAN 01", "labelTitle")
        live.addWidget(self.fan_live_title)
        self.fan_live_rpm = _label("— RPM", "bigNumber")
        live.addWidget(self.fan_live_rpm)
        self.fan_live_metrics = _label("PWM — %   ·   — °C", "minor")
        live.addWidget(self.fan_live_metrics)
        self.fan_live_state = _label("Очікуємо дані контролера", "minor", True)
        live.addWidget(self.fan_live_state)
        self.fan_live_card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )

        editor = QFrame()
        editor.setObjectName("quietCard")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(17, 14, 17, 14)
        editor_layout.setSpacing(8)
        editor_layout.addWidget(_label("РЕДАГУВАННЯ КРИВОЇ", "sectionLabel"))
        _move_controls(curve_actions, editor_layout)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        tuning = QFrame()
        tuning.setObjectName("quietCard")
        tuning_layout = QVBoxLayout(tuning)
        tuning_layout.setContentsMargins(17, 14, 17, 14)
        tuning_layout.setSpacing(8)
        tuning_layout.addWidget(_label("РЕЖИМ РЕГУЛЮВАННЯ", "sectionLabel"))
        _move_controls(regulation_actions, tuning_layout)
        tuning.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self.fan_control_panel = QWidget()
        side = QVBoxLayout(self.fan_control_panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(10)
        side.addWidget(self.fan_live_card)
        side.addWidget(editor)
        side.addWidget(tuning)
        side.addStretch(1)
        self.fan_control_panel.setMinimumWidth(270)
        self.fan_control_panel.setMaximumWidth(360)
        self.fan_control_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        split = QGridLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setHorizontalSpacing(13)
        split.setVerticalSpacing(13)
        split.addWidget(curve_box, 0, 0)
        split.addWidget(self.fan_control_panel, 0, 1)
        split.setColumnStretch(0, 7)
        split.setColumnStretch(1, 4)
        curve_layout.addLayout(split)
        curve_layout.addWidget(_label(
            "Крива змінюється перетягуванням точок. Вона записується в ESP32 "
            "тільки після натискання «Зберегти». Обмеження силового DC PWM не змінюються.",
            "minor", True,
        ))
        curve_layout.addStretch(1)
        self.fan_workspace_tabs.addTab(curve_page, "Керування та криві")

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 12, 0, 0)
        list_layout.setSpacing(10)
        table_box.setTitle("8 каналів · PWM, RPM та джерела температури")
        table_box.setMinimumHeight(400)
        self.controller.fan_table.setMaximumHeight(16777215)
        list_layout.addWidget(table_box)
        list_layout.addStretch(1)
        self.fan_workspace_tabs.addTab(list_page, "Список вентиляторів")

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(0, 12, 0, 0)
        history_box.setTitle("Історія вибраного вентилятора")
        history_box.setMinimumHeight(390)
        history_layout.addWidget(history_box)
        history_layout.addStretch(1)
        self.fan_workspace_tabs.addTab(history_page, "Історія")

        layout.addWidget(self.fan_workspace_tabs, 1)
        layout.addStretch(1)
        self.controller.fan_box.currentIndexChanged.connect(
            lambda _index: self._refresh_fan_detail()
        )
        self._refresh_fan_detail()
        self._add_page("fans", page)

    def _refresh_fan_detail(self) -> None:
        channel = self.controller.fan_box.currentData()
        if channel is None:
            return
        self.fan_live_title.setText(f"FAN {channel:02d}")
        if not self.is_channel_available(channel):
            self.fan_live_rpm.setText("— RPM")
            self.fan_live_metrics.setText("Фізичний канал вимкнено")
            self.fan_live_state.setText("Недоступний на цій платі")
            return
        status = self._fan_statuses.get(channel)
        if not self.is_connected or status is None or self._fan_telemetry_stale(channel):
            self.fan_live_rpm.setText("— RPM")
            self.fan_live_metrics.setText("PWM — %   ·   — °C")
            self.fan_live_state.setText(
                "Статус вентилятора застарів"
                if self.is_connected and status is not None else "Немає актуальної телеметрії"
            )
            self.fan_live_state.setProperty("role", "caution" if status is not None else "minor")
        else:
            self.fan_live_rpm.setText(
                f"{status.rpm:,} RPM".replace(",", " ") if status.rpm_feedback else "— RPM"
            )
            temp = f"{status.deci_c / 10:.1f} °C" if status.fresh else "— °C"
            self.fan_live_metrics.setText(f"PWM {status.pwm}%   ·   {temp}")
            if status.fault:
                message, role = "Аварія вентилятора · перевір TACH", "negative"
            elif not status.fresh:
                message, role = "Немає температури · захисне охолодження", "caution"
            else:
                message, role = (
                    "Автоматичне регулювання" if status.mode.lower() == "auto"
                    else "Ручне керування"
                ), "positive"
            self.fan_live_state.setText(message)
            self.fan_live_state.setProperty("role", role)
        self.fan_live_state.style().unpolish(self.fan_live_state)
        self.fan_live_state.style().polish(self.fan_live_state)

    def _create_argb(self, rgb_box, scenes: Iterable[str]) -> None:
        page, layout = self._content(
            "Підсвітка ARGB",
            "Вибери зону й ефект. Розташування зон показано схематично.",
        )
        self.argb_workspace_tabs = QTabWidget()
        self.argb_workspace_tabs.setObjectName("argbWorkspaceTabs")
        self.argb_workspace_tabs.setDocumentMode(True)
        self.argb_workspace_tabs.tabBar().setDrawBase(False)

        scenes_page = QWidget()
        scenes_layout = QVBoxLayout(scenes_page)
        scenes_layout.setContentsMargins(0, 12, 0, 0)
        scenes_layout.setSpacing(13)

        zone_map = QFrame()
        zone_map.setObjectName("quietCard")
        map_layout = QVBoxLayout(zone_map)
        map_layout.setContentsMargins(17, 15, 17, 15)
        map_layout.setSpacing(12)
        map_layout.addWidget(_label("8 НЕЗАЛЕЖНИХ ЗОН", "sectionLabel"))
        map_grid = QGridLayout()
        map_grid.setContentsMargins(0, 0, 0, 0)
        map_grid.setHorizontalSpacing(9)
        map_grid.setVerticalSpacing(9)
        self.argb_zone_tiles: dict[int, tuple[QFrame, QFrame]] = {}
        for ch in range(1, 9):
            tile = QFrame()
            tile.setObjectName("zoneTile")
            tile.setProperty("selected", False)
            line = QHBoxLayout(tile)
            line.setContentsMargins(10, 9, 10, 9)
            line.setSpacing(9)
            pick = QPushButton(f"ARGB {ch:02d}")
            pick.setProperty("role", "ghost")
            pick.setFixedWidth(84)
            pick.setToolTip(f"Вибрати канал ARGB {ch} без зміни світлодіодів")
            pick.clicked.connect(
                lambda _checked=False, zone=ch: self.zone_box.setCurrentIndex(zone - 1)
            )
            line.addWidget(pick)
            strip = QFrame()
            strip.setObjectName("zonePixels")
            strip.setProperty("selected", False)
            strip.setFixedHeight(9)
            strip.setMinimumWidth(35)
            line.addWidget(strip, 1)
            self.argb_zone_tiles[ch] = (tile, strip)
            map_grid.addWidget(tile, (ch - 1) // 2, (ch - 1) % 2)
        map_grid.setColumnStretch(0, 1)
        map_grid.setColumnStretch(1, 1)
        map_layout.addLayout(map_grid)
        map_layout.addWidget(_label(
            "Схема вибору каналів · кольори не зчитуються з фізичних LED.",
            "minor", True,
        ))

        select = QFrame()
        select.setObjectName("quietCard")
        control = QVBoxLayout(select)
        control.setContentsMargins(17, 15, 17, 15)
        control.setSpacing(9)
        control.addWidget(_label("СЦЕНА", "sectionLabel"))
        control.addWidget(_label("Канал", "labelTitle"))
        self.zone_box = QComboBox()
        self.zone_box.setMinimumWidth(110)
        for ch in range(1, 9):
            self.zone_box.addItem(f"ARGB {ch}", ch)
        self.zone_box.currentIndexChanged.connect(self._zone_changed)
        control.addWidget(self.zone_box)
        control.addWidget(_label("Ефект", "labelTitle"))
        self.scene_box = QComboBox()
        self.scene_box.addItems(list(scenes))
        self.scene_box.setMinimumWidth(170)
        control.addWidget(self.scene_box)
        self.scope_one = QRadioButton("Лише вибрана зона")
        self.scope_all = QRadioButton("Усі 8 зон")
        self.scope_one.setChecked(True)
        control.addWidget(self.scope_one)
        control.addWidget(self.scope_all)
        apply_button = QPushButton("Застосувати ефект")
        apply_button.setProperty("role", "primary")
        apply_button.clicked.connect(self._apply_scene)
        control.addWidget(apply_button)
        control.addStretch(1)

        work = QGridLayout()
        work.setContentsMargins(0, 0, 0, 0)
        work.setHorizontalSpacing(13)
        work.addWidget(zone_map, 0, 0)
        work.addWidget(select, 0, 1)
        work.setColumnStretch(0, 7)
        work.setColumnStretch(1, 4)
        scenes_layout.addLayout(work)

        # All original manual controls remain wired to the controller;
        # move only their widgets out of the formerly sprawling rgb_box.
        rgb_layout = rgb_box.layout()
        manual_row = rgb_layout.takeAt(0).layout()
        if manual_row is None:
            raise RuntimeError("Manual ARGB controls were not found")
        quick = QFrame()
        quick.setObjectName("quietCard")
        quick_layout = QVBoxLayout(quick)
        quick_layout.setContentsMargins(17, 14, 17, 14)
        quick_layout.setSpacing(9)
        quick_layout.addWidget(_label("ШВИДКІ КОМАНДИ", "sectionLabel"))
        quick_actions = QHBoxLayout()
        quick_actions.setSpacing(9)
        _move_controls(manual_row, quick_actions)
        quick_layout.addLayout(quick_actions)
        scenes_layout.addWidget(quick)
        scenes_layout.addWidget(_label(
            "Ефекти надсилаються на контролер після застосування. "
            "Умовні смужки вище позначають вибір, а не фактичну підсвітку.",
            "minor", True,
        ))
        scenes_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(scenes_page, "Ефекти")

        openrgb_page = QWidget()
        openrgb_layout = QVBoxLayout(openrgb_page)
        openrgb_layout.setContentsMargins(0, 12, 0, 0)
        openrgb_layout.setSpacing(12)
        native = QFrame()
        native.setObjectName("quietCard")
        native_layout = QVBoxLayout(native)
        native_layout.setContentsMargins(17, 15, 17, 15)
        native_layout.setSpacing(8)
        native_layout.addWidget(_label("OPENRGB SDK", "sectionLabel"))
        self.native_checkbox = QCheckBox("Native OpenRGB SDK · 8 зон")
        self.native_checkbox.toggled.connect(self.controller.toggle_native_openrgb)
        native_layout.addWidget(self.native_checkbox)
        native_layout.addWidget(_label(
            "Локальний сервер 127.0.0.1:6743. У OpenRGB увімкни Remote SDK server.",
            "minor", True,
        ))
        openrgb_layout.addWidget(native)
        rgb_box.setTitle("E1.31 / DDP · USB-міст і параметри передачі")
        for label in rgb_box.findChildren(QLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        openrgb_layout.addWidget(rgb_box)
        note = QFrame()
        note.setObjectName("quietCard")
        foot = QVBoxLayout(note)
        foot.setContentsMargins(17, 14, 17, 14)
        foot.addWidget(_label(
            "Вісім E1.31 Universes (1–8) → 8 зон, DMX Start 1. "
            "Для прямого Wi-Fi E1.31/DDP відкрий налаштування ESP32.",
            "minor", True,
        ))
        openrgb_layout.addWidget(note)
        openrgb_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(openrgb_page, "OpenRGB")

        studio_page = QWidget()
        studio_layout = QVBoxLayout(studio_page)
        studio_layout.setContentsMargins(0, 12, 0, 0)
        studio_layout.setSpacing(9)
        self.studio = ArgbStudioPanel(self.controller)
        studio_layout.addWidget(self.studio)
        studio_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(studio_page, "Студія")

        temperature_page = QWidget()
        temperature_layout = QVBoxLayout(temperature_page)
        temperature_layout.setContentsMargins(0, 12, 0, 0)
        self.temperature_argb = TemperatureArgbPanel(self.controller)
        temperature_layout.addWidget(self.temperature_argb)
        self.argb_workspace_tabs.addTab(temperature_page, "Температура")
        native_fx_page = QWidget()
        native_fx_layout = QVBoxLayout(native_fx_page)
        native_fx_layout.setContentsMargins(0, 12, 0, 0)
        self.native_effects = NativeEffectsPanel(self.controller)
        native_fx_layout.addWidget(self.native_effects)
        native_fx_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(native_fx_page, "Ефекти ESP32")

        reactive_page = QWidget()
        reactive_layout = QVBoxLayout(reactive_page)
        reactive_layout.setContentsMargins(0, 12, 0, 0)
        self.reactive_argb = ReactiveArgbPanel(self.controller)
        reactive_layout.addWidget(self.reactive_argb)
        reactive_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(reactive_page, "Реактивні датчики")

        audio_page = QWidget()
        audio_layout = QVBoxLayout(audio_page)
        audio_layout.setContentsMargins(0, 12, 0, 0)
        self.audio_reactive = AudioReactivePanel(self.controller)
        audio_layout.addWidget(self.audio_reactive)
        audio_layout.addStretch(1)
        self.argb_workspace_tabs.addTab(audio_page, "Звукова підсвітка")

        layout.addWidget(self.argb_workspace_tabs, 1)
        layout.addStretch(1)
        self._refresh_argb_zone_tiles()
        self._add_page("argb", page)

    def _refresh_argb_zone_tiles(self) -> None:
        for ch, (tile, strip) in self.argb_zone_tiles.items():
            active = self.zone_box.currentData() == ch
            for widget in (tile, strip):
                if widget.property("selected") != active:
                    widget.setProperty("selected", active)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)

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
        self.sensor_workspace_tabs.tabBar().setDrawBase(False)

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
            "Конфігурація контролера через USB · збереження лише після підтвердження.",
        )
        self.device_settings = DeviceSettingsPanel(self.controller)
        self.device_settings.setMinimumWidth(0)
        self.device_settings.setMaximumWidth(16777215)
        self.device_settings.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )

        self._esp_help_card = QFrame()
        self._esp_help_card.setObjectName("quietCard")
        self._esp_help_card.setMinimumWidth(250)
        self._esp_help_card.setMaximumWidth(310)
        self._esp_help_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        guide = QVBoxLayout(self._esp_help_card)
        guide.setContentsMargins(17, 17, 17, 17)
        guide.setSpacing(11)
        guide.addWidget(_label("ЯК ЦЕ ПРАЦЮЄ", "sectionLabel"))
        guide.addWidget(_label("1. Зчитай стан", "labelTitle"))
        guide.addWidget(_label(
            "Параметри ESP32 читаються через USB. Поля блокуються, "
            "доки відповідь не отримана.", "minor", True,
        ))
        guide.addWidget(_label("2. Зміни потрібне", "labelTitle"))
        guide.addWidget(_label(
            "Перемикай вкладки без застосування інших параметрів. "
            "Зміни Wi-Fi та MQTT позначаються крапкою.", "minor", True,
        ))
        guide.addWidget(_label("3. Підтвердь запис", "labelTitle"))
        guide.addWidget(_label(
            "Кнопка збереження внизу застосовує лише поточну категорію. "
            "Результат перевіряється повторним читанням.", "minor", True,
        ))
        guide.addSpacing(5)
        guide.addWidget(_label("ВАЖЛИВО", "sectionLabel"))
        guide.addWidget(_label(
            "Паролі не записуються в налаштування Windows. "
            "GPIO, MOSFET та апаратний fail-ON не змінюються звідси.",
            "minor", True,
        ))
        diagnostics = QPushButton("Перевірити діагностику")
        diagnostics.setProperty("role", "ghost")
        diagnostics.clicked.connect(lambda: self.show_page("service"))
        guide.addWidget(diagnostics)

        self.esp_settings_columns = QHBoxLayout()
        self.esp_settings_columns.setContentsMargins(0, 0, 0, 0)
        self.esp_settings_columns.setSpacing(15)
        self.esp_settings_columns.addWidget(
            self.device_settings, 4, Qt.AlignmentFlag.AlignTop
        )
        self.esp_settings_columns.addWidget(
            self._esp_help_card, 1, Qt.AlignmentFlag.AlignTop
        )
        layout.addLayout(self.esp_settings_columns)
        layout.addStretch(1)
        self._add_page("esp32", page)
        self._reflow_device_settings()

    def _reflow_device_settings(self) -> None:
        if hasattr(self, "_esp_help_card"):
            # The help rail is optional; never squeeze settings on 1080px screens.
            self._esp_help_card.setVisible(self.width() >= 1260)

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
        self.service_workspace_tabs.tabBar().setDrawBase(False)

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
        if key in ADVANCED_PAGES and not self.advanced_toggle.isChecked():
            self.advanced_toggle.setChecked(True)
        self.stack.setCurrentIndex(self.page_index[key])
        self.setAccessibleDescription(f"Активний розділ: {key}")
        self.stack.widget(self.page_index[key]).verticalScrollBar().setValue(0)
        for name, button in self.nav.items():
            button.setChecked(name == key)

    def open_fan(self, channel: int) -> None:
        if not self.is_channel_available(channel):
            return
        self.controller.fan_box.setCurrentIndex(channel - 1)
        self.show_page("fans")

    def sync_zone(self, index: int) -> None:
        if self.zone_box.currentIndex() != index and 0 <= index < 8:
            self.zone_box.blockSignals(True)
            self.zone_box.setCurrentIndex(index)
            self.zone_box.blockSignals(False)
            self._refresh_argb_zone_tiles()

    def _zone_changed(self, index: int) -> None:
        if 0 <= index < 8:
            self.controller.fan_box.setCurrentIndex(index)
            self._refresh_argb_zone_tiles()

    def _apply_scene(self) -> None:
        self.controller.apply_argb_scene(
            self.scene_box.currentText(), self.scope_all.isChecked()
        )

    def set_connected(self, connected: bool, port_name: str = "") -> None:
        self.is_connected = bool(connected)
        self.temperature_argb.set_connected(connected)
        if connected:
            self.connection_text.setText(f"ESP32 · {port_name}")
            self.connection_text.setProperty("role", "positive")
            self.summary_esp.setText(port_name or "Підключено")
        else:
            self._fan_statuses.clear()
            self._last_fan_update.clear()
            self._expired_fan_channels.clear()
            self.connection_text.setText("ESP32 · не підключено")
            self.connection_text.setProperty("role", "caution")
            self.summary_esp.setText("Не підключено")
            self.update_pc_state("unknown")
            self.summary_mqtt.setText("Не підключено")
            self._channel_mask_known = False
            self.available_channel_mask = 0xFF
            self.channel_availability.setText("01–08")
            for row in range(8):
                for combo in (self.controller.fan_box, self.zone_box):
                    item = combo.model().item(row)
                    if item is not None:
                        item.setEnabled(True)
                tile = self.argb_zone_tiles[row + 1][0]
                tile.setProperty("disabled", False)
                for button in tile.findChildren(QPushButton):
                    button.setEnabled(True)
            for labels in self.fan_cards.values():
                labels["rpm"].setText("— RPM")
                labels["metrics"].setText("— %  ·  — °C")
                frame = self._fan_frames[next(ch for ch, card in self.fan_cards.items() if card is labels)]
                frame.setProperty("state", "idle")
                frame.style().unpolish(frame)
                frame.style().polish(frame)
                labels["bar"].setValue(0)
                labels["bar"].setProperty("state", "idle")
                labels["bar"].setToolTip("PWM: немає даних")
                labels["bar"].style().unpolish(labels["bar"])
                labels["bar"].style().polish(labels["bar"])
                labels["state"].setText("Немає даних")
                labels["state"].setProperty("role", "minor")
                labels["state"].style().unpolish(labels["state"])
                labels["state"].style().polish(labels["state"])
        self.sidebar_connection_hint.setText(
            f"ESP32 · {port_name}" if connected else "ESP32 не підключено"
        )
        self._update_cooling_health()
        self._refresh_attention_count()
        self._reflow_fan_cards()
        self._refresh_fan_detail()
        self._update_pc_buttons()
        self.device_settings.set_connected(connected)
        self.connection_text.style().unpolish(self.connection_text)
        self.connection_text.style().polish(self.connection_text)

    def is_channel_available(self, channel: int) -> bool:
        return 1 <= channel <= 8 and bool(self.available_channel_mask & (1 << (channel - 1)))

    def set_channel_mask(self, mask: int) -> None:
        """Apply firmware-reported capabilities without changing the 8-channel protocol."""
        if not isinstance(mask, int) or not 0 <= mask <= 0xFF:
            return
        self._channel_mask_known = True
        self.available_channel_mask = mask
        active = mask.bit_count()
        self.channel_availability.setText(f"Доступно {active}/8 каналів")
        self.channel_availability.setToolTip(
            "Зайняті Flash/PSRAM GPIO не можуть бути розблоковані програмно."
        )
        for channel in range(1, 9):
            enabled = self.is_channel_available(channel)
            self._fan_frames[channel].setProperty("state", "idle" if enabled else "disabled")
            self._fan_frames[channel].setToolTip(
                f"Вентилятор {channel}" if enabled
                else f"Канал {channel} недоступний на поточній платі"
            )
            if not enabled:
                labels = self.fan_cards[channel]
                labels["rpm"].setText("— RPM")
                labels["metrics"].setText("Фізичний вихід вимкнено")
                labels["state"].setText("Недоступний")
                labels["state"].setProperty("role", "minor")
                labels["bar"].setValue(0)
                labels["bar"].setProperty("state", "idle")
            for widget in (self._fan_frames[channel], self.fan_cards[channel]["state"]):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            row = self.controller.fan_box.model().item(channel - 1)
            if row is not None:
                row.setEnabled(enabled)
            zone = self.zone_box.model().item(channel - 1)
            if zone is not None:
                zone.setEnabled(enabled)
            tile = self.argb_zone_tiles[channel][0]
            tile.setProperty("disabled", not enabled)
            for button in tile.findChildren(QPushButton):
                button.setEnabled(enabled)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
        self._update_cooling_health()
        self._refresh_attention_count()
        self._reflow_fan_cards()
        self._refresh_fan_detail()

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
        if not self.is_channel_available(channel):
            return
        self._fan_statuses[channel] = status
        self._last_fan_update[channel] = time.monotonic()
        self._expired_fan_channels.discard(channel)
        self._fan_frames[channel].setToolTip(
            f"FAN {channel:02d} · {status.pwm}% PWM · "
            + (f"{status.rpm} RPM" if status.rpm_feedback else "TACH недоступний")
        )
        labels["rpm"].setText(
            f"{status.rpm:,} RPM".replace(",", " ") if status.rpm_feedback else "— RPM"
        )
        temp = f"{status.deci_c / 10:.1f} °C" if status.fresh else "— °C"
        labels["metrics"].setText(f"PWM {status.pwm:3d}%  ·  {temp}")
        bar = labels["bar"]
        bar.setValue(max(0, min(100, int(status.pwm))))
        bar.setToolTip(f"PWM вентилятора {channel}: {status.pwm}%")
        bar.setAccessibleDescription(
            f"Канал {channel}, PWM {status.pwm} відсотків, "
            + ("аварія" if status.fault else "захист" if not status.fresh else "норма")
        )
        bar_state = "critical" if status.fault else "warning" if not status.fresh else "normal"
        if bar.property("state") != bar_state:
            bar.setProperty("state", bar_state)
            bar.style().unpolish(bar)
            bar.style().polish(bar)
        frame = self._fan_frames[channel]
        if frame.property("state") != bar_state:
            frame.setProperty("state", bar_state)
            frame.style().unpolish(frame)
            frame.style().polish(frame)
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
        self._refresh_attention_count()
        if self._attention_only:
            self._reflow_fan_cards()
        if channel == self.controller.fan_box.currentData():
            self._refresh_fan_detail()

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

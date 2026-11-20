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
from hardware_sensor_ui import FanTemperatureSourceDialog, HardwareSensorPanel
from argb_studio_ui import ArgbStudioPanel
from argb_effects import render_effect
from config_presets import RGB_SCENES
from native_effects_ui import NativeEffectsPanel
from reactive_argb_ui import ReactiveArgbPanel
from audio_reactive_ui import AudioReactivePanel
from temperature_argb_ui import TemperatureArgbPanel
from maintenance_ui import MaintenancePanel
from device_settings_ui import DeviceSettingsPanel
from diagnostics_ui import DiagnosticPanel
from diagnostics import FanHealth
from sensor_manager_ui import SensorManagerPanel
from fan_animation import FanRotor
from channel_names_ui import ChannelNames, ChannelTitle, plain_tooltip
from protocol import FanStatus
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLayout, QPushButton, QProgressBar, QRadioButton, QScrollArea, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget, QDialog, QLineEdit, QListWidget,
    QListWidgetItem, QSizePolicy, QTabWidget, QToolButton, QStyle,
)


FAN_TELEMETRY_TTL = 15.0  # > two 5 s STATUS polls, tolerant of USB jitter
ESP_TEMPERATURE_TTL = 10.0  # CoolingController::kSensorTimeoutMs
ARGB_EVIDENCE_TTL = 15.0  # A one-shot ESP32 readback is not a live feed.
ARGB_FRAME_TTL = 3.0  # Firmware releases its USB stream mode after 3 s.
ARGB_RAINBOW = ((255, 0, 0), (255, 170, 0), (0, 255, 80), (0, 120, 255), (190, 0, 255))

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
QFrame#metricsStrip, QFrame#fanCard, QFrame#quietCard,
QFrame#nativeQuickStart, QFrame#nativeActions {
    background-color: palette(base); border: 1px solid palette(mid); border-radius: 8px;
}
QFrame#metricSlot { border: none; background: transparent; }
QFrame#systemBanner {
    background: transparent; border: none; border-right: 1px solid palette(mid);
    border-radius: 0px;
}
QFrame#fanCard:hover { border: 1px solid palette(highlight); }
QFrame#fanCard[state="warning"] { border-color: #b68745; }
QFrame#fanCard[state="critical"] { border-color: #bb5561; }
QFrame#systemBanner[state="warning"] { border-left: 3px solid #b68745; }
QFrame#systemBanner[state="critical"] { border-left: 3px solid #bb5561; }
QFrame#fanCard[state="disabled"], QFrame#zoneTile[disabled="true"] { background-color: palette(window); }
QFrame#zoneTile { background-color: palette(base); border: 1px solid palette(mid); border-radius: 6px; }
QFrame#zoneTile[selected="true"] { border-color: palette(highlight); }
QFrame#systemBanner[state="normal"] { border-left: 3px solid palette(highlight); }
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
QPushButton[role="channelSelect"] { min-height: 33px; font-weight: 500; }
QPushButton[role="channelSelect"]:checked {
    background-color: palette(highlight); color: palette(highlighted-text);
    border: 1px solid palette(highlight); font-weight: 700;
}
QPushButton[role="channelSelect"]:disabled { color: palette(mid); }
QPushButton#coolingChannel {
    border: 1px solid palette(mid); border-radius: 5px; padding: 4px 3px;
    background-color: palette(button); color: palette(button-text);
}
QPushButton#coolingChannel:checked {
    background-color: palette(highlight); color: palette(highlighted-text);
    border-color: palette(highlight);
}
QPushButton#coolingChannel:disabled { color: palette(mid); }
QPushButton#coolingChannel[telemetry="warning"]:!checked { border-color: #b68745; }
QPushButton#coolingChannel[telemetry="critical"]:!checked { border-color: #bb5561; }
QPushButton#coolingChannel:focus, QPushButton#coolingChannel:hover:enabled:!checked {
    border-color: palette(highlight);
}
QPushButton#coolingChannel:checked:focus { border-color: palette(highlighted-text); }
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
        all_fans: QWidget,
        selected_controls: QWidget,
        cooling_tools: QWidget,
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
        self.channel_names = ChannelNames(controller.settings)
        self.setObjectName("dashboardRoot")
        self.nav: dict[str, QPushButton] = {}
        self.page_index: dict[str, int] = {}
        self.fan_cards: dict[int, dict[str, QWidget]] = {}
        self.fan_preset_buttons: dict[str, QPushButton] = {}
        self.pc_buttons: dict[str, QPushButton] = {}
        self.is_connected = False
        self._connection_port = ""
        self._demo = False
        self._esp_replied = False
        self._dc_ready: bool | None = None
        self._argb_colors: dict[int, tuple[tuple[int, int, int], ...]] = {}
        self._argb_brightness: dict[int, int] = {}
        self._argb_readback: dict[int, tuple[str, float]] = {}
        self._argb_request: dict[int, tuple[str, float, float]] = {}
        self.current_pc_state = "unknown"
        self.current_pc_busy = False
        self.pc_state_updated_at = 0.0
        self._fan_statuses: dict[int, FanStatus] = {}
        self._cooling_sources: dict[int, tuple[FanHealth, float]] = {}
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

        self.hardware_sensor = HardwareSensorPanel(self.controller)
        self._create_overview()
        self._create_fans(all_fans, selected_controls, cooling_tools, choose_row, curve_box, history_box)
        self._create_sensors(sensors_box)
        self._create_argb(rgb_box, scenes)
        self._create_pc(pc_box)
        self._create_device_settings()
        self._create_service(
            calibration_box, hardware_rgb, config_files,
            preset_row, diagnostic_row,
        )
        self._create_logs(log_box)
        self._rotor_last = time.monotonic()
        self._rotor_timer = QTimer(self)
        self._rotor_timer.setInterval(50)
        self._rotor_timer.timeout.connect(self._advance_fan_rotors)
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
        self._rotor_timer.start()

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
        lay.setContentsMargins(9, 5, 9, 5)
        lay.setSpacing(3)
        lay.addWidget(_label(title.upper(), "sectionLabel"))
        value = _label(initial, "metricValue", True)
        lay.addWidget(value)
        lay.addWidget(_label(subtitle, "minor", True))
        slot.setMinimumWidth(0)
        slot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return slot, value

    @staticmethod
    def _expandable_panel(layout: QVBoxLayout, title: str, content: QWidget,
                          *, expanded: bool = False) -> QToolButton:
        """Place a pre-existing feature panel in an inline disclosure section."""
        frame = QFrame()
        frame.setObjectName("quietCard")
        section = QVBoxLayout(frame)
        section.setContentsMargins(13, 10, 13, 10)
        section.setSpacing(8)
        toggle = QToolButton(frame)
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        toggle.setAccessibleName(title)
        toggle.setToolTip("Розгорнути або згорнути параметри без зміни стану ESP32")
        section.addWidget(toggle)
        section.addWidget(content)
        toggle.toggled.connect(content.setVisible)
        toggle.toggled.connect(
            lambda checked: toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            )
        )
        toggle.setChecked(expanded)
        content.setVisible(expanded)
        layout.addWidget(frame)
        return toggle

    def _create_overview(self) -> None:
        page, layout = self._content(
            "Головна",
            "Стан ESP32 і керування вентиляторами.",
        )
        # One single status strip: ESP32 + sensors + ARGB + MQTT + PC power.
        # No second banner and no action buttons competing with the fan cards.
        header = layout.itemAt(0).widget()
        if header is not None:
            header.hide()
            layout.removeWidget(header)
            header.setParent(None)
            header.deleteLater()
        layout.setContentsMargins(7, 10, 7, 12)
        layout.setSpacing(9)
        telemetry = QFrame()
        telemetry.setObjectName("metricsStrip")
        strip_layout = QVBoxLayout(telemetry)
        strip_layout.setContentsMargins(7, 7, 7, 7)
        self._summary_grid = QGridLayout()
        self._summary_grid.setHorizontalSpacing(0)
        self._summary_grid.setVerticalSpacing(0)
        self._summary_grid_columns = 5
        self._summary_cards: list[QWidget] = []

        banner = QFrame()
        banner.setObjectName("systemBanner")
        banner.setProperty("state", "idle")
        self.system_banner = banner
        status_layout = QVBoxLayout(banner)
        status_layout.setContentsMargins(10, 5, 10, 5)
        status_layout.setSpacing(3)
        status_layout.addWidget(_label("ESP32-S3", "sectionLabel"))
        self.health_title = _label("Контролер не підключено", "metricValue", True)
        status_layout.addWidget(self.health_title)
        self.summary_esp = _label("USB · —", "minor", True)
        status_layout.addWidget(self.summary_esp)
        # Preserve the detailed state for diagnostics/accessibility, not as a
        # multi-line block that needlessly doubles the dashboard height.
        self.health_description = _label(
            "Підключи ESP32 через USB для перевірки охолодження.", "minor", True
        )
        self.health_description.hide()
        banner.setMinimumWidth(0)
        banner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._summary_cards.append(banner)

        for key, title, hint in (
            ("temp", "Датчики", "NWinfo · температури ПК"),
            ("rgb", "ARGB", "OpenRGB"),
            ("mqtt", "MQTT", "Home Assistant"),
            ("pc", "Живлення ПК", "PWR_SW"),
        ):
            card, value = self._summary_card(title, "—", hint)
            self._summary_cards.append(card)
            setattr(self, f"summary_{key}", value)

        for index, card in enumerate(self._summary_cards):
            self._summary_grid.addWidget(card, 0, index)
            self._summary_grid.setColumnStretch(index, 1)
        strip_layout.addLayout(self._summary_grid)
        layout.addWidget(telemetry)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(_label("ВЕНТИЛЯТОРИ", "sectionLabel"))
        self.channel_availability = _label("01–08", "minor")
        heading.addWidget(self.channel_availability)
        heading.addStretch(1)
        self.channel_names_button = QPushButton("Назви каналів…")
        self.channel_names_button.clicked.connect(self._edit_channel_names)
        heading.addWidget(self.channel_names_button)
        details = QCheckBox("Джерела температур")
        details.setToolTip("Показувати джерело температури під RPM")
        self.show_sources = details
        details.setChecked(
            str(self.controller.settings.value("showFanSources", "false")).lower()
            in ("true", "1")
        )
        details.toggled.connect(self._toggle_sources)
        details.setParent(self)  # retained setting without a dashboard control
        details.hide()
        self.attention_filter = QPushButton("Проблемні")
        self.attention_filter.setCheckable(True)
        self.attention_filter.setProperty("role", "filter")
        self.attention_filter.setToolTip(
            "Залишити на екрані канали з аварією, застарілою температурою "
            "або ще не отриманим статусом. Фільтр не змінює керування."
        )
        self.attention_filter.setAccessibleName("Показати тільки проблемні вентилятори")
        self.attention_filter.toggled.connect(self._toggle_attention_filter)
        self.attention_filter.setParent(self)  # retained logic without extra toolbar
        self.attention_filter.hide()
        layout.addLayout(heading)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._fan_grid = grid
        for ch in range(1, 9):
            frame = QFrame()
            frame.setObjectName("fanCard")
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            frame.setToolTip(f"Вентилятор {ch} · відкрий налаштування для деталей")
            box = QVBoxLayout(frame)
            box.setContentsMargins(10, 7, 10, 7)
            box.setSpacing(4)
            heading_row = QHBoxLayout()
            title = ChannelTitle(number=f"FAN {ch:02d}")
            title.set_title(self.channel_names.title("FAN", ch))
            heading_row.addWidget(title, 1)
            state = _label("Очікування", "minor")
            heading_row.addWidget(state)
            box.addLayout(heading_row)
            readings = QHBoxLayout()
            readings.setSpacing(7)
            rotor = FanRotor()
            readings.addWidget(rotor)
            rpm = _label("— RPM", "metricValue", True)
            readings.addWidget(rpm, 1)
            box.addLayout(readings)
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
                "bar": duty, "rotor": rotor, "settings_button": action, "title": title,
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

    def _edit_channel_names(self) -> None:
        if not self.channel_names.edit(self):
            return
        for channel, card in self.fan_cards.items():
            card["title"].set_title(self.channel_names.title("FAN", channel))
            self._refresh_fan_channel_telemetry(channel)
        self._refresh_fan_name(self.controller.fan_box.currentData())
        self._refresh_argb_names()
        self._refresh_argb_targets()

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
        self.controller.refresh_pc_temperature_evidence()
        if not self.is_connected:
            return
        now = time.monotonic()
        self.refresh_cooling_source()
        self._refresh_argb_owner()
        self.temperature_argb.refresh_gradient()
        expired = {
            ch for ch in self._fan_statuses
            if self._fan_telemetry_stale(ch, now)
        }
        new_expired = expired - self._expired_fan_channels
        if not new_expired:
            return
        self._expired_fan_channels.update(new_expired)
        for ch in new_expired:
            self._refresh_fan_channel_telemetry(ch)
            labels = self.fan_cards.get(ch)
            if not labels or not self.is_channel_available(ch):
                continue
            age = max(0, int(now - self._last_fan_update[ch]))
            labels["rpm"].setText("— RPM")
            labels["rotor"].set_rpm(0)
            labels["metrics"].setText("PWM — %  ·  — °C")
            labels["state"].setText("Застарів")
            labels["state"].setProperty("role", "caution")
            labels["state"].style().unpolish(labels["state"])
            labels["state"].style().polish(labels["state"])
            bar = labels["bar"]
            bar.setValue(0)
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
        columns = 4 if available >= 805 else 3 if available >= 630 else 2
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_fan_cards()

    def _update_cooling_health(self) -> None:
        if not self.is_connected:
            title = "Контролер не підключено"
            detail = "Підключи ESP32 через USB. Без температур ПК контролер використовує захисний режим."
            state = "idle"
        elif not self._esp_replied:
            title = "Очікуємо ESP32"
            detail = "USB-порт відкрито, але відповіді ESP32 ще немає."
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
                title = f"Свіжа телеметрія · {count}/{expected}"
                detail = "ESP32 передає актуальні статуси без повідомлень про аварії."
                state = "normal"
        if self.is_connected and self._dc_ready is False:
            detail += " Силовий DC PWM заблоковано апаратним захистом; це не вимір швидкості."
        if self._demo:
            title = "DEMO · тестові дані"
            detail = "Локальна демонстрація; ці дані не підтверджують стан контролера."
        self.health_title.setText(title)
        self.health_description.setText(detail)
        self.system_banner.setToolTip(detail)
        self.health_title.setToolTip(detail)
        if self.system_banner.property("state") != state:
            self.system_banner.setProperty("state", state)
            self.system_banner.style().unpolish(self.system_banner)
            self.system_banner.style().polish(self.system_banner)

    def _create_fans(self, all_fans, selected_controls, cooling_tools, choose_row, curve_box, history_box) -> None:
        page, layout = self._content(
            "Охолодження",
            "Обери FAN і налаштуй швидкість залежно від температури.",
        )
        layout.setContentsMargins(7, 8, 7, 8)
        layout.setSpacing(6)
        toolbar = QFrame()
        toolbar.setObjectName("quietCard")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(8, 5, 8, 5)
        bar.setSpacing(5)
        _move_controls(choose_row, bar)
        # Keep the original combo as the single protocol/state model. Replace
        # its visible editor with eight one-click, mutually exclusive buttons.
        bar.removeWidget(self.controller.fan_box)
        self.controller.fan_box.setParent(toolbar)
        self.controller.fan_box.hide()

        self.fan_channel_group = QButtonGroup(self)
        self.fan_channel_group.setExclusive(True)
        self.fan_channel_buttons: dict[int, QPushButton] = {}
        for ch in range(1, 9):
            button = QPushButton()
            button.setObjectName("coolingChannel")
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.fan_channel_group.addButton(button, ch)
            button.clicked.connect(
                lambda _checked=False, channel=ch:
                    self.controller.fan_box.setCurrentIndex(channel - 1)
            )
            self.fan_channel_buttons[ch] = button
            self._refresh_fan_channel_telemetry(ch)
            bar.addWidget(button, 1)
        self.controller.fan_box.currentIndexChanged.connect(
            lambda _index: self._refresh_fan_channel_buttons()
        )
        self._refresh_fan_channel_buttons()
        self.controller.type_box.setMaximumWidth(220)
        layout.addWidget(toolbar)
        self.fan_curve_editor = QWidget()
        curve_layout = QVBoxLayout(self.fan_curve_editor)
        curve_layout.setContentsMargins(0, 0, 0, 0)
        curve_layout.setSpacing(6)

        # Retain all original Qt widgets and signals. Only move their layouts
        # from below the enormous chart into a readable adjacent editor.
        original_layout = curve_box.layout()
        curve_actions = original_layout.takeAt(1).layout()
        regulation_actions = original_layout.takeAt(1).layout()
        if curve_actions is None or regulation_actions is None:
            raise RuntimeError("Fan editor controls were not found")
        curve_box.setTitle("Температура → швидкість вентилятора (PWM)")
        self.controller.curve_plot.setMinimumHeight(250)
        curve_box.setMaximumHeight(360)
        curve_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.fan_live_card = QFrame()
        self.fan_live_card.setObjectName("quietCard")
        live = QVBoxLayout(self.fan_live_card)
        live.setContentsMargins(12, 6, 12, 6)
        live.setSpacing(3)
        self.fan_live_title = ChannelTitle()
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
        editor_layout.setContentsMargins(12, 6, 12, 6)
        editor_layout.setSpacing(3)
        editor_layout.addWidget(_label("КРИВА ESP32 · NVS", "sectionLabel"))
        self.fan_curve_source = _label("Джерело: —", "minor", True)
        self.fan_curve_source.setTextFormat(Qt.TextFormat.PlainText)
        self.fan_curve_pc_evidence = _label("ПК (локально): немає вимірів", "minor", True)
        self.fan_curve_pc_evidence.setTextFormat(Qt.TextFormat.PlainText)
        self.fan_curve_esp_source = _label("Джерело ESP32: невідоме", "minor", True)
        self.fan_curve_status = _label("Локальна крива", "minor", True)
        editor_layout.addWidget(self.fan_curve_esp_source)
        editor_layout.addWidget(self.fan_curve_source)
        editor_layout.addWidget(self.fan_curve_pc_evidence)
        self.temperature_source_dialog = FanTemperatureSourceDialog(self.hardware_sensor, self)
        self.temperature_source_button = QPushButton("Джерело температури…")
        self.temperature_source_button.clicked.connect(self._open_temperature_source)
        self.hardware_sensor.support_changed.connect(self._update_temperature_source)
        editor_layout.addWidget(self.temperature_source_button)
        editor_layout.addWidget(self.fan_curve_status)
        _move_controls(curve_actions, editor_layout)
        editor_layout.addWidget(_label("ПРЕСЕТИ · ВИБРАНИЙ FAN", "sectionLabel"))

        preset_row = QGridLayout()
        for index, name in enumerate(("Silent", "Default", "Maximum", "Custom")):
            button = QPushButton(name)
            button.setToolTip("Застосувати до вибраного FAN. Потрібне підтвердження запису в NVS.")
            button.clicked.connect(
                lambda _checked=False, preset=name: self.controller.apply_fan_quick_preset(
                    self.controller.current_fan, preset
                )
            )
            preset_row.addWidget(button, index // 2, index % 2)
            self.fan_preset_buttons[name] = button
        editor_layout.addLayout(preset_row)

        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        tuning = QFrame()
        tuning.setObjectName("quietCard")
        tuning_layout = QVBoxLayout(tuning)
        tuning_layout.setContentsMargins(17, 14, 17, 14)
        tuning_layout.setSpacing(8)
        tuning_layout.addWidget(_label("ДОДАТКОВЕ КЕРУВАННЯ", "sectionLabel"))
        tuning_layout.addWidget(_label(
            "Змінюй ці параметри лише якщо знаєш тип підключення "
            "вентилятора та маєш датчик RPM.",
            "minor", True,
        ))
        _move_controls(regulation_actions, tuning_layout)
        tuning_layout.addWidget(self.controller.secondary_checkbox)
        tuning_layout.addWidget(_label("Тип підключення вентилятора", "labelTitle"))
        tuning_layout.addWidget(self.controller.type_box)
        type_apply = next(
            (button for button in toolbar.findChildren(QPushButton)
             if button.text() == "Встановити тип"), None
        )
        if type_apply is not None:
            tuning_layout.addWidget(type_apply)
        pid_actions = original_layout.takeAt(1)
        if pid_actions is not None and pid_actions.layout() is not None:
            _move_controls(pid_actions.layout(), tuning_layout)

        tuning.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self.fan_control_panel = QWidget()
        side = QVBoxLayout(self.fan_control_panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(6)
        side.addWidget(self.fan_live_card)
        side.addWidget(editor)
        self.advanced_fan_toggle = QToolButton()
        self.advanced_fan_toggle.setText("Розширене керування  ▸")
        self.advanced_fan_toggle.setCheckable(True)
        self.advanced_fan_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.advanced_fan_toggle.setToolTip(
            "PID, два датчики температури, RPM і тип підключення"
        )
        side.addWidget(self.advanced_fan_toggle)
        side.addWidget(tuning)
        tuning.setVisible(False)
        self.advanced_fan_toggle.toggled.connect(tuning.setVisible)
        self.advanced_fan_toggle.toggled.connect(
            lambda active: self.advanced_fan_toggle.setText(
                "Розширене керування  ▾" if active
                else "Розширене керування  ▸"
            )
        )
        side.addStretch(1)
        self.fan_control_panel.setMinimumWidth(270)
        self.fan_control_panel.setMaximumWidth(360)
        self.fan_control_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        split = QGridLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setHorizontalSpacing(13)
        chart = QVBoxLayout()
        chart.setSpacing(6)
        chart.addWidget(curve_box)
        self.fan_curve_operating = _label("Робоча точка: —", "minor", True)
        chart.addWidget(self.fan_curve_operating)
        self.fan_curve_numeric = QPushButton("Редагувати точки числами…")
        self.fan_curve_numeric.setToolTip("Змінює локальну чернетку; запис у ESP32 — окремою кнопкою.")
        self.fan_curve_numeric.clicked.connect(self.controller.edit_curve_numbers)
        chart.addWidget(self.fan_curve_numeric, alignment=Qt.AlignmentFlag.AlignLeft)
        chart.addStretch(1)
        split.addLayout(chart, 0, 0)
        split.addWidget(self.fan_control_panel, 0, 1)
        split.setColumnStretch(0, 7)
        split.setColumnStretch(1, 4)
        curve_layout.addLayout(split)
        self.fan_selected_controls = selected_controls
        curve_layout.addWidget(selected_controls)
        layout.addWidget(self.fan_curve_editor)

        history_box.setMinimumHeight(390)
        history_box.setMaximumHeight(440)
        self.fan_history_panel = history_box
        layout.addWidget(history_box)

        self.fan_global_panel = all_fans
        self.fan_global_toggle = self._expandable_panel(layout, "Усі вентилятори", all_fans)
        layout.addWidget(cooling_tools)
        layout.addStretch(1)
        self.controller.fan_box.currentIndexChanged.connect(
            lambda _index: self._refresh_fan_detail()
        )
        self._refresh_fan_detail()
        self._add_page("fans", page)

    def _refresh_fan_channel_buttons(self) -> None:
        selected = self.controller.fan_box.currentData()
        for channel, button in self.fan_channel_buttons.items():
            button.setChecked(selected == channel)

    def _refresh_fan_channel_telemetry(self, channel: int) -> None:
        button = self.fan_channel_buttons[channel]
        title = f"FAN {channel:02d}"
        rpm, pwm, state = "— RPM", "PWM —", "idle"
        status = self._fan_statuses.get(channel)
        if not self.is_channel_available(channel):
            detail = "Канал недоступний на цій платі"
        elif not self.is_connected or status is None:
            detail = "Немає актуальної телеметрії"
        elif self._fan_telemetry_stale(channel):
            detail, state = "Статус вентилятора застарів", "warning"
        else:
            if status.rpm_feedback:
                rpm = f"{status.rpm:,} RPM".replace(",", " ")
            pwm = f"PWM {status.pwm}%"
            if status.fault:
                detail, state = "Аварія вентилятора · перевір TACH", "critical"
            elif not status.fresh:
                detail, state = "Немає температури · захисне охолодження", "warning"
            else:
                mode = "Авто" if status.mode.lower() == "auto" else "Вручну"
                detail = f"{mode} · {status.deci_c / 10:.1f} °C"
        button.setText(f"{title}\n{rpm}\n{pwm}")
        name = self.channel_names.title("FAN", channel)
        button.setAccessibleName(f"Вибрати {name}")
        button.setToolTip(plain_tooltip(f"{name} · {rpm} · {pwm}\n{detail}"))
        button.setAccessibleDescription(f"{rpm}, {pwm}. {detail}")
        if button.property("telemetry") != state:
            button.setProperty("telemetry", state)
            button.style().unpolish(button)
            button.style().polish(button)

    def _open_temperature_source(self) -> None:
        if self.temperature_source_button.isEnabled():
            self.temperature_source_dialog.open_for_channel(self.controller.current_fan)

    def _update_temperature_source(self) -> None:
        channel = self.controller.current_fan
        enabled = (self.is_connected and not self._demo and self.hardware_sensor.available
                   and self.is_channel_available(channel))
        self.temperature_source_button.setEnabled(enabled)
        self.temperature_source_button.setToolTip(
            "Джерело основної кривої ESP32: Windows, DS18B20 (основний або резервний)."
            if enabled else "Потрібні доступний FAN і підтримка DS18B20 на підключеному ESP32."
        )
        dialog = self.temperature_source_dialog
        if dialog.channel is not None and (not enabled or dialog.channel != channel):
            dialog.reject()

    def _refresh_fan_name(self, channel: int) -> None:
        name = self.channel_names.title("FAN", channel)
        self.fan_live_title.set_title(name)
        history_title = f"Історія вибраного вентилятора · {name}"
        # Group box titles treat a single ampersand as a mnemonic.
        self.fan_history_panel.setTitle(history_title.replace("&", "&&"))

    def _refresh_curve_operating_point(self) -> None:
        controller = self.controller
        channel, secondary = controller._active_curve_key()
        status = self._fan_statuses.get(channel)
        live, model = controller.curve_live_point, controller.curve_model_point
        live.hide()
        model.hide()
        note = ""
        if not self.is_connected or self._demo or not self.is_channel_available(channel) or status is None:
            text = "Робоча точка: немає даних ESP32"
        elif self._fan_telemetry_stale(channel):
            text = "Робоча точка: статус ESP32 застарів"
        elif secondary:
            text = "Робоча точка: STATUS не містить температури кривої 2"
        elif not status.fresh:
            text = "Робоча точка: температура ESP32 застаріла"
        elif not (0 <= status.deci_c <= 1250 and 0 <= status.pwm <= 100):
            text = "Робоча точка: некоректний статус ESP32"
        else:
            celsius = status.deci_c / 10
            live.setData([celsius], [status.pwm])
            live.show()
            text = f"◆ ESP32: {celsius:.1f} °C · PWM {status.pwm}%"
            note = "PWM зі STATUS — значення контролера, не фізичний вимір."
            if (status.mode == "auto" and not status.fault
                    and not controller.fan_dual_enabled[channel]
                    and not controller.fan_pid_enabled[channel]):
                points = controller._active_curve()
                pwm = points[-1][1]
                if celsius <= points[0][0]:
                    pwm = points[0][1]
                else:
                    for (t0, p0), (t1, p1) in zip(points, points[1:]):
                        if celsius <= t1:
                            span = (t1 - t0) * 10
                            pwm = p0 + ((status.deci_c - t0 * 10) * (p1 - p0) + span // 2) // span
                            break
                model.setData([celsius], [pwm])
                model.show()
                kind = "чернетка" if (channel, secondary) in controller._curve_dirty else "крива в редакторі"
                text += f"  ▪ Модель: {pwm}% ({kind})"
                note += " Модель використовує показану криву та температуру STATUS, без фільтрів і захистів ESP32."
            else:
                text += "  · Модель не застосовується"
        self.fan_curve_operating.setText(text)
        self.fan_curve_operating.setToolTip(note)

    def observe_cooling_source(self, health: FanHealth) -> None:
        if not self.is_connected or self._demo or not self.is_channel_available(health.channel):
            return
        self._cooling_sources[health.channel] = (health, time.monotonic())
        if health.channel == self.controller.current_fan:
            self.refresh_cooling_source()

    def refresh_cooling_source(self) -> None:
        channel, secondary = self.controller._active_curve_key()
        text = "Джерело ESP32: невідоме"
        note = "Джерело основної кривої з останньої відповіді HEALTH, не налаштування Windows."
        report = self._cooling_sources.get(channel)
        if secondary:
            note = "HEALTH не повідомляє джерело кривої 2."
        elif self.is_connected and not self._demo and self.is_channel_available(channel) and report:
            health, received = report
            elapsed = time.monotonic() - received
            source = {"usb": "USB", "ds18b20": "DS18B20", "mqtt": "MQTT"}.get(health.source)
            if elapsed > FAN_TELEMETRY_TTL or (health.age_ms is not None and (
                    not health.fresh or elapsed + health.age_ms / 1000 > ESP_TEMPERATURE_TTL)):
                text = "Джерело ESP32: дані застаріли"
            elif source and health.age_ms is not None:
                text = f"Джерело ESP32: {source}"
            elif health.source == "none":
                text = "Джерело ESP32: немає даних датчика"
        self.fan_curve_esp_source.setText(text)
        self.fan_curve_esp_source.setToolTip(note)

    def _refresh_fan_detail(self) -> None:
        self._update_preset_availability()
        self._update_temperature_source()
        self._refresh_curve_operating_point()
        self.refresh_cooling_source()
        channel = self.controller.fan_box.currentData()
        if channel is None:
            return
        self.fan_selected_controls.setEnabled(self.is_channel_available(channel))
        self._refresh_fan_name(channel)
        if not self.is_channel_available(channel):
            self.fan_live_rpm.setText("— RPM")
            self.fan_live_metrics.setText("Фізичний канал вимкнено")
            self.fan_live_state.setText("Недоступний на цій платі")
            self.fan_live_state.setProperty("role", "minor")
            self.fan_live_state.style().unpolish(self.fan_live_state)
            self.fan_live_state.style().polish(self.fan_live_state)
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
            "Кольори, автоматичні ефекти та синхронізація з OpenRGB.",
        )
        layout.addWidget(_label("КОЛЬОРИ · ВИБІР ЗОНИ", "sectionLabel"))

        # The hidden QComboBox keeps the shared quick-command and scene target.
        # Automatic effect panels retain their own zone controls.
        zone_map = QFrame()
        zone_map.setObjectName("quietCard")
        map_layout = QHBoxLayout(zone_map)
        map_layout.setContentsMargins(12, 11, 12, 11)
        map_layout.setSpacing(7)
        self.argb_zone_tiles: dict[int, tuple[QFrame, QFrame]] = {}
        self.argb_channel_buttons: dict[int, QPushButton] = {}
        self.argb_channel_group = QButtonGroup(self)
        self.argb_channel_group.setExclusive(True)
        for ch in range(1, 9):
            tile = QFrame()
            tile.setObjectName("zoneTile")
            tile.setProperty("selected", False)
            cell = QVBoxLayout(tile)
            cell.setContentsMargins(4, 4, 4, 4)
            cell.setSpacing(5)
            pick = QPushButton(f"{ch:02d}")
            pick.setProperty("role", "channelSelect")
            pick.setCheckable(True)
            pick.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.argb_channel_group.addButton(pick, ch)
            pick.clicked.connect(
                lambda _checked=False, channel=ch:
                    self.zone_box.setCurrentIndex(channel - 1)
            )
            cell.addWidget(pick)
            strip = QFrame()
            strip.setObjectName("zonePixels")
            strip.setProperty("selected", False)
            strip.setFixedHeight(5)
            cell.addWidget(strip)
            self.argb_channel_buttons[ch] = pick
            self.argb_zone_tiles[ch] = (tile, strip)
            map_layout.addWidget(tile, 1)
        layout.addWidget(zone_map)
        self.argb_owner = _label("", "minor", True)
        layout.addWidget(self.argb_owner)

        select = QFrame()
        select.setObjectName("quietCard")
        control = QVBoxLayout(select)
        control.setContentsMargins(17, 15, 17, 15)
        control.setSpacing(9)
        control.addWidget(_label("СЦЕНА", "sectionLabel"))
        self.zone_box = QComboBox(select)
        for ch in range(1, 9):
            self.zone_box.addItem(f"ARGB {ch}", ch)
        self.zone_box.currentIndexChanged.connect(self._zone_changed)
        self.zone_box.hide()  # internal state model, replaced by eight buttons
        control.addWidget(_label("Ефект", "labelTitle"))
        self.scene_box = QComboBox()
        for scene in scenes:
            if scene != "OpenRGB":
                self.scene_box.addItem(scene, f"preset:{scene}")
        self.scene_box.setMinimumWidth(170)
        editor = QHBoxLayout()
        editor.addWidget(self.scene_box, 1)
        self.argb_draft_rotor = FanRotor(draft=True)
        self.argb_draft_caption = _label("", "minor")
        editor.addWidget(self.argb_draft_rotor)
        editor.addWidget(self.argb_draft_caption)
        control.addLayout(editor)
        self.scope_one = QRadioButton("Лише вибрана зона")
        self.scope_all = QRadioButton("Усі доступні зони")
        self.scope_one.setChecked(True)
        control.addWidget(self.scope_one)
        control.addWidget(self.scope_all)
        self.argb_scene_target = _label("", "minor", True)
        self.argb_scene_target.setTextFormat(Qt.TextFormat.PlainText)
        control.addWidget(self.argb_scene_target)
        self.argb_apply_button = QPushButton("Застосувати ефект")
        self.argb_apply_button.setProperty("role", "primary")
        self.argb_apply_button.clicked.connect(self._apply_scene)
        control.addWidget(self.argb_apply_button)

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
        self.argb_quick_target = ChannelTitle("sectionLabel")
        quick_layout.addWidget(self.argb_quick_target)
        quick_actions = QHBoxLayout()
        quick_actions.setSpacing(9)
        _move_controls(manual_row, quick_actions)
        quick_layout.addLayout(quick_actions)
        self.argb_quick_buttons = quick.findChildren(QPushButton)
        layout.addWidget(quick)
        layout.addWidget(select)
        self.native_effects = NativeEffectsPanel(self.controller)
        self.temperature_argb = TemperatureArgbPanel(self.controller)
        self.reactive_argb = ReactiveArgbPanel(self.controller)
        self.audio_reactive = AudioReactivePanel(self.controller)
        self.argb_effect_panels: dict[str, QWidget] = {}
        self.argb_effect_target_hint = _label("", "minor", True)
        self.argb_effect_target_hint.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.argb_effect_target_hint)
        self.scene_box.insertSeparator(self.scene_box.count())
        for key, title, panel in (
            ("native", "Автономні ефекти ESP32", self.native_effects),
            ("temperature", "За температурою", self.temperature_argb),
            ("sensors", "За показниками датчиків", self.reactive_argb),
            ("audio", "За звуком", self.audio_reactive),
        ):
            self.scene_box.addItem(title, key)
            self.argb_effect_panels[key] = panel
            layout.addWidget(panel)
        self.scene_box.currentIndexChanged.connect(self._argb_effect_changed)

        layout.addWidget(_label(
            "Прев’ю ARGB на лопатях (Головна) моделює надіслані кольори, "
            "а не фактичну підсвітку. Без даних про колір лопаті показують лише RPM. "
            "Сірі канали недоступні на цій платі.",
            "minor", True,
        ))
        self.studio = ArgbStudioPanel(self.controller)
        self.argb_studio_toggle = self._expandable_panel(
            layout, "Створити власний ефект", self.studio
        )

        layout.addWidget(_label("СИНХРОНІЗАЦІЯ", "sectionLabel"))
        openrgb = QWidget()
        openrgb_layout = QVBoxLayout(openrgb)
        openrgb_layout.setContentsMargins(0, 0, 0, 0)
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
        self._expandable_panel(layout, "OpenRGB", openrgb)
        layout.addStretch(1)
        self.scope_all.toggled.connect(self._refresh_argb_targets)
        self._refresh_argb_names()
        self._refresh_argb_zone_tiles()
        self._add_page("argb", page)

    def _refresh_argb_zone_tiles(self) -> None:
        selected = self.zone_box.currentData()
        for ch, (tile, strip) in self.argb_zone_tiles.items():
            active = selected == ch
            self.argb_channel_buttons[ch].setChecked(active)
            active = active and self.is_channel_available(ch)
            for widget in (tile, strip):
                if widget.property("selected") != active:
                    widget.setProperty("selected", active)
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)

        available = self.is_channel_available(selected)
        for panel in (self.native_effects, self.reactive_argb, self.audio_reactive):
            panel.set_channel(selected, available)
        self.temperature_argb.set_channel(selected, self.available_channel_mask)
        key = self.controller.settings.value(f"argb/editor/{selected}", "")
        index = self.scene_box.findData(key)
        blocked = self.scene_box.blockSignals(True)
        self.scene_box.setCurrentIndex(max(0, index))
        self.scene_box.blockSignals(blocked)
        self._show_argb_effect_panel()
        self._refresh_argb_targets()
        self._refresh_argb_owner()

    def argb_targets(self, all_zones: bool) -> list[int]:
        selected = self.zone_box.currentData()
        return [ch for ch in range(1, 9)
                if (all_zones or ch == selected) and self.is_channel_available(ch)]

    def _refresh_argb_names(self) -> None:
        for channel, button in self.argb_channel_buttons.items():
            name = self.channel_names.title("ARGB", channel)
            button.setAccessibleName(f"Вибрати {name}")
            button.setToolTip(plain_tooltip(f"{name} · вибір каналу без відправлення команд"))

    def _refresh_argb_targets(self) -> None:
        targets = self.argb_targets(self.scope_all.isChecked())
        selected = self.zone_box.currentData()
        name = self.channel_names.title("ARGB", selected)
        target = ("ARGB " + ", ".join(f"{ch:02d}" for ch in targets)
                  if self.scope_all.isChecked() else name)
        self.argb_scene_target.setText(f"Ціль сцени: {target}" if targets else "Ціль сцени недоступна")
        available = self.is_channel_available(selected)
        self.argb_effect_target_hint.setText(
            f"Налаштування вибраного каналу · {name}" if available
            else f"{name} · канал недоступний на цій платі"
        )
        self.argb_quick_target.set_title(
            f"ШВИДКІ КОМАНДИ · ЛИШЕ {name}" if available
            else f"ШВИДКІ КОМАНДИ · {name} НЕДОСТУПНА"
        )
        online = self.is_connected and not self._demo
        self.argb_apply_button.setEnabled(online and bool(targets))
        for button in self.argb_quick_buttons:
            button.setEnabled(online and available)

    def clear_argb_preview(self, channel: int | None = None) -> None:
        channels = (channel,) if channel is not None else tuple(self._argb_colors)
        for ch in channels:
            if self._argb_colors.pop(ch, None) is not None:
                self.fan_cards[ch]["rotor"].set_strip_preview(None)

    def note_argb_readback(self, channel: int, source: str, active: bool) -> None:
        if not self.is_connected or self._demo or not self.is_channel_available(channel):
            return
        if active:
            self._argb_readback[channel] = (source, time.monotonic())
            self._argb_request.pop(channel, None)
            self.clear_argb_preview(channel)
        elif self._argb_readback.get(channel, (None, 0))[0] == source:
            self._argb_readback.pop(channel)
        if channel == self.zone_box.currentData():
            self._refresh_argb_owner()

    def note_argb_request(self, channel: int, text: str, ttl: float = ARGB_EVIDENCE_TTL) -> None:
        if not self.is_connected or self._demo or not self.is_channel_available(channel):
            return
        self._argb_readback.pop(channel, None)
        self._argb_request[channel] = (text, time.monotonic(), ttl)
        if channel == self.zone_box.currentData():
            self._refresh_argb_owner()

    def note_argb_frame(self, channel: int, source: str) -> None:
        self.note_argb_request(channel, f"{source} · кадр у черзі", ARGB_FRAME_TTL)

    def _refresh_argb_draft(self, now: float) -> None:
        channel = self.zone_box.currentData()
        key = self.scene_box.currentData() or ""
        colors, brightness, animated = (), 255, False
        caption = "Чернетка · локально"
        if not self.is_channel_available(channel):
            caption = "Чернетка · зона недоступна"
        elif key.startswith("preset:"):
            preset = RGB_SCENES.get(key.removeprefix("preset:"), {})
            brightness = preset.get("brightness", 255)
            if preset.get("mode") == "solid":
                colors = (tuple(preset["rgb"]),)
            elif preset.get("mode") == "rainbow":
                colors, animated = ARGB_RAINBOW, True
            elif preset.get("mode") == "off":
                colors = ((0, 0, 0),)
        elif key == "native":
            panel = self.native_effects
            # Five visual blade samples, not LED count or ESP32 pixel output.
            primary, secondary = panel.colors
            frame = render_effect(panel.mode.currentText(), 5, now, primary, secondary,
                                  panel.brightness.value(), panel.speed.value() / 5)
            colors = tuple(tuple(frame[i:i + 3]) for i in range(0, len(frame), 3))
            if panel.direction.isChecked():
                colors = colors[::-1]
        elif key == "temperature":
            color = self.temperature_argb.draft_color
            if color is not None:
                colors = (color,)
        elif key in ("sensors", "audio"):
            panel = self.argb_effect_panels[key]
            colors, brightness = panel.colors, panel.brightness.value()
            caption = "Чернетка · зразок палітри"
        if self.argb_draft_caption.text() != caption:
            self.argb_draft_caption.setText(caption)
        shown = [tuple(round(value * brightness / 255) for value in rgb) for rgb in colors]
        self.argb_draft_rotor.set_strip_preview(shown, animated=animated)

    def _refresh_argb_owner(self) -> None:
        channel = self.zone_box.currentData()
        owner = "невідомий"
        detail = ""
        now = time.monotonic()
        if not self.is_channel_available(channel):
            detail = "канал недоступний"
        elif not self.is_connected or self._demo:
            detail = "немає зв’язку з ESP32"
        else:
            readback = self._argb_readback.get(channel)
            request = self._argb_request.get(channel)
            if readback and now - readback[1] <= ARGB_EVIDENCE_TTL:
                owner = f"{readback[0]} · відповідь ESP32"
            elif request and now - request[1] <= request[2]:
                detail = request[0]
            elif readback or request:
                detail = "дані застаріли"
        text = f"Керування ARGB {channel:02d}: {owner}" + (f" · {detail}" if detail else "")
        if self.argb_owner.text() != text:
            self.argb_owner.setText(text)
        enabled = [label for active, label in (
            (self.native_checkbox.isChecked(), "OpenRGB SDK"),
            (self.controller.bridge_checkbox.isChecked(), "Міст E1.31"),
            (self.controller.audio_capture.running, "Захоплення звуку"),
        ) if active]
        tooltip = (
            "Відповідь ESP32 показує режим на момент зчитування, а не фактичне світло. "
            "Команди, кадри в черзі та ввімкнені служби не підтверджують керування зоною."
            + ("\nСлужби ПК: " + ", ".join(enabled) if enabled else "")
        )
        if tooltip != self.argb_owner.toolTip():
            self.argb_owner.setToolTip(tooltip)

    def note_argb_command(self, message: str) -> None:
        """Preview supported local requests, never infer lighting from fan telemetry."""
        tokens = message.upper().split()
        if not tokens:
            return
        mode = tokens[0]
        if mode in ("FX", "RFX", "AUDIOCFG"):
            if len(tokens) >= 3 and tokens[1] in ("SET", "STOP"):
                try:
                    channel = int(tokens[2])
                except ValueError:
                    return
                self.clear_argb_preview(channel)
                self.note_argb_request(channel, f"{mode} {tokens[1]} · команду надіслано")
            return
        if len(tokens) != {"LED": 5, "BRIGHT": 3, "RAINBOW": 2, "OFF": 2}.get(mode):
            return
        try:
            channel, *values = map(int, tokens[1:])
        except ValueError:
            return
        if not self.is_channel_available(channel) or not all(0 <= value <= 255 for value in values):
            return
        if mode == "BRIGHT":
            self._argb_brightness[channel] = values[0]
        elif self.controller.bridge_checkbox.isChecked() or self.native_checkbox.isChecked():
            return
        elif mode == "LED":
            self._argb_colors[channel] = ((values[0], values[1], values[2]),)
        elif mode == "RAINBOW":
            self._argb_colors[channel] = ARGB_RAINBOW
        elif mode == "OFF":
            self._argb_colors[channel] = ((0, 0, 0),)
        if mode != "BRIGHT":
            self.note_argb_request(channel, f"{mode} · команду надіслано")
        colors = self._argb_colors.get(channel)
        if colors:
            brightness = self._argb_brightness.get(channel, 255)
            shown = [tuple(round(value * brightness / 255) for value in rgb) for rgb in colors]
            self.fan_cards[channel]["rotor"].set_strip_preview(shown, animated=len(colors) > 1)

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

    def _create_sensors(self, sensors_box: QGroupBox) -> None:
        page, layout = self._content(
            "Температури",
            "Температури NWinfo, фізичні DS18B20 та джерела для кривих вентиляторів.",
        )
        sensors_box.setTitle("Датчики ПК · NWinfo")
        sensors_box.setMinimumHeight(360)
        tools = QHBoxLayout()
        tools.addWidget(_label("CPU · GPU · SSD · RAM", "minor"), 1)
        scan = QPushButton("Оновити")
        scan.clicked.connect(self.controller.refresh_temperatures)
        tools.addWidget(scan)
        tools.addWidget(self.controller.sensor_status)
        sensors_box.layout().insertLayout(0, tools)
        layout.addWidget(sensors_box)

        layout.addWidget(self.hardware_sensor)

        self.sensor_manager = SensorManagerPanel(self.controller)
        layout.addWidget(self.sensor_manager)
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
        layout.addWidget(self.device_settings)
        layout.addStretch(1)
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
        self.diagnostics.health_observed.connect(self.observe_cooling_source)
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

    def _argb_effect_changed(self) -> None:
        key = self.scene_box.currentData()
        if key is not None:
            self.controller.settings.setValue(f"argb/editor/{self.zone_box.currentData()}", key)
        self._show_argb_effect_panel()

    def _show_argb_effect_panel(self) -> None:
        family = self.scene_box.currentData()
        self.argb_effect_target_hint.setVisible(family in self.argb_effect_panels)
        for key, panel in self.argb_effect_panels.items():
            panel.setVisible(family == key)
        for control in (self.scope_one, self.scope_all,
                        self.argb_scene_target, self.argb_apply_button):
            control.setVisible(bool(family and family.startswith("preset:")))
        self._refresh_argb_draft(time.monotonic())

    def _apply_scene(self) -> None:
        key = self.scene_box.currentData()
        if not key or not key.startswith("preset:"):
            return
        self.controller.apply_argb_scene(
            key.removeprefix("preset:"), self.scope_all.isChecked()
        )

    def note_esp_response(self, dc_ready: bool | None = None) -> None:
        if not self.is_connected or self._demo:
            return
        if dc_ready is not None:
            self._dc_ready = dc_ready
            if not dc_ready:
                self.summary_esp.setText("DC PWM заблоковано")
            else:
                self.summary_esp.setText(f"USB · {self._connection_port}")
        if not self._esp_replied or dc_ready is not None:
            if not self._esp_replied:
                self.controller.statusBar().showMessage(
                    f"USB · {self._connection_port} · відповідь ESP32 отримано"
                )
            self._esp_replied = True
            self._refresh_connection_text()
            self._update_cooling_health()

    def _refresh_connection_text(self) -> None:
        port = self._connection_port
        if self._demo:
            text, role = "DEMO · тестові дані", "caution"
        elif not self.is_connected:
            text, role = "ESP32 · не підключено", "caution"
        elif self._esp_replied:
            text, role = f"{port} · ESP32 відповіла", "positive"
        else:
            text, role = f"{port} · відкрито, очікуємо ESP32", "caution"
        self.connection_text.setText(text)
        self.connection_text.setProperty("role", role)
        self.connection_text.style().unpolish(self.connection_text)
        self.connection_text.style().polish(self.connection_text)
        self.sidebar_connection_hint.setText(text)

    def set_connected(self, connected: bool, port_name: str = "", *, demo: bool = False) -> None:
        self.is_connected = bool(connected)
        self._connection_port = port_name
        self._demo = connected and demo
        self._esp_replied = False
        self._dc_ready = None
        self.clear_argb_preview()
        self._argb_brightness.clear()
        self._argb_readback.clear()
        self._argb_request.clear()
        self.temperature_argb.set_connected(connected)
        if connected:
            self.summary_esp.setText("Не підключено до обладнання" if demo else f"USB · {port_name}")
        else:
            self._fan_statuses.clear()
            self._cooling_sources.clear()
            self._last_fan_update.clear()
            self._expired_fan_channels.clear()
            self.summary_esp.setText("USB · —")
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
                self.fan_channel_buttons[row + 1].setEnabled(True)
                self.argb_channel_buttons[row + 1].setEnabled(True)
                tile = self.argb_zone_tiles[row + 1][0]
                tile.setProperty("disabled", False)
                for button in tile.findChildren(QPushButton):
                    button.setEnabled(True)
            for labels in self.fan_cards.values():
                labels["settings_button"].setEnabled(True)
                labels["rpm"].setText("— RPM")
                labels["metrics"].setText("— %  ·  — °C")
                frame = self._fan_frames[next(ch for ch, card in self.fan_cards.items() if card is labels)]
                frame.setProperty("state", "idle")
                frame.style().unpolish(frame)
                frame.style().polish(frame)
                labels["bar"].setValue(0)
                labels["rotor"].set_rpm(0)
                labels["bar"].setProperty("state", "idle")
                labels["bar"].setToolTip("PWM: немає даних")
                labels["bar"].style().unpolish(labels["bar"])
                labels["bar"].style().polish(labels["bar"])
                labels["state"].setText("Немає даних")
                labels["state"].setProperty("role", "minor")
                labels["state"].style().unpolish(labels["state"])
                labels["state"].style().polish(labels["state"])
        self._refresh_connection_text()
        self._update_preset_availability()
        self._refresh_argb_targets()
        self._refresh_argb_owner()
        self._refresh_argb_draft(time.monotonic())
        self._update_cooling_health()
        self._refresh_attention_count()
        self._reflow_fan_cards()
        for channel in self.fan_channel_buttons:
            self._refresh_fan_channel_telemetry(channel)
        self._refresh_fan_detail()
        if hasattr(self.controller, "dashboard"):
            self.controller.refresh_curve_feedback()
        self._update_pc_buttons()
        self.device_settings.set_connected(connected)

    def _update_preset_availability(self) -> None:
        enabled = (self.is_connected and not self._demo and self._channel_mask_known
                   and self.is_channel_available(self.controller.current_fan))
        for button in self.fan_preset_buttons.values():
            button.setEnabled(enabled)

    def _advance_fan_rotors(self) -> None:
        now = time.monotonic()
        delta = min(.1, max(0.0, now - self._rotor_last))
        self._rotor_last = now
        if not self.isVisible() or self.window().isMinimized():
            return
        if self.stack.currentIndex() == self.page_index["argb"]:
            self._refresh_argb_draft(now)
            return
        if not self.is_connected:
            return
        if self.stack.currentIndex() != self.page_index["overview"]:
            return
        for channel, data in self.fan_cards.items():
            rotor = data["rotor"]
            if self.is_channel_available(channel) and not self._fan_telemetry_stale(channel):
                rotor.advance(delta)
            elif rotor.rpm:
                rotor.set_rpm(0)

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
            self.fan_cards[channel]["settings_button"].setEnabled(enabled)
            self.fan_channel_buttons[channel].setEnabled(enabled)
            self._refresh_fan_channel_telemetry(channel)
            self.argb_channel_buttons[channel].setEnabled(enabled)
            if not enabled:
                self._cooling_sources.pop(channel, None)
                self.clear_argb_preview(channel)
                self._argb_brightness.pop(channel, None)
                self._argb_readback.pop(channel, None)
                self._argb_request.pop(channel, None)
                labels = self.fan_cards[channel]
                labels["rpm"].setText("— RPM")
                labels["metrics"].setText("Фізичний вихід вимкнено")
                labels["state"].setText("Недоступний")
                labels["state"].setProperty("role", "minor")
                labels["bar"].setValue(0)
                labels["rotor"].set_rpm(0)
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
        self._refresh_argb_zone_tiles()
        self._update_cooling_health()
        self._refresh_attention_count()
        self._reflow_fan_cards()
        self._refresh_fan_detail()
        self.controller.refresh_curve_feedback()

    def set_sensor_count(self, count: int, available: bool = True, metric_count: int = 0) -> None:
        self.summary_temp.setText(
            f"{count} температур · {metric_count} інших" if count else
            f"0 температур · {metric_count} інших" if available else "Датчики недоступні"
        )

    def set_bridge_state(self, enabled: bool, frames: int = 0) -> None:
        if enabled:
            self.clear_argb_preview()
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

    def update_fan(self, channel: int, status: FanStatus) -> None:
        labels = self.fan_cards.get(channel)
        if labels is None:
            return
        if not self.is_channel_available(channel):
            return
        self.note_esp_response()
        self._fan_statuses[channel] = status
        if not status.fresh:
            self._cooling_sources.pop(channel, None)
        self._last_fan_update[channel] = time.monotonic()
        self._expired_fan_channels.discard(channel)
        self._refresh_fan_channel_telemetry(channel)
        self._fan_frames[channel].setToolTip(
            f"FAN {channel:02d} · {status.pwm}% PWM · "
            + (f"{status.rpm} RPM" if status.rpm_feedback else "TACH недоступний")
        )
        labels["rpm"].setText(
            f"{status.rpm:,} RPM".replace(",", " ") if status.rpm_feedback else "— RPM"
        )
        labels["rotor"].set_rpm(
            status.rpm if status.rpm_feedback and not status.fault else 0
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
            if channel == self.controller.current_fan:
                self.controller.refresh_curve_feedback()

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

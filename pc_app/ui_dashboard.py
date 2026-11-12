"""Modern, task-based PySide6 shell for the existing 8Fan/8ARGB controller.

The original controls are *moved*, not recreated. Their signal connections and
the firmware/serial/safety behaviour stay in main.py.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLayout, QPushButton, QRadioButton, QScrollArea, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)


PAGES = (
    ("overview", "◉  Огляд", "Огляд системи", "Стан охолодження та підсвітки з одного погляду"),
    ("fans", "≋  Вентилятори", "Вентилятори", "Температурні криві, швидкість і джерела даних"),
    ("argb", "✦  ARGB", "Підсвітка", "Сцени для восьми незалежних зон та OpenRGB"),
    ("pc", "⏻  Живлення ПК", "Живлення ПК", "Керування кнопкою PWR_SW з перевіркою стану"),
    ("service", "⚙  Сервіс", "Додаткові налаштування", "Калібрування, конфігурація та діагностика"),
    ("logs", "☷  Логи", "Журнал подій", "Повідомлення контролера та ручні команди"),
)

STYLE = """
QMainWindow, QWidget#dashboardRoot, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #10141d; color: #e8edf7; font-family: "Segoe UI";
}
QWidget { color: #e8edf7; font-size: 10pt; }
QFrame#sidebar { background: #151b27; border-right: 1px solid #2b3545; }
QFrame#topbar { background: #141b27; border-bottom: 1px solid #2b3545; }
QFrame#summaryCard, QFrame#fanCard, QFrame#quietCard {
    background: #1b2432; border: 1px solid #2b3749; border-radius: 12px;
}
QFrame#fanCard:hover { border: 1px solid #4b7695; }
QLabel[role="brand"] { font-size: 19pt; font-weight: 750; color: #f1f6ff; }
QLabel[role="pageTitle"] { font-size: 22pt; font-weight: 700; color: #f1f6ff; }
QLabel[role="bigNumber"] { font-size: 21pt; font-weight: 750; color: #f5f8ff; }
QLabel[role="minor"] { font-size: 9pt; color: #9babbd; }
QLabel[role="labelTitle"] { font-size: 10pt; font-weight: 650; color: #eaf1fd; }
QLabel[role="positive"] { color: #70cda6; font-weight: 600; }
QLabel[role="caution"] { color: #edba6d; font-weight: 600; }
QLabel[role="negative"] { color: #f18b92; font-weight: 600; }
QGroupBox {
    background: #1b2432; border: 1px solid #2b3749; border-radius: 12px;
    margin-top: 19px; padding-top: 12px; font-weight: 650;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; top: 1px; padding: 0 4px; color: #e8eff8; }
QPushButton {
    background: #29364a; color: #eef4fd; border: 1px solid #394d65;
    border-radius: 8px; padding: 8px 13px; min-height: 23px;
}
QPushButton:hover { background: #34465e; border-color: #55718f; }
QPushButton:pressed { background: #263b55; }
QPushButton:disabled { background: #222935; color: #718093; border-color: #303b48; }
QPushButton[role="primary"] { background: #236d99; border-color: #368dbb; color: white; font-weight: 650; }
QPushButton[role="primary"]:hover { background: #2d83b5; }
QPushButton[role="danger"] { background: #522b38; border-color: #8d4654; color: #ffd3d7; }
QPushButton[role="danger"]:hover { background: #713544; }
QPushButton[role="nav"] {
    background: transparent; border: none; border-radius: 9px;
    padding: 11px 15px; text-align: left; font-weight: 550; color: #aebdd1;
}
QPushButton[role="nav"]:hover { background: #222e40; color: white; }
QPushButton[role="nav"]:checked {
    background: #203a55; color: #a9defb; font-weight: 700;
    border-left: 3px solid #4ca7dc;
}
QComboBox, QLineEdit {
    background: #141d2a; color: #eef4fc; border: 1px solid #394a61;
    border-radius: 7px; padding: 7px 9px; min-height: 23px;
    selection-background-color: #256b94;
}
QComboBox:hover, QLineEdit:focus { border-color: #58a5d3; }
QComboBox QAbstractItemView { background: #1d2939; color: #eef4fc; selection-background-color: #315a80; }
QTableWidget, QTextEdit, QListWidget {
    background: #141d2a; alternate-background-color: #1c2737;
    color: #e9eff7; gridline-color: #2a394d; border: 1px solid #304054;
    border-radius: 8px; selection-background-color: #284c6e;
}
QHeaderView::section {
    background: #253246; color: #cbd9e9; padding: 7px;
    border: 0px; border-right: 1px solid #36465b;
}
QCheckBox, QRadioButton { spacing: 8px; }
QStatusBar { background: #151d29; color: #9eafc2; border-top: 1px solid #263447; }
QScrollBar:vertical { background: #182131; width: 10px; border: 0; }
QScrollBar::handle:vertical { background: #465a73; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QSplitter::handle { background: #202d40; width: 6px; }
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
        self._create_argb(rgb_box, scenes)
        self._create_pc(pc_box)
        self._create_service(
            calibration_box, sensors_box, hardware_rgb, config_files,
            preset_row, diagnostic_row,
        )
        self._create_logs(log_box)
        self.show_page("overview")
        self.set_connected(False)
        self.controller.setStyleSheet(STYLE)

    def _sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(208)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 26, 15, 18)
        layout.setSpacing(6)
        layout.addWidget(_label("FanARGB", "brand"))
        layout.addWidget(_label("ESP32-S3  /  CONTROL", "minor"))
        layout.addSpacing(26)
        for key, caption, _title, _subtitle in PAGES:
            button = QPushButton(caption)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, selected=key: self.show_page(selected))
            layout.addWidget(button)
            self.nav[key] = button
        layout.addStretch(1)
        layout.addWidget(_label("8 вентиляторів · 8 ARGB", "minor"))
        layout.addWidget(_label("Локальне керування", "minor"))
        return panel

    def _topbar(self, refresh_ports: QPushButton) -> QWidget:
        panel = QFrame()
        panel.setObjectName("topbar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(10)
        self.connection_text = _label("●  Не підключено", "caution")
        layout.addWidget(self.connection_text)
        layout.addStretch(1)
        layout.addWidget(_label("Порт:", "minor"))
        self.controller.port_box.setMinimumWidth(180)
        layout.addWidget(self.controller.port_box)
        refresh_ports.setText("Оновити")
        refresh_ports.setToolTip("Оновити список COM-портів")
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
        value = _label(initial, "labelTitle")
        lay.addWidget(value)
        lay.addWidget(_label(subtitle, "minor"))
        return card, value

    def _create_overview(self) -> None:
        page, layout = self._content(
            "Огляд системи",
            "Головне без зайвих налаштувань. Натисни на вентилятор, щоб змінити його параметри.",
        )
        summary = QHBoxLayout()
        summary.setSpacing(12)
        for key, title, hint in (
            ("esp", "ESP32-S3", "Підключення контролера"),
            ("temp", "Датчики ПК", "Libre Hardware Monitor"),
            ("rgb", "ARGB / OpenRGB", "Приймання E1.31"),
            ("pc", "Живлення ПК", "PWR_SW · опція"),
        ):
            card, value = self._summary_card(title, "—", hint)
            setattr(self, f"summary_{key}", value)
            summary.addWidget(card, 1)
        layout.addLayout(summary)
        heading = QHBoxLayout()
        heading.addWidget(_label("Вентилятори · 8 каналів", "labelTitle"))
        heading.addStretch(1)
        shortcut = QPushButton("Відкрити налаштування")
        shortcut.clicked.connect(lambda: self.show_page("fans"))
        heading.addWidget(shortcut)
        layout.addLayout(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for ch in range(1, 9):
            frame = QFrame()
            frame.setObjectName("fanCard")
            box = QVBoxLayout(frame)
            box.setContentsMargins(17, 14, 17, 13)
            box.setSpacing(9)
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
            source = _label("Джерело: не вибрано", "minor")
            source.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            source.setToolTip("Джерело температури для автоматичного керування")
            box.addWidget(source)
            action = QPushButton("Налаштувати  →")
            action.clicked.connect(lambda checked=False, channel=ch: self.open_fan(channel))
            box.addWidget(action)
            grid.addWidget(frame, (ch - 1) // 4, (ch - 1) % 4)
            self.fan_cards[ch] = {
                "rpm": rpm, "metrics": metrics, "source": source, "state": state,
            }
        layout.addLayout(grid)
        note = QFrame()
        note.setObjectName("quietCard")
        nlay = QHBoxLayout(note)
        nlay.setContentsMargins(17, 12, 17, 12)
        nlay.addWidget(_label(
            "Автоматичне охолодження: якщо температури перестають надходити, "
            "контролер переходить у захисний режим для відповідного вентилятора.",
            "minor", True,
        ))
        layout.addWidget(note)
        layout.addStretch(1)
        self._add_page("overview", page)

    def _create_fans(self, table_box, choose_row, curve_box, history_box) -> None:
        page, layout = self._content(
            "Вентилятори", "Вибери канал у таблиці та налаштуй автоматичну криву.",
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        table_box.setTitle("Канали та джерела температури")
        table_box.setMinimumWidth(435)
        splitter.addWidget(table_box)
        right_panel = QWidget()
        editor = QVBoxLayout(right_panel)
        editor.setContentsMargins(4, 0, 0, 0)
        editor.setSpacing(12)
        row_holder = QFrame()
        row_holder.setObjectName("quietCard")
        row_layout = QHBoxLayout(row_holder)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(8)
        _move_controls(choose_row, row_layout)
        editor.addWidget(row_holder)
        curve_box.setTitle("Крива PWM · переміщуй п'ять точок")
        curve_box.setMinimumHeight(355)
        editor.addWidget(curve_box, 3)
        history_box.setTitle("Історія вибраного вентилятора")
        editor.addWidget(history_box, 1)
        splitter.addWidget(right_panel)
        splitter.setSizes([460, 695])
        splitter.setMinimumHeight(610)
        layout.addWidget(splitter, 1)
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

    def _create_service(
        self, calibration_box, sensors_box, hardware_rgb, config_files,
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
        layout.addWidget(calibration_box)
        network = self._service_group("Налаштування ARGB, Wi-Fi та живлення стрічок", hardware_rgb)
        layout.addWidget(network)
        combined = self._service_group("Профіль усієї системи · 8 вентиляторів + ARGB", preset_row, config_files)
        layout.addWidget(combined)
        advanced = self._service_group("Діагностика та MQTT / Home Assistant", diagnostic_row)
        layout.addWidget(advanced)

        sensors_box.setTitle("Libre Hardware Monitor · доступні датчики")
        sensors_box.setMinimumHeight(235)
        layout.addWidget(sensors_box)
        endpoint = QGroupBox("Сервер датчиків")
        ep = QHBoxLayout(endpoint)
        ep.setContentsMargins(16, 20, 16, 12)
        ep.addWidget(_label("LHM URL:", "minor"))
        ep.addWidget(self.controller.lhm_url, 1)
        ep.addWidget(self.controller.lhm_status)
        layout.addWidget(endpoint)
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
            self.connection_text.setText("●  ESP32 не підключено")
            self.connection_text.setProperty("role", "caution")
            self.summary_esp.setText("Не підключено")
            self.update_pc_state("unknown")
            self.summary_mqtt = None
            for labels in self.fan_cards.values():
                labels["rpm"].setText("— RPM")
                labels["metrics"].setText("— %  ·  — °C")
                labels["state"].setText("Немає даних")
        self._update_pc_buttons()
        self.connection_text.style().unpolish(self.connection_text)
        self.connection_text.style().polish(self.connection_text)

    def set_sensor_count(self, count: int, available: bool = True) -> None:
        self.summary_temp.setText(f"{count} датчиків" if available else "Немає зв'язку")

    def set_bridge_state(self, enabled: bool, frames: int = 0) -> None:
        if enabled:
            self.summary_rgb.setText(f"E1.31 · {frames} кадрів")
        else:
            self.summary_rgb.setText("Міст вимкнений")

    def update_fan(self, channel: int, status) -> None:
        labels = self.fan_cards.get(channel)
        if labels is None:
            return
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

    def set_fan_source(self, channel: int, source_name: str) -> None:
        labels = self.fan_cards.get(channel)
        if labels:
            labels["source"].setText(f"Джерело: {source_name}")
            labels["source"].setToolTip(source_name)

    def update_pc_state(self, status: str) -> None:
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

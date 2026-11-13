"""Single PC-side control center for settings stored in ESP32 NVS.

Device configuration is read back over USB. Secret fields remain blank after
save and are never copied to QSettings or log history. Commands are applied
one at a time with firmware acknowledgements and a fresh readback, not
optimistic "Saved!" alerts on a successful OS write.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget, QTabWidget, QSizePolicy,
)

try:
    from .device_config_protocol import decode_value, fields, wifi_command, mqtt_commands, mqtt_transaction_commands
except ImportError:
    from device_config_protocol import decode_value, fields, wifi_command, mqtt_commands, mqtt_transaction_commands


class DeviceSettingsPanel(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.version = 0
        self.serial_version = 5
        self.connected = False
        self.wifi_config: dict[str, object] = {}
        self.mqtt_config: dict[str, object] = {}
        self._wifi_dirty = False
        self._mqtt_dirty = False
        self._loading = False
        self._wifi_known = False
        self._mqtt_known = False
        self._rgb_known = False
        self._fan_known = False
        self._argb_verified: set[str] = set()
        self._strip_snapshot: dict[int, dict[str, object]] = {}
        self._fan_snapshot: dict[int, dict[str, int]] = {}
        self._budget_current: int | None = None
        self._operations: deque[tuple[str, str]] = deque()
        self._active: tuple[str, str] | None = None
        self._verify: str | None = None
        self._expected: dict[str, object] = {}
        self.ack_timer = QTimer(self)
        self.ack_timer.setSingleShot(True)
        self.ack_timer.timeout.connect(self._timeout)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)
        self.header = QLabel("Підключи ESP32-S3 через USB, щоб прочитати конфігурацію.")
        self.header.setWordWrap(True)
        root.addWidget(self.header)

        refresh_row = QHBoxLayout()
        self.refresh_button = QPushButton("↻  Прочитати все з ESP32")
        self.refresh_button.clicked.connect(self.refresh_all)
        refresh_row.addWidget(self.refresh_button)
        self.result = QLabel("Немає з’єднання")
        self.result.setWordWrap(True)
        refresh_row.addWidget(self.result, 1)
        root.addLayout(refresh_row)

        # One settings category at a time, without the long dense scrolling form.
        self._tab_keys = ("wifi", "mqtt", "argb", "fan")
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("esp32ConfigTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        root.addWidget(self.tabs)

        # Wi-Fi is persisted to ESP32 NVS, not to Windows QSettings.
        wifi_box = QWidget()
        wifi_form = QFormLayout(wifi_box)
        wifi_form.setContentsMargins(17, 20, 17, 16)
        wifi_form.setSpacing(12)
        self.wifi_status = QLabel("Немає даних")
        self.wifi_status.setWordWrap(True)
        wifi_form.addRow("Стан:", self.wifi_status)
        self.wifi_ssid = QLineEdit()
        self.wifi_ssid.setPlaceholderText("Назва мережі, включно з пробілами")
        self.wifi_ssid.setMaxLength(32)
        wifi_form.addRow("SSID:", self.wifi_ssid)
        self.wifi_password = QLineEdit()
        self.wifi_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.wifi_password.setPlaceholderText("Порожній — зберегти пароль лише при незмінному SSID")
        wifi_form.addRow("Пароль:", self.wifi_password)
        self.wifi_reveal = QCheckBox("Показати пароль")
        self.wifi_reveal.toggled.connect(
            lambda visible: self.wifi_password.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )
        wifi_form.addRow("", self.wifi_reveal)
        self.wifi_open = QCheckBox("Мережа без пароля (відкрита)")
        wifi_form.addRow("", self.wifi_open)
        wifi_actions = QHBoxLayout()
        self.wifi_save = QPushButton("Зберегти Wi-Fi у ESP32")
        self.wifi_save.setProperty("role", "primary")
        self.wifi_save.clicked.connect(self.save_wifi)
        wifi_actions.addWidget(self.wifi_save)
        self.wifi_disable = QPushButton("Вимкнути й очистити Wi-Fi")
        self.wifi_disable.setProperty("role", "danger")
        self.wifi_disable.clicked.connect(self.disable_wifi)
        wifi_actions.addWidget(self.wifi_disable)
        wifi_form.addRow("", wifi_actions)
        self.wifi_ssid.textEdited.connect(self._mark_wifi_dirty)
        self.wifi_password.textEdited.connect(self._mark_wifi_dirty)
        self.wifi_open.toggled.connect(self._toggle_open_wifi)
        self.tabs.addTab(wifi_box, "Wi-Fi")

        mqtt_box = QWidget()
        mqtt_form = QFormLayout(mqtt_box)
        mqtt_form.setContentsMargins(17, 20, 17, 16)
        mqtt_form.setSpacing(12)
        self.mqtt_status = QLabel("Немає даних")
        self.mqtt_status.setWordWrap(True)
        mqtt_form.addRow("Стан:", self.mqtt_status)
        self.mqtt_host = QLineEdit()
        self.mqtt_host.setPlaceholderText("Наприклад 192.168.1.15 або homeassistant.local")
        self.mqtt_host.setMaxLength(63)
        mqtt_form.addRow("Broker:", self.mqtt_host)
        self.mqtt_port = QSpinBox()
        self.mqtt_port.setRange(1, 65535)
        self.mqtt_port.setValue(1883)
        mqtt_form.addRow("Порт:", self.mqtt_port)
        self.mqtt_user = QLineEdit()
        self.mqtt_user.setPlaceholderText("Порожній — анонімне підключення")
        self.mqtt_user.setMaxLength(31)
        mqtt_form.addRow("Користувач:", self.mqtt_user)
        self.mqtt_password = QLineEdit()
        self.mqtt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.mqtt_password.setPlaceholderText("Порожній — зберегти пароль, якщо користувач той самий")
        mqtt_form.addRow("Пароль:", self.mqtt_password)
        self.mqtt_reveal = QCheckBox("Показати пароль")
        self.mqtt_reveal.toggled.connect(
            lambda visible: self.mqtt_password.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )
        mqtt_form.addRow("", self.mqtt_reveal)
        self.mqtt_enabled = QCheckBox("Увімкнути MQTT на ESP32")
        self.mqtt_discovery = QCheckBox("Публікувати Home Assistant MQTT Discovery")
        mqtt_form.addRow("", self.mqtt_enabled)
        mqtt_form.addRow("", self.mqtt_discovery)
        self.mqtt_temperature = QCheckBox("Дозволити зовнішні MQTT-температури як резервні")
        mqtt_form.addRow("", self.mqtt_temperature)
        mqtt_actions = QHBoxLayout()
        self.mqtt_save = QPushButton("Записати MQTT / HA у ESP32")
        self.mqtt_save.setProperty("role", "primary")
        self.mqtt_save.clicked.connect(self.save_mqtt)
        mqtt_actions.addWidget(self.mqtt_save)
        self.mqtt_reset = QPushButton("Очистити MQTT у ESP32")
        self.mqtt_reset.setProperty("role", "danger")
        self.mqtt_reset.clicked.connect(self.reset_mqtt)
        mqtt_actions.addWidget(self.mqtt_reset)
        mqtt_form.addRow("", mqtt_actions)
        note = QLabel("MQTT працює напряму з ESP32 після налаштування. "
                      "TCP/1883 без TLS — лише довірена локальна мережа. "
                      "Вимкнення Discovery очищує retained-записи після зв’язку з MQTT.")
        note.setWordWrap(True)
        mqtt_form.addRow("", note)
        self.mqtt_host.textEdited.connect(self._mark_mqtt_dirty)
        self.mqtt_user.textEdited.connect(self._mark_mqtt_dirty)
        self.mqtt_password.textEdited.connect(self._mark_mqtt_dirty)
        self.mqtt_port.valueChanged.connect(self._mark_mqtt_dirty)
        self.mqtt_enabled.toggled.connect(self._mark_mqtt_dirty)
        self.mqtt_discovery.toggled.connect(self._mark_mqtt_dirty)
        self.mqtt_temperature.toggled.connect(self._mark_mqtt_dirty)
        self.tabs.addTab(mqtt_box, "MQTT / HA")

        # Per-zone ARGB hardware settings, fetched from the actual controller.
        rgb_box = QWidget()
        rgb_form = QFormLayout(rgb_box)
        rgb_form.setContentsMargins(17, 20, 17, 16)
        rgb_form.setSpacing(12)
        self.argb_status = QLabel("Немає даних")
        rgb_form.addRow("Ліміт струму:", self.argb_status)
        self.rgb_zone = QComboBox()
        for ch in range(1, 9):
            self.rgb_zone.addItem(f"ARGB {ch}", ch)
        self.rgb_zone.currentIndexChanged.connect(self.request_strip)
        rgb_form.addRow("Канал:", self.rgb_zone)
        self.rgb_count = QSpinBox()
        self.rgb_count.setRange(1, 170)
        self.rgb_count.setValue(30)
        rgb_form.addRow("LED:", self.rgb_count)
        self.rgb_reverse = QCheckBox("Зворотний напрямок стрічки")
        rgb_form.addRow("", self.rgb_reverse)
        self.rgb_brightness = QSpinBox()
        self.rgb_brightness.setRange(0, 255)
        self.rgb_brightness.setValue(255)
        rgb_form.addRow("Яскравість:", self.rgb_brightness)
        self.rgb_budget = QSpinBox()
        self.rgb_budget.setRange(100, 20000)
        self.rgb_budget.setSingleStep(100)
        self.rgb_budget.setValue(2000)
        rgb_form.addRow("Бюджет 5 В, мА:", self.rgb_budget)
        rgb_actions = QHBoxLayout()
        self.rgb_save = QPushButton("Зберегти ARGB")
        self.rgb_save.clicked.connect(self.save_argb)
        rgb_actions.addWidget(self.rgb_save)
        rgb_form.addRow("", rgb_actions)
        rgb_note = QLabel("Кількість LED, напрямок і бюджет зберігаються в NVS. "
                          "Яскравість активна до перезапуску ESP32. "
                          "Бюджет струму — програмна оцінка, не заміна запобіжника.")
        rgb_note.setWordWrap(True)
        rgb_form.addRow("", rgb_note)
        self.tabs.addTab(rgb_box, "ARGB")

        fan_box = QWidget()
        fan_form = QFormLayout(fan_box)
        fan_form.setContentsMargins(17, 20, 17, 16)
        fan_form.setSpacing(12)
        self.fan_zone = QComboBox()
        for ch in range(1, 9):
            self.fan_zone.addItem(f"Fan {ch}", ch)
        self.fan_zone.currentIndexChanged.connect(self.request_fan)
        fan_form.addRow("Канал:", self.fan_zone)
        self.fan_ppr = QSpinBox()
        self.fan_ppr.setRange(1, 12)
        self.fan_ppr.setValue(2)
        fan_form.addRow("Імпульсів TACH / оберт:", self.fan_ppr)
        self.fan_critical = QSpinBox()
        self.fan_critical.setRange(40, 120)
        self.fan_critical.setValue(90)
        fan_form.addRow("Критична температура, °C:", self.fan_critical)
        self.fan_stall = QSpinBox()
        self.fan_stall.setRange(0, 3000)
        self.fan_stall.setValue(0)
        fan_form.addRow("Поріг зупинки, RPM:", self.fan_stall)
        self.fan_info = QLabel("Параметри з ESP ще не прочитано")
        self.fan_info.setWordWrap(True)
        fan_form.addRow("Статус:", self.fan_info)
        fan_actions = QHBoxLayout()
        self.fan_save = QPushButton("Зберегти пороги в ESP32")
        self.fan_save.clicked.connect(self.save_fan)
        fan_actions.addWidget(self.fan_save)
        fans_page = QPushButton("Криві, PID та калібрування…")
        fans_page.clicked.connect(lambda: self.controller.dashboard.show_page("fans"))
        fan_actions.addWidget(fans_page)
        fan_form.addRow("", fan_actions)
        self.tabs.addTab(fan_box, "TACH / пороги")

        links = QHBoxLayout()
        sensor_link = QPushButton("DS18B20 / джерела температур…")
        sensor_link.clicked.connect(lambda: self.controller.dashboard.show_page("sensors"))
        links.addWidget(sensor_link)
        power_link = QPushButton("Живлення ПК / PWR_SW…")
        power_link.clicked.connect(lambda: self.controller.dashboard.show_page("pc"))
        links.addWidget(power_link)
        root.addLayout(links)
        limitations = QLabel(
            "GPIO-розводка, схема живлення вентиляторів, фізичний fail-ON, "
            "увімкнення драйвера DC PWM і PWR_SW задаються апаратно/під час "
            "компіляції, а не небезпечним записом довільних GPIO з Windows."
        )
        limitations.setWordWrap(True)
        root.addWidget(limitations)
        root.addStretch(1)
        self._action_buttons = (
            self.refresh_button, self.wifi_save, self.wifi_disable,
            self.mqtt_save, self.mqtt_reset, self.rgb_save, self.fan_save,
        )
        self._editors = {
            "wifi": (self.wifi_ssid, self.wifi_password, self.wifi_reveal, self.wifi_open),
            "mqtt": (self.mqtt_host, self.mqtt_port, self.mqtt_user,
                     self.mqtt_password, self.mqtt_reveal, self.mqtt_enabled,
                     self.mqtt_discovery, self.mqtt_temperature),
            "argb": (self.rgb_count, self.rgb_reverse, self.rgb_brightness, self.rgb_budget),
            "fan": (self.fan_ppr, self.fan_critical, self.fan_stall),
        }
        previous_tab = str(controller.settings.value("esp32SettingsTab", "wifi"))
        self.select_tab(previous_tab)
        self.tabs.currentChanged.connect(
            lambda index: controller.settings.setValue(
                "esp32SettingsTab", self._tab_keys[index]
            )
        )
        self.tabs.currentChanged.connect(self._fit_active_tab)
        self._fit_active_tab()
        self.set_connected(False)

    def select_tab(self, key: str) -> bool:
        if key not in self._tab_keys:
            return False
        self.tabs.setCurrentIndex(self._tab_keys.index(key))
        self._fit_active_tab()
        return True

    def _fit_active_tab(self, *_args) -> None:
        page = self.tabs.currentWidget()
        if page is None:
            return
        # QTabWidget otherwise keeps the height of the longest hidden form,
        # leaving a large blank panel beneath short tabs such as Wi-Fi.
        self.tabs.setMaximumHeight(max(
            290, page.sizeHint().height() + self.tabs.tabBar().sizeHint().height() + 28
        ))
        self.tabs.updateGeometry()

    def _refresh_dirty_tabs(self) -> None:
        self.tabs.setTabText(0, "Wi-Fi •" if self._wifi_dirty else "Wi-Fi")
        self.tabs.setTabText(1, "MQTT / HA •" if self._mqtt_dirty else "MQTT / HA")

    def _mark_wifi_dirty(self, *_args) -> None:
        if not self._loading:
            self._wifi_dirty = True
            self._refresh_dirty_tabs()

    def _toggle_open_wifi(self, checked: bool) -> None:
        self._update_buttons()
        self._mark_wifi_dirty()

    def _mark_mqtt_dirty(self, *_args) -> None:
        if not self._loading:
            self._mqtt_dirty = True
            self._refresh_dirty_tabs()

    def _mark_ready_if_initial_read(self) -> None:
        if (self._wifi_known and self._mqtt_known and
                self.result.text().startswith("ESP32 підключено ·")):
            self._state_label("✓ Конфігурацію ESP32 зчитано")

    def _state_label(self, message: str) -> None:
        self.result.setText(message)
        role = "negative" if message.startswith("⚠") else (
            "positive" if message.startswith("✓") else "minor"
        )
        self.result.setProperty("role", role)
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)

    def set_connected(self, connected: bool) -> None:
        self.connected = bool(connected)
        if connected:
            self._state_label("ESP32 підключено · зчитування налаштувань…")
        else:
            self.ack_timer.stop()
            self._operations.clear()
            self._active = None
            self._verify = None
            self.version = 0
            self.serial_version = 5
            self._strip_snapshot.clear()
            self._fan_snapshot.clear()
            self._budget_current = None
            self.wifi_config.clear()
            self.mqtt_config.clear()
            self._wifi_dirty = False
            self._mqtt_dirty = False
            self._wifi_known = self._mqtt_known = False
            self._rgb_known = self._fan_known = False
            self.wifi_password.clear()
            self.mqtt_password.clear()
            self._loading = True
            self.wifi_ssid.clear()
            self.wifi_open.setChecked(False)
            self.mqtt_host.clear()
            self.mqtt_user.clear()
            self.mqtt_port.setValue(1883)
            self.mqtt_enabled.setChecked(False)
            self.mqtt_discovery.setChecked(False)
            self.mqtt_temperature.setChecked(False)
            self.wifi_reveal.setChecked(False)
            self.mqtt_reveal.setChecked(False)
            self._loading = False
            self._refresh_dirty_tabs()
            self._state_label("ESP32 не підключено · зміни недоступні")
            self.wifi_status.setText("ESP32 не підключено")
            self.mqtt_status.setText("ESP32 не підключено")
        self._update_buttons()

    def set_version(self, version: int, serial_version: int = 5) -> None:
        self.version = version
        self.serial_version = serial_version
        self.header.setText(
            f"ESP32 firmware v{version} · конфігурація через USB · NVS"
            if version >= 8 else
            f"ESP32 firmware v{version}: для повного налаштування потрібна прошивка v8+"
        )
        self._update_buttons()
        if version >= 8:
            self.refresh_all()

    def _update_buttons(self) -> None:
        ready = self.connected and self.version >= 8
        working = (self._active is not None or bool(self._operations) or
                   self._verify is not None)
        self.tabs.setEnabled(not working)
        known = {"wifi": self._wifi_known, "mqtt": self._mqtt_known,
                 "argb": self._rgb_known, "fan": self._fan_known}
        for group, editors in self._editors.items():
            for editor in editors:
                editor.setEnabled(ready and known[group] and not working)
        self.wifi_password.setEnabled(
            ready and self._wifi_known and not working and not self.wifi_open.isChecked()
        )
        self.refresh_button.setEnabled(ready and not working)
        self.rgb_zone.setEnabled(ready and not working)
        self.fan_zone.setEnabled(ready and not working)
        for button, known in (
            (self.wifi_save, self._wifi_known),
            (self.wifi_disable, self._wifi_known),
            (self.mqtt_save, self._mqtt_known),
            (self.mqtt_reset, self._mqtt_known),
            (self.rgb_save, self._rgb_known),
            (self.fan_save, self._fan_known),
        ):
            button.setEnabled(ready and not working and known)

    def refresh_all(self) -> None:
        if not self.connected or self.version < 8:
            return
        for cmd in (
            "WIFI CONFIG?", "MQTT CONFIG?", "ARGBSTATUS",
            f"STRIPCFG? {self.rgb_zone.currentData()}",
            f"CONFIG {self.fan_zone.currentData()}",
        ):
            self.controller.send(cmd)

    def refresh_online(self) -> None:
        if not self.connected or self.version < 8:
            return
        self.controller.send("WIFI CONFIG?")
        self.controller.send("MQTT CONFIG?")

    def request_strip(self, *_args) -> None:
        self._rgb_known = False
        self._update_buttons()
        if self.connected and self.version >= 8:
            self.controller.send(f"STRIPCFG? {self.rgb_zone.currentData()}")

    def request_fan(self, *_args) -> None:
        self._fan_known = False
        self._update_buttons()
        if self.connected and self.version >= 8:
            self.controller.send(f"CONFIG {self.fan_zone.currentData()}")

    def _start(self, operations: list[tuple[str, str]],
               verify: str, expected: dict[str, object]) -> None:
        if not self.connected or self.version < 8:
            QMessageBox.warning(self, "Налаштування ESP32", "Спочатку підключи ESP32 з прошивкою v8+.")
            return
        if self._active is not None or self._verify is not None:
            return
        if not operations:
            # Preserve unsaved input in other tabs while refreshing this one.
            if verify == "wifi":
                self._wifi_dirty = False
            elif verify == "mqtt":
                self._mqtt_dirty = False
            self._refresh_dirty_tabs()
            self._state_label("Зміни не потрібні · зчитую поточний стан")
            self.refresh_all()
            return
        self._verify = verify
        self._expected = expected
        self._argb_verified.clear()
        self._operations = deque(operations)
        self._state_label("Запис налаштувань в ESP32…")
        self._send_next()

    def _send_next(self) -> None:
        self.ack_timer.stop()
        self._active = None
        if not self._operations:
            kind = self._verify
            self._state_label("ESP32 підтвердив запис · перевіряю налаштування…")
            if kind == "wifi":
                self.controller.send("WIFI CONFIG?")
            elif kind == "mqtt":
                self.controller.send("MQTT CONFIG?")
            elif kind == "argb":
                self.controller.send(f"STRIPCFG? {self.rgb_zone.currentData()}")
                self.controller.send("ARGBSTATUS")
            elif kind == "fan":
                self.controller.send(f"CONFIG {self.fan_zone.currentData()}")
            self._verify = "pending_" + str(kind)
            self.ack_timer.start(5000)
            self._update_buttons()
            return
        command, ack = self._operations.popleft()
        self._active = (command.split(" ", 1)[0], ack)
        self._update_buttons()
        if not self.controller.send(command):
            self._fail("USB-запис не вдався; налаштування можуть бути застосовані частково.")
            return
        self.ack_timer.start(5000)

    def _timeout(self) -> None:
        self._fail("ESP32 не відповів на запис. Перевір COM-порт і перечитай налаштування.")

    def _fail(self, message: str) -> None:
        if self._verify == "mqtt" and self.serial_version >= 7 and self.connected:
            self.controller.send("MQTT TX CANCEL")
        self.ack_timer.stop()
        self._active = None
        self._operations.clear()
        self._verify = None
        self._state_label("⚠ " + message)
        self._update_buttons()

    def _complete(self, success: bool) -> None:
        self.ack_timer.stop()
        self._active = None
        self._operations.clear()
        self._verify = None
        self._expected = {}
        self._state_label(
            "✓ ESP32 підтвердив і повернув збережені параметри"
            if success else
            "⚠ Параметри ESP32 відрізняються — перечитай стан перед повтором"
        )
        self._update_buttons()

    def save_wifi(self) -> None:
        try:
            ssid = self.wifi_ssid.text()
            command = wifi_command(
                ssid, self.wifi_password.text(),
                previous_ssid=str(self.wifi_config.get("ssid", "")),
                configured=bool(self.wifi_config.get("enabled", False)),
                open_network=self.wifi_open.isChecked(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Wi-Fi", str(exc))
            return
        self.wifi_password.clear()
        self.wifi_reveal.setChecked(False)
        self._start([(command, "OK WIFI_SET")], "wifi", {"ssid": ssid, "enabled": True})

    def disable_wifi(self) -> None:
        if QMessageBox.question(
            self, "Вимкнути Wi-Fi",
            "Видалити SSID і пароль із ESP32 NVS? MQTT та Wi-Fi ARGB від'єднаються.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.wifi_password.clear()
        self._start([("WIFI OFF", "OK WIFI_OFF")], "wifi", {"enabled": False})

    def save_mqtt(self) -> None:
        username = self.mqtt_user.text()
        try:
            builder = mqtt_transaction_commands if self.serial_version >= 7 else mqtt_commands
            commands = builder(
                host=self.mqtt_host.text(), port=self.mqtt_port.value(),
                username=username, password=self.mqtt_password.text(),
                enabled=self.mqtt_enabled.isChecked(),
                discovery=self.mqtt_discovery.isChecked(),
                allow_temperatures=self.mqtt_temperature.isChecked(),
                current=self.mqtt_config,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "MQTT", str(exc))
            return
        expected = {
            "host": self.mqtt_host.text().strip(),
            "port": self.mqtt_port.value(),
            "username": username,
            "enabled": self.mqtt_enabled.isChecked(),
            "discovery": self.mqtt_discovery.isChecked(),
            "allow_temperatures": self.mqtt_temperature.isChecked(),
        }
        self.mqtt_password.clear()
        self.mqtt_reveal.setChecked(False)
        ack = "OK MQTT_TX" if self.serial_version >= 7 else "OK MQTT_SAVED"
        self._start([(cmd, ack) for cmd in commands], "mqtt", expected)

    def reset_mqtt(self) -> None:
        if QMessageBox.question(
            self, "Очистити MQTT",
            "Видалити broker, логін та пароль MQTT із NVS ESP32?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.mqtt_password.clear()
        operations = (
            [("MQTT TX START", "OK MQTT_TX"), ("MQTT TX CLEAR", "OK MQTT_TX"),
             ("MQTT TX COMMIT", "OK MQTT_TX")]
            if self.serial_version >= 7 else [("MQTT CLEAR", "OK MQTT_SAVED")]
        )
        expected = {"host": "", "username": "", "enabled": False, "port": 1883}
        if self.serial_version >= 7:
            expected.update({"allow_temperatures": False, "discovery": True})
        self._start(operations, "mqtt", expected)

    def save_argb(self) -> None:
        ch = self.rgb_zone.currentData()
        count = self.rgb_count.value()
        reverse = self.rgb_reverse.isChecked()
        budget = self.rgb_budget.value()
        bright = self.rgb_brightness.value()
        previous = self._strip_snapshot.get(ch, {})
        geometry_changed = (previous.get("leds") != count or
                            previous.get("reverse") != reverse)
        brightness_changed = previous.get("brightness") != bright
        budget_changed = self._budget_current != budget
        if self.serial_version >= 6 and (geometry_changed or brightness_changed or budget_changed):
            ops = [(f"ARGBCFG {ch} {count} {int(reverse)} {budget} {bright}",
                    "OK ARGBCFG_SAVED")]
        else:
            ops = []
            if previous.get("leds") != count:
                ops.append((f"STRIP {ch} {count}", "OK STRIP_SAVED"))
            if previous.get("reverse") != reverse:
                ops.append((f"REVERSE {ch} {int(reverse)}", "OK STRIP_SAVED"))
            if budget_changed:
                ops.append((f"RGBBUDGET {budget}", "OK BUDGET_SAVED"))
            if brightness_changed:
                ops.append((f"BRIGHT {ch} {bright}", "OK"))
        self._start(ops, "argb", {
            "channel": ch, "leds": count, "reverse": reverse,
            "budget": budget, "brightness": bright,
        })

    def save_fan(self) -> None:
        ch = self.fan_zone.currentData()
        if QMessageBox.question(
            self, "Зберегти пороги вентилятора",
            "Змінити апаратні пороги й імпульси TACH у NVS? "
            "Неправильний PPR призведе до хибних RPM. "
            "Керування живленням залишається під апаратними захистами.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        ppr = self.fan_ppr.value()
        critical = self.fan_critical.value()
        stall = self.fan_stall.value()
        previous = self._fan_snapshot.get(ch, {})
        if self.serial_version >= 6:
            operations = [] if (previous.get("ppr") == ppr and
                                previous.get("crit") == critical and
                                previous.get("stall") == stall) else [
                (f"FANCFG {ch} {ppr} {critical} {stall}", "OK FANCFG_SAVED")
            ]
        else:
            operations = []
            for key, command, value in (
                ("ppr", "PPR", ppr), ("crit", "CRIT", critical),
                ("stall", "STALL", stall),
            ):
                if previous.get(key) != value:
                    operations.append((f"{command} {ch} {value}", "OK CONFIG"))
        self._start(operations, "fan",
                    {"channel": ch, "ppr": ppr, "crit": critical, "stall": stall})

    def handle_line(self, line: str) -> bool:
        if line.startswith("WIFI_CONFIG "):
            self._on_wifi_config(fields(line, "WIFI_CONFIG"))
            return True
        if line.startswith("MQTT_CONFIG "):
            self._on_mqtt_config(fields(line, "MQTT_CONFIG"))
            return True
        if line.startswith("STRIPCFG "):
            self._on_strip_config(fields(line, "STRIPCFG"))
            return True
        if line.startswith("ARGBSTATUS "):
            self._on_argb_status(fields(line, "ARGBSTATUS"))
            return True
        if self._active is not None:
            if line == self._active[1]:
                self._send_next()
                return True
            if line.startswith("ERR "):
                self._fail(f"Контролер відхилив операцію: {line}")
                return True
        return False

    def _on_wifi_config(self, data: dict[str, str]) -> None:
        try:
            ssid = decode_value(data["SSID_HEX"], 32)
            new = {"ssid": ssid, "enabled": data["ENABLED"] == "1",
                   "connected": data["CONNECTED"] == "1",
                   "password_set": data["PASSWORD_SET"] == "1",
                   "ip": data.get("IP", "-")}
        except (ValueError, KeyError):
            self._fail("Некоректна відповідь Wi-Fi від ESP32")
            return
        self.wifi_config = new
        self._wifi_known = True
        self._update_buttons()
        self._mark_ready_if_initial_read()
        self.wifi_status.setText(
            ("Підключено · " + str(new["ip"]) if new["connected"] else
             "Збережено, очікує мережу" if new["enabled"] else
             "Вимкнено") + (" · пароль встановлено" if new["password_set"] else "")
        )
        if not self._wifi_dirty:
            self._loading = True
            self.wifi_ssid.setText(ssid)
            self.wifi_open.setChecked(new["enabled"] and not new["password_set"])
            self._loading = False
        if self._verify == "pending_wifi":
            good = all(new.get(k) == v for k, v in self._expected.items())
            self._wifi_dirty = False
            self._refresh_dirty_tabs()
            self._complete(good)

    def _on_mqtt_config(self, data: dict[str, str]) -> None:
        try:
            new = {
                "host": decode_value(data["HOST_HEX"], 63),
                "username": decode_value(data["USER_HEX"], 31),
                "enabled": data["ENABLED"] == "1",
                "connected": data["CONNECTED"] == "1",
                "port": int(data["PORT"]),
                "discovery": data["DISCOVERY"] == "1",
                "allow_temperatures": data.get("TEMP_ALLOW", "0") == "1",
                "topic": data.get("TOPIC", ""),
            }
        except (ValueError, KeyError):
            self._fail("Некоректна відповідь MQTT від ESP32")
            return
        self.mqtt_config = new
        self._mqtt_known = True
        self._update_buttons()
        self._mark_ready_if_initial_read()
        self.mqtt_status.setText(
            ("Підключено до брокера" if new["connected"] else
             "Налаштовано, офлайн" if new["enabled"] else "Вимкнено")
            + " · " + str(new["topic"])
        )
        if not self._mqtt_dirty:
            self._loading = True
            self.mqtt_host.setText(str(new["host"]))
            self.mqtt_port.setValue(int(new["port"]))
            self.mqtt_user.setText(str(new["username"]))
            self.mqtt_enabled.setChecked(bool(new["enabled"]))
            self.mqtt_discovery.setChecked(bool(new["discovery"]))
            self.mqtt_temperature.setChecked(bool(new["allow_temperatures"]))
            self._loading = False
        if self._verify == "pending_mqtt":
            good = all(new.get(k) == v for k, v in self._expected.items())
            self._mqtt_dirty = False
            self._refresh_dirty_tabs()
            self._complete(good)

    def _on_strip_config(self, data: dict[str, str]) -> None:
        try:
            ch = int(data["CH"])
            pixels = int(data["LEDS"])
            reverse = data["REVERSE"] == "1"
            brightness = int(data["BRIGHT"])
        except (ValueError, KeyError):
            return
        self._strip_snapshot[ch] = {"leds": pixels, "reverse": reverse, "brightness": brightness}
        if ch == self.rgb_zone.currentData():
            self._rgb_known = True
            self._update_buttons()
            self.rgb_count.setValue(pixels)
            self.rgb_reverse.setChecked(reverse)
            self.rgb_brightness.setValue(brightness)
        if self._verify == "pending_argb" and ch == self._expected.get("channel"):
            if (pixels != self._expected.get("leds") or
                    reverse != self._expected.get("reverse") or
                    brightness != self._expected.get("brightness")):
                self._complete(False)
            else:
                self._argb_verified.add("strip")
                if "budget" in self._argb_verified:
                    self._complete(True)

    def _on_argb_status(self, data: dict[str, str]) -> None:
        try:
            budget = int(data["LIMIT_MA"])
            requested = int(data["REQUESTED_MA"])
        except (ValueError, KeyError):
            return
        self._budget_current = budget
        self.rgb_budget.setValue(budget)
        limited = data.get("LIMITED_MA")
        self.argb_status.setText(
            f"{budget} мА · запит {requested} мА" +
            (f" · після обмеження {limited} мА" if limited is not None else "")
        )
        if self._verify == "pending_argb":
            if budget != self._expected.get("budget"):
                self._complete(False)
            else:
                self._argb_verified.add("budget")
                if "strip" in self._argb_verified:
                    self._complete(True)

    def on_fan_config(self, line: str) -> None:
        parts = line.split()
        if len(parts) < 3 or parts[0] != "CONFIG":
            return
        try:
            ch = int(parts[1])
            data = dict(x.split("=", 1) for x in parts[2:] if "=" in x)
            ppr = int(data["PPR"])
            crit = int(data["CRIT"])
            stall = int(data["STALL"])
        except (ValueError, KeyError):
            return
        self._fan_snapshot[ch] = {"ppr": ppr, "crit": crit, "stall": stall}
        if ch == self.fan_zone.currentData():
            self._fan_known = True
            self._update_buttons()
            self.fan_ppr.setValue(ppr)
            self.fan_critical.setValue(crit)
            self.fan_stall.setValue(stall)
            self.fan_info.setText(
                "Тип " + data.get("TYPE", "?") + "-pin · старт " +
                data.get("START", "?") + "% · мін. хід " +
                data.get("RUN", "?") + "% · PID " + data.get("PID", "?")
            )
        if self._verify == "pending_fan" and ch == self._expected.get("channel"):
            self._complete(
                ppr == self._expected.get("ppr") and
                crit == self._expected.get("crit") and
                stall == self._expected.get("stall")
            )

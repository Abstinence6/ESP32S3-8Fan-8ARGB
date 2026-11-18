"""Eight ESP32-rendered responsive RGB scenes and arbitrary NWinfo sensor routing.

The entire animation runs on the ESP; host only sends selected scalar values.
Users can supply the same numeric slot through MQTT without a Windows process.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QSlider, QVBoxLayout, QWidget,
)
try:
    from .reactive_argb import (
        MAPPING_KEY, default_scene, dump_slots, load_slots, make_set,
        parse_readback,
    )
except ImportError:
    from reactive_argb import (
        MAPPING_KEY, default_scene, dump_slots, load_slots, make_set,
        parse_readback,
    )

STYLES = ("Колір залежно від значення", "Індикатор рівня / шкала",
          "Яскравість залежно від значення", "Швидкість анімації")
PATTERNS = ("Gradient", "Wave", "Breathe", "Chase")


def _local_sources():
    choices=[]
    for index in range(8):
        choices.append((1+index, f"ESP: RPM FAN {index+1}"))
    for index in range(8):
        choices.append((9+index, f"ESP: температура керування FAN {index+1}"))
    for index in range(8):
        choices.append((17+index, f"ESP: DS18B20 №{index+1}"))
    for index in range(8):
        choices.append((33+index, f"ESP: фактичний PWM FAN {index+1}"))
    return choices

LOCAL_SOURCES = _local_sources()


class ReactiveArgbPanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("RGB за навантаженням, RPM, потужністю та датчиками")
        self.controller=controller
        self.supported=False
        self.current=1
        self.colors=((0,100,255),(255,0,0))
        self._loading=False
        self.configs={ch:default_scene(ch) for ch in range(1,9)}
        self._invalid_host_config=False
        try:
            self.host_slots=list(load_slots(str(controller.settings.value(MAPPING_KEY,""))))
        except ValueError:
            self.host_slots=[""]*8
            self._invalid_host_config=True
        root=QVBoxLayout(self)
        help_text=QLabel(
            "Рендер анімації та конфігурація зберігаються в ESP32. Локальні "
            "RPM/PWM/DS18B20 працюють без ПК. Для GPU/CPU load, W, RAM, MHz "
            "та інших NWinfo-датчиків ПК передає лише числове значення. "
            "Той самий слот можна оновлювати через MQTT/Home Assistant.")
        help_text.setWordWrap(True)
        root.addWidget(help_text)
        zone=QHBoxLayout()
        zone.addWidget(QLabel("ARGB-зона"))
        self.channel=QComboBox()
        for ch in range(1,9):
            self.channel.addItem(f"ARGB {ch}",ch)
        zone.addWidget(self.channel)
        zone.addStretch()
        root.addLayout(zone)

        row=QHBoxLayout()
        row.addWidget(QLabel("Джерело"))
        self.source=QComboBox()
        row.addWidget(self.source,1)
        root.addLayout(row)
        row=QHBoxLayout()
        row.addWidget(QLabel("Резерв"))
        self.fallback=QComboBox()
        self.fallback.addItem("Немає: помаранчева індикація",0)
        for ident,name in LOCAL_SOURCES:
            self.fallback.addItem(name,ident)
        row.addWidget(self.fallback,1)
        root.addLayout(row)

        self.host_label=QLabel("ПК-датчик для вибраного слота")
        root.addWidget(self.host_label)
        self.host_sensor=QComboBox()
        root.addWidget(self.host_sensor)
        self.mqtt_help=QLabel(
            "MQTT: esp32fan/esp32s3/reactive/N/set, де N — номер слота/зони. "
            "Значення передається в десятих частках одиниці.")
        self.mqtt_help.setWordWrap(True)
        root.addWidget(self.mqtt_help)

        row=QHBoxLayout()
        row.addWidget(QLabel("Візуалізація"))
        self.style=QComboBox()
        self.style.addItems(STYLES)
        row.addWidget(self.style,1)
        row.addWidget(QLabel("Базовий ефект"))
        self.pattern=QComboBox()
        self.pattern.addItems(PATTERNS)
        row.addWidget(self.pattern,1)
        root.addLayout(row)

        row=QHBoxLayout()
        row.addWidget(QLabel("Мінімум"))
        self.low=QDoubleSpinBox()
        self.low.setDecimals(1)
        self.low.setRange(0,999999.9)
        self.low.setValue(30.0)
        row.addWidget(self.low,1)
        row.addWidget(QLabel("Максимум"))
        self.high=QDoubleSpinBox()
        self.high.setDecimals(1)
        self.high.setRange(0.1,1000000.0)
        self.high.setValue(85.0)
        row.addWidget(self.high,1)
        root.addLayout(row)

        row=QHBoxLayout()
        for index in range(2):
            btn=QPushButton(f"Колір {index+1}…")
            btn.clicked.connect(lambda _=False,j=index:self._pick(j))
            row.addWidget(btn)
        self.reverse=QCheckBox("Реверс")
        row.addWidget(self.reverse)
        root.addLayout(row)

        row=QHBoxLayout()
        row.addWidget(QLabel("Швидкість"))
        self.speed=QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(1,10)
        self.speed.setValue(3)
        row.addWidget(self.speed)
        row.addWidget(QLabel("Яскравість"))
        self.brightness=QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0,255)
        self.brightness.setValue(64)
        row.addWidget(self.brightness)
        root.addLayout(row)
        self.boot=QCheckBox("Автоматично запускати цю сцену після reset ESP32 (opt-in)")
        root.addWidget(self.boot)

        buttons=QHBoxLayout()
        self.actions=[]
        for text,fn in (("▶ Перегляд",self.preview),("■ Вимкнути",self.stop),
                        ("Зчитати",self.readback),("Зберегти в ESP32",self.save)):
            button=QPushButton(text)
            button.clicked.connect(fn)
            buttons.addWidget(button)
            self.actions.append(button)
        root.addLayout(buttons)
        self.status=QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.channel.currentIndexChanged.connect(self._select_channel)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.host_sensor.currentIndexChanged.connect(self._host_changed)
        self._select_channel()
        self.set_supported(False)

    def set_supported(self, supported: bool):
        self.supported=supported
        for button in self.actions:
            button.setEnabled(supported)
        if not supported:
            self.status.setText("Підключи ESP32 з підтримкою RFX=1")
        else:
            self.status.setText("ESP32 сам розраховує ефекти; готово до налаштування")

    def _sources(self,ch:int):
        self.source.blockSignals(True)
        self.source.clear()
        for ident,name in LOCAL_SOURCES:
            self.source.addItem(name,ident)
        self.source.addItem(f"ПК або MQTT: слот {ch}",24+ch)
        self.source.blockSignals(False)

    def _select_channel(self,*_):
        self.current=self.channel.currentData() or 1
        self._loading=True
        self._sources(self.current)
        self._fill(self.configs[self.current])
        # A zone change uses that zone's saved metric, never the previous zone's combo.
        self.host_sensor.blockSignals(True)
        self.host_sensor.clear()
        self.host_sensor.blockSignals(False)
        self.refresh_sensors()
        self._loading=False
        if self.supported and self.controller.port:
            self.readback()

    def _fill(self,scene):
        index=self.source.findData(scene.source)
        self.source.setCurrentIndex(index if index>=0 else 0)
        fallback=self.fallback.findData(scene.fallback)
        self.fallback.setCurrentIndex(fallback if fallback>=0 else 0)
        self.style.setCurrentIndex(scene.style-1)
        self.pattern.setCurrentIndex(scene.pattern-1)
        self.low.setValue(scene.low/10.0)
        self.high.setValue(scene.high/10.0)
        self.colors=(scene.primary,scene.secondary)
        self.speed.setValue(scene.speed)
        self.brightness.setValue(scene.brightness)
        self.reverse.setChecked(bool(scene.direction))
        self.boot.setChecked(scene.boot)
        self._source_changed()

    def _pick(self,index):
        value=QColorDialog.getColor(QColor(*self.colors[index]),self,"Колір")
        if value.isValid():
            colors=list(self.colors)
            colors[index]=(value.red(),value.green(),value.blue())
            self.colors=tuple(colors)

    def _source_changed(self,*_):
        is_host=self.source.currentData()==24+self.current
        if not self._loading:
            source=self.source.currentData()
            if source is not None and 1 <= source <= 8:
                self.low.setValue(0); self.high.setValue(2500)
            elif source is not None and 9 <= source <= 24:
                self.low.setValue(30); self.high.setValue(85)
            elif source is not None and 33 <= source <= 40:
                self.low.setValue(0); self.high.setValue(100)
            elif is_host:
                self._host_changed()
        self.host_label.setVisible(is_host)
        self.host_sensor.setVisible(is_host)
        self.mqtt_help.setVisible(is_host)

    def _host_changed(self,*_):
        if self._loading:
            return
        label=self.host_sensor.currentData()
        if isinstance(label,str) and label:
            unit=self.host_sensor.currentText()
            if "°C" in unit:
                lo,hi=30.0,90.0
            elif "%" in unit:
                lo,hi=0.0,100.0
            elif " W " in " "+unit+" ":
                lo,hi=0.0,350.0
            elif "RPM" in unit:
                lo,hi=0.0,2500.0
            elif "MHz" in unit:
                lo,hi=0.0,5000.0
            else:
                return
            self.low.setValue(lo)
            self.high.setValue(hi)

    def refresh_sensors(self):
        current=self.host_sensor.currentData()
        selected=current if isinstance(current,str) else self.host_slots[self.current-1]
        self.host_sensor.blockSignals(True)
        self.host_sensor.clear()
        self.host_sensor.addItem("MQTT / Home Assistant (без даних з ПК)","")
        for sensor in sorted(self.controller.temperatures,key=lambda x:x.name.casefold()):
            self.host_sensor.addItem(f"Температура · {sensor.name} · °C",
                                    "temp:"+sensor.sensor_id)
        for sensor in sorted(self.controller.sensor_sampler.metrics,key=lambda x:x.name.casefold()):
            self.host_sensor.addItem(f"{sensor.name} · {sensor.unit}",
                                    "metric:"+sensor.sensor_id)
        index=self.host_sensor.findData(selected)
        if index<0 and selected:
            self.host_sensor.addItem("Недоступний: "+selected,selected)
            index=self.host_sensor.count()-1
        self.host_sensor.setCurrentIndex(max(0,index))
        self.host_sensor.blockSignals(False)

    def _make_scene(self):
        from dataclasses import replace
        scene=replace(self.configs[self.current],
            channel=self.current,source=int(self.source.currentData()),
            fallback=int(self.fallback.currentData()),style=self.style.currentIndex()+1,
            low=round(self.low.value()*10),high=round(self.high.value()*10),
            pattern=self.pattern.currentIndex()+1,primary=self.colors[0],
            secondary=self.colors[1],speed=self.speed.value(),
            brightness=self.brightness.value(),direction=int(self.reverse.isChecked()),
            boot=self.boot.isChecked())
        return scene

    def _send(self,text):
        return bool(self.supported and self.controller.port and self.controller.send(text))

    def _stop_external(self):
        shell=self.controller.dashboard
        if shell.studio.active: shell.studio.stop()
        if shell.temperature_argb.active: shell.temperature_argb.stop()
        if shell.native_checkbox.isChecked(): shell.native_checkbox.setChecked(False)
        if self.controller.bridge_checkbox.isChecked(): self.controller.bridge_checkbox.setChecked(False)

    def preview(self):
        try:
            scene=self._make_scene()
            command=make_set(scene)
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,"Реактивна підсвітка",str(exc))
            return False
        self._stop_external()
        if not self._send(command):
            self.status.setText("USB недоступний або ESP32 не підтримує RFX")
            return False
        self.configs[self.current]=scene
        slots=self.host_slots.copy()
        slots[self.current-1]=(str(self.host_sensor.currentData() or "")
                               if scene.source==24+self.current else "")
        if not self._invalid_host_config:
            self.host_slots=list(load_slots(dump_slots(slots)))
            self.controller.settings.setValue(MAPPING_KEY,dump_slots(self.host_slots))
        else:
            self.status.setText("RFX надіслано, але попередній запис ПК-датчиків пошкоджено. "
                                "Для нового збереження потрібне окреме підтвердження.")
            return True
        self.status.setText("Ефект запущено на ESP32; збереження в NVS окремою кнопкою")
        return True

    def save(self):
        if not self.preview(): return
        if self._invalid_host_config:
            answer=QMessageBox.question(self,"Відновлення налаштувань",
                "Збережений список ПК-датчиків пошкоджено. Перезаписати його поточними налаштуваннями?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes: return
            slots=self.host_slots.copy()
            slots[self.current-1]=(str(self.host_sensor.currentData() or "")
                                   if self.source.currentData()==24+self.current else "")
            self.host_slots=list(load_slots(dump_slots(slots)))
            self.controller.settings.setValue(MAPPING_KEY,dump_slots(self.host_slots))
            self._invalid_host_config=False
        if (self._send(f"RFX BOOT {self.current} {int(self.boot.isChecked())}") and
            self._send("RFX SAVE")):
            self.status.setText("Очікування підтвердження збереження RFX_SAVED")

    def stop(self):
        if self._send(f"RFX STOP {self.current}"):
            self.status.setText("Реактивний ефект вимкнено")

    def readback(self):
        self._send(f"RFX? {self.current}")

    def handle_line(self,line):
        if line=="OK RFX_SAVED":
            self.status.setText("ESP32 підтвердив збереження правил у NVS")
            return True
        if line.startswith("ERR RFX"):
            self.status.setText("ESP32 відхилив команду: "+line)
            return True
        scene=parse_readback(line)
        if scene is None:
            return False
        self.configs[scene.channel]=scene
        if scene.channel==self.current:
            self._loading=True
            self._fill(scene)
            self.refresh_sensors()
            self._loading=False
            source="актуальні" if scene.fresh else "відсутні"
            self.status.setText(
                f"ARGB {scene.channel}: {'запущено' if scene.active else 'зупинено'} · "
                f"дані {source}" + (f" · {scene.value/10:.1f}" if scene.fresh else ""))
        return True

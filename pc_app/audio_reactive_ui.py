"""Per-zone ESP32 audio-reactive editor and explicit Windows loopback opt-in."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,QColorDialog,QComboBox,QGroupBox,QHBoxLayout,
    QLabel,QMessageBox,QPushButton,QSlider,QVBoxLayout,
)

STYLES=("VU-шкала","4 частотні смуги","Басовий імпульс","Звукова хвиля")


class AudioReactivePanel(QGroupBox):
    def __init__(self, controller):
        super().__init__("Audio Reactive · обчислення ефектів на ESP32")
        self.controller=controller
        self.supported=False
        self._channel=1
        self._channel_available=True
        self._drafts={}
        self._configs={}
        self._read_intent={}
        self.colors=((0,150,255),(255,40,100))
        self._default=(0,100,64,self.colors,False)
        root=QVBoxLayout(self)
        intro=QLabel(
            "ESP32 сам рендерить анімації. Windows надсилає лише 4 числові "
            "рівні частот. Запис звуку не зберігається. Без Windows можна "
            "передавати рівні з MQTT або під'єднати окреме джерело.")
        intro.setWordWrap(True)
        root.addWidget(intro)
        row=QHBoxLayout()
        row.addWidget(QLabel("Ефект"))
        self.style=QComboBox()
        self.style.addItems(STYLES)
        row.addWidget(self.style,1)
        root.addLayout(row)
        row=QHBoxLayout()
        row.addWidget(QLabel("Чутливість"))
        self.gain=QSlider(Qt.Orientation.Horizontal)
        self.gain.setRange(1,200)
        self.gain.setValue(100)
        row.addWidget(self.gain)
        row.addWidget(QLabel("Яскравість"))
        self.brightness=QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0,255)
        self.brightness.setValue(64)
        row.addWidget(self.brightness)
        root.addLayout(row)
        row=QHBoxLayout()
        for n in range(2):
            btn=QPushButton(f"Колір {n+1}…")
            btn.clicked.connect(lambda _=False,i=n:self._pick(i))
            row.addWidget(btn)
        root.addLayout(row)
        self.boot=QCheckBox("Запускати аудіосцену після reset (на початку тихо)")
        root.addWidget(self.boot)
        self.capture=QCheckBox("Системний звук Windows (WASAPI) · спільне джерело для всіх зон")
        self.capture.setChecked(str(controller.settings.value(
            "audioCaptureEnabled","false")).lower() in ("true","1"))
        self.capture.toggled.connect(self._capture_changed)
        root.addWidget(self.capture)
        btns=QHBoxLayout()
        self.buttons=[]
        for label,fn in (("▶ Перегляд",self.preview),("■ Вимкнути",self.stop),
                         ("Зчитати",lambda: self.readback(replace_draft=True)),
                         ("Зберегти в ESP32",self.save)):
            btn=QPushButton(label)
            btn.clicked.connect(fn)
            btns.addWidget(btn)
            self.buttons.append(btn)
        self.buttons[-1].setToolTip("ESP32 зберігає всі поточні аудіосцени в NVS.")
        root.addLayout(btns)
        self.status=QLabel("Потрібна прошивка AUDIO=1")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.set_supported(False)

    def set_channel(self, channel: int, available: bool):
        if channel != self._channel:
            self._remember_draft()
            self._channel=channel
            self._fill(*self._drafts.get(channel,self._configs.get(channel,self._default)))
            self.set_supported(self.supported)
        self._channel_available=available
        self._update_buttons()

    def _remember_draft(self):
        ch=self._channel
        values=(self.style.currentIndex(), self.gain.value(), self.brightness.value(),
                self.colors, self.boot.isChecked())
        # A known draft may match the defaults after a disconnect clears the cache.
        if values==self._drafts.get(ch):
            return values
        requested=self._read_intent.get(ch)
        # A post-request edit is a draft even when it matches the old cache.
        if (values!=self._configs.get(ch,self._default)
                or (requested is not None and values!=requested)):
            self._drafts[ch]=values
        else:
            self._drafts.pop(ch,None)
        return values

    def _fill(self, style, gain, brightness, colors, boot):
        self.style.setCurrentIndex(style)
        self.gain.setValue(gain)
        self.brightness.setValue(brightness)
        self.colors=colors
        self.boot.setChecked(boot)

    def set_supported(self, enabled: bool):
        if self.supported and not enabled:
            self._remember_draft()
            self._configs.clear()
            self._read_intent.clear()
            self._fill(*self._drafts.get(self._channel,self._default))
        self.supported=enabled
        self._update_buttons()
        self.capture.setEnabled(enabled)
        if enabled and self._channel in self._drafts and self._channel in self._configs:
            self._show_draft_status()
        elif enabled and self._channel in self._configs:
            self.status.setText("Аудіосцена завантажена з ESP32")
        else:
            self.status.setText("Готово до аудіоефектів" if enabled
                                else "Потрібен ESP32 з AUDIO=1")

    def _show_draft_status(self):
        self.status.setText("Незбережена чернетка · «Зчитати» замінить її даними ESP32")

    def _update_buttons(self):
        for btn in self.buttons:
            btn.setEnabled(self.supported and self._channel_available)

    def _capture_changed(self,enabled: bool):
        self.controller.set_audio_capture_enabled(enabled)

    def _pick(self,index: int):
        color=QColorDialog.getColor(QColor(*self.colors[index]),self,"Колір аудіоефекту")
        if color.isValid():
            palette=list(self.colors)
            palette[index]=(color.red(),color.green(),color.blue())
            self.colors=tuple(palette)

    def _ready(self)->bool:
        return self.supported and self._channel_available and self.controller.port is not None

    def _send(self,text: str)->bool:
        return self._ready() and self.controller.send(text)

    def preview(self)->bool:
        if not self._ready():
            return False
        ch=self._channel
        parts=[ch,self.style.currentIndex()+1,self.gain.value(),self.brightness.value(),
               *self.colors[0],*self.colors[1]]
        shell=self.controller.dashboard
        if shell.studio.active: shell.studio.stop()
        if shell.temperature_argb.active: shell.temperature_argb.stop()
        if shell.native_checkbox.isChecked(): shell.native_checkbox.setChecked(False)
        if self.controller.bridge_checkbox.isChecked(): self.controller.bridge_checkbox.setChecked(False)
        if not self._send("AUDIOCFG SET "+" ".join(map(str,parts))):
            self.status.setText("Не вдалося надіслати AUDIOCFG")
            return False
        self.status.setText("Сцена активна на ESP32 (ще не збережена)")
        return True

    def save(self):
        if not self.preview(): return
        ch=self._channel
        if self._send(f"AUDIOCFG BOOT {ch} {int(self.boot.isChecked())}") and self._send("AUDIOCFG SAVE"):
            self.status.setText("Очікування підтвердження AUDIOCFG_SAVED")

    def stop(self):
        if self._send(f"AUDIOCFG STOP {self._channel}"):
            self.status.setText("Аудіосцену вимкнено")

    def readback(self, *, replace_draft=False):
        ch=self._channel
        requested=self._remember_draft()
        if self._send(f"AUDIOCFG? {ch}") and replace_draft:
            self._read_intent[ch]=requested

    def handle_line(self,line: str)->bool:
        if line=="OK AUDIOCFG_SAVED":
            self.status.setText("ESP32 підтвердив запис аудіосцен у NVS")
            return True
        if line.startswith("ERR AUDIOCFG"):
            self.status.setText("ESP32 відхилив аудіокоманду: "+line)
            return True
        if not line.startswith("AUDIOCFG CH="): return False
        if not self.supported: return True
        try:
            fields=dict(x.split("=",1) for x in line.split()[1:] if "=" in x)
            ch=int(fields["CH"])
            style=int(fields["STYLE"])
            gain=int(fields["GAIN"])
            bright=int(fields["BRIGHT"])
            primary=tuple(int(v) for v in fields["R1"].split(","))
            secondary=tuple(int(v) for v in fields["R2"].split(","))
            boot=int(fields["BOOT"])
            if not (1<=ch<=8 and 1<=style<=4 and 1<=gain<=200 and
                    0<=bright<=255 and len(primary)==3 and len(secondary)==3
                    and all(0<=c<=255 for c in (*primary,*secondary)) and boot in (0,1)):
                return True
        except (KeyError,TypeError,ValueError):
            return True
        visible=ch==self._channel
        if visible:
            self._remember_draft()
        values=(style-1,gain,bright,(primary,secondary),bool(boot))
        self._configs[ch]=values
        draft=self._drafts.get(ch)
        expected=self._read_intent.pop(ch,None)
        if draft is not None and draft!=expected and draft!=values:
            if visible:
                self._show_draft_status()
            return True
        self._drafts.pop(ch,None)
        if visible:
            self._fill(*values)
            self.status.setText("Аудіосцена завантажена з ESP32")
        return True

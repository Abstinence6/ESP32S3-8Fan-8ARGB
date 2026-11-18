"""Device-resident profiles and passive airflow assistant (USB dialogs)."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout,
)
try:
    from .autonomy_protocol import (
        aircfg_command,parse_airflow,parse_fan,parse_profile
    )
except ImportError:
    from autonomy_protocol import (
        aircfg_command,parse_airflow,parse_fan,parse_profile
    )

class OfflineProfilesDialog(QDialog):
    def __init__(self,controller,parent=None):
        super().__init__(parent or controller)
        self.controller=controller
        self.setWindowTitle("Автономні профілі ESP32")
        self.setMinimumWidth(440)
        root=QVBoxLayout(self)
        description=QLabel(
            "Три профілі зберігаються у NVS ESP32. Збереження знімає "
            "постійні криві з контролера та поточні ARGB-режими, не змінює "
            "порогів безпеки. Перемикання профілю не записує flash.")
        description.setWordWrap(True)
        root.addWidget(description)
        self.slot=QComboBox()
        for ch in range(1,4): self.slot.addItem(f"Профіль {ch}",ch)
        root.addWidget(self.slot)
        row=QHBoxLayout()
        for text,callback in (
            ("Прочитати",self.refresh),
            ("Зберегти поточне",self.capture),
            ("Увімкнути",self.select),
            ("Скинути до базового",self.clear),
        ):
            b=QPushButton(text)
            b.clicked.connect(callback)
            row.addWidget(b)
        root.addLayout(row)
        row=QHBoxLayout()
        button=QPushButton("Відновлювати після reset")
        button.clicked.connect(self.set_boot)
        row.addWidget(button)
        button=QPushButton("Вимкнути автозапуск")
        button.clicked.connect(self.disable_boot)
        row.addWidget(button)
        root.addLayout(row)
        self.info=QLabel("Зчитати стан ESP32")
        self.info.setWordWrap(True)
        root.addWidget(self.info)
        self.refresh()

    def _send(self,text):
        if not self.controller.send(text):
            self.info.setText("Немає підключення до ESP32")
            return False
        return True

    def refresh(self):
        self._send("PROFILE?")

    def capture(self):
        ch=self.slot.currentData()
        answer=QMessageBox.question(self,"Зберегти профіль",
            f"Перезаписати слот {ch} у NVS? Будуть скопійовані постійні криві "
            "ESP32 та поточні режими ARGB (не тимчасові криві Windows).",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Yes:
            self._send(f"PROFILE SAVE {ch}")

    def select(self):
        self._send(f"PROFILE SELECT {self.slot.currentData()}")

    def clear(self):
        self._send("PROFILE CLEAR")

    def set_boot(self):
        ch=self.slot.currentData()
        if QMessageBox.question(self,"Автономний запуск",
            f"Увімкнути профіль {ch} при кожному старті ESP32?",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self._send(f"PROFILE BOOT {ch}")

    def disable_boot(self):
        self._send("PROFILE BOOT 0")

    def handle_line(self,line):
        if line.startswith("OK PROFILE"):
            self.info.setText("ESP32 прийняв команду; зчитую поточний стан…")
            self.refresh()
            return True
        if line.startswith("ERR PROFILE"):
            self.info.setText("Помилка: "+line)
            return True
        state=parse_profile(line)
        if not state: return False
        self.info.setText(
            f"Активний: {state.active or 'базовий'}, після reset: "
            f"{state.boot or 'базовий'}; збережені: "+
            ", ".join(str(i+1) for i,v in enumerate(state.saved) if v or ()) )
        return True


class AirflowDialog(QDialog):
    def __init__(self,controller,parent=None):
        super().__init__(parent or controller)
        self.controller=controller
        self.setWindowTitle("Airflow Assistant — оцінка CFM, не тиску")
        self.setMinimumWidth(470)
        root=QVBoxLayout(self)
        info=QLabel(
            "Пасивна оцінка за паспортними CFM і RPM. НЕ вимірює "
            "реальний тиск у корпусі. Для результату потрібні достовірні "
            "TACH для кожного налаштованого вентилятора, вдув і видув.")
        info.setWordWrap(True)
        root.addWidget(info)
        form=QFormLayout()
        self.channel=QComboBox()
        for ch in range(1,9): self.channel.addItem(f"FAN {ch}",ch)
        self.channel.currentIndexChanged.connect(self.read_channel)
        form.addRow("Вентилятор",self.channel)
        self.direction=QComboBox()
        for label,val in (("Не враховувати",0),("Вдув",1),("Видув",2)):
            self.direction.addItem(label,val)
        form.addRow("Напрямок",self.direction)
        self.rpm=QSpinBox()
        self.rpm.setRange(0,25000)
        self.rpm.setValue(1800)
        form.addRow("Паспортний максимум, RPM",self.rpm)
        self.cfm=QSpinBox()
        self.cfm.setRange(0,3000)
        self.cfm.setValue(650)
        self.cfm.setSuffix(" ×0.1 CFM")
        form.addRow("Паспортний потік, 0.1 CFM",self.cfm)
        self.restriction=QSpinBox()
        self.restriction.setRange(1,100)
        self.restriction.setValue(80)
        self.restriction.setSuffix(" %")
        form.addRow("Оціночний коеф. корпусу",self.restriction)
        root.addLayout(form)
        row=QHBoxLayout()
        for label,method in (
            ("Зчитати",self.read_channel),
            ("Зберегти в ESP32",self.save),
            ("Оцінити баланс",self.refresh_balance),
        ):
            b=QPushButton(label)
            b.clicked.connect(method)
            row.addWidget(b)
        root.addLayout(row)
        self.status=QLabel("Не вимірюється в паскалях · оцінка ненадійна без TACH")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.read_channel()

    def _send(self,text):
        if not self.controller.send(text):
            self.status.setText("ESP32 не підключено")
            return False
        return True

    def read_channel(self,*_):
        self._send(f"AIRCFG? {self.channel.currentData()}")

    def save(self):
        direction=self.direction.currentData()
        rpm=self.rpm.value() if direction else 0
        cfm=self.cfm.value() if direction else 0
        try:
            command=aircfg_command(self.channel.currentData(),direction,
                                   rpm,cfm,self.restriction.value())
        except ValueError as exc:
            QMessageBox.warning(self,"Airflow Assistant",str(exc))
            return
        if QMessageBox.question(self,"Оцінка повітряного потоку",
            "Зберегти ручні параметри в NVS ESP32? Цей модуль ніколи "
            "не регулює PWM і не є датчиком тиску.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self._send(command)

    def refresh_balance(self):
        self._send("AIRFLOW?")

    def handle_line(self,line):
        if line.startswith("OK AIRCFG"):
            self.status.setText("ESP32 підтвердив збереження; перечитую канал")
            self.read_channel()
            return True
        if line.startswith("ERR AIRCFG"):
            self.status.setText("Помилка: "+line)
            return True
        channel=parse_fan(line)
        if channel is not None:
            if channel.channel==self.channel.currentData():
                self.direction.setCurrentIndex(self.direction.findData(channel.direction))
                self.rpm.setValue(channel.rated_rpm)
                self.cfm.setValue(channel.cfm10)
                self.restriction.setValue(max(1,channel.restriction))
            return True
        result=parse_airflow(line)
        if result is None: return False
        self.status.setText(
            f"Вдув {result.intake_cfm:.1f} CFM, видув {result.exhaust_cfm:.1f} CFM, "
            f"баланс {result.balance:+d}% — {result.tendency} (лише оцінка)"
            if result.valid else
            f"Недостатньо TACH: {result.unknown} каналів невідомі. "
            "Не можна обчислити достовірну оцінку."
        )
        return True

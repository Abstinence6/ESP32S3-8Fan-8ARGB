"""Opt-in Windows process -> temporary fan profile rules."""
from __future__ import annotations
from pathlib import PureWindowsPath
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QLineEdit, QComboBox, QSpinBox, QPushButton, QCheckBox,
    QFileDialog, QMessageBox)
try:
    from .application_profiles import AppRule, dumps, loads
except ImportError:
    from application_profiles import AppRule, dumps, loads

class ApplicationProfilesDialog(QDialog):
    def __init__(self, settings, changed, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Профілі за застосунками")
        self.setMinimumWidth(510)
        self.settings = settings
        self.changed = changed
        try:
            self.rules = list(loads(str(settings.value("appProfileRulesV1", ""))))
        except ValueError:
            self.rules = []
            QMessageBox.warning(self, "Правила", "Збережені правила некоректні; резервну копію не змінено.")
        box = QVBoxLayout(self)
        self.enabled = QCheckBox("Увімкнути профілі за запущеними програмами")
        self.enabled.setChecked(str(settings.value("appProfilesEnabled", "false")).lower() in ("true","1"))
        box.addWidget(self.enabled)
        box.addWidget(QLabel("Режими застосовуються тимчасово, без запису NVS."))
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._selected)
        box.addWidget(self.items)
        row = QHBoxLayout()
        self.executable = QLineEdit()
        self.executable.setPlaceholderText("application.exe")
        row.addWidget(self.executable)
        browse = QPushButton("Обрати EXE")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        box.addLayout(row)
        row2 = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.addItems(("Silent","Balanced","Performance"))
        row2.addWidget(self.profile)
        self.priority = QSpinBox()
        self.priority.setRange(0,100)
        self.priority.setValue(50)
        self.priority.setPrefix("Пріоритет ")
        row2.addWidget(self.priority)
        box.addLayout(row2)
        row3 = QHBoxLayout()
        for name,fn in (("Додати / оновити",self._upsert),("Видалити",self._remove),
                        ("Зберегти налаштування",self._save)):
            button = QPushButton(name)
            button.clicked.connect(fn)
            row3.addWidget(button)
        box.addLayout(row3)
        self._refresh()

    def _refresh(self,index=-1):
        self.items.blockSignals(True)
        self.items.clear()
        for rule in self.rules:
            self.items.addItem(f"{rule.executable} → {rule.profile} · {rule.priority}")
        self.items.blockSignals(False)
        self.items.setCurrentRow(index)
        self._selected(index)

    def _selected(self,index):
        if not 0 <= index < len(self.rules):
            return
        rule=self.rules[index]
        self.executable.setText(rule.executable)
        self.profile.setCurrentText(rule.profile)
        self.priority.setValue(rule.priority)

    def _browse(self):
        path,_=QFileDialog.getOpenFileName(self,"Оберіть програму", "", "Windows EXE (*.exe)")
        if path:
            self.executable.setText(PureWindowsPath(path).name)

    def _upsert(self):
        rule=AppRule(self.executable.text().strip(),self.profile.currentText(),self.priority.value())
        index=self.items.currentRow()
        candidate=self.rules.copy()
        if 0 <= index < len(candidate):
            candidate[index]=rule
        else:
            candidate.append(rule)
        try:
            clean=loads(dumps(candidate))
        except ValueError as exc:
            QMessageBox.warning(self,"Правила",str(exc))
            return
        self.rules=list(clean)
        self._refresh(index if index>=0 else len(self.rules)-1)

    def _remove(self):
        index=self.items.currentRow()
        if 0 <= index < len(self.rules):
            self.rules.pop(index)
            self._refresh()

    def _save(self):
        try:
            payload=dumps(self.rules)
        except ValueError as exc:
            QMessageBox.warning(self,"Правила",str(exc))
            return
        self.settings.setValue("appProfileRulesV1",payload)
        self.settings.setValue("appProfilesEnabled",self.enabled.isChecked())
        self.changed()
        self.accept()

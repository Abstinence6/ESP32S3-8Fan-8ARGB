"""Small GUI for named fan groups; actual outputs remain ESP safety-gated."""
from __future__ import annotations
try:
    from .fan_groups import FanGroup, command, dumps, loads, validate
except ImportError:
    from fan_groups import FanGroup, command, dumps, loads, validate
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QLineEdit, QCheckBox, QPushButton, QLabel, QMessageBox, QInputDialog)

class FanGroupsDialog(QDialog):
    def __init__(self, settings, send, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Групи вентиляторів")
        self.setMinimumWidth(460)
        self.settings = settings
        self.send = send
        try:
            self.groups = list(loads(str(settings.value("fanGroupsV1", ""))))
        except ValueError:
            self.groups = []
            QMessageBox.warning(self, "Групи", "Помилкова конфігурація груп; її не перезаписано.")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Кожен вентилятор може бути лише в одній групі."))
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self._selected)
        layout.addWidget(self.items)
        self.name = QLineEdit()
        self.name.setMaxLength(48)
        self.name.setPlaceholderText("Назва групи")
        layout.addWidget(self.name)
        check_row = QHBoxLayout()
        self.boxes = []
        for ch in range(1, 9):
            box = QCheckBox(str(ch))
            self.boxes.append(box)
            check_row.addWidget(box)
        layout.addLayout(check_row)
        edit = QHBoxLayout()
        for title, callback in (("Зберегти групу", self._save), ("Видалити", self._delete)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            edit.addWidget(button)
        layout.addLayout(edit)
        control = QHBoxLayout()
        for title, callback in (("→ Авто", self._auto), ("PWM вручну…", self._manual)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            control.addWidget(button)
        layout.addLayout(control)
        self._refresh()

    def _refresh(self, index: int = -1):
        self.items.blockSignals(True)
        self.items.clear()
        for group in self.groups:
            self.items.addItem(group.name + " · FAN " + ", ".join(map(str, group.channels)))
        self.items.blockSignals(False)
        self.items.setCurrentRow(index)
        self._selected(index)

    def _selected(self, index: int):
        group = self.groups[index] if 0 <= index < len(self.groups) else None
        self.name.setText(group.name if group else "")
        for ch, box in enumerate(self.boxes, 1):
            box.setChecked(group is not None and ch in group.channels)

    def _save(self):
        index = self.items.currentRow()
        group = FanGroup(self.name.text(), tuple(ch for ch, box in enumerate(self.boxes, 1) if box.isChecked()))
        candidate = self.groups.copy()
        if 0 <= index < len(candidate):
            candidate[index] = group
        else:
            candidate.append(group)
        try:
            payload = dumps(candidate)
            clean = list(validate(candidate))
        except ValueError as exc:
            QMessageBox.warning(self, "Групи", str(exc))
            return
        self.settings.setValue("fanGroupsV1", payload)
        self.groups = clean
        self._refresh(len(clean) - 1 if index < 0 else index)

    def _delete(self):
        index = self.items.currentRow()
        if not 0 <= index < len(self.groups):
            return
        candidate = self.groups.copy()
        candidate.pop(index)
        self.settings.setValue("fanGroupsV1", dumps(candidate))
        self.groups = candidate
        self._refresh()

    def _chosen(self):
        index = self.items.currentRow()
        if not 0 <= index < len(self.groups):
            QMessageBox.warning(self, "Групи", "Вибери збережену групу.")
            return None
        return self.groups[index]

    def _send(self, group, action, duty=None):
        if not self.send(command(group, action, duty)):
            QMessageBox.warning(self, "Групи", "COM-порт недоступний. Команду не підтверджено.")

    def _auto(self):
        group = self._chosen()
        if group is not None:
            self._send(group, "auto")

    def _manual(self):
        group = self._chosen()
        if group is None:
            return
        value, ok = QInputDialog.getInt(self, "Груповий PWM", "PWM, %:", 100, 0, 100)
        if ok:
            self._send(group, "manual", value)

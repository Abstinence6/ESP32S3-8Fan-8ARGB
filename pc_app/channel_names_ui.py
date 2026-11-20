"""Local display names for fixed, numbered FAN and ARGB slots."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout,
)


MAX_CHANNEL_NAME = 32
SLOTS = tuple((kind, ch) for kind in ("FAN", "ARGB") for ch in range(1, 9))


def _key(kind: str, channel: int) -> str:
    return f"channelNames/{kind}/{channel}"


def _clean(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.splitlines()).strip()[:MAX_CHANNEL_NAME].rstrip()


def plain_tooltip(text: str) -> str:
    escaped = escape(text).replace("\n", "<br>")
    return f"<span>{escaped}</span>"


class ChannelNames:
    def __init__(self, settings: QSettings) -> None:
        self.settings = settings
        self.names = {slot: _clean(settings.value(_key(*slot), "")) for slot in SLOTS}

    def title(self, kind: str, channel: int) -> str:
        number = f"{kind} {channel:02d}"
        name = self.names[kind, channel]
        return f"{number} · {name}" if name else number

    def edit(self, parent) -> bool:
        dialog = QDialog(parent)
        dialog.setWindowTitle("Назви каналів")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Назви зберігаються лише на цьому ПК. Номери каналів не змінюються."))
        layout.addWidget(QLabel("Залиш поле порожнім, щоб повернути стандартний підпис."))
        grid = QGridLayout()
        layout.addLayout(grid)
        fields = {}
        for kind, channel in SLOTS:
            column = 0 if kind == "FAN" else 2
            label = QLabel(f"{kind} {channel:02d}")
            field = QLineEdit()
            field.setObjectName(f"channelName{kind}{channel}")
            field.setAccessibleName(label.text())
            field.setMaxLength(MAX_CHANNEL_NAME)
            field.setText(self.names[kind, channel])
            label.setBuddy(field)
            grid.addWidget(label, channel - 1, column)
            grid.addWidget(field, channel - 1, column + 1)
            fields[kind, channel] = field
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        changed = False
        if accepted:
            for slot, field in fields.items():
                name = _clean(field.text())
                if name == self.names[slot]:
                    continue
                self.names[slot] = name
                if name:
                    self.settings.setValue(_key(*slot), name)
                else:
                    self.settings.remove(_key(*slot))
                changed = True
            if changed:
                self.settings.sync()
        dialog.deleteLater()
        return changed


class ChannelTitle(QLabel):
    """Elide long display names without widening a grid or losing the full name."""

    def __init__(self, role: str = "labelTitle", *, number: str = "") -> None:
        super().__init__()
        self._number = number
        self.setProperty("role", role)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_title(self, title: str) -> None:
        if title == self.accessibleName():
            return
        self.setAccessibleName(title)
        self.setToolTip(plain_tooltip(title))
        self._elide()

    def _elide(self) -> None:
        metrics = self.fontMetrics()
        if self._number:
            self.setMinimumWidth(metrics.horizontalAdvance(self._number) + 1)
        text = metrics.elidedText(
            self.accessibleName(), Qt.TextElideMode.ElideRight, self.contentsRect().width()
        )
        self.setText(text if text.startswith(self._number) else self._number)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._elide()

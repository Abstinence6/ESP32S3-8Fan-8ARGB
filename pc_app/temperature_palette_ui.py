"""Editor for controller-persisted temperature palettes."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

try:
    from .temperature_palette import Palette, validate_palette
except ImportError:
    from temperature_palette import Palette, validate_palette


class TemperaturePaletteDialog(QDialog):
    def __init__(self, channel: int, points: Palette, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"ARGB {channel} · палітра за температурою")
        self.resize(560, 465)
        root = QVBoxLayout(self)
        hint = QLabel("Вкажи від 4 до 8 точок: температура °C і колір RGB. "
                      "Між точками колір плавно інтерполюється. "
                      "Зміни зберігаються тільки в NVS ESP32 після підтвердження.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.grid = QGridLayout()
        for c, name in enumerate(("Температура, °C", "R", "G", "B")):
            self.grid.addWidget(QLabel(name), 0, c)
        self.rows: list[tuple[QSpinBox, QSpinBox, QSpinBox, QSpinBox]] = []
        for p in points:
            self._add_row(p)
        root.addLayout(self.grid)
        tools = QHBoxLayout()
        add = QPushButton("Додати точку")
        add.clicked.connect(self.add_row)
        tools.addWidget(add)
        remove = QPushButton("Прибрати останню")
        remove.clicked.connect(self.remove_row)
        tools.addWidget(remove)
        root.addLayout(tools)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.points = validate_palette(points)

    def _add_row(self, values: tuple[int, int, int, int]) -> None:
        row = len(self.rows) + 1
        widgets = []
        for i, value in enumerate(values):
            box = QSpinBox()
            box.setRange(0, 125 if i == 0 else 255)
            box.setValue(value)
            self.grid.addWidget(box, row, i)
            widgets.append(box)
        self.rows.append(tuple(widgets))

    def add_row(self) -> None:
        if len(self.rows) >= 8:
            return
        last = self.rows[-1]
        temp = min(125, last[0].value() + 5)
        self._add_row((temp, 255, 0, 0))

    def remove_row(self) -> None:
        if len(self.rows) <= 4:
            return
        for widget in self.rows.pop():
            self.grid.removeWidget(widget)
            widget.deleteLater()

    def accept(self) -> None:
        try:
            points = tuple(tuple(w.value() for w in row) for row in self.rows)
            self.points = validate_palette(points)
        except ValueError as exc:
            QMessageBox.warning(self, "Некоректна палітра", str(exc))
            return
        super().accept()

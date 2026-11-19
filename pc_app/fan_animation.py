"""Small animated fan view, driven only by fresh RPM measurements."""
from __future__ import annotations
import math
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget

class FanRotor(QWidget):
    """Symbolic (slowed down) rotation proportional to measured RPM."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rpm = 0
        self.angle = 0.0
        self.setFixedSize(44, 44)
        self.setAccessibleName("Анімований індикатор RPM")
        self.setToolTip("Обертання пропорційне TACH RPM, але сповільнене для сприйняття.")

    def set_rpm(self, value):
        self.rpm = value if type(value) is int and 0 < value <= 30000 else 0
        self.setAccessibleDescription(
            f"{self.rpm} обертів/хв" if self.rpm else "Немає достовірного RPM"
        )
        self.update()

    def advance(self, seconds):
        if not self.rpm or not math.isfinite(seconds) or seconds <= 0:
            return
        turns_per_second = min(5.0, self.rpm / 500.0)
        self.angle = (self.angle + 360.0 * turns_per_second * min(seconds, .12)) % 360.0
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        scale = min(self.width(), self.height()) / 48.0
        painter.scale(scale, scale)
        palette = self.palette()
        border = palette.color(QPalette.ColorRole.Mid)
        blades = palette.color(
            QPalette.ColorRole.Highlight if self.rpm else QPalette.ColorRole.Mid
        )
        painter.setPen(QPen(border, 1.7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 21, 21)
        painter.save()
        painter.rotate(self.angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(blades)
        for index in range(5):
            painter.save()
            painter.rotate(index * 72)
            shape = QPainterPath()
            shape.moveTo(1, -2)
            shape.cubicTo(15, -2, 19, -17, 8, -18)
            shape.cubicTo(-3, -18, -4, -9, 1, -2)
            painter.drawPath(shape)
            painter.restore()
        painter.restore()
        painter.setPen(QPen(border, 1.3))
        painter.setBrush(palette.color(QPalette.ColorRole.Window))
        painter.drawEllipse(QPointF(0, 0), 4, 4)
        painter.end()

"""Small fan view with RPM-driven rotation and optional ARGB blade colors."""
from __future__ import annotations
import math
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget

_RPM_TOOLTIP = "Обертання пропорційне TACH RPM, але сповільнене для сприйняття."
_BLADE_COUNT = 5
_COLOR_CYCLE_FRAMES = 32

class FanRotor(QWidget):
    """Symbolic (slowed down) rotation proportional to measured RPM."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rpm = 0
        self.angle = 0.0
        self._strip_colors: tuple[QColor, ...] = ()
        self._strip_animated = False
        self._strip_frame = 0
        self._strip_timer = QTimer(self)
        self._strip_timer.setInterval(50)
        self._strip_timer.timeout.connect(self._advance_strip)
        self.setFixedSize(44, 44)
        self.setAccessibleName("Анімований індикатор RPM")
        self.setToolTip(_RPM_TOOLTIP)

    def set_strip_preview(self, colors, *, animated: bool = False) -> None:
        """Color the blades from QColor inputs or RGB(A) byte tuples/lists.

        Empty input (or None) clears the preview. It does not reflect measured
        lighting or affect RPM. Callers clear it when preview data is unavailable.
        """
        valid = []
        for value in () if colors is None else colors:
            if value is None:
                continue
            try:
                if isinstance(value, (tuple, list)):
                    if len(value) not in (3, 4) or not all(
                        type(component) is int and 0 <= component <= 255 for component in value
                    ):
                        continue
                    color = QColor(*value)
                else:
                    color = QColor(value)
            except (TypeError, OverflowError):
                continue
            if color.isValid():
                valid.append(color)
        preview = tuple(valid)
        animated = animated and any(color != preview[0] for color in preview[1:])
        if preview == self._strip_colors and animated == self._strip_animated:
            return
        self._strip_colors = preview
        self._strip_animated = animated
        if not animated:
            self._strip_frame = 0
        self._watch_preview_visibility()
        self.setToolTip(
            _RPM_TOOLTIP + "\nКольори лопатей: попередній перегляд ARGB, не телеметрія."
            if preview else _RPM_TOOLTIP
        )
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._watch_preview_visibility()

    def hideEvent(self, event):
        self.window().removeEventFilter(self)
        self._strip_timer.stop()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_strip_timer()
        return super().eventFilter(watched, event)

    def _watch_preview_visibility(self):
        if self.isVisible() and self._strip_animated:
            self.window().installEventFilter(self)
        else:
            self.window().removeEventFilter(self)
        self._sync_strip_timer()

    def _sync_strip_timer(self):
        if self._strip_animated and self.isVisible() and not self.window().isMinimized():
            if not self._strip_timer.isActive():
                self._strip_timer.start()
        else:
            self._strip_timer.stop()

    def _advance_strip(self):
        self._strip_frame = (self._strip_frame + 1) % _COLOR_CYCLE_FRAMES
        self.update()

    def _preview_color(self, blade: int) -> QColor:
        colors = self._strip_colors
        phase = blade / _BLADE_COUNT + self._strip_frame / _COLOR_CYCLE_FRAMES
        position = phase * len(colors)
        index = int(position)
        color = colors[index % len(colors)]
        if not self._strip_animated:
            return color
        next_color = colors[(index + 1) % len(colors)]
        fraction = position - index
        return QColor(*(round(a + (b - a) * fraction)
                        for a, b in zip(color.getRgb(), next_color.getRgb())))

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
        for index in range(_BLADE_COUNT):
            painter.save()
            painter.rotate(index * 360 / _BLADE_COUNT)
            painter.setBrush(self._preview_color(index) if self._strip_colors else blades)
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

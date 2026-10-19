"""Lightweight animated processing indicator; no external image assets."""

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .theme import theme_color


class BusyIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setAccessibleName("正在處理")
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self._advance)
        self.hide()

    def set_running(self, running):
        self.setVisible(running)
        if running:
            self.timer.start()
        else:
            self.timer.stop()

    def _advance(self):
        self.phase = (self.phase + 1) % 12
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(11, 11)
        for index in range(12):
            color = QColor(theme_color("#2b4098"))
            color.setAlpha(35 + ((index - self.phase) % 12) * 20)
            painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            angle = index * math.pi / 6
            painter.drawLine(
                round(math.cos(angle) * 6),
                round(math.sin(angle) * 6),
                round(math.cos(angle) * 9),
                round(math.sin(angle) * 9),
            )

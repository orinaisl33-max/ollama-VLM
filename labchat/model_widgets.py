"""Capability colors for the model picker, evaluated against the active theme."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QStyledItemDelegate

from .config import find_model
from .theme import theme_color


class ModelCapabilityDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        model = find_model(index.data(Qt.ItemDataRole.UserRole))
        if model is not None and not model.vision:
            color = QColor(theme_color("#8c3c16"))
            option.palette.setColor(QPalette.ColorRole.Text, color)
            option.palette.setColor(QPalette.ColorRole.HighlightedText, color)

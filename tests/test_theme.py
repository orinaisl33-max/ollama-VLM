"""Shared light theme must override OS dark colors for new dialogs."""

import unittest

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from labchat.speech_widgets import SpeechPanel
from labchat.theme import apply_theme

APP = QApplication.instance() or QApplication([])


class ThemeTests(unittest.TestCase):
    def test_new_dialogs_inherit_complete_light_palette(self):
        original = APP.palette()
        dark = QPalette(original)
        dark.setColor(QPalette.ColorRole.Window, QColor("#333333"))
        APP.setPalette(dark)
        root = QWidget()
        panel = None
        dialog = None
        try:
            apply_theme(root)
            panel = SpeechPanel(root, auto_discover=False)
            dialog = QDialog()
            panel.dialog.ensurePolished()
            dialog.ensurePolished()
            for item in (panel.dialog, dialog):
                self.assertEqual(item.palette().color(QPalette.ColorRole.Window).name(), "#f4f7f8")
                self.assertEqual(
                    item.palette().color(QPalette.ColorRole.WindowText).name(), "#182b36"
                )
            self.assertGreaterEqual(panel.dialog.minimumWidth(), 480)
        finally:
            if panel:
                panel.shutdown()
            if dialog:
                dialog.deleteLater()
            root.deleteLater()
            APP.setPalette(original)

    def test_dark_dialogs_and_local_styles_do_not_reset_appearance(self):
        from labchat.reader import AnswerReader
        from labchat.theme import current_theme, local_style

        root = QWidget()
        reader = None
        try:
            apply_theme(root, "dark")
            local_style(root, "QWidget { background:white; color:#182b36; }")
            reader = AnswerReader("**可讀的文字**\n\n- 清單項目")
            self.assertEqual(current_theme(), "dark")
            self.assertIn("#1d2735", root.styleSheet())
            selected = reader.preview.document().find("可讀的文字")
            self.assertEqual(selected.charFormat().foreground().color().name(), "#e6edf5")
            marker = reader.preview.document().find("清單項目").block().charFormat()
            self.assertEqual(marker.foreground().color().name(), "#e6edf5")
            apply_theme(root, "light")
            self.assertIn("background:white", root.styleSheet())
            self.assertEqual(selected.charFormat().foreground().color().name(), "#182b36")
        finally:
            apply_theme(root, "light")
            if reader:
                reader.deleteLater()
            root.deleteLater()

    def test_primary_text_contrast_in_both_modes(self):
        from labchat.theme import DARK_COLORS

        def luminance(color):
            rgb = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in rgb
            ]
            return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

        for text, background in [
            ("#182b36", "#ffffff"),
            ("#2b4098", "#edf3ff"),
            (DARK_COLORS["#182b36"], DARK_COLORS["#ffffff"]),
            (DARK_COLORS["#2b4098"], DARK_COLORS["#edf3ff"]),
            (DARK_COLORS["#647781"], DARK_COLORS["#f4f7f8"]),
        ]:
            light, dark = sorted((luminance(text), luminance(background)), reverse=True)
            self.assertGreaterEqual((light + 0.05) / (dark + 0.05), 4.5)

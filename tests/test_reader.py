import unittest

from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from labchat.reader import AnswerReader

APP = QApplication.instance() or QApplication([])


class ReaderTests(unittest.TestCase):
    def test_markdown_tables_and_code_copy_without_external_resources(self):
        dialog = AnswerReader(
            "# 標題\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('hello')\n```\n\n![x](file:///etc/passwd)\n<script>alert(1)</script>"
        )
        try:
            self.assertIn("<table", dialog.preview.document().toHtml())
            self.assertFalse(dialog.preview.openLinks())
            self.assertFalse(dialog.preview.openExternalLinks())
            resource = dialog.preview.document().resource(
                QTextDocument.ResourceType.ImageResource, QUrl("file:///etc/passwd")
            )
            self.assertFalse(resource)
            dialog.copy_selected_code()
            self.assertEqual(APP.clipboard().text(), "print('hello')")
        finally:
            dialog.deleteLater()

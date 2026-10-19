"""Attachment names identify current requests without exposing the selected directory."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class ImageNameTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        self.w = Window(history_path=Path(temp.name) / "history.sqlite3")
        self.addCleanup(self.w.deleteLater)
        self.addCleanup(self.w.close)

    def attach(self):
        with (
            patch(
                "labchat.window.QFileDialog.getOpenFileName",
                return_value=("/private/photos/測試 <圖片>&.jpg", ""),
            ),
            patch("labchat.window.prepare_image", return_value="encoded-image"),
        ):
            self.w.choose_image()

    def test_filename_visible_as_literal_text_and_not_sent_to_model(self):
        self.attach()
        self.w.input.setPlainText("您看到什麼")
        with patch.object(self.w.client, "start") as start:
            self.w.submit()
        text = self.w.chat.toPlainText()
        self.assertIn("已附加圖片（測試 <圖片>&.jpg）", text)
        self.assertNotIn("/private/photos", text)
        messages = start.call_args.args[1]
        self.assertNotIn("測試 <圖片>&.jpg", str(messages))

    def test_removal_and_reuse_preserve_correct_filename(self):
        self.attach()
        self.w.remove_image()
        self.assertEqual(self.w.image_filename, "")
        self.w.reuse_picture()
        self.assertEqual(self.w.image_filename, "測試 <圖片>&.jpg")

    def test_text_message_does_not_show_previous_filename(self):
        self.attach()
        self.w.remove_image()
        self.w.input.setPlainText("純文字")
        with patch.object(self.w.client, "start"):
            self.w.submit()
        self.assertNotIn("已附加圖片", self.w.chat.toPlainText())

    def test_saved_picture_without_original_filename_clears_previous_name(self):
        self.attach()
        with patch.object(self.w.store, "load_picture", return_value=("saved", [])):
            self.assertTrue(self.w._load_saved_picture(1))
        self.w.reuse_picture()
        self.assertEqual(self.w.image_filename, "")

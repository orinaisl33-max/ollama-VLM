"""Answer menu actions must expose availability and preserve attachments on failure."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from test_attachments import png_data

from labchat.conversations import HistoryError
from labchat.grounding import Box
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class AnswerActionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        self.w = Window(history_path=Path(temp.name) / "history.sqlite3")
        self.addCleanup(self.w.deleteLater)
        self.addCleanup(self.w.close)

    def action(self, button):
        return next(a for a, b in self.w.answer_menu_items if b is button)

    def test_text_conversation_does_not_enable_empty_picture_history(self):
        w = self.w
        w.conversation_id = w.store.append(None, "qwen3.5:2b", "問題", "回答")
        w.busy(False)
        w._sync_answer_menu()
        action = self.action(w.picture_button)
        self.assertFalse(action.isEnabled())
        self.assertIn("尚無", action.text())
        w.open_saved_picture()
        self.assertIn("後續", w.status.text())

    def test_saved_image_action_opens_actual_picture_and_annotation(self):
        w = self.w
        data = png_data()
        w.store.set_pictures(True)
        w.conversation_id = w.store.append(None, "qwen3.5:2b", "看圖", "回答", True, image=data)
        w._sync_answer_menu()
        action = self.action(w.picture_button)
        self.assertTrue(action.isEnabled())
        self.assertIn("1 張", action.text())
        with patch(
            "labchat.window.QInputDialog.getItem", side_effect=lambda *args: (args[3][0], True)
        ):
            action.trigger()
        self.assertEqual(w.last_image, data)
        self.assertIsNotNone(w.annotation_dialog)

    def test_failed_saved_picture_load_keeps_current_attachment_and_boxes(self):
        w = self.w
        w.conversation_id = w.store.append(None, "qwen3.5:2b", "問題", "回答")
        w.image = w.last_image = "original-png"
        boxes = [Box("原框", (10, 20, 300, 400), "manual")]
        w.annotation_boxes = list(boxes)
        with (
            patch.object(w.store, "pictures", return_value=[{"sequence": 1, "prompt": "已存"}]),
            patch.object(w.store, "load_picture", side_effect=HistoryError("讀取失敗")),
            patch(
                "labchat.window.QInputDialog.getItem", side_effect=lambda *args: (args[3][0], True)
            ),
            patch(
                "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
            ),
        ):
            w.open_saved_picture()
        self.assertEqual(w.image, "original-png")
        self.assertEqual(w.last_image, "original-png")
        self.assertEqual(w.annotation_boxes, boxes)
        self.assertIn("讀取失敗", w.status.text())

    def test_reuse_action_attaches_without_sending_or_replacing_draft(self):
        w = self.w
        data = png_data()
        w.last_image = data
        w.input.setPlainText("原有草稿")
        w._sync_answer_menu()
        action = self.action(w.reuse_button)
        self.assertTrue(action.isEnabled())
        with patch.object(w.client, "start") as start, patch.object(w.input, "setFocus") as focus:
            action.trigger()
            start.assert_not_called()
            focus.assert_called_once()
        self.assertEqual(w.image, data)
        self.assertEqual(w.input.toPlainText(), "原有草稿")
        self.assertIn("尚未發送", w.status.text())
        self.assertIn("不會自動", w.image_label.toolTip())

    def test_missing_image_text_only_model_and_recording_show_unavailable(self):
        w = self.w
        w._sync_answer_menu()
        self.assertFalse(self.action(w.reuse_button).isEnabled())
        self.assertIn("尚無", self.action(w.reuse_button).text())
        w.last_image = png_data()
        w.model.setCurrentIndex(w.model.findData("deepseek-r1:1.5b"))
        w.last_image = png_data()
        w._sync_answer_menu()
        self.assertFalse(self.action(w.reuse_button).isEnabled())
        self.assertIn("圖文模型", self.action(w.reuse_button).text())
        w.model.setCurrentIndex(w.model.findData("qwen3.5:2b"))
        w.last_image = png_data()
        w.dictation.state = "recording"
        w._sync_answer_menu()
        self.assertFalse(self.action(w.reuse_button).isEnabled())
        w.reuse_picture()
        self.assertIsNone(w.image)
        w.dictation.state = "idle"

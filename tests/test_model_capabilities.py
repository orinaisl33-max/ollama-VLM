"""Model capability guards prevent sending images to text-only backends."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from test_annotation import image_data

from labchat.annotation import AnnotationDialog
from labchat.client import ChatClient
from labchat.config import MODELS, TEXT_SYSTEM_PROMPT, build_messages, find_model
from labchat.conversations import ConversationStore
from labchat.window import Window

APP = QApplication.instance() or QApplication([])
TEXT = "deepseek-r1:1.5b"


class ModelCapabilityTests(unittest.TestCase):
    def test_text_prompt_and_image_rejection(self):
        for model in MODELS:
            if model.vision:
                self.assertIn(
                    "images", build_messages([], "看圖", "data", model=model.identifier)[-1]
                )
            else:
                self.assertIn(
                    TEXT_SYSTEM_PROMPT,
                    build_messages([], "問題", None, model=model.identifier)[0]["content"],
                )
                with self.assertRaises(ValueError):
                    build_messages([], "看圖", "data", model=model.identifier)
        self.assertFalse(find_model(TEXT).vision)
        self.assertIsNone(find_model("unknown"))

    def test_new_models_can_be_restored_from_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.db"
            store = ConversationStore(path)
            try:
                for model in MODELS:
                    store.save_preferences({"model": model.identifier})
                    self.assertEqual(store.get_preferences()["model"], model.identifier)
            finally:
                store.close()

    def test_client_rejects_images_before_network(self):
        client = ChatClient()
        try:
            with patch.object(client.network, "post") as post, self.assertRaises(ValueError):
                client.start(TEXT, [{"role": "user", "content": "看圖", "images": ["data"]}])
            post.assert_not_called()
            self.assertFalse(client.active)
            self.assertFalse(client.total_timer.isActive())
        finally:
            client.shutdown()
            client.deleteLater()

    def test_window_capability_controls_and_submit_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Window(history_path=Path(directory) / "test.sqlite3")
            try:
                w.model.setCurrentIndex(w.model.findData(TEXT))
                self.assertFalse(w.attach.isEnabled())
                w.busy(True)
                w.busy(False)
                self.assertFalse(w.attach.isEnabled())
                with patch("labchat.window.QFileDialog.getOpenFileName") as picker:
                    w.choose_image()
                    picker.assert_not_called()
                w.input.setPlainText("保留文字")
                w.use_suggestion("請分析我附加的圖片，說明物件。")
                self.assertEqual(w.input.toPlainText(), "保留文字")
                w.image = image_data()
                with patch.object(w.client, "start") as start:
                    w.submit()
                    start.assert_not_called()
                self.assertEqual(w.input.toPlainText(), "保留文字")
                self.assertIsNotNone(w.image)
                w.image = None
                w.model.setCurrentIndex(0)
                self.assertTrue(w.attach.isEnabled())
            finally:
                w.shutdown()
                w.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_text_model_annotation_disables_only_ai(self):
        dialog = AnnotationDialog(image_data(), TEXT)
        try:
            self.assertFalse(dialog.auto_button.isEnabled())
            with patch.object(dialog.client, "start") as start:
                dialog.automatic()
                start.assert_not_called()
            self.assertIn("圖片", dialog.status.text())
        finally:
            dialog.reject()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_ultralight_vision_retains_manual_export_without_ai_grounding(self):
        model = next(m for m in MODELS if m.vision and not m.grounding)
        dialog = AnnotationDialog(image_data(), model.identifier)
        try:
            self.assertFalse(dialog.auto_button.isEnabled())
            self.assertTrue(dialog.export_json.isEnabled())
            self.assertTrue(dialog.export_png.isEnabled())
            self.assertTrue(dialog.canvas.isEnabled())
            with patch.object(dialog.client, "start") as start:
                dialog.automatic()
                start.assert_not_called()
        finally:
            dialog.reject()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

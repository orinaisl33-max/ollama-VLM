import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from labchat.attachments import image_bytes, validate_boxes
from labchat.conversations import ConversationStore, HistoryError
from labchat.grounding import Box


def png_data():
    image = QImage(32, 16, QImage.Format.Format_RGB32)
    image.fill(0xFF123456)
    data = QByteArray()
    output = QBuffer(data)
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(output, "PNG")
    return base64.b64encode(bytes(data)).decode()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "history.sqlite3"
        self.store = ConversationStore(self.path)
        self.addCleanup(self.store.close)

    def test_png_boxes_restart_and_cascade_delete(self):
        encoded = png_data()
        boxes = [Box("人工框", (0, 0, 500, 500), "manual")]
        identifier = self.store.append(
            None, "qwen3.5:2b", "圖？", "水果。", True, image=encoded, boxes=boxes
        )
        sequence = self.store.last_sequence
        self.assertEqual(self.store.load_picture(identifier, sequence), (encoded, boxes))
        self.store.close()
        self.store = ConversationStore(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.pictures(identifier)), 1)
        updated = [Box("新名稱", (20, 20, 600, 600), "manual")]
        self.store.save_boxes(identifier, sequence, updated)
        self.assertEqual(self.store.load_picture(identifier, sequence)[1], updated)
        self.store.delete(identifier)
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0], 0
        )

    def test_image_cap_rolls_back_text_and_attachment_as_one_unit(self):
        with patch("labchat.attachments.MAX_ATTACHMENT_BYTES", 1):
            with self.assertRaises(HistoryError):
                self.store.append(None, "qwen3.5:2b", "問", "答", True, image=png_data())
        self.assertEqual(self.store.list(), [])
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 0
        )

    def test_invalid_images_and_annotations_rejected(self):
        for encoded in ("not-base64", base64.b64encode(b"bad").decode()):
            with self.assertRaises(ValueError):
                image_bytes(encoded)
        with self.assertRaises(ValueError):
            validate_boxes([{"label": "x", "bbox": [True, 0, 10, 10], "source": "manual"}])
        with self.assertRaises(ValueError):
            validate_boxes([{"label": "x", "bbox": [0, 0, 10, 10], "source": "file:///x"}])

    def test_pictures_default_off_and_settings_survive_restart(self):
        self.assertFalse(self.store.pictures_enabled())
        self.store.set_pictures(True)
        self.store.set_saving(False)
        self.assertTrue(self.store.pictures_enabled())
        self.assertFalse(self.store.saving_enabled())

    def test_attachment_update_cannot_cross_conversation_boundary(self):
        identifier = self.store.append(None, "qwen3.5:2b", "圖", "答", True, image=png_data())
        sequence = self.store.last_sequence
        other = self.store.append(None, "qwen3.5:2b", "另一題", "答")
        with self.assertRaises(HistoryError):
            self.store.save_boxes(other, sequence, [])
        with self.assertRaises(HistoryError):
            self.store.load_picture(other, sequence)
        self.assertEqual(len(self.store.pictures(identifier)), 1)

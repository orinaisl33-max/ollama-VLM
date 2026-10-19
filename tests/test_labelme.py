"""Labelme export uses rectangles in pixel coordinates on the embedded source PNG."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from labchat.annotation import AnnotationDialog
from labchat.grounding import Box
from labchat.labelme_export import labelme_document

APP = QApplication.instance() or QApplication([])


def source_png():
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    data = QByteArray()
    output = QBuffer(data)
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(output, "PNG")
    return base64.b64encode(bytes(data)).decode()


class LabelmeTests(unittest.TestCase):
    def test_pixels_schema_and_embedded_clean_image(self):
        encoded = source_png()
        boxes = [
            Box("輪椅", (100, 200, 800, 700), "model"),
            Box("人工確認", (0, 0, 1000, 1000), "manual"),
        ]
        document = labelme_document(encoded, boxes, "範例.png")
        self.assertEqual(document["imageWidth"], 400)
        self.assertEqual(document["imageHeight"], 200)
        self.assertEqual(document["imagePath"], "範例.png")
        self.assertEqual(document["imageData"], encoded)
        self.assertEqual(document["shapes"][0]["points"], [[40.0, 40.0], [320.0, 140.0]])
        self.assertEqual(document["shapes"][1]["points"], [[0.0, 0.0], [400.0, 200.0]])
        for index, shape in enumerate(document["shapes"]):
            self.assertEqual(shape["shape_type"], "rectangle")
            self.assertIsNone(shape["group_id"])
            self.assertIsNone(shape["mask"])
            self.assertEqual(shape["flags"]["ai_suggested"], index == 0)
        image = QImage.fromData(base64.b64decode(document["imageData"]), "PNG")
        self.assertEqual(image.pixelColor(40, 40), QColor("white"))
        json.dumps(document, allow_nan=False)

    def test_empty_annotations_are_valid_and_invalid_paths_or_boxes_rejected(self):
        self.assertEqual(labelme_document(source_png(), [])["shapes"], [])
        for path in ("../x.png", "C:\\private\\x.png", "/private/x.png", "x.jpg"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                labelme_document(source_png(), [], path)
        with self.assertRaises(ValueError):
            labelme_document(source_png(), [Box("錯誤", (0, 0, 1001, 200))])

    def test_labelme_export_button_writes_portable_json_and_preserves_on_failure(self):
        dialog = AnnotationDialog(source_png(), "qwen3.5:2b")
        try:
            dialog.canvas.boxes = [Box("矩形", (100, 100, 500, 500), "manual")]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "labelme.json"
                with patch(
                    "labchat.annotation.QFileDialog.getSaveFileName",
                    return_value=(str(path), "JSON"),
                ):
                    dialog._export_labelme()
                payload = json.loads(path.read_text())
                self.assertEqual(payload["imagePath"], "labelme.png")
                before = path.read_bytes()
                with (
                    patch(
                        "labchat.annotation.QFileDialog.getSaveFileName",
                        return_value=(str(path), "JSON"),
                    ),
                    patch("labchat.annotation.QSaveFile.commit", return_value=False),
                    patch("labchat.annotation.QMessageBox.warning") as warning,
                ):
                    dialog._export_labelme()
                self.assertTrue(warning.called)
                self.assertEqual(path.read_bytes(), before)
        finally:
            dialog.reject()
            dialog.deleteLater()

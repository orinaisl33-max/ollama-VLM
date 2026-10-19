"""Grounding is approximate; test validation, coordinate mapping, edits and exports."""

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from labchat.annotation import AnnotationDialog
from labchat.client import ChatResult
from labchat.grounding import Box, grounding_messages, grounding_schema, parse_boxes, preview_boxes
from labchat.indicators import BusyIndicator
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


def image_data():
    image = QImage(400, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return base64.b64encode(bytes(data)).decode()


class GroundingTests(unittest.TestCase):
    def test_scope_has_only_current_image_and_bound_not_required_count(self):
        messages = grounding_messages("current-image", "人物", 2)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(messages[1]["images"], ["current-image"])
        self.assertIn("人物", messages[1]["content"])
        self.assertIn("最多 2", messages[1]["content"])
        self.assertEqual(grounding_schema(2)["properties"]["objects"]["maxItems"], 2)
        self.assertEqual(grounding_schema()["properties"]["objects"]["maxItems"], 10)

    def test_stream_only_accepts_complete_entries_at_every_split(self):
        first = '{"label":"杯子\\"一","bbox":[10,20,300,400]}'
        second = '{"label":"水果","bbox":[500,20,800,400]}'
        prefix = '{"objects":['
        text = prefix + first + "," + second + "]}"
        for position in range(len(text) + 1):
            expected = int(position >= len(prefix + first)) + int(
                position >= len(prefix + first + "," + second)
            )
            self.assertEqual(len(preview_boxes(text[:position])), expected, position)
        self.assertEqual(len(preview_boxes(text, 1)), 1)
        self.assertEqual(preview_boxes("解說不是JSON"), [])

    def test_stream_rejects_invalid_complete_coordinates(self):
        with self.assertRaises(ValueError):
            preview_boxes('{"objects":[{"label":"錯誤","bbox":[0,0,1001,20]}')

    def test_near_identical_same_label_is_suppressed_but_distinct_objects_remain(self):
        rows = [
            {"label": "枕頭", "bbox": [100, 100, 400, 400]},
            {"label": "枕頭", "bbox": [102, 102, 402, 402]},
            {"label": "枕頭", "bbox": [500, 100, 800, 400]},
            {"label": "床", "bbox": [100, 100, 400, 400]},
        ]
        result = parse_boxes(json.dumps({"objects": rows}))
        self.assertEqual(len(result), 3)
        self.assertEqual([box.label for box in result], ["枕頭", "枕頭", "床"])

    def test_valid_coordinates_and_duplicate_removal(self):
        box = {"label": "蘋果", "bbox": [10, 20, 300, 400]}
        result = parse_boxes(json.dumps({"objects": [box, box]}))
        self.assertEqual(result, [Box("蘋果", (10, 20, 300, 400))])

    def test_reject_invalid_boxes_without_fabricating_coordinates(self):
        for coords in (
            [0, 0, 0, 10],
            [-1, 0, 100, 200],
            [0, 0, 1001, 1000],
            [True, 0, 100, 200],
            [0.1, 0, 100, 200],
            [0, 0, 100],
        ):
            with self.subTest(coords=coords), self.assertRaises(ValueError):
                parse_boxes(json.dumps({"objects": [{"label": "test", "bbox": coords}]}))
        for payload in ("bad", "{}", '{"objects":[null]}'):
            with self.assertRaises(ValueError):
                parse_boxes(payload)

    def test_qwen_style_fenced_array_and_bbox_alias(self):
        result = parse_boxes('```json\n[{"label":"蘋果","bbox_2d":[10,20,300,400]}]\n```')
        self.assertEqual(result, [Box("蘋果", (10, 20, 300, 400))])
        self.assertEqual(parse_boxes("[]"), [])


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        self.dialog = AnnotationDialog(image_data(), "qwen3.5:2b")
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.dialog.reject)

    def test_move_resize_and_undo_redo_keep_normalized_coordinates(self):
        original = Box("待調整", (100, 100, 400, 600), "model")
        self.dialog.canvas.boxes = [original]
        self.dialog._refresh()
        self.dialog.show()
        APP.processEvents()
        self.dialog.edit_mode.setCurrentIndex(1)
        canvas = self.dialog.canvas
        rect = canvas.image_rect()

        def point(x, y):
            return QPoint(
                round(rect.left() + x * rect.width() / 1000),
                round(rect.top() + y * rect.height() / 1000),
            )

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point(250, 350))
        QTest.mouseMove(canvas, point(400, 450))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=point(400, 450))
        moved = canvas.boxes[0]
        for actual, expected in zip(moved.bbox, (250, 200, 550, 700), strict=True):
            self.assertLessEqual(abs(actual - expected), 5)
        self.assertEqual(moved.source, "manual")
        self.dialog.undo()
        self.assertEqual(canvas.boxes, [original])
        self.dialog.redo()
        self.assertEqual(canvas.boxes, [moved])
        self.dialog.undo()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point(400, 600))
        QTest.mouseMove(canvas, point(700, 900))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=point(700, 900))
        for actual, expected in zip(canvas.boxes[0].bbox, (100, 100, 700, 900), strict=True):
            self.assertLessEqual(abs(actual - expected), 5)

    def test_import_annotation_hash_check_and_undo(self):
        original = Box("原框", (100, 100, 400, 600), "manual")
        self.dialog.canvas.boxes = [original]
        with tempfile.TemporaryDirectory() as directory:
            target = str(Path(directory) / "boxes.json")
            with patch(
                "labchat.annotation.QFileDialog.getSaveFileName", return_value=(target, "JSON")
            ):
                self.dialog._export_json()
            self.dialog.canvas.boxes = []
            with patch(
                "labchat.annotation.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                self.assertTrue(self.dialog.import_annotations(target))
            self.assertEqual(self.dialog.canvas.boxes, [original])
            self.dialog.undo()
            self.assertEqual(self.dialog.canvas.boxes, [])
            payload = json.loads(Path(target).read_text())
            payload["image_sha256"] = "0" * 64
            Path(target).write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                self.dialog.import_annotations(target)
            self.assertEqual(self.dialog.canvas.boxes, [])

    def test_model_results_preserve_manual_boxes(self):
        self.dialog.canvas.boxes = [Box("人工框", (0, 0, 100, 100), "manual")]
        result = ChatResult(
            "success", json.dumps({"objects": [{"label": "AI框", "bbox": [200, 100, 400, 500]}]})
        )
        self.dialog._completed(result)
        self.assertEqual(len(self.dialog.canvas.boxes), 2)
        self.assertEqual(self.dialog.canvas.boxes[0].source, "manual")
        self.assertFalse(self.dialog.spinner.timer.isActive())

    def test_repeated_ai_results_replace_previous_ai_and_keep_manual(self):
        manual = Box("人工", (0, 0, 100, 100), "manual")
        self.dialog.canvas.boxes = [manual, Box("舊AI", (200, 200, 400, 400))]
        result = ChatResult(
            "success", json.dumps({"objects": [{"label": "新AI", "bbox": [300, 300, 500, 500]}]})
        )
        self.dialog._completed(result)
        self.dialog._completed(result)
        self.assertEqual([box.label for box in self.dialog.canvas.boxes], ["人工", "新AI"])
        self.assertIn("qwen3.5:2b", self.dialog.model_label.text())

    def test_failure_and_invalid_coordinates_preserve_annotations(self):
        original = Box("原框", (0, 0, 100, 100), "manual")
        self.dialog.canvas.boxes = [original]
        for result in (
            ChatResult("error", error="failed"),
            ChatResult("cancelled"),
            ChatResult("success", "bad"),
            ChatResult("success", "{}", truncated=True),
        ):
            self.dialog._completed(result)
            self.assertEqual(self.dialog.canvas.boxes, [original])

    def test_manual_draw_uses_image_coordinates_with_letterboxing(self):
        self.dialog.show()
        APP.processEvents()
        canvas = self.dialog.canvas
        rect = canvas.image_rect()
        start = QPoint(
            round(rect.left() + rect.width() * 0.1), round(rect.top() + rect.height() * 0.2)
        )
        end = QPoint(
            round(rect.left() + rect.width() * 0.8), round(rect.top() + rect.height() * 0.7)
        )
        with patch("labchat.annotation.QInputDialog.getText", return_value=("測試物件", True)):
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(canvas.boxes), 1)
        self.assertEqual(canvas.boxes[0].source, "manual")
        for actual, expected in zip(canvas.boxes[0].bbox, (100, 200, 800, 700), strict=True):
            self.assertLessEqual(abs(actual - expected), 4)

    def test_rename_delete_and_atomic_export(self):
        self.dialog.canvas.boxes = [Box("舊名", (100, 100, 500, 700), "manual")]
        self.dialog._refresh()
        with patch("labchat.annotation.QInputDialog.getText", return_value=("新名", True)):
            self.dialog._rename()
        self.assertEqual(self.dialog.canvas.boxes[0].label, "新名")
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "test.png"
            self.assertTrue(self.dialog._save(str(png), self.dialog.canvas.export_image()))
            image = QImage(str(png))
            self.assertEqual((image.width(), image.height()), (400, 200))
            self.assertNotEqual(image.pixelColor(40, 40), QColor("white"))
            data = Path(directory) / "test.json"
            self.assertTrue(self.dialog._save(str(data), b'{"objects":[]}'))
            self.assertEqual(json.loads(data.read_text()), {"objects": []})
        self.dialog._delete()
        self.assertEqual(self.dialog.canvas.boxes, [])

    def test_annotation_initial_geometry_fits_available_screen(self):
        area = self.dialog.screen().availableGeometry()
        self.assertTrue(area.contains(self.dialog.geometry()))

    def test_elapsed_time_survives_fallback_and_freezes_on_finish(self):
        d = self.dialog
        with patch.object(d.client, "start"):
            d.automatic()
            self.assertTrue(d.elapsed_timer.isActive())
            self.assertEqual(d.elapsed_label.text(), "已運行 00:00")
            clock = Mock()
            clock.isValid.return_value = True
            clock.elapsed.return_value = 65000
            d.elapsed_clock = clock
            d._update_elapsed()
            self.assertEqual(d.elapsed_label.text(), "已運行 01:05")
            d._completed(ChatResult("error", http_status=501))
            clock.start.assert_not_called()
            self.assertTrue(d.elapsed_timer.isActive())
            d._completed(ChatResult("cancelled"))
            self.assertFalse(d.elapsed_timer.isActive())
            self.assertEqual(d.elapsed_label.text(), "本次耗時 01:05")
            d.automatic()
            clock.start.assert_called_once()
        d.reject()
        self.assertFalse(d.elapsed_timer.isActive())

    def test_structured_request_and_cancel_lifecycle(self):
        with patch.object(self.dialog.client, "start") as start:
            self.dialog.automatic()
            self.assertIn("format_schema", start.call_args.kwargs)
            self.assertEqual(start.call_args.kwargs["max_tokens"], 1088)
            self.assertTrue(start.call_args.kwargs["deterministic"])
            self.assertTrue(self.dialog.spinner.timer.isActive())
        self.dialog.reject()
        self.assertFalse(self.dialog.spinner.timer.isActive())

    def test_progressive_preview_commits_only_complete_success_and_undo_restores_original(self):
        original = Box("舊框", (10, 20, 300, 400))
        self.dialog.canvas.boxes = [original]
        with patch.object(self.dialog.client, "start"):
            self.dialog.automatic()
        self.assertEqual(self.dialog.box_limit.value(), 10)
        partial = '{"objects":[{"label":"新框","bbox":[100,200,500,600]}'
        self.dialog.client.chunk.emit(partial)
        self.assertEqual(self.dialog.canvas.boxes, [original])
        self.assertEqual(self.dialog.canvas.preview, [Box("新框", (100, 200, 500, 600))])
        self.assertIn("預覽", self.dialog.list_title.text())
        self.dialog._completed(ChatResult("success", partial + "]}"))
        self.assertIsNone(self.dialog.canvas.preview)
        self.assertEqual(self.dialog.canvas.boxes, [Box("新框", (100, 200, 500, 600))])
        self.dialog.undo()
        self.assertEqual(self.dialog.canvas.boxes, [original])

    def test_cancel_error_truncation_and_bad_final_retract_preview_without_changing_history(self):
        original = Box("人工", (10, 20, 300, 400), "manual")
        partial = '{"objects":[{"label":"新框","bbox":[100,200,500,600]}'
        for result in (
            ChatResult("cancelled"),
            ChatResult("error"),
            ChatResult("success", partial, truncated=True),
            ChatResult("success", partial),
        ):
            self.dialog.canvas.boxes = [original]
            with patch.object(self.dialog.client, "start"):
                self.dialog.automatic()
            self.dialog.client.chunk.emit(partial)
            self.assertIsNotNone(self.dialog.canvas.preview)
            self.dialog._completed(result)
            self.assertIsNone(self.dialog.canvas.preview)
            self.assertEqual(self.dialog.canvas.boxes, [original])
            self.assertEqual(self.dialog._undo_history, [])
            self.dialog.client.chunk.emit(partial)
            self.assertIsNone(self.dialog.canvas.preview)

    def test_excess_results_preserve_existing_annotations_and_undo(self):
        self.dialog._request_limit = 1
        original = Box("人工", (0, 0, 100, 100), "manual")
        self.dialog.canvas.boxes = [original]
        rows = [{"label": str(i), "bbox": [100, 100, 400, 400]} for i in range(2)]
        self.dialog._completed(ChatResult("success", json.dumps({"objects": rows})))
        self.assertEqual(self.dialog.canvas.boxes, [original])
        self.assertEqual(self.dialog._undo_history, [])
        self.assertIn("上限", self.dialog.status.text())

    def test_fallback_keeps_scope_and_generation_options(self):
        self.dialog.target.setText("人物")
        self.dialog.box_limit.setValue(2)
        with patch.object(self.dialog.client, "start") as start:
            self.dialog.automatic()
            first = start.call_args
            self.dialog._completed(ChatResult("error", http_status=501))
            second = start.call_args
            self.assertEqual(first.args, second.args)
            self.assertEqual(second.kwargs["max_tokens"], 320)
            self.assertTrue(second.kwargs["deterministic"])
            self.assertNotIn("format_schema", second.kwargs)

    def test_window_keeps_recent_image_for_annotation_until_reset(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        w = Window(history_path=Path(directory.name) / "history.sqlite3")
        try:
            w.image = w.last_image = image_data()
            w.remove_image()
            self.assertIsNone(w.image)
            self.assertIsNotNone(w.last_image)
            w.open_annotation()
            self.assertIsNotNone(w.annotation_dialog)
            w.annotation_dialog.canvas.boxes = [Box("保存框", (0, 0, 100, 100), "manual")]
            w.annotation_dialog.reject()
            self.assertIsNone(w.annotation_dialog)
            w.open_annotation()
            self.assertEqual(len(w.annotation_dialog.canvas.boxes), 1)
            w.annotation_dialog.reject()
            w.reset()
            self.assertIsNone(w.last_image)
            self.assertTrue(w.annotate_button.isHidden())
        finally:
            w.close()
            w.deleteLater()

    def test_main_spinner_stops_on_cancel_and_shutdown(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        w = Window(history_path=Path(directory.name) / "history.sqlite3")
        try:
            w.busy(True)
            self.assertTrue(w.spinner.timer.isActive())
            w._on_completed(ChatResult("cancelled"))
            self.assertFalse(w.spinner.timer.isActive())
            w.busy(True)
            w.shutdown()
            self.assertFalse(w.spinner.timer.isActive())
        finally:
            w.close()
            w.deleteLater()

    def test_spinner_animates_and_stops(self):
        indicator = BusyIndicator()
        indicator.set_running(True)
        QTest.qWait(100)
        self.assertNotEqual(indicator.phase, 0)
        indicator.set_running(False)
        self.assertFalse(indicator.timer.isActive())
        indicator.deleteLater()

    def test_unsupported_schema_retries_once_without_schema(self):
        with patch.object(self.dialog.client, "start") as start:
            self.dialog._completed(ChatResult("error", http_status=501))
            start.assert_called_once()
            self.assertNotIn("format_schema", start.call_args.kwargs)
            self.dialog._completed(ChatResult("error", http_status=501))
            self.assertEqual(start.call_count, 1)

    def test_annotation_fields_stay_readable_under_dark_system_palette(self):
        original = APP.palette()
        dark = QPalette(original)
        dark.setColor(QPalette.ColorRole.Window, QColor("#222222"))
        dark.setColor(QPalette.ColorRole.Base, QColor("#111111"))
        APP.setPalette(dark)
        dialog = None
        try:
            dialog = AnnotationDialog(image_data(), "qwen3.5:2b")
            dialog.show()
            APP.processEvents()
            self.assertEqual(
                dialog.target.palette().color(QPalette.ColorRole.Base).name(), "#ffffff"
            )
            self.assertEqual(
                dialog.items.palette().color(QPalette.ColorRole.Base).name(), "#ffffff"
            )
            self.assertNotEqual(
                dialog.items.palette().color(QPalette.ColorRole.Text).name(), "#ffffff"
            )
            dialog.resize(760, 600)
            APP.processEvents()
            self.assertEqual(dialog.width(), 760)
            self.assertEqual(dialog.height(), 600)
        finally:
            if dialog is not None:
                dialog.reject()
                dialog.deleteLater()
            APP.setPalette(original)

    def test_closed_annotation_cannot_restart_or_fallback(self):
        self.dialog.reject()
        with patch.object(self.dialog.client, "start") as start:
            self.dialog.automatic()
            self.dialog._completed(ChatResult("error", http_status=501))
            start.assert_not_called()

    def test_untrusted_error_is_plain_text(self):
        self.dialog._completed(ChatResult("error", error="<b>fake markup</b>"))
        self.assertEqual(self.dialog.status.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<b>fake markup</b>", self.dialog.status.text())

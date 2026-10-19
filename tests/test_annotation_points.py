"""Visual reference points follow rectangle geometry and never mutate annotations."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from test_annotation import image_data

from labchat.annotation import COLORS, AnnotationDialog, reference_points
from labchat.grounding import Box

APP = QApplication.instance() or QApplication([])


class AnnotationPointTests(unittest.TestCase):
    def setUp(self):
        self.dialog = AnnotationDialog(image_data(), "qwen3.5:2b")
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.dialog.reject)
        self.box = Box("方塊", (100, 100, 700, 900), "manual")
        self.dialog.canvas.boxes = [self.box]
        self.dialog._refresh()

    def test_fractional_center_and_four_edge_midpoints(self):
        center, edges = reference_points((101, 203, 700, 902))
        self.assertEqual(center, (400.5, 552.5))
        self.assertEqual(edges, ((400.5, 203), (400.5, 902), (101, 552.5), (700, 552.5)))

    def test_independent_checkboxes_and_export_match_without_mutating_boxes(self):
        d = self.dialog
        self.assertFalse(d.center_points.isChecked())
        self.assertFalse(d.edge_midpoints.isChecked())
        color = QColor(COLORS[0])
        initial = d.canvas.export_image()
        self.assertEqual(initial.pixelColor(160, 100), QColor("white"))
        d.center_points.setChecked(True)
        center_only = d.canvas.export_image()
        self.assertEqual(center_only.pixelColor(160, 100), color)
        self.assertEqual(center_only.pixelColor(43, 100), QColor("white"))
        d.edge_midpoints.setChecked(True)
        both = d.canvas.export_image()
        self.assertEqual(both.pixelColor(160, 100), color)
        self.assertEqual(both.pixelColor(43, 100), color)
        self.assertEqual(both.pixelColor(160, 177), color)
        d.center_points.setChecked(False)
        edges_only = d.canvas.export_image()
        self.assertEqual(edges_only.pixelColor(160, 100), QColor("white"))
        self.assertEqual(edges_only.pixelColor(43, 100), color)
        d.edge_midpoints.setChecked(False)
        self.assertEqual(d.canvas.export_image(), initial)
        self.assertEqual(d.canvas.boxes, [self.box])
        self.assertEqual(d._undo_history, [])
        self.assertEqual(d.canvas.image.pixelColor(160, 100), QColor("white"))

    def test_points_follow_new_geometry_and_preview_uses_same_options(self):
        d = self.dialog
        d.center_points.setChecked(True)
        d.edge_midpoints.setChecked(True)
        d.canvas.boxes = [Box("移動後", (300, 100, 900, 900), "manual")]
        exported = d.canvas.export_image()
        self.assertEqual(exported.pixelColor(240, 100), QColor(COLORS[0]))
        self.assertEqual(exported.pixelColor(160, 100), QColor("white"))
        d.canvas.preview = [self.box]
        with patch("labchat.annotation.paint_boxes") as paint:
            d.canvas.grab()
            self.assertTrue(paint.call_args.kwargs["preview"])
            self.assertTrue(paint.call_args.kwargs["show_center"])
            self.assertTrue(paint.call_args.kwargs["show_midpoints"])
        self.assertEqual(d.canvas.boxes[0].label, "移動後")

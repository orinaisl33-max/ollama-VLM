"""Search coalescing, batched layout and explicit clipboard actions."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from labchat.client import ChatResult
from labchat.conversation_widgets import ConversationDialog, ConversationSidebar
from labchat.conversations import ConversationStore
from labchat.theme import apply_theme
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConversationStore(Path(self.temp.name) / "search.sqlite3")
        self.addCleanup(self.store.close)
        self.first = self.store.append(None, "qwen3.5:2b", "第一組", "含有關鍵內容")
        self.second = self.store.append(None, "qwen3.5:2b", "第二組", "其他內容")
        self.root = QWidget()
        self.root.store = self.store
        self.addCleanup(self.root.deleteLater)
        self.sidebar = ConversationSidebar(self.root)
        self.sidebar.refresh(self.store.list(), self.first)

    def test_fast_typing_runs_one_final_fulltext_query(self):
        with patch.object(self.store, "list", wraps=self.store.list) as query:
            for text in ("關", "關鍵", "關鍵內容"):
                self.sidebar.search.setText(text)
            query.assert_not_called()
            QTest.qWait(250)
            query.assert_called_once_with("關鍵內容")
        visible = [
            self.sidebar.items.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.sidebar.items.count())
            if not self.sidebar.items.item(i).isHidden()
        ]
        self.assertEqual(visible, [self.first])

    def test_clear_cancels_pending_search_and_restores_all_without_query(self):
        with patch.object(self.store, "list", wraps=self.store.list) as query:
            self.sidebar.search.setText("找不到")
            self.sidebar.search.clear()
            QTest.qWait(250)
            query.assert_not_called()
        self.assertFalse(self.sidebar.search_timer.isActive())
        self.assertTrue(all(not self.sidebar.items.item(i).isHidden() for i in range(2)))

    def test_pending_search_cannot_activate_stale_item(self):
        activated = []
        self.sidebar.activated.connect(activated.append)
        self.sidebar.search.setText("關鍵")
        self.sidebar._activate(self.sidebar.items.item(0))
        self.assertEqual(activated, [])
        self.sidebar.filter()
        self.assertFalse(self.sidebar.search_timer.isActive())

    def test_management_actions_wait_for_search_result(self):
        dialog = ConversationDialog(self.store, self.root)
        try:
            dialog.items.setCurrentRow(0)
            self.assertTrue(dialog.open_button.isEnabled())
            with patch.object(self.store, "list", wraps=self.store.list) as query:
                dialog.search.setText("無")
                dialog.search.setText("無結果")
                self.assertIsNone(dialog.identifier())
                self.assertFalse(dialog.delete_button.isEnabled())
                QTest.qWait(250)
                query.assert_called_once_with("無結果")
            self.assertFalse(dialog.open_button.isEnabled())
            dialog.search.clear()
            self.assertTrue(dialog.open_button.isEnabled())
        finally:
            dialog.deleteLater()


class HistoryAndCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.w = Window(history_path=Path(self.temp.name) / "history.sqlite3")
        self.addCleanup(self.w.deleteLater)
        self.addCleanup(self.w.shutdown)

    def test_batched_history_preserves_markdown_and_recent_model_context(self):
        w = self.w
        identifier = None
        for i in range(12):
            identifier = w.store.append(
                None if i == 0 else identifier, "qwen3.5:2b", f"問題{i}", f"**回答{i}**"
            )
        self.assertTrue(w.load_conversation(identifier))
        text = w.chat.toPlainText()
        self.assertIn("問題0", text)
        self.assertIn("回答11", text)
        self.assertNotIn("**回答11**", text)
        self.assertEqual(len(w.history), 6)
        self.assertEqual(w.history[-1]["content"], "**回答11**")
        self.assertTrue(w.chat.document().isLayoutEnabled())
        self.assertFalse(w._bulk_rendering)

    def test_failed_render_restores_layout_and_painting(self):
        w = self.w
        turn = {"prompt": "問", "answer": "答", "has_image": False}
        with patch.object(w, "_render_answer", side_effect=ValueError("模擬排版失敗")):
            with self.assertRaises(ValueError):
                w._render_history([turn])
        self.assertTrue(w.chat.document().isLayoutEnabled())
        self.assertTrue(w.chat.updatesEnabled())
        self.assertFalse(w._bulk_rendering)

    def test_copy_is_explicit_raw_text_and_reset_clears_target(self):
        w = self.w
        original = APP.clipboard().text()
        try:
            answer = "**重點**\n```python\nprint('test')\n```"
            w._set_copy_answer(answer)
            self.assertEqual(APP.clipboard().text(), original)
            w.copy_button.click()
            self.assertEqual(APP.clipboard().text(), answer)
            w.reset()
            self.assertFalse(w.copy_button.isEnabled())
            self.assertEqual(w._copy_answer, "")
        finally:
            APP.clipboard().setText(original)

    def test_cancelled_reply_does_not_replace_completed_copy_target(self):
        w = self.w
        w._set_copy_answer("先前完成回答")
        w._on_completed(ChatResult("cancelled", "未完成片段"))
        self.assertEqual(w._copy_answer, "先前完成回答")

    def test_copy_is_blocked_while_request_active(self):
        w = self.w
        w._set_copy_answer("完成回答")
        w.client._reply = object()
        try:
            with patch("PySide6.QtWidgets.QApplication.clipboard") as clipboard:
                w.copy_answer()
                clipboard.assert_not_called()
        finally:
            w.client._reply = None

    def test_new_shortcut_uses_existing_guard_during_recording(self):
        w = self.w
        w.input.setPlainText("不要清除")
        w.dictation.state = "recording"
        shortcut = next(
            s for s in w.shortcuts if s.key() == QKeySequence(QKeySequence.StandardKey.New)
        )
        shortcut.activated.emit()
        self.assertEqual(w.input.toPlainText(), "不要清除")
        w.dictation.state = "idle"


class ApplicationExitTests(unittest.TestCase):
    def test_real_application_entry_closes_with_temporary_store(self):
        script = """
import logging, tempfile
from pathlib import Path
from PySide6.QtCore import QTimer
import main as entry
from labchat.window import Window
with tempfile.TemporaryDirectory() as folder:
    class TemporaryWindow(Window):
        def __init__(self):
            super().__init__(history_path=Path(folder)/'test.sqlite3')
            QTimer.singleShot(150, self.close)
    entry.Window = TemporaryWindow
    entry.RotatingFileHandler = lambda *a, **k: logging.NullHandler()
    raise SystemExit(entry.main())
"""
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertNotIn("shared QObject was deleted directly", result.stderr)

    def test_same_theme_new_window_does_not_restyle_existing_widgets(self):
        root = QWidget()
        child = QWidget()
        try:
            apply_theme(root, "light")
            with patch.object(APP, "setStyleSheet") as restyle:
                apply_theme(child, "light")
                restyle.assert_not_called()
            self.assertEqual(child.palette().color(QPalette.ColorRole.Window).name(), "#f4f7f8")
        finally:
            root.deleteLater()
            child.deleteLater()

    def test_changed_palette_is_repaired_even_with_same_theme_name(self):
        root = QWidget()
        try:
            apply_theme(root, "light")
            palette = QPalette(APP.palette())
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#ff0000"))
            APP.setPalette(palette)
            apply_theme(root, "light")
            self.assertEqual(APP.palette().color(QPalette.ColorRole.WindowText).name(), "#182b36")
        finally:
            root.deleteLater()

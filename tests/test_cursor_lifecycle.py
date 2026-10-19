"""Prevent stale transcript cursors and retain actionable Qt diagnostics."""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler, qWarning
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication

from labchat.diagnostics import install_qt_diagnostics
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class CursorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.w = Window(history_path=Path(self.temp.name) / "history.db")
        self.addCleanup(self.w.deleteLater)
        self.addCleanup(self.w.shutdown)

    def test_reset_discards_old_anchors_and_buffered_output(self):
        w = self.w
        w._begin_turn("舊問題")
        w._answer_start = QTextCursor(w.chat.document())
        w._queued_text.append("舊回答的待顯示文字")
        w.render_timer.start()
        self.assertTrue(w.reset())
        self.assertIsNone(w._answer_start)
        self.assertIsNone(w._ai_stamp_cursor)
        self.assertFalse(w.render_timer.isActive())
        self.assertFalse(w._queued_text)
        w._begin_turn("新問題")
        w._render_answer("**新回答**")
        text = w.chat.toPlainText()
        self.assertIn("新問題", text)
        self.assertIn("新回答", text)
        self.assertNotIn("舊回答", text)

    def test_foreign_cursor_cannot_replace_current_conversation(self):
        self.w._begin_turn("目前問題")
        previous = self.w.chat.toPlainText()
        foreign = QTextDocument("其他文件")
        cursor = QTextCursor(foreign)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        with self.assertLogs("labchat.window", level="WARNING"):
            self.w._render_answer("不應覆蓋", cursor)
        self.assertEqual(self.w.chat.toPlainText(), previous)


class QtDiagnosticTests(unittest.TestCase):
    def test_cursor_warning_is_traced_without_logging_message_content(self):
        forwarded = []
        old = qInstallMessageHandler(lambda kind, context, message: forwarded.append(message))
        restore = install_qt_diagnostics()
        try:
            message = "QTextCursor::setPosition: private-test-sentinel"
            with self.assertLogs("labchat.diagnostics", level="WARNING") as logs:
                qWarning(message)
            self.assertIn("call stack", logs.output[0])
            self.assertNotIn("private-test-sentinel", logs.output[0])
            self.assertEqual(forwarded, [message])
            restore()
            qWarning("diagnostic handler restored")
            self.assertEqual(forwarded[-1], "diagnostic handler restored")
        finally:
            restore()
            qInstallMessageHandler(old)

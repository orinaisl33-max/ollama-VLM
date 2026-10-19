"""Timestamp persistence, legacy compatibility and transcript formatting."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from labchat.conversation_io import export_document, validate_document
from labchat.conversations import ConversationStore
from labchat.timestamps import clock_label, validate_timestamp
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class TimestampTests(unittest.TestCase):
    def test_invalid_values(self):
        for value in (True, -1, float("nan"), float("inf"), 10**500, "12:30"):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                validate_timestamp(value)
        self.assertEqual(clock_label(None), "")

    def test_roundtrip_and_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory) / "history.sqlite3")
            try:
                identifier = store.append(
                    None, "qwen3.5:2b", "問題", "回答", asked_at=1750000000, answered_at=1750000030
                )
                record = store.load(identifier)
                document = export_document(record)
                self.assertEqual(document["version"], 2)
                restored = store.import_record(validate_document(document))
                self.assertEqual(store.load(restored)["turns"], record["turns"])
                document["version"] = 1
                for turn in document["turns"]:
                    del turn["asked_at"], turn["answered_at"]
                self.assertIsNone(validate_document(document)["turns"][0]["asked_at"])
            finally:
                store.close()

    def test_version_four_migration_preserves_unknown_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            store = ConversationStore(path)
            identifier = store.append(None, "qwen3.5:2b", "舊問題", "舊回答")
            store.close()
            with sqlite3.connect(path) as db:
                db.execute("ALTER TABLE turns DROP COLUMN asked_at")
                db.execute("ALTER TABLE turns DROP COLUMN answered_at")
                db.execute("PRAGMA user_version=4")
            store = ConversationStore(path)
            try:
                turn = store.load(identifier)["turns"][0]
                self.assertEqual(turn["answer"], "舊回答")
                self.assertIsNone(turn["asked_at"])
                self.assertIsNone(turn["answered_at"])
                self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 5)
            finally:
                store.close()

    def test_transcript_clock_does_not_replace_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(history_path=str(Path(directory) / "history.sqlite3"))
            try:
                window._begin_turn("問題", asked_at=1750000000)
                anchor = QTextCursor(window.chat.document())
                anchor.movePosition(QTextCursor.MoveOperation.End)
                anchor.setKeepPositionOnInsert(True)
                window.append("正在回答")
                window._insert_clock(QTextCursor(window._ai_stamp_cursor), 1750000030)
                window._render_answer("**完成回答**", anchor)
                text = window.chat.toPlainText()
                self.assertIn("你  ·  " + clock_label(1750000000), text)
                self.assertIn("AI 助理  ·  " + clock_label(1750000030), text)
                self.assertIn("完成回答", text)
                self.assertNotIn("正在回答", text)
                self.assertEqual(window.speech_panel.mode.parent(), window.speech_panel.dialog)
                self.assertTrue(window.appearance_button.isHidden())
            finally:
                window.close()

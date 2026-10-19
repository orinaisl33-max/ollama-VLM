"""Persistent text history: transactions, limits, restart and damaged-file behavior."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from labchat.conversations import ConversationStore, HistoryError


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "history" / "conversations.sqlite3"
        self.store = ConversationStore(self.path)
        self.addCleanup(self.store.close)

    def turn(self, identifier=None, prompt="測試問題", answer="測試回答"):
        return self.store.append(identifier, "qwen3.5:2b", prompt, answer)

    def test_restart_keeps_complete_text_and_image_flag_only(self):
        identifier = self.store.append(None, "qwen3.5:2b", "圖片是什麼？", "水果。", True)
        self.store.close()
        self.store = ConversationStore(self.path)
        self.addCleanup(self.store.close)
        record = self.store.load(identifier)
        self.assertEqual(record["model"], "qwen3.5:2b")
        self.assertEqual(
            record["turns"],
            [
                {
                    "prompt": "圖片是什麼？",
                    "answer": "水果。",
                    "has_image": 1,
                    "asked_at": None,
                    "answered_at": None,
                }
            ],
        )
        self.assertNotIn("images", str(record))

    def test_order_rename_and_sql_parameters(self):
        first = self.turn(prompt="第一題")
        second = self.turn(prompt="第二題")
        self.turn(first, prompt="續問")
        self.assertEqual([r["id"] for r in self.store.list()], [first, second])
        self.store.rename(first, "名稱'; DROP TABLE turns; --\u202e")
        self.assertNotIn("\u202e", self.store.load(first)["title"])
        self.assertEqual(len(self.store.load(first)["turns"]), 2)

    def test_delete_cascades_and_does_not_delete_other_conversation(self):
        first, second = self.turn(), self.turn()
        self.store.delete(first)
        self.assertEqual([r["id"] for r in self.store.list()], [second])
        count = self.store.connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        self.assertEqual(count, 1)
        with self.assertRaises(HistoryError):
            self.store.load(first)

    def test_capacity_rejection_rolls_back_new_conversation(self):
        with patch("labchat.conversations.MAX_TOTAL_CHARS", 1):
            with self.assertRaises(HistoryError):
                self.turn()
        self.assertEqual(self.store.list(), [])
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 0
        )

    def test_existing_turn_limit_preserves_previous_content(self):
        identifier = self.turn()
        with patch("labchat.conversations.MAX_TURNS", 1):
            with self.assertRaises(HistoryError):
                self.turn(identifier)
        self.assertEqual(len(self.store.load(identifier)["turns"]), 1)

    def test_conversation_limit_never_silently_removes_old_records(self):
        identifier = self.turn()
        with patch("labchat.conversations.MAX_CONVERSATIONS", 1):
            with self.assertRaises(HistoryError):
                self.turn()
        self.assertEqual(self.store.list()[0]["id"], identifier)

    def test_deleted_or_different_model_cannot_receive_appended_turn(self):
        identifier = self.turn()
        with self.assertRaises(HistoryError):
            self.store.append(identifier, "qwen3.5:4b", "問", "答")
        self.store.delete(identifier)
        with self.assertRaises(HistoryError):
            self.turn(identifier)
        self.assertEqual(self.store.list(), [])

    def test_invalid_text_never_creates_records(self):
        for prompt, answer in (("", "回答"), ("問題", ""), ("\ud800", "答案"), ("問", "\udfff")):
            with self.subTest(prompt=repr(prompt), answer=repr(answer)):
                with self.assertRaises(HistoryError):
                    self.turn(prompt=prompt, answer=answer)
        self.assertEqual(self.store.list(), [])

    def test_two_connections_can_append_without_lost_updates(self):
        identifier = self.turn()
        other = ConversationStore(self.path)
        try:
            other.append(identifier, "qwen3.5:2b", "第二問", "第二答")
            self.turn(identifier, "第三問", "第三答")
            self.assertEqual(len(other.load(identifier)["turns"]), 3)
        finally:
            other.close()

    def test_newer_schema_not_overwritten(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(HistoryError):
            ConversationStore(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_corrupt_database_is_not_deleted_or_replaced(self):
        self.store.close()
        original = b"not a sqlite database: keep original"
        self.path.write_bytes(original)
        with self.assertRaises(HistoryError):
            ConversationStore(self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_closed_store_rejects_writes(self):
        self.store.close()
        self.store.close()
        with self.assertRaises(HistoryError):
            self.turn()

    def test_drafts_are_isolated_survive_restart_and_clear_after_delete(self):
        identifier = self.turn()
        self.store.save_draft(identifier, "qwen3.5:2b", "此對話草稿")
        self.store.save_draft("new:qwen3.5:2b", "qwen3.5:2b", "新對話草稿")
        self.store.close()
        self.store = ConversationStore(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(self.store.get_draft(identifier), "此對話草稿")
        self.assertEqual(self.store.get_draft("new:qwen3.5:2b"), "新對話草稿")
        self.store.delete(identifier)
        self.assertEqual(self.store.get_draft(identifier), "")
        self.assertEqual(self.store.get_draft("new:qwen3.5:2b"), "新對話草稿")

    def test_invalid_or_oversize_draft_does_not_replace_previous_draft(self):
        self.store.save_draft("new:qwen3.5:2b", "qwen3.5:2b", "保留")
        with self.assertRaises(HistoryError):
            self.store.save_draft("new:qwen3.5:2b", "qwen3.5:2b", "字" * 16001)
        self.assertEqual(self.store.get_draft("new:qwen3.5:2b"), "保留")
        with self.assertRaises(HistoryError):
            self.store.save_draft("nonexistent", "qwen3.5:2b", "不可新增孤兒")

    def test_schema_one_migration_preserves_turns(self):
        identifier = self.turn()
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE drafts")
            db.execute("PRAGMA user_version=1")
        self.store = ConversationStore(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(len(self.store.load(identifier)["turns"]), 1)
        self.store.save_draft(identifier, "qwen3.5:2b", "升級後")
        self.assertEqual(self.store.get_draft(identifier), "升級後")

    def test_fulltext_search_pin_and_clear_all_preserve_privacy_setting(self):
        first = self.turn(prompt="一般標題", answer="內文有特殊關鍵詞")
        second = self.turn(prompt="另一組")
        self.assertEqual([r["id"] for r in self.store.list("特殊關鍵詞")], [first])
        self.store.set_pinned(first, True)
        self.assertEqual(self.store.list()[0]["id"], first)
        self.assertEqual(self.store.list("%_"), [])
        self.store.save_draft(second, "qwen3.5:2b", "草稿")
        self.store.set_saving(False)
        self.store.clear_all()
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.get_draft(second), "")
        self.assertFalse(self.store.saving_enabled())

    def test_unrecognized_columns_are_not_automatically_migrated(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute("ALTER TABLE conversations RENAME COLUMN title TO unexpected")
            db.execute("PRAGMA user_version=1")
        original = self.path.read_bytes()
        with self.assertRaises(HistoryError):
            ConversationStore(self.path)
        self.assertEqual(self.path.read_bytes(), original)

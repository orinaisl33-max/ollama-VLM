import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from labchat.conversation_io import (
    export_document,
    read_document,
    validate_document,
    write_document,
)
from labchat.conversations import ConversationStore, HistoryError


class ConversationIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ConversationStore(self.root / "history.sqlite3")
        self.addCleanup(self.store.close)
        self.identifier = self.store.append(
            None, "qwen3.5:2b", "測試？", "**回答** <script>alert(1)</script>", True
        )
        self.record = self.store.load(self.identifier)

    def test_json_roundtrip_restores_new_copy_without_overwriting(self):
        target = self.root / "out.json"
        write_document(target, self.record)
        restored = self.store.import_record(read_document(target))
        self.assertNotEqual(restored, self.identifier)
        self.assertEqual(self.store.load(restored)["turns"], self.record["turns"])
        self.assertEqual(len(self.store.list()), 2)

    def test_new_french_and_google_models_can_restore_text_archives(self):
        document = export_document(self.record)
        for model in ("ministral-3:3b", "gemma3:4b"):
            document["model"] = model
            identifier = self.store.import_record(validate_document(document))
            self.assertEqual(self.store.load(identifier)["model"], model)

    def test_invalid_fields_versions_roles_and_limits_rejected(self):
        valid = export_document(self.record)
        for field, value in (
            ("version", True),
            ("version", 99),
            ("model", "https://evil"),
            ("title", ""),
            ("turns", []),
        ):
            bad = copy.deepcopy(valid)
            bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(HistoryError):
                validate_document(bad)
        bad = copy.deepcopy(valid)
        bad["turns"][0]["prompt"] = "\x00"
        with self.assertRaises(HistoryError):
            validate_document(bad)
        bad = copy.deepcopy(valid)
        bad["turns"][0]["images"] = ["file:///secret"]
        with self.assertRaises(HistoryError):
            validate_document(bad)

    def test_failed_import_rolls_back_entire_new_record(self):
        before = self.store.list()
        with patch("labchat.conversations.MAX_TOTAL_CHARS", 1):
            with self.assertRaises(HistoryError):
                self.store.import_record(read_document(self.write_json()))
        self.assertEqual(self.store.list(), before)

    def write_json(self):
        target = self.root / "out.json"
        write_document(target, self.record)
        return target

    def test_bounded_read_and_bad_encoding_or_json(self):
        target = self.root / "bad.json"
        for data in (b"\xff", b"{}", b"[" * 2000, b"null"):
            target.write_bytes(data)
            with self.assertRaises(HistoryError):
                read_document(target)
        target.write_text(json.dumps(export_document(self.record)), encoding="utf-8")
        with patch("labchat.conversation_io.MAX_IMPORT_BYTES", 10):
            with self.assertRaises(HistoryError):
                read_document(target)

    def test_markdown_is_readable_and_escapes_html(self):
        target = self.root / "out.md"
        write_document(target, self.record, markdown=True)
        text = target.read_text()
        self.assertIn("AI 助理", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)

    def test_export_failure_preserves_existing_file(self):
        target = self.root / "out.json"
        target.write_text("original")
        with patch("labchat.conversation_io.QSaveFile.commit", return_value=False):
            with self.assertRaises(HistoryError):
                write_document(target, self.record)
        self.assertEqual(target.read_text(), "original")

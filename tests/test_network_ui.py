"""Regression tests against a local fake server; no model or internet required."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QInputMethodEvent, QTextCursor, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from labchat.client import ChatClient, ServiceProbe
from labchat.conversation_widgets import ConversationDialog
from labchat.conversations import HistoryError
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class Server(ThreadingHTTPServer):
    daemon_threads = True
    mode = "normal"
    payload = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.server.mode == "catalog_slow":
            time.sleep(0.3)
        if self.server.mode == "catalog_bad":
            data = b'{"models":[null]}'
        else:
            data = b'{"models":[{"name":"qwen3.5:2b"}]}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def do_POST(self):
        self.server.payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        mode = self.server.mode
        status = 200
        events = [{"message": {"content": "測試回答"}}, {"done": True}]
        if mode == "thinking":
            events = [
                {"message": {"thinking": "內部推理", "content": ""}},
                {"message": {"content": "正式回答"}},
                {"done": True},
            ]
        elif mode == "grounding_stream":
            events = [
                {"message": {"content": '{"objects":[{"label":"杯子","bbox":[10,20,300,400]}'}},
                {"message": {"content": ',{"label":"水果","bbox":[500,20,800,400]}'}},
                {"message": {"content": "]}"}},
                {"done": True},
            ]
        elif mode == "http_error":
            status = 404
            events = [{"error": "model missing"}]
        elif mode == "redirect":
            status = 302
        elif mode == "broken":
            events = None
        elif mode == "server_error":
            events = [{"error": "runner unavailable"}]
        elif mode == "no_done":
            events = events[:1]
        elif mode == "empty":
            events = [{"done": True}]
        elif mode == "truncated":
            events[-1]["done_reason"] = "length"
        elif mode == "after_done":
            events += [{"message": {"content": "extra"}}]
        data = (
            b"not-json\n"
            if events is None
            else b"\n".join(json.dumps(e, ensure_ascii=False).encode() for e in events)
        )
        if mode == "heartbeat":
            data = b"\n" * 20 + data
        self.send_response(status)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(data)))
        if mode == "redirect":
            self.send_header("Location", "http://127.0.0.1:1/should-not-follow")
        self.end_headers()
        try:
            if mode == "slow":
                time.sleep(0.4)
            if mode == "heartbeat":
                for _ in range(20):
                    self.wfile.write(b"\n")
                    self.wfile.flush()
                    time.sleep(0.02)
                data = data[20:]
            if mode == "grounding_stream":
                for index, event in enumerate(events):
                    self.wfile.write(json.dumps(event, ensure_ascii=False).encode())
                    if index < len(events) - 1:
                        self.wfile.write(b"\n")
                        self.wfile.flush()
                        time.sleep(0.15)
                    self.wfile.flush()
            elif mode == "split":
                for byte in data:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            else:
                self.wfile.write(data)
                self.wfile.flush()
        except OSError:
            pass


def wait_for(predicate, timeout=3000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not predicate():
        raise AssertionError("Qt event wait timed out")


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        # Tests run without app.exec(); explicitly process Qt deferred destruction.
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        self.server.mode = "normal"
        self.client = ChatClient(base_url=self.url, idle_timeout_ms=1000, total_timeout_ms=2000)
        self.results = []
        self.chunks = []
        self.client.completed.connect(self.results.append)
        self.client.chunk.connect(self.chunks.append)
        self.addCleanup(self.client.deleteLater)
        self.addCleanup(self.client.shutdown)

    def start(self, mode="normal"):
        self.server.mode = mode
        self.client.start("qwen3.5:2b", [{"role": "user", "content": "測試"}])

    def result(self):
        wait_for(lambda: bool(self.results))
        self.assertFalse(self.client.active)
        self.assertFalse(self.client.idle_timer.isActive())
        self.assertFalse(self.client.total_timer.isActive())
        self.assertEqual(len(self.results), 1)
        return self.results[0]

    def test_fragmented_utf8_final_without_newline(self):
        self.start("split")
        result = self.result()
        self.assertEqual(result.status, "success")
        self.assertEqual(result.answer, "測試回答")
        self.assertEqual("".join(self.chunks), result.answer)
        self.assertEqual(self.server.payload["options"]["num_ctx"], 4096)

    def test_grounding_options_are_stable_and_chat_defaults_unchanged(self):
        self.client.start("qwen3.5:2b", [{"role": "user", "content": "框選"}], deterministic=True)
        self.assertEqual(self.result().status, "success")
        self.assertEqual(self.server.payload["options"]["seed"], 42)
        self.assertEqual(self.server.payload["options"]["temperature"], 0)

    def test_annotation_draws_streamed_boxes_before_request_completes(self):
        from test_annotation import image_data

        from labchat.annotation import AnnotationDialog

        self.server.mode = "grounding_stream"
        dialog = AnnotationDialog(image_data(), "qwen3.5:2b")
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        dialog.client.base_url = self.url
        dialog.automatic()
        wait_for(lambda: dialog.canvas.preview is not None)
        self.assertTrue(dialog.client.active)
        self.assertEqual(len(dialog.canvas.preview), 1)
        self.assertEqual(dialog.canvas.boxes, [])
        self.assertFalse(dialog.export_json.isEnabled())
        wait_for(lambda: dialog.canvas.preview is not None and len(dialog.canvas.preview) == 2)
        self.assertTrue(dialog.client.active)
        wait_for(lambda: not dialog.client.active)
        self.assertIsNone(dialog.canvas.preview)
        self.assertEqual(len(dialog.canvas.boxes), 2)

    def test_reasoning_is_not_displayed_or_sent_to_speech_chunks(self):
        self.start("thinking")
        result = self.result()
        self.assertEqual(result.status, "success")
        self.assertEqual(result.answer, "正式回答")
        self.assertEqual("".join(self.chunks), "正式回答")

    def test_failure_modes(self):
        for mode in (
            "http_error",
            "redirect",
            "broken",
            "server_error",
            "no_done",
            "empty",
            "after_done",
        ):
            with self.subTest(mode=mode):
                self.results.clear()
                self.chunks.clear()
                self.start(mode)
                self.assertEqual(self.result().status, "error")
                self.assertTrue(self.results[0].error)

    def test_length_limit_is_visible(self):
        self.start("truncated")
        result = self.result()
        self.assertEqual(result.status, "success")
        self.assertTrue(result.truncated)

    def test_answer_bound(self):
        with patch("labchat.client.MAX_ANSWER_CHARS", 2):
            self.start()
            self.assertEqual(self.result().status, "error")

    def test_cancel_is_single_and_client_can_be_reused(self):
        self.start("slow")
        with self.assertRaises(RuntimeError):
            self.start()
        self.client.cancel()
        self.client.cancel()
        self.assertEqual(self.result().status, "cancelled")
        QTest.qWait(450)
        self.assertEqual(len(self.results), 1)
        self.results.clear()
        self.start()
        self.assertEqual(self.result().status, "success")

    def test_idle_timeout(self):
        self.client.idle_timeout_ms = 50
        self.start("slow")
        self.assertEqual(self.result().status, "timeout")

    def test_total_timeout_despite_heartbeat(self):
        self.client.total_timeout_ms = 100
        self.start("heartbeat")
        self.assertEqual(self.result().status, "timeout")

    def test_shutdown_does_not_emit_completion(self):
        self.start("slow")
        self.client.shutdown()
        QTest.qWait(450)
        self.assertEqual(self.results, [])
        self.assertFalse(self.client.active)

    def test_service_catalog_validation(self):
        probe = ServiceProbe(self.client.network, base_url=self.url)
        self.addCleanup(probe.deleteLater)
        self.addCleanup(probe.shutdown)
        values = []
        probe.updated.connect(lambda models, error: values.append((models, error)))
        probe.refresh()
        wait_for(lambda: bool(values))
        self.assertEqual(values[0], ({"qwen3.5:2b"}, ""))
        values.clear()
        self.server.mode = "catalog_bad"
        probe.refresh()
        wait_for(lambda: bool(values))
        self.assertIsNone(values[0][0])
        self.assertTrue(values[0][1])

    def window(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        window = Window(history_path=os.path.join(directory.name, "conversations.sqlite3"))
        window.client.base_url = self.url
        window.probe.base_url = self.url
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        return window

    def test_assistant_markdown_and_literal_user_prompt(self):
        w = self.window()
        w.append("你\n**使用者原文**\n\nAI 助理\n")
        anchor = QTextCursor(w.chat.document())
        anchor.movePosition(QTextCursor.MoveOperation.End)
        anchor.setKeepPositionOnInsert(True)
        w.append("**人物狀態**")
        answer = "### 情境分析\n\n**人物狀態**：可見人物躺在地板。\n\n![外圖](file:///etc/passwd)"
        w._render_answer(answer, anchor)
        text = w.chat.toPlainText()
        self.assertIn("**使用者原文**", text)
        self.assertNotIn("**人物狀態**", text)
        self.assertNotIn("### 情境分析", text)
        self.assertIsNone(w.chat.document().lastBlock().textList())
        self.assertIn("人物狀態", text)
        selected = w.chat.document().find("人物狀態")
        self.assertGreaterEqual(selected.charFormat().fontWeight(), 600)
        resource = w.chat.document().resource(
            QTextDocument.ResourceType.ImageResource, QUrl("file:///etc/passwd")
        )
        self.assertFalse(resource)
        self.assertFalse(
            w.chat.textInteractionFlags() & Qt.TextInteractionFlag.LinksAccessibleByMouse
        )

    def test_restored_answers_use_markdown_but_keep_original_archive(self):
        w = self.window()
        answer = "**粗體回答**\n\n- 清單項目"
        identifier = w.store.append(None, "qwen3.5:2b", "**原始提問**", answer)
        self.assertTrue(w.load_conversation(identifier))
        self.assertIn("**原始提問**", w.chat.toPlainText())
        self.assertNotIn("**粗體回答**", w.chat.toPlainText())
        prompt_cursor = w.chat.document().find("**原始提問**")
        self.assertEqual(
            prompt_cursor.currentFrame().frameFormat().background().color().name(), "#edf3ff"
        )
        answer_cursor = w.chat.document().find("粗體回答")
        self.assertEqual(answer_cursor.charFormat().foreground().color().name(), "#182b36")
        self.assertEqual(w.store.load(identifier)["turns"][0]["answer"], answer)

    def test_appearance_switch_preserves_draft_markdown_and_stream_anchor(self):
        from labchat.theme import apply_theme, current_theme

        w = self.window()
        try:
            w.input.setPlainText("未送出的草稿")
            w.input.insertPlainText("新增")
            draft = w.input.toPlainText()
            w._begin_turn("原始問題")
            anchor = QTextCursor(w.chat.document())
            anchor.movePosition(QTextCursor.MoveOperation.End)
            anchor.setKeepPositionOnInsert(True)
            position = anchor.position()
            w.append("串流中的暫存文字")
            w.toggle_appearance()
            self.assertEqual(current_theme(), "dark")
            self.assertEqual(w.input.toPlainText(), draft)
            self.assertTrue(w.input.document().isUndoAvailable())
            self.assertEqual(anchor.position(), position)
            w._render_answer("**粗體回答**\n\n- 清單", anchor)
            selected = w.chat.document().find("粗體回答")
            self.assertEqual(selected.charFormat().foreground().color().name(), "#e6edf5")
            self.assertGreaterEqual(selected.charFormat().fontWeight(), 600)
            prompt = w.chat.document().find("原始問題")
            self.assertEqual(
                prompt.currentFrame().frameFormat().background().color().name(), "#233453"
            )
            w.toggle_appearance()
            self.assertEqual(selected.charFormat().foreground().color().name(), "#182b36")
            self.assertEqual(w.input.toPlainText(), draft)
        finally:
            apply_theme(w, "light")

    def test_sidebar_cards_keep_selection_and_search(self):
        w = self.window()
        first = w.store.append(None, "qwen3.5:2b", "分析圖片情境", "回答")
        second = w.store.append(None, "qwen3.5:2b", "Hi", "您好")
        w.conversation_id = first
        w._refresh_sidebar()
        self.assertEqual(w.sidebar.items.currentItem().data(Qt.ItemDataRole.UserRole), first)
        self.assertIn("border:1px solid", w.sidebar.items.styleSheet())
        w.sidebar.search.setText("Hi")
        wait_for(lambda: not w.sidebar.search_timer.isActive())
        visible = [
            w.sidebar.items.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(w.sidebar.items.count())
            if not w.sidebar.items.item(i).isHidden()
        ]
        self.assertEqual(visible, [second])

    def test_sidebar_full_height_and_composer_only_in_right_workspace(self):
        from PySide6.QtCore import QPoint

        w = self.window()
        w.resize(1200, 900)
        w.show()
        QTest.qWait(20)
        self.assertTrue(w.sidebar.isVisible())
        self.assertFalse(w.compact_new.isVisible())
        self.assertIs(w.clear, w.sidebar.new_button)
        self.assertIs(w.composer.parentWidget(), w.workspace_panel)
        self.assertEqual(w.sidebar.geometry().bottom(), w.workspace_panel.geometry().bottom())
        self.assertGreater(w.composer.mapTo(w, QPoint(0, 0)).x(), w.sidebar.geometry().right())
        w.resize(720, 680)
        QTest.qWait(20)
        self.assertFalse(w.sidebar.isVisible())
        self.assertTrue(w.compact_new.isVisible())
        self.assertLessEqual(w.composer.geometry().right(), w.workspace_panel.width())

    def test_inline_activity_tracks_waiting_receiving_and_cancellation(self):
        w = self.window()
        w.show()
        self.server.mode = "slow"
        w.input.setPlainText("載入狀態測試")
        w.submit()
        self.assertTrue(w.assistant_activity.active)
        self.assertTrue(w.assistant_activity.spinner.timer.isActive())
        self.assertIn("準備模型", w.assistant_activity.label.text())
        w._on_chunk("測試文字")
        self.assertIn("正在產生回答", w.assistant_activity.label.text())
        w.cancel()
        wait_for(lambda: not w.client.active)
        self.assertFalse(w.assistant_activity.active)
        self.assertFalse(w.assistant_activity.timer.isActive())
        self.assertTrue(w.assistant_activity.isHidden())
        self.assertEqual(w.input.toPlainText(), "載入狀態測試")

    def test_inline_activity_cleans_up_success_failure_and_shutdown(self):
        w = self.window()
        for mode in ("normal", "http_error"):
            self.server.mode = mode
            w.input.setPlainText("測試")
            w.submit()
            wait_for(lambda: not w.client.active)
            self.assertFalse(w.assistant_activity.active)
            self.assertFalse(w.assistant_activity.spinner.timer.isActive())
        self.server.mode = "slow"
        w.submit()
        self.assertTrue(w.assistant_activity.active)
        w.shutdown()
        self.assertFalse(w.assistant_activity.active)
        self.assertFalse(w.assistant_activity.timer.isActive())

    def test_compact_new_conversation_is_guarded_during_recording(self):
        w = self.window()
        w.input.setPlainText("不要遺失的草稿")
        w.dictation.state = "recording"
        w.request_new_conversation()
        self.assertEqual(w.input.toPlainText(), "不要遺失的草稿")
        w.dictation.state = "idle"

    def test_missing_model_preserves_prompt_and_opens_settings(self):
        w = self.window()
        w.installed_models = set()
        w.input.setPlainText("尚未下載，請保留我的問題")
        with patch.object(w, "open_model_settings") as settings:
            w.submit()
            settings.assert_called_once()
        self.assertFalse(w.client.active)
        self.assertEqual(w.input.toPlainText(), "尚未下載，請保留我的問題")
        self.assertIn("尚未下載", w.status.text())

    def test_cancel_generation_stops_speech_queue_immediately(self):
        w = self.window()
        with (
            patch.object(w.speech_panel, "stop_reading") as stop,
            patch.object(w.client, "cancel") as cancel,
        ):
            w.cancel()
            stop.assert_called_once()
            cancel.assert_called_once()

    def test_dictation_appends_without_sending_and_interlocks(self):
        w = self.window()
        w.input.setPlainText("原有草稿")
        w.dictation._set_state("recording", "測試狀態，不錄音")
        self.assertFalse(w.send.isEnabled())
        self.assertFalse(w.model.isEnabled())
        w.submit()
        self.assertFalse(w.client.active)
        w.dictation._set_state("transcribing", "辨識中")
        self.assertTrue(w.dictation.spinner.timer.isActive())
        w.dictation._set_state("idle", "完成")
        w.dictation.text_ready.emit("辨識文字")
        self.assertEqual(w.input.toPlainText(), "原有草稿\n辨識文字")
        self.assertFalse(w.client.active)
        self.assertTrue(w.send.isEnabled())
        self.assertTrue(w.model.isEnabled())
        self.assertFalse(w.dictation.spinner.timer.isActive())

    def test_window_commit_cancel_retry_and_reset(self):
        w = self.window()
        w.input.setPlainText("問題")
        w.submit()
        w.submit()
        wait_for(lambda: not w.client.active)
        self.assertEqual(len(w.history), 2)
        self.assertEqual(w.answer, "測試回答")
        self.assertEqual(w.input.toPlainText(), "")
        self.assertIn("測試回答", w.chat.toPlainText())
        identifier = w.conversation_id
        self.assertEqual(len(w.store.load(identifier)["turns"]), 1)
        self.server.mode = "slow"
        w.input.setPlainText("保留輸入")
        w.image = "test-image"
        w.submit()
        w.cancel()
        wait_for(lambda: not w.client.active)
        self.assertEqual(len(w.history), 2)
        self.assertEqual(w.input.toPlainText(), "保留輸入")
        self.assertEqual(w.image, "test-image")
        self.assertTrue(w.send.isEnabled())
        self.assertEqual(len(w.store.load(identifier)["turns"]), 1)
        self.server.mode = "normal"
        w.submit()
        wait_for(lambda: not w.client.active)
        self.assertIsNone(w.image)
        self.assertEqual(len(w.history), 4)
        self.assertNotIn("images", str(w.history))
        w.reset()
        self.assertEqual(w.history, [])
        self.assertEqual(w.pages.currentIndex(), 0)
        self.assertEqual(len(w.store.load(identifier)["turns"]), 2)

    def test_open_saved_conversation_restores_model_and_recent_context(self):
        w = self.window()
        identifier = w.store.append(None, "qwen3.5:4b", "<b>問題</b>", "舊回答", True)
        w.store.append(identifier, "qwen3.5:4b", "續問", "新回答")
        self.assertTrue(w.load_conversation(identifier))
        self.assertEqual(w.conversation_id, identifier)
        self.assertEqual(w.model.currentData(), "qwen3.5:4b")
        self.assertEqual(len(w.history), 4)
        self.assertIn("<b>問題</b>", w.chat.toPlainText())
        self.assertIn("圖片提問", w.chat.toPlainText())
        self.assertEqual(w.speech_panel.answer, "新回答")
        self.assertIsNone(w.image)

    def test_storage_failure_keeps_successful_reply_and_reports_unsaved_state(self):
        w = self.window()
        w.input.setPlainText("問題")
        with patch.object(w.store, "append", side_effect=HistoryError("磁碟儲存失敗")):
            w.submit()
            wait_for(lambda: not w.client.active)
        self.assertTrue(w.archive_failed)
        self.assertIn("磁碟儲存失敗", w.status.text())
        w._on_service_checked({"qwen3.5:2b"}, "")
        self.assertIn("磁碟儲存失敗", w.status.text())
        self.assertIn("測試回答", w.chat.toPlainText())
        self.assertEqual(len(w.history), 2)
        self.assertEqual(w.store.list(), [])

    def test_load_history_decline_preserves_draft_and_current_context(self):
        w = self.window()
        identifier = w.store.append(None, "qwen3.5:2b", "舊問題", "舊回答")
        w.input.setPlainText("未送出草稿")
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.No
        ):
            self.assertFalse(w.load_conversation(identifier))
        self.assertEqual(w.input.toPlainText(), "未送出草稿")
        self.assertIsNone(w.conversation_id)

    def test_delete_current_archive_clears_model_context_but_keeps_draft(self):
        w = self.window()
        identifier = w.store.append(None, "qwen3.5:2b", "私有問題", "私有回答")
        w.load_conversation(identifier)
        w.input.setPlainText("保留草稿")
        w.store.delete(identifier)
        w._history_deleted(identifier)
        self.assertEqual(w.history, [])
        self.assertEqual(w.chat.toPlainText(), "")
        self.assertEqual(w.input.toPlainText(), "保留草稿")

    def test_history_browser_empty_filter_rename_and_confirmed_delete(self):
        w = self.window()
        dialog = ConversationDialog(w.store, w)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.open_button.isEnabled())
        identifier = w.store.append(None, "qwen3.5:2b", "測試紀錄", "回答")
        dialog.refresh()
        dialog.items.setCurrentRow(0)
        self.assertTrue(dialog.open_button.isEnabled())
        dialog.search.setText("不存在")
        self.assertFalse(dialog.open_button.isEnabled())
        dialog.search.clear()
        with patch(
            "labchat.conversation_widgets.QInputDialog.getText", return_value=("新名稱", True)
        ):
            dialog.rename_selected()
        self.assertEqual(w.store.load(identifier)["title"], "新名稱")
        dialog.items.setCurrentRow(0)
        with patch(
            "labchat.conversation_widgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            dialog.delete_selected()
        self.assertEqual(len(w.store.list()), 1)
        with patch(
            "labchat.conversation_widgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.delete_selected()
        self.assertEqual(w.store.list(), [])
        self.assertFalse(dialog.open_button.isEnabled())

    def test_mode_switch_clears_old_conversation(self):
        w = self.window()
        w.history = [{"role": "user", "content": "old"}]
        w.model.setCurrentIndex(1)
        self.assertEqual(w.history, [])
        self.assertEqual(w.model.currentData(), "qwen3.5:4b")

    def test_french_google_models_show_real_installation_state_and_can_switch(self):
        w = self.window()
        models = {"ministral-3:3b", "gemma3:4b"}
        w._on_service_checked(models, "")
        for identifier in models:
            index = w.model.findData(identifier)
            self.assertGreaterEqual(index, 0)
            self.assertIn("已安裝", w.model.itemText(index))
            w.model.setCurrentIndex(index)
            self.assertEqual(w.model.currentData(), identifier)
            self.assertIn("圖片", w.model_note.text())

    def test_picture_opt_in_restores_pixels_boxes_and_supports_reuse(self):
        from test_attachments import png_data

        from labchat.grounding import Box

        w = self.window()
        w.store.set_pictures(True)
        w.image = w.last_image = png_data()
        original = w.image
        w.annotation_boxes = [Box("原框", (0, 0, 500, 500), "manual")]
        w.input.setPlainText("這張圖是什麼？")
        w.submit()
        wait_for(lambda: not w.client.active)
        identifier = w.conversation_id
        sequence = w.store.last_sequence
        self.assertEqual(w.store.load_picture(identifier, sequence)[0], original)
        w.reset()
        self.assertTrue(w.load_conversation(identifier))
        self.assertIsNone(w.image)
        self.assertEqual(w.last_image, original)
        self.assertEqual(len(w.annotation_boxes), 1)
        w.open_annotation()
        w.annotation_dialog.canvas.boxes = [Box("修正框", (100, 100, 600, 600), "manual")]
        w.annotation_dialog.reject()
        self.assertEqual(w.store.load_picture(identifier, sequence)[1][0].label, "修正框")
        w.reuse_picture()
        self.assertEqual(w.image, original)

    def test_disabled_saving_does_not_write_turns_or_drafts(self):
        w = self.window()
        w.store.set_saving(False)
        w.input.setPlainText("不保存的問題")
        w._save_draft()
        w.submit()
        wait_for(lambda: not w.client.active)
        self.assertEqual(w.store.list(), [])
        self.assertEqual(w.store.get_draft("new:qwen3.5:2b"), "")
        self.assertIn("測試回答", w.chat.toPlainText())

    def test_draft_switches_are_isolated_by_model_and_archived_conversation(self):
        w = self.window()
        w.input.setPlainText("2B新草稿")
        w.model.setCurrentIndex(1)
        self.assertEqual(w.input.toPlainText(), "")
        w.input.setPlainText("4B新草稿")
        w.model.setCurrentIndex(0)
        self.assertEqual(w.input.toPlainText(), "2B新草稿")
        identifier = w.store.append(None, "qwen3.5:2b", "先前問答", "先前回答")
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            w.load_conversation(identifier)
        w.input.setPlainText("特定對話草稿")
        w.reset()
        self.assertEqual(w.input.toPlainText(), "2B新草稿")
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            w.load_conversation(identifier)
        self.assertEqual(w.input.toPlainText(), "特定對話草稿")

    def test_privacy_setting_requires_confirmation_and_clear_requires_confirmation(self):
        w = self.window()
        w.store.append(None, "qwen3.5:2b", "保留問題", "保留回答")
        dialog = ConversationDialog(w.store, w)
        self.addCleanup(dialog.deleteLater)
        with patch(
            "labchat.conversation_widgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            dialog.saving.setChecked(False)
            dialog.clear_records()
        self.assertTrue(w.store.saving_enabled())
        self.assertEqual(len(w.store.list()), 1)
        with patch(
            "labchat.conversation_widgets.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.saving.setChecked(False)
            dialog.clear_records()
        self.assertFalse(w.store.saving_enabled())
        self.assertEqual(w.store.list(), [])

    def test_failed_draft_save_can_cancel_window_close(self):
        w = self.window()
        w.input.setPlainText("保留最後草稿")
        event = QCloseEvent()
        with (
            patch.object(w, "_save_draft", return_value=False),
            patch(
                "labchat.window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.No,
            ),
        ):
            w.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertFalse(w._closing)
        self.assertEqual(w.input.toPlainText(), "保留最後草稿")

    def test_chinese_composition_and_shift_enter(self):
        w = self.window()
        w.input.setPlainText("草稿")
        QTest.keyClick(w.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertIn("\n", w.input.toPlainText())
        w.input.inputMethodEvent(QInputMethodEvent("注音", []))
        QTest.keyClick(w.input, Qt.Key.Key_Return)
        self.assertFalse(w.client.active)

    def test_image_demo_requires_attachment(self):
        w = self.window()
        w.input.setPlainText("請分析我附加的圖片，說明主題。")
        w.submit()
        self.assertFalse(w.client.active)
        self.assertIn("先按", w.status.text())

    def test_failed_reply_keeps_draft_without_history(self):
        w = self.window()
        self.server.mode = "broken"
        w.input.setPlainText("不應加入紀錄")
        w.submit()
        wait_for(lambda: not w.client.active)
        self.assertEqual(w.history, [])
        self.assertEqual(w.input.toPlainText(), "不應加入紀錄")
        self.assertTrue(w.send.isEnabled())
        self.assertIn("請求失敗", w.chat.toPlainText())

    def test_close_window_aborts_without_committing(self):
        w = self.window()
        self.server.mode = "slow"
        w.input.setPlainText("closing")
        w.submit()
        w.close()
        QTest.qWait(450)
        self.assertFalse(w.client.active)
        self.assertEqual(w.history, [])
        self.assertIsNone(w.pending)

    def test_reply_html_is_plain_text_and_normal_weight(self):
        w = self.window()
        w.append("<b>not markup</b>")
        self.assertIn("<b>not markup</b>", w.chat.toPlainText())
        cursor = w.chat.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.movePosition(cursor.MoveOperation.PreviousCharacter)
        self.assertEqual(cursor.charFormat().fontWeight(), 400)

    def test_transcript_is_bounded(self):
        from labchat.config import MAX_TRANSCRIPT_CHARS

        w = self.window()
        w.append("x" * (MAX_TRANSCRIPT_CHARS + 10))
        w._trim_transcript()
        self.assertLessEqual(w.chat.document().characterCount(), MAX_TRANSCRIPT_CHARS)

    def test_recovery_updates_service_status(self):
        w = self.window()
        w._on_service_checked(None, "服務未啟動")
        self.assertIn("未連線", w.badge.text())
        w._on_service_checked({"qwen3.5:2b"}, "")
        self.assertIn("已就緒", w.status.text())
        self.assertIn("已安裝", w.model.currentText())

    def test_manual_service_check_has_progress_and_visible_result(self):
        w = self.window()
        self.server.mode = "catalog_slow"
        w.input.setPlainText("保留草稿")
        w.service_action.trigger()
        self.assertTrue(w.service_dialog.isVisible())
        self.assertTrue(w.service_dialog.spinner.timer.isActive())
        self.assertFalse(w.service_dialog.retry.isEnabled())
        reply = w.probe.reply
        w.show_service_status()
        self.assertIs(w.probe.reply, reply)
        wait_for(lambda: w.service_dialog.retry.isEnabled())
        self.assertIn("可以開始對話", w.service_dialog.heading.text())
        self.assertIn(self.url, w.service_dialog.details.text())
        self.assertIn("檢查時間", w.service_dialog.details.text())
        self.assertFalse(w.service_dialog.spinner.timer.isActive())
        self.assertEqual(w.input.toPlainText(), "保留草稿")
        w.service_dialog.close()
        w._on_service_checked({"qwen3.5:2b"}, "")
        self.assertFalse(w.service_dialog.isVisible())

    def test_service_check_failure_and_missing_model_are_actionable(self):
        w = self.window()
        w._on_service_checked(set(), "")
        self.assertIn("尚未安裝", w.service_dialog.heading.text())
        self.assertIn("模型設定", w.service_dialog.details.text())
        self.server.mode = "catalog_bad"
        w.show_service_status()
        wait_for(lambda: w.service_dialog.retry.isEnabled())
        self.assertIn("無法確認服務狀態", w.service_dialog.heading.text())
        self.assertIn("ollama serve", w.service_dialog.details.text())
        self.server.mode = "normal"
        w.service_dialog.retry.click()
        wait_for(lambda: w.service_dialog.retry.isEnabled())
        self.assertIn("可以開始對話", w.service_dialog.heading.text())

    def test_catalog_has_total_deadline_and_can_retry(self):
        probe = ServiceProbe(self.client.network, base_url=self.url, timeout_ms=40)
        self.addCleanup(probe.deleteLater)
        self.addCleanup(probe.shutdown)
        results = []
        probe.updated.connect(lambda models, error: results.append((models, error)))
        self.server.mode = "catalog_slow"
        probe.refresh()
        wait_for(lambda: bool(results))
        self.assertIsNone(results[0][0])
        self.assertTrue(results[0][1])
        self.assertFalse(probe.deadline.isActive())
        self.server.mode = "normal"
        results.clear()
        probe.timeout_ms = 1000
        probe.refresh()
        wait_for(lambda: bool(results))
        self.assertEqual(results[0], ({"qwen3.5:2b"}, ""))

    def test_cancel_from_chunk_then_immediate_restart_has_no_stale_events(self):
        stopped = False

        def stop_first_chunk(text):
            nonlocal stopped
            if not stopped:
                stopped = True
                self.client.cancel()

        def restart(result):
            if result.status == "cancelled":
                self.client.start("qwen3.5:2b", [{"role": "user", "content": "restart"}])

        self.client.chunk.connect(stop_first_chunk)
        self.client.completed.connect(restart)
        self.start()
        wait_for(lambda: len(self.results) == 2)
        self.assertEqual([result.status for result in self.results], ["cancelled", "success"])
        self.assertEqual(self.results[1].answer, "測試回答")
        self.assertFalse(self.client.active)

    def test_fifty_completed_requests_release_reply_objects(self):
        from PySide6.QtNetwork import QNetworkReply

        for _ in range(50):
            self.results.clear()
            self.start()
            self.assertEqual(self.result().status, "success")
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(self.client.network.findChildren(QNetworkReply), [])

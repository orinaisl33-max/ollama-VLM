"""Data-loss guards, preference restart and microphone settings without recording."""

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QByteArray
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtWidgets import QApplication, QMessageBox

from labchat.conversations import ConversationStore, HistoryError
from labchat.dictation import DictationPanel, audio_level
from labchat.grounding import Box
from labchat.preferences import DEFAULTS
from labchat.speech import Voice
from labchat.theme import apply_theme, current_theme
from labchat.window import Window

APP = QApplication.instance() or QApplication([])


class SwitchProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.w = Window(history_path=Path(self.temp.name) / "test.sqlite3")
        self.addCleanup(self.w.deleteLater)
        self.addCleanup(self.w.shutdown)

    def test_oversize_draft_new_conversation_preserves_unsaved_input(self):
        w = self.w
        w.input.setPlainText("已存草稿")
        self.assertTrue(w._save_draft())
        w.input.setPlainText("字" * 16001)
        w.request_new_conversation()
        self.assertEqual(w.input.toPlainText(), "字" * 16001)
        self.assertIn("已停止切換", w.status.text())
        w._on_service_checked({"qwen3.5:2b"}, "")
        self.assertIn("已停止切換", w.status.text())

    def test_write_failure_blocks_model_switch_and_keeps_context(self):
        w = self.w
        w.input.setPlainText("不能遺失")
        before = w._draft_key
        with patch.object(w.store, "save_draft", side_effect=HistoryError("寫入失敗")):
            w.model.setCurrentIndex(1)
        self.assertEqual(w.model.currentIndex(), 0)
        self.assertEqual(w._draft_key, before)
        self.assertEqual(w.input.toPlainText(), "不能遺失")
        self.assertEqual(w.store.get_preferences()["model"], "qwen3.5:2b")

    def test_failed_save_blocks_history_load(self):
        w = self.w
        identifier = w.store.append(None, "qwen3.5:4b", "舊問題", "舊回答")
        w.input.setPlainText("保留目前輸入")
        with patch.object(w, "_save_draft", return_value=False):
            self.assertFalse(w.load_conversation(identifier))
        self.assertIsNone(w.conversation_id)
        self.assertEqual(w.input.toPlainText(), "保留目前輸入")

    def test_failed_target_draft_read_preserves_model_and_attachment(self):
        w = self.w
        w.input.setPlainText("保留輸入")
        w.image = "test-state"
        with (
            patch(
                "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
            ),
            patch.object(w.store, "get_draft", side_effect=HistoryError("讀取失敗")),
        ):
            w.model.setCurrentIndex(1)
        self.assertEqual(w.model.currentIndex(), 0)
        self.assertEqual(w.image, "test-state")
        self.assertEqual(w.input.toPlainText(), "保留輸入")

    def test_declined_model_switch_keeps_attachment_boxes_and_draft(self):
        w = self.w
        w.input.setPlainText("目前草稿")
        w.image = w.last_image = "test-state"
        boxes = [Box("人工框", (0, 0, 500, 500), "manual")]
        w.annotation_boxes = list(boxes)
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.No
        ) as ask:
            w.model.setCurrentIndex(1)
            ask.assert_called_once()
        self.assertEqual(w.model.currentIndex(), 0)
        self.assertEqual(w.image, "test-state")
        self.assertEqual(w.annotation_boxes, boxes)
        self.assertEqual(w.input.toPlainText(), "目前草稿")

    def test_confirmed_switch_saves_original_draft_and_clears_attachment(self):
        w = self.w
        w.input.setPlainText("原模型草稿")
        w.image = "test-state"
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            w.model.setCurrentIndex(1)
        self.assertIsNone(w.image)
        self.assertEqual(w.model.currentData(), "qwen3.5:4b")
        self.assertEqual(w.store.get_draft("new:qwen3.5:2b"), "原模型草稿")
        self.assertEqual(w.store.get_preferences()["model"], "qwen3.5:4b")

    def test_disabled_saving_requires_confirmation_before_discarding_text(self):
        w = self.w
        w.store.set_saving(False)
        w.input.setPlainText("未保存文字")
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.No
        ) as ask:
            w.request_new_conversation()
            ask.assert_called_once()
        self.assertEqual(w.input.toPlainText(), "未保存文字")

    def test_new_conversation_with_image_only_can_be_cancelled(self):
        w = self.w
        w.image = w.last_image = "test-state"
        with patch(
            "labchat.window.QMessageBox.question", return_value=QMessageBox.StandardButton.No
        ):
            w.request_new_conversation()
        self.assertEqual(w.image, "test-state")

    def test_second_save_failure_rolls_back_model_before_any_reset(self):
        w = self.w
        w.input.setPlainText("保留原始草稿")
        with patch.object(w.store, "save_draft", side_effect=[None, HistoryError("再次寫入失敗")]):
            w.model.setCurrentIndex(1)
        self.assertEqual(w.model.currentIndex(), 0)
        self.assertEqual(w._draft_model, "qwen3.5:2b")
        self.assertEqual(w.input.toPlainText(), "保留原始草稿")


class PreferenceTests(unittest.TestCase):
    def test_preferences_roundtrip_and_invalid_write_preserves_previous(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.sqlite3"
            store = ConversationStore(path)
            self.assertEqual(store.get_preferences(), DEFAULTS)
            prefs = {**DEFAULTS, "appearance": "dark", "model": "gemma3:4b", "microphone": "0102"}
            store.save_preferences(prefs)
            for bad in (
                {"model": "not-allowed"},
                {"speech_rate": True},
                {"microphone": "xyz"},
                {"command": "bad"},
            ):
                with self.assertRaises(HistoryError):
                    store.save_preferences(bad)
                self.assertEqual(store.get_preferences(), prefs)
            store.close()
            store = ConversationStore(path)
            try:
                self.assertEqual(store.get_preferences(), prefs)
            finally:
                store.close()

    def test_restart_restores_controls_without_playback_or_recording(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "prefs.sqlite3"
            w = Window(history_path=path)
            w.speech_panel._voices_ready([Voice("Meijia", "zh_TW"), Voice("Tingting", "zh_CN")])
            w.toggle_appearance()
            w.model.setCurrentIndex(4)
            w.speech_panel.rate.setCurrentIndex(2)
            w.speech_panel.voice.setCurrentIndex(1)
            w.speech_panel.mode.setCurrentIndex(1)
            w.shutdown()
            w.deleteLater()
            with patch("labchat.speech.SpeechController.speak") as speak:
                restored = Window(history_path=path)
                try:
                    restored.speech_panel._voices_ready(
                        [Voice("Meijia", "zh_TW"), Voice("Tingting", "zh_CN")]
                    )
                    self.assertEqual(current_theme(), "dark")
                    self.assertEqual(restored.model.currentData(), "gemma3:4b")
                    self.assertEqual(restored.speech_panel.voice.currentData(), "Tingting")
                    self.assertEqual(restored.speech_panel.rate.currentData(), 205)
                    self.assertEqual(restored.speech_panel.mode.currentData(), "stream")
                    self.assertEqual(restored.dictation.state, "idle")
                    self.assertIsNone(restored.dictation.source)
                    speak.assert_not_called()
                finally:
                    apply_theme(restored, "light")
                    restored.shutdown()
                    restored.deleteLater()

    def test_corrupt_preferences_do_not_disable_chat_store(self):
        with tempfile.TemporaryDirectory() as d:
            store = ConversationStore(Path(d) / "prefs.sqlite3")
            try:
                store.connection.execute(
                    "INSERT INTO settings VALUES ('ui_preferences',?)",
                    (json.dumps({"speech_rate": 999}),),
                )
                store.connection.commit()
                with self.assertRaises(HistoryError):
                    store.get_preferences()
                identifier = store.append(None, "qwen3.5:2b", "問", "答")
                self.assertEqual(store.load(identifier)["turns"][0]["answer"], "答")
            finally:
                store.close()

    def test_missing_saved_voice_falls_back_to_available_voice(self):
        with tempfile.TemporaryDirectory() as d:
            w = Window(history_path=Path(d) / "prefs.sqlite3")
            try:
                w.speech_panel.preferred_voice = "Unavailable voice"
                w.speech_panel._voices_ready([Voice("Meijia", "zh_TW")])
                self.assertEqual(w.speech_panel.voice.currentData(), "Meijia")
                self.assertFalse(w.speech_panel.controller.active)
            finally:
                w.shutdown()
                w.deleteLater()


class MicrophoneSettingsTests(unittest.TestCase):
    def setUp(self):
        self.panel = DictationPanel()
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.shutdown)

    def test_refresh_without_input_never_records_or_requests_permission(self):
        panel = self.panel
        with (
            patch("labchat.dictation.QMediaDevices.audioInputs", return_value=[]),
            patch.object(panel, "toggle") as toggle,
        ):
            panel.refresh_inputs()
            self.assertIn("未偵測到麥克風", panel.diagnostics.text())
            self.assertEqual(panel.devices.count(), 1)
            toggle.assert_not_called()
            self.assertIsNone(panel.source)

    def test_selected_missing_device_never_silently_uses_default(self):
        panel = self.panel
        with patch("labchat.dictation.QMediaDevices.audioInputs", return_value=[]):
            panel.set_preferred_device("0102")
            self.assertIsNone(panel._input_device())
            self.assertEqual(panel.devices.currentData(), "0102")
            self.assertIn("未連接", panel.devices.currentText())

    def test_device_selection_and_disconnect_cancel_only_active_recording(self):
        panel = self.panel
        device = Mock()
        device.id.return_value = QByteArray(b"usb")
        device.description.return_value = "USB test microphone"
        with patch("labchat.dictation.QMediaDevices.audioInputs", return_value=[device]):
            panel.refresh_inputs()
            panel.devices.setCurrentIndex(1)
            self.assertIs(panel._input_device(), device)
            self.assertEqual(panel.preferred_device, b"usb".hex())
        panel.state = "recording"
        panel._active_device = b"usb".hex()
        with (
            patch("labchat.dictation.QMediaDevices.audioInputs", return_value=[]),
            patch.object(panel, "cancel") as cancel,
        ):
            panel._devices_changed()
            cancel.assert_called_once()
        panel.state = "transcribing"
        with (
            patch("labchat.dictation.QMediaDevices.audioInputs", return_value=[]),
            patch.object(panel, "cancel") as cancel,
        ):
            panel._devices_changed()
            cancel.assert_not_called()

    def test_level_handles_silence_peak_nonfinite_and_partial_frames(self):
        fmt = QAudioFormat()
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.assertEqual(audio_level(b"\x00" * 20, fmt), 0)
        self.assertEqual(audio_level(struct.pack("<h", 16384) + b"\x01", fmt), 50)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self.assertEqual(audio_level(struct.pack("<ff", float("nan"), float("inf")), fmt), 0)
        self.assertEqual(audio_level(struct.pack("<f", 2.0), fmt), 100)

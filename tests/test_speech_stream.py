"""Stream speech tests never use real speakers or a network service."""

import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from labchat.speech import Voice
from labchat.speech_stream import SentenceBuffer
from labchat.speech_widgets import SpeechPanel

APP = QApplication.instance() or QApplication([])


class BufferTests(unittest.TestCase):
    def test_sentence_emits_before_generation_finishes(self):
        buffer = SentenceBuffer()
        self.assertEqual(buffer.feed("這是一段還沒有說完的文字"), [])
        ready = buffer.feed("，現在這個完整句子已經結束。後面繼續")
        self.assertEqual(len(ready), 1)
        self.assertNotIn("後面繼續", ready[0])
        self.assertEqual(buffer.feed("", final=True), ["後面繼續"])
        self.assertEqual(buffer.feed("", final=True), [])

    def test_fences_and_tables_across_single_character_chunks(self):
        buffer = SentenceBuffer()
        text = "開始說明。\n```python\nsecret_command()\n```\n| 名稱 | 數量 |\n|---|---|\n| 橘子 | 1 |\n\n最後一段。"
        spoken = []
        for char in text:
            spoken.extend(buffer.feed(char))
        spoken.extend(buffer.feed("", final=True))
        result = "".join(spoken)
        self.assertNotIn("secret_command", result)
        self.assertNotIn("橘子", result)
        self.assertIn("最後一段", result)
        self.assertEqual(result.count("程式碼區塊已略過"), 1)
        self.assertEqual(result.count("表格內容請參閱畫面"), 1)

    def test_decimal_url_and_inline_code_not_split_in_middle(self):
        buffer = SentenceBuffer()
        ready = buffer.feed("測試資料的數字為 3.14，連結是 https://example.com/a。這裡才是結尾。")
        result = "".join(ready + buffer.feed("", final=True))
        self.assertIn("3.14", result)
        self.assertNotIn("https://", result)
        self.assertIn("連結已略過", result)

    def test_controls_removed_across_chunks(self):
        buffer = SentenceBuffer()
        result = []
        for text in ["正常文字 [[ra", "te 900]] 現在是一句完整的內容。", "\n"]:
            result.extend(buffer.feed(text))
        self.assertNotIn("[[", "".join(result))
        self.assertNotIn("rate", "".join(result))

    def test_unclosed_code_not_read(self):
        buffer = SentenceBuffer()
        result = buffer.feed("```\n不應朗讀的內容", final=True)
        self.assertNotIn("不應朗讀", "".join(result))


class StreamPanelTests(unittest.TestCase):
    def setUp(self):
        self.panel = SpeechPanel(auto_discover=False)
        self.panel.controller.voices = [Voice("Meijia", "zh_TW")]
        self.panel._voices_ready(self.panel.controller.voices)
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.shutdown)
        self.spoken = []

    def speak(self, text, voice, rate):
        self.spoken.append(text)
        self.panel.controller.active = True
        return True

    def done(self):
        self.panel.controller.active = False
        self.panel._activity_changed(False)
        QTest.qWait(10)

    def test_stream_starts_before_done_and_tail_once(self):
        panel = self.panel
        panel.mode.setCurrentIndex(1)
        with patch.object(panel.controller, "speak", side_effect=self.speak):
            panel.begin_generation()
            panel.feed_generation("第一段已經足夠完整，可以開始進行語音朗讀。")
            self.assertEqual(len(self.spoken), 1)
            self.assertTrue(panel.generating)
            panel.feed_generation("第二段繼續產生，不能與上一段重疊。")
            self.assertEqual(len(self.spoken), 1)
            panel.finish_generation("完整回答原文")
            self.done()
            self.done()
            result = "".join(self.spoken)
            self.assertEqual(result.count("第一段"), 1)
            self.assertEqual(result.count("第二段"), 1)
            self.assertNotIn("完整回答原文", result)

    def test_stop_clears_queue_and_remaining_generation(self):
        panel = self.panel
        panel.mode.setCurrentIndex(1)
        with (
            patch.object(panel.controller, "speak", side_effect=self.speak),
            patch.object(panel.controller, "stop"),
        ):
            panel.begin_generation()
            panel.feed_generation("第一段已經足夠完整，可以開始進行語音朗讀。")
            panel.feed_generation("待播內容\n")
            panel.stop_reading()
            panel.feed_generation("停止後不得朗讀\n")
            panel.finish_generation("停止後不得朗讀")
            self.done()
            self.assertEqual(len(self.spoken), 1)
            self.assertEqual(panel._segments, [])

    def test_cancelled_generation_does_not_play_tail(self):
        panel = self.panel
        panel.mode.setCurrentIndex(1)
        with patch.object(panel.controller, "speak") as speak:
            panel.begin_generation()
            panel.feed_generation("尚未結束")
            panel.finish_generation("")
            speak.assert_not_called()

    def test_mode_change_mid_generation_does_not_restart_reading(self):
        panel = self.panel
        panel.mode.setCurrentIndex(2)
        with patch.object(panel.controller, "speak") as speak:
            panel.begin_generation()
            panel.mode.setCurrentIndex(0)
            panel.finish_generation("不應讀出")
            speak.assert_not_called()

    def test_queue_and_total_budget_are_bounded(self):
        panel = self.panel
        panel.mode.setCurrentIndex(1)
        with patch.object(panel.controller, "speak", side_effect=self.speak):
            panel.begin_generation()
            panel.feed_generation("這是夠長的起始句，可以開始播放並留下後續佇列。\n")
            for _ in range(100):
                panel.feed_generation("待播段落" * 30 + "\n")
            self.assertLessEqual(panel._stream_chars, 8000)
            self.assertLessEqual(len(panel._segments), 64)
            self.assertTrue(panel._stream_stopped)

    def test_short_heading_waits_and_final_short_answer_is_spoken(self):
        panel = self.panel
        panel.mode.setCurrentIndex(1)
        with patch.object(panel.controller, "speak", side_effect=self.speak):
            panel.begin_generation()
            panel.feed_generation("### 標題\n")
            self.assertEqual(self.spoken, [])
            panel.finish_generation("### 標題")
            self.assertEqual(len(self.spoken), 1)
            self.assertIn("標題", self.spoken[0])

    def test_manual_read_still_available_when_mode_off(self):
        panel = self.panel
        with patch.object(panel.controller, "speak") as speak:
            panel.begin_generation()
            panel.feed_generation("回答。")
            panel.finish_generation("回答。")
            speak.assert_not_called()
            panel.read_answer()
            speak.assert_called_once_with("回答。", "Meijia", 175)

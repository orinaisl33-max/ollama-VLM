"""Speech tests use a fake subprocess; no sound is played by automated tests."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from labchat.speech import SpeechController, Voice, parse_voices, prepare_speech
from labchat.speech_widgets import SpeechPanel

APP = QApplication.instance() or QApplication([])


def wait_for(condition):
    deadline = time.monotonic() + 4
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not condition():
        raise AssertionError("Speech subprocess timed out")


class SpeechTextTests(unittest.TestCase):
    def test_parse_localized_names_and_preferred_voice(self):
        voices = parse_voices(
            "Sandy (中文（台灣）) zh_TW # hi\nMeijia zh_TW # hi\nAlex en_US # hi\nTingting zh_CN # hi\nMeijia zh_TW # hi"
        )
        self.assertEqual([v.name for v in voices], ["Meijia", "Sandy (中文（台灣）)", "Tingting"])
        self.assertIn("台灣中文", voices[0].label)

    def test_markdown_and_code_cleaned(self):
        result = prepare_speech(
            '# 標題\n**重點**與[說明](https://example.com)。\n```python\nprint("不應朗讀")\n```\n`變數`'
        )
        self.assertNotIn("print", result.text)
        self.assertNotIn("https", result.text)
        self.assertNotIn("**", result.text)
        self.assertIn("程式碼區塊已略過", result.text)
        self.assertIn("變數", result.text)

    def test_control_sequences_removed_after_unescape(self):
        result = prepare_speech("正常 [[rate 900]] &#91;&#91;volm 0&#93;&#93;\x00文字")
        self.assertNotIn("[[", result.text)
        self.assertNotIn("\x00", result.text)
        self.assertIn("正常", result.text)

    def test_long_text_is_explicitly_truncated(self):
        with patch("labchat.speech.MAX_SPEECH_CHARS", 20):
            result = prepare_speech("長內容。" * 20)
        self.assertTrue(result.truncated)
        self.assertIn("朗讀至此", result.text)

    def test_inline_fences_and_unclosed_speech_controls_removed(self):
        result = prepare_speech("正常。```secret()```結尾。[[rate 999")
        self.assertNotIn("secret", result.text)
        self.assertNotIn("[[", result.text)
        self.assertIn("結尾", result.text)


class SpeechProcessTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.capture = Path(temp.name) / "capture.json"
        self.script = Path(temp.name) / "fake_speech.py"
        self.script.write_text("""import sys,json,time
from pathlib import Path
capture=Path(sys.argv[1]); args=sys.argv[2:]
if args == ['-v','?']:
    print('Meijia zh_TW # test\\nFail zh_CN # test')
else:
    text=sys.stdin.read()
    if 'slow' in text: time.sleep(2)
    capture.write_text(json.dumps({'args':args,'text':text}))
    sys.exit(2 if args[1]=='Fail' else 0)
""")
        self.speech = SpeechController(
            program=sys.executable, prefix_args=[str(self.script), str(self.capture)]
        )
        self.addCleanup(self.speech.deleteLater)
        self.addCleanup(self.speech.shutdown)
        self.errors = []
        self.activities = []
        self.statuses = []
        self.speech.failed.connect(self.errors.append)
        self.speech.activity_changed.connect(self.activities.append)
        self.speech.status_changed.connect(self.statuses.append)
        self.speech.refresh_voices()
        wait_for(lambda: bool(self.speech.voices))

    def test_stdin_text_and_rate_clamp_without_shell(self):
        self.assertTrue(self.speech.speak("中文 $(whoami) `code`", "Meijia", 999))
        wait_for(lambda: not self.speech.active)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured["args"], ["-v", "Meijia", "-r", "260", "-f", "-"])
        self.assertIn("$(whoami)", captured["text"])
        self.assertEqual(self.activities, [True, False])
        self.assertEqual(self.errors, [])

    def test_stop_then_replay(self):
        self.speech.speak("slow", "Meijia")
        self.assertFalse(self.speech.speak("overlap", "Meijia"))
        self.speech.stop()
        wait_for(lambda: not self.speech.active)
        self.assertIn("已停止朗讀", self.statuses)
        self.assertTrue(self.speech.speak("重播", "Meijia"))
        wait_for(lambda: not self.speech.active)
        self.assertEqual(json.loads(self.capture.read_text())["text"], "重播")

    def test_failure_releases_controls(self):
        self.speech.speak("錯誤測試", "Fail")
        wait_for(lambda: not self.speech.active)
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.activities, [True, False])

    def test_failed_to_start_finishes_once(self):
        self.speech.program = "/path/does/not/exist"
        self.speech.speak("失敗", "Meijia")
        wait_for(lambda: not self.speech.active)
        self.assertEqual(len(self.errors), 1)
        self.assertFalse(self.speech.play_timer.isActive())

    def test_shutdown_reaps_process(self):
        self.speech.speak("slow", "Meijia")
        self.speech.shutdown()
        self.assertFalse(self.speech.active)
        self.assertFalse(self.speech.speak("不能重播", "Meijia"))
        self.assertEqual(self.speech.player.state(), self.speech.player.ProcessState.NotRunning)

    def test_unknown_voice_and_empty_text_do_not_start(self):
        self.assertFalse(self.speech.speak("text", "Unknown"))
        self.assertFalse(self.speech.speak("   ", "Meijia"))
        self.assertFalse(self.speech.active)

    def test_timeout_reports_failure_once(self):
        self.speech.speak("slow", "Meijia")
        self.speech.play_timer.start(20)
        wait_for(lambda: not self.speech.active)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("時間上限", self.errors[0])
        self.assertIn("時間上限", self.statuses[-1])

    def test_shutdown_from_start_signal_does_not_spawn(self):
        self.speech.activity_changed.connect(
            lambda active: self.speech.shutdown() if active else None
        )
        self.assertFalse(self.speech.speak("不得啟動", "Meijia"))
        self.assertEqual(self.speech.player.state(), self.speech.player.ProcessState.NotRunning)
        self.assertFalse(self.speech.play_timer.isActive())

    def test_stop_from_start_signal_does_not_spawn(self):
        self.speech.activity_changed.connect(lambda active: self.speech.stop() if active else None)
        self.assertFalse(self.speech.speak("不得啟動", "Meijia"))
        self.assertFalse(self.speech.active)
        self.assertEqual(self.activities, [True, False])

    def test_refresh_failure_clears_stale_voices(self):
        self.speech.program = "/path/does/not/exist"
        self.speech.refresh_voices()
        self.assertEqual(self.speech.voices, [])


class SpeechPanelTests(unittest.TestCase):
    def test_auto_read_only_success_and_stop_on_next_question(self):
        panel = SpeechPanel(auto_discover=False)
        panel.controller.voices = [Voice("Meijia", "zh_TW")]
        panel._voices_ready(panel.controller.voices)
        panel.mode.setCurrentIndex(2)
        with (
            patch.object(panel.controller, "speak", return_value=True) as speak,
            patch.object(panel.controller, "stop") as stop,
        ):
            panel.begin_generation()
            panel.finish_generation("成功回答")
            speak.assert_called_once_with("成功回答", "Meijia", 175)
            panel.begin_generation()
            self.assertFalse(panel.play.isEnabled())
            self.assertGreaterEqual(stop.call_count, 2)
            panel.finish_generation("")
            self.assertEqual(speak.call_count, 1)
            panel.reset()
        panel.shutdown()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_auto_waits_for_previous_process_to_finish_stopping(self):
        panel = SpeechPanel(auto_discover=False)
        panel.controller.voices = [Voice("Meijia", "zh_TW")]
        panel._voices_ready(panel.controller.voices)
        panel.mode.setCurrentIndex(2)
        panel.controller.active = True
        with patch.object(panel.controller, "speak", return_value=True) as speak:
            panel.finish_generation("新回覆")
            speak.assert_not_called()
            panel.controller.active = False
            panel._activity_changed(False)
            QTest.qWait(10)
            speak.assert_called_once_with("新回覆", "Meijia", 175)
        panel.shutdown()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_refresh_prevents_stale_voice_playback_and_resumes_auto(self):
        panel = SpeechPanel(auto_discover=False)
        panel.controller.voices = [Voice("Meijia", "zh_TW")]
        panel._voices_ready(panel.controller.voices)
        panel.mode.setCurrentIndex(2)
        with (
            patch.object(panel.controller, "refresh_voices"),
            patch.object(panel.controller, "speak", return_value=True) as speak,
        ):
            panel.refresh()
            self.assertFalse(panel.voice.isEnabled())
            self.assertFalse(panel.preview.isEnabled())
            panel.finish_generation("等待聲音清單")
            speak.assert_not_called()
            panel._voices_ready(panel.controller.voices)
            QTest.qWait(10)
            speak.assert_called_once_with("等待聲音清單", "Meijia", 175)
        panel.shutdown()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_closing_settings_stops_preview_only(self):
        panel = SpeechPanel(auto_discover=False)
        panel.controller.voices = [Voice("Meijia", "zh_TW")]
        panel._voices_ready(panel.controller.voices)
        with (
            patch.object(panel.controller, "speak", return_value=True),
            patch.object(panel.controller, "stop") as stop,
        ):
            panel.preview_voice()
            panel.dialog.reject()
            stop.assert_called_once()
            stop.reset_mock()
            panel.answer = "一般回答"
            panel.read_answer()
            panel.dialog.reject()
            stop.assert_not_called()
        panel.shutdown()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_missing_voices_disable_auto_and_do_not_attempt_playback(self):
        panel = SpeechPanel(auto_discover=False)
        panel.controller.voices = [Voice("Meijia", "zh_TW")]
        panel._voices_ready(panel.controller.voices)
        panel.mode.setCurrentIndex(2)
        panel._voices_ready([])
        self.assertEqual(panel.mode.currentData(), "off")
        with patch.object(panel.controller, "speak") as speak:
            panel.finish_generation("聲音已移除")
            panel.read_answer()
            speak.assert_not_called()
        panel.shutdown()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

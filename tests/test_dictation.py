"""Offline dictation safety tests; never access the real microphone."""

import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QProcess
from PySide6.QtMultimedia import QAudioFormat, QtAudio
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from labchat.dictation import DictationPanel, pcm16_mono

APP = QApplication.instance() or QApplication([])


def fmt(kind=QAudioFormat.SampleFormat.Int16, rate=16000, channels=1):
    result = QAudioFormat()
    result.setSampleFormat(kind)
    result.setSampleRate(rate)
    result.setChannelCount(channels)
    return result


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not condition():
        raise AssertionError("dictation did not finish")


class AudioTests(unittest.TestCase):
    def test_stereo_float_resampling_and_bounds(self):
        data = struct.pack("<ff", 0.5, 0.25) * 48000
        result = pcm16_mono(data, fmt(QAudioFormat.SampleFormat.Float, 48000, 2))
        self.assertEqual(len(result), 32000)
        self.assertAlmostEqual(struct.unpack_from("<h", result)[0], 12288, delta=1)

    def test_silence_and_short_audio_rejected(self):
        for data in (b"\0" * 32000, b"\1" * 100):
            with self.assertRaises(ValueError):
                pcm16_mono(data, fmt())

    def test_nonfinite_audio_rejected_as_silence(self):
        with self.assertRaises(ValueError):
            pcm16_mono(
                struct.pack("<f", float("nan")) * 16000, fmt(QAudioFormat.SampleFormat.Float)
            )


class LifecycleTests(unittest.TestCase):
    def test_countdown_polls_audio_error_without_native_enum_signal(self):
        self.panel.source = Mock()
        self.panel.source.error.return_value = QtAudio.Error.NoError
        self.panel.state = "recording"
        self.panel.record_clock.start()
        with patch.object(self.panel, "cancel") as cancel:
            self.panel._update_countdown()
            cancel.assert_not_called()
            self.panel.source.error.return_value = QtAudio.Error.OpenError
            self.panel._update_countdown()
            cancel.assert_called_once()
        self.panel.source = None

    def setUp(self):
        self.panel = DictationPanel()
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.shutdown)
        self.texts = []
        self.panel.text_ready.connect(self.texts.append)

    def test_countdown_uses_elapsed_time_and_stops_at_zero(self):
        panel = self.panel
        panel.state = "recording"
        panel.record_clock = Mock()
        panel.record_clock.isValid.return_value = True
        for elapsed, expected, urgent in [
            (0, "30", False),
            (1001, "29", False),
            (25001, "05", True),
        ]:
            panel.record_clock.elapsed.return_value = elapsed
            panel._update_countdown()
            self.assertIn(expected, panel.countdown.text())
            self.assertEqual(panel.countdown.property("urgent"), urgent)
        panel.record_clock.elapsed.return_value = 31000
        with patch.object(panel, "finish_recording") as finish:
            panel._update_countdown()
            self.assertIn("00", panel.countdown.text())
            finish.assert_called_once()

    def test_countdown_timer_stops_on_cancel_and_transcription(self):
        panel = self.panel
        panel._set_state("recording", "錄音")
        panel.countdown_timer.start()
        panel._set_state("transcribing", "辨識")
        self.assertFalse(panel.countdown_timer.isActive())
        self.assertTrue(panel.countdown.isHidden())
        panel.countdown_timer.start()
        panel.cancel()
        self.assertFalse(panel.countdown_timer.isActive())

    def test_missing_dependencies_never_start_capture(self):
        with patch("labchat.dictation.MODEL", Path("/nonexistent-model")):
            self.panel.toggle()
        self.assertEqual(self.panel.state, "idle")
        self.assertIsNone(self.panel.source)

    def test_success_cleanup_and_text_signal(self):
        panel = self.panel
        panel.temp = tempfile.TemporaryDirectory()
        directory = Path(panel.temp.name)
        (directory / "result.txt").write_text("測試辨識文字", encoding="utf-8")
        panel.state = "transcribing"
        panel._finished(0, QProcess.ExitStatus.NormalExit)
        self.assertEqual(self.texts, ["測試辨識文字"])
        self.assertFalse(directory.exists())
        self.assertEqual(panel.state, "idle")

    def test_cancel_running_process_no_text_and_cleanup(self):
        panel = self.panel
        panel.temp = tempfile.TemporaryDirectory()
        directory = Path(panel.temp.name)
        (directory / "result.txt").write_text("不得填入", encoding="utf-8")
        panel.state = "transcribing"
        panel.process.start(sys.executable, ["-c", "import time; time.sleep(10)"])
        wait_for(lambda: panel.process.state() == QProcess.ProcessState.Running)
        panel.cancel()
        wait_for(lambda: panel.state == "idle")
        self.assertEqual(self.texts, [])
        self.assertFalse(directory.exists())
        self.assertFalse(panel.timer.isActive())

    def test_oversized_result_not_emitted(self):
        panel = self.panel
        panel.temp = tempfile.TemporaryDirectory()
        (Path(panel.temp.name) / "result.txt").write_text("x" * 32001)
        panel.state = "transcribing"
        panel._finished(0, QProcess.ExitStatus.NormalExit)
        self.assertEqual(self.texts, [])

    def test_failed_start_recovers(self):
        panel = self.panel
        panel.state = "transcribing"
        panel.process.start("/nonexistent/whisper", [])
        wait_for(lambda: panel.state == "idle")
        self.assertTrue(panel.record.isEnabled())
        self.assertEqual(self.texts, [])

    def test_cancel_pending_permission_does_not_record(self):
        panel = self.panel
        panel.state = "permission"
        panel.cancel()
        with patch.object(panel, "toggle") as toggle:
            panel._permission_ready(None)
            toggle.assert_not_called()

    def test_timeout_cancels_and_removes_temporary_audio(self):
        panel = self.panel
        panel.temp = tempfile.TemporaryDirectory()
        directory = Path(panel.temp.name)
        panel.state = "transcribing"
        panel._timeout()
        self.assertEqual(panel.state, "idle")
        self.assertFalse(directory.exists())
        self.assertEqual(self.texts, [])

    def test_shutdown_does_not_emit_text(self):
        panel = self.panel
        panel.state = "transcribing"
        panel.temp = tempfile.TemporaryDirectory()
        directory = Path(panel.temp.name)
        panel.shutdown()
        self.assertFalse(directory.exists())
        self.assertEqual(self.texts, [])

"""Real macOS TTS stream smoke, writing temporary synthetic WAVs without speaker output."""

import json
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from labchat.speech import Voice
from labchat.speech_widgets import SpeechPanel

app = QApplication([])
with tempfile.TemporaryDirectory(prefix="labchat-stream-tts-") as directory:
    panel = SpeechPanel(auto_discover=False)
    panel.controller.voices = [Voice("Meijia", "zh_TW")]
    panel._voices_ready(panel.controller.voices)
    panel.mode.setCurrentIndex(1)
    path = Path(directory) / "segment.wav"
    panel.controller.prefix_args = [
        "--file-format=WAVE",
        "--data-format=LEI16@22050",
        "-o",
        str(path),
    ]
    results = []
    errors = []
    started = time.monotonic()
    panel.controller.failed.connect(errors.append)

    def finished(code, _status):
        if code == 0 and path.exists():
            with wave.open(str(path), "rb") as audio:
                results.append(
                    {
                        "ready_seconds": round(time.monotonic() - started, 3),
                        "audio_seconds": round(audio.getnframes() / audio.getframerate(), 3),
                    }
                )

    panel.controller.player.finished.connect(finished)
    panel.begin_generation()
    panel.feed_generation("第一段內容已經完成，現在可以先開始朗讀。\n")
    started_while_generating = panel.controller.active and panel.generating
    deadline = time.monotonic() + 15
    while not results and time.monotonic() < deadline:
        QTest.qWait(10)
    panel.feed_generation("第二段繼續補充，最後一句也需要完整播放。\n")
    panel.finish_generation("第一段及第二段的完整原文")
    while (panel.controller.active or panel._segments) and time.monotonic() < deadline:
        QTest.qWait(10)
    assert started_while_generating and len(results) == 2 and not errors, (results, errors)
    assert all(item["audio_seconds"] > 0 for item in results)
    panel.shutdown()
    print(
        json.dumps(
            {
                "started_before_generation_finished": started_while_generating,
                "segments": results,
                "errors": errors,
                "speaker_playback": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

"""Local Ollama + real TTS concurrency smoke; synthetic prompt, temporary WAV, no speakers."""

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

from labchat.client import ChatClient
from labchat.speech import Voice
from labchat.speech_widgets import SpeechPanel

app = QApplication([])
with tempfile.TemporaryDirectory(prefix="labchat-pipeline-") as directory:
    panel = SpeechPanel(auto_discover=False)
    panel.controller.voices = [Voice("Meijia", "zh_TW")]
    panel._voices_ready(panel.controller.voices)
    panel.mode.setCurrentIndex(1)
    audio_path = Path(directory) / "segment.wav"
    panel.controller.prefix_args = [
        "--file-format=WAVE",
        "--data-format=LEI16@22050",
        "-o",
        str(audio_path),
    ]
    client = ChatClient()
    results, segments, errors, events = [], [], [], []
    started = time.monotonic()

    def activity(active):
        if active:
            events.append(
                {
                    "tts_start_seconds": round(time.monotonic() - started, 3),
                    "model_still_generating": not bool(results),
                }
            )

    def speech_finished(code, _status):
        if code == 0 and audio_path.exists():
            with wave.open(str(audio_path), "rb") as audio:
                segments.append(round(audio.getnframes() / audio.getframerate(), 3))

    def completed(result):
        results.append(result)
        panel.finish_generation(result.answer if result.status == "success" else "")

    panel.controller.activity_changed.connect(activity)
    panel.controller.failed.connect(errors.append)
    panel.controller.player.finished.connect(speech_finished)
    client.chunk.connect(panel.feed_generation)
    client.completed.connect(completed)
    panel.begin_generation()
    client.start(
        "qwen3.5:2b",
        [
            {
                "role": "user",
                "content": "請用繁體中文寫三句介紹本機人工智慧的話，每句至少二十字，使用句號，不要標題或清單。",
            }
        ],
        max_tokens=200,
    )
    deadline = time.monotonic() + 150
    try:
        while time.monotonic() < deadline:
            QTest.qWait(20)
            if results and not panel.controller.active and not panel._segments:
                break
        report = {
            "model_status": results[0].status if results else "timeout",
            "answer_chars": len(results[0].answer) if results else 0,
            "tts_events": events,
            "segment_audio_seconds": segments,
            "errors": errors,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "speaker_playback": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        assert results and results[0].status == "success" and segments and not errors
        assert any(item["model_still_generating"] for item in events), (
            "TTS did not start before generation completed"
        )
    finally:
        client.shutdown()
        panel.shutdown()

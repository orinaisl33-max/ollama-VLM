"""Real offline STT smoke using synthetic speech; no microphone or personal recordings."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from labchat.dictation import MODEL, DictationPanel
from labchat.speech import parse_voices

app = QApplication([])
with tempfile.TemporaryDirectory(prefix="labchat-stt-smoke-") as folder:
    path = Path(folder) / "speech.wav"
    voices = parse_voices(
        subprocess.run(
            ["/usr/bin/say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
    )
    if not voices:
        raise RuntimeError(
            "未找到已安裝的中文聲音；請至 macOS 系統設定下載中文聲音，再重試完整驗收。"
        )
    voice = voices[0].name
    subprocess.run(
        [
            "/usr/bin/say",
            "-v",
            voice,
            "--file-format=WAVE",
            "--data-format=LEI16@16000",
            "-o",
            str(path),
            "-f",
            "-",
        ],
        input="您好，請幫我整理今天的工作重點。",
        text=True,
        check=True,
        timeout=30,
    )
    panel = DictationPanel()
    panel.program = shutil.which("whisper-cli")
    if not panel.program:
        raise RuntimeError("找不到 whisper-cli，請依語音指南安裝並確認 PATH。")
    panel.fmt = QAudioFormat()
    panel.fmt.setSampleRate(16000)
    panel.fmt.setChannelCount(1)
    panel.fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    with wave.open(str(path), "rb") as audio:
        panel.data.extend(audio.readframes(audio.getnframes()))
    results = []
    panel.text_ready.connect(results.append)
    panel.state = "recording"
    started = time.monotonic()
    panel.finish_recording()
    deadline = started + 185
    while panel.state != "idle" and time.monotonic() < deadline:
        QTest.qWait(50)
    report = {
        "model": MODEL.name,
        "synthetic_voice": voice,
        "synthetic_only": True,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "result": results,
        "status": panel.note.text(),
        "temporary_cleaned": panel.temp is None,
    }
    panel.shutdown()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert results and "工作" in results[0] and "整理" in results[0], report
    assert report["temporary_cleaned"]

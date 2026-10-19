"""macOS speech backend: asynchronous, local, and independent from model inference."""

import html
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

MAX_SPEECH_CHARS = 8000


@dataclass(frozen=True)
class Voice:
    name: str
    locale: str

    @property
    def label(self) -> str:
        region = {"zh_TW": "台灣中文", "zh_CN": "中文", "zh_HK": "香港中文"}.get(
            self.locale, self.locale
        )
        name = "美佳 Meijia" if self.name == "Meijia" else self.name
        return f"{name} · {region}"


def parse_voices(output: str) -> list[Voice]:
    voices = []
    for line in output.splitlines():
        match = re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Z]{2})\s+#", line)
        if match and match[2] in ("zh_TW", "zh_CN", "zh_HK"):
            voice = Voice(match[1].strip(), match[2])
            if voice not in voices:
                voices.append(voice)
    # Prefer a normal Taiwanese narration voice, not the system's novelty voices.
    return sorted(voices, key=lambda v: (v.name != "Meijia", v.locale != "zh_TW", v.locale, v.name))


@dataclass(frozen=True)
class SpokenText:
    text: str
    truncated: bool


def prepare_speech(text: str) -> SpokenText:
    """Convert display Markdown to prose; never pass speech-control commands through."""
    text = re.sub(r"```.*?(?:```|\Z)", "。程式碼區塊已略過。", text, flags=re.S)
    text = re.sub(r"~~~.*?(?:~~~|\Z)", "。程式碼區塊已略過。", text, flags=re.S)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"圖片：\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "連結已略過", text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\[\[.*?(?:\]\]|\Z)", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+)", "", text)
    text = re.sub(r"(?m)^\s*[-:| ]{3,}\s*$", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = text.replace("|", "，")
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = len(text) > MAX_SPEECH_CHARS
    if truncated:
        end = text.rfind("。", 0, MAX_SPEECH_CHARS)
        text = text[: end + 1 if end > MAX_SPEECH_CHARS // 2 else MAX_SPEECH_CHARS]
        text += "\n內容較長，朗讀至此。"
    return SpokenText(text, truncated)


class SpeechController(QObject):
    voices_ready = Signal(object)
    activity_changed = Signal(bool)
    status_changed = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None, *, program="/usr/bin/say", prefix_args=()):
        super().__init__(parent)
        self.program = program
        self.prefix_args = list(prefix_args)
        self.voices: list[Voice] = []
        self.active = False
        self.closed = False
        self.cancelled = False
        self.stop_reason = ""
        self.playback_error = ""
        self.payload = b""
        self.truncated = False
        self.discovery_error = False
        self.voice_data = bytearray()
        self.player = QProcess(self)
        self.player.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        self.player.started.connect(self._started)
        self.player.finished.connect(self._finished)
        self.player.errorOccurred.connect(self._error)
        self.discovery = QProcess(self)
        self.discovery.readyReadStandardOutput.connect(self._read_voices)
        self.discovery.finished.connect(self._voices_finished)
        self.discovery.errorOccurred.connect(self._voices_error)
        self.discovery_timer = QTimer(self)
        self.discovery_timer.setSingleShot(True)
        self.discovery_timer.timeout.connect(self._discovery_timeout)
        self.play_timer = QTimer(self)
        self.play_timer.setSingleShot(True)
        self.play_timer.timeout.connect(self._play_timeout)

    def refresh_voices(self):
        if self.closed or self.discovery.state() != QProcess.ProcessState.NotRunning:
            return
        if not Path(self.program).is_file():
            self.voices = []
            self.voices_ready.emit([])
            self.failed.emit("找不到 macOS 語音服務，本機朗讀無法使用。")
            return
        self.voice_data.clear()
        self.discovery_error = False
        self.discovery.start(self.program, self.prefix_args + ["-v", "?"])
        self.discovery_timer.start(5000)

    def _read_voices(self):
        self.voice_data.extend(bytes(self.discovery.readAllStandardOutput()))
        if len(self.voice_data) > 256_000:
            self._discovery_timeout()

    def _discovery_timeout(self):
        self.discovery_error = True
        self.discovery.kill()

    def _voices_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and not self.closed:
            self.discovery_timer.stop()
            self.voices = []
            self.voices_ready.emit([])
            self.failed.emit("無法啟動聲音清單，請檢查系統語音設定。")

    def _voices_finished(self, code, exit_status):
        self.discovery_timer.stop()
        if self.closed:
            return
        self._read_voices()
        self.voices = (
            []
            if self.discovery_error or code != 0 or exit_status != QProcess.ExitStatus.NormalExit
            else parse_voices(self.voice_data.decode("utf-8", errors="replace"))
        )
        self.voices_ready.emit(self.voices)
        if not self.voices:
            self.failed.emit("沒有可用的中文聲音，請先至 macOS 語音設定下載，再重新整理。")

    def speak(self, text: str, voice: str, rate: int = 175) -> bool:
        if self.closed or self.active:
            return False
        if not any(item.name == voice for item in self.voices):
            self.failed.emit("請先選擇可用的聲音。")
            return False
        prepared = prepare_speech(text)
        if not prepared.text:
            self.failed.emit("這段回覆沒有可朗讀的文字。")
            return False
        self.payload = prepared.text.encode("utf-8")
        self.truncated = prepared.truncated
        self.cancelled = False
        self.stop_reason = ""
        self.playback_error = ""
        self.active = True
        self.activity_changed.emit(True)
        if self.closed:
            return False
        if self.cancelled:
            self._complete("已停止朗讀")
            return False
        self.status_changed.emit("正在準備本機語音…")
        if self.closed:
            return False
        if self.cancelled:
            self._complete("已停止朗讀")
            return False
        # No shell. Text stays in stdin rather than appearing in process arguments or files.
        self.player.start(
            self.program,
            self.prefix_args + ["-v", voice, "-r", str(max(100, min(260, rate))), "-f", "-"],
        )
        self.play_timer.start(600000)
        return True

    def _started(self):
        if self.cancelled or self.closed:
            self.player.kill()
            return
        if self.player.write(self.payload) < 0:
            self.playback_error = "無法傳送朗讀文字，請重新播放。"
            self.player.kill()
            return
        self.payload = b""
        self.player.closeWriteChannel()
        self.status_changed.emit(
            "正在朗讀 · 長內容最多朗讀 8000 字" if self.truncated else "正在朗讀 · 可隨時停止"
        )

    def stop(self):
        if self.active and not self.cancelled:
            self.cancelled = True
            self.stop_reason = "cancelled"
            self.player.kill()

    def _play_timeout(self):
        if self.active:
            self.cancelled = True
            self.stop_reason = "timeout"
            self.player.kill()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._complete("無法啟動本機語音服務。", failed=True)

    def _finished(self, code, exit_status):
        if self.stop_reason == "timeout":
            self._complete("朗讀已達時間上限，已停止。", failed=True)
        elif self.playback_error:
            self._complete(self.playback_error, failed=True)
        elif self.cancelled:
            self._complete("已停止朗讀")
        elif code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self._complete("朗讀完成" + (" · 長內容已截短" if self.truncated else ""))
        else:
            self._complete("朗讀失敗，請確認聲音已下載完成及音訊輸出正常。", failed=True)

    def _complete(self, message, failed=False):
        if not self.active:
            return
        self.active = False
        self.payload = b""
        self.play_timer.stop()
        if not self.closed:
            self.activity_changed.emit(False)
            self.status_changed.emit(message)
            if failed:
                self.failed.emit(message)

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.discovery_timer.stop()
        self.play_timer.stop()
        self.payload = b""
        for process in (self.player, self.discovery):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                # A bounded wait only on application shutdown prevents orphan speech processes.
                process.waitForFinished(500)
        self.active = False

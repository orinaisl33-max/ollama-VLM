"""Bounded microphone capture and offline whisper.cpp transcription; never auto-send."""

import math
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QElapsedTimer,
    QMicrophonePermission,
    QProcess,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices, QtAudio
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .indicators import BusyIndicator

MODEL = Path(__file__).resolve().parent.parent / "models" / "ggml-small.bin"


def audio_level(data, fmt):
    """Bounded peak meter; inspect at most 4096 scalar PCM samples."""
    kinds = {
        QAudioFormat.SampleFormat.Int16: ("h", 32768),
        QAudioFormat.SampleFormat.Int32: ("i", 2147483648),
        QAudioFormat.SampleFormat.Float: ("f", 1),
        QAudioFormat.SampleFormat.UInt8: ("B", 128),
    }
    if fmt.sampleFormat() not in kinds:
        return 0
    kind, scale = kinds[fmt.sampleFormat()]
    size = struct.calcsize("<" + kind)
    length = len(data) // size * size
    chunk = data[max(0, length - 4096 * size) : length]
    peak = 0.0
    for (value,) in struct.iter_unpack("<" + kind, chunk):
        value = (value - 128 if kind == "B" else value) / scale
        if math.isfinite(value):
            peak = max(peak, abs(value))
    return min(100, round(peak * 100))


def microphone_icon():
    """High-DPI vector-drawn badge with contrast in both application themes."""
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#3559c7"))
    painter.drawEllipse(0, 0, 24, 24)
    painter.setPen(QPen(QColor("#ffffff"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(9, 4, 6, 10, 3, 3)
    painter.drawArc(6, 8, 12, 10, 180 * 16, 180 * 16)
    painter.drawLine(12, 18, 12, 21)
    painter.drawLine(9, 21, 15, 21)
    painter.end()
    return QIcon(pixmap)


def pcm16_mono(data, fmt):
    """Convert a complete bounded Qt PCM recording to 16 kHz signed mono PCM."""
    kinds = {
        QAudioFormat.SampleFormat.Int16: ("h", 32768),
        QAudioFormat.SampleFormat.Int32: ("i", 2147483648),
        QAudioFormat.SampleFormat.Float: ("f", 1),
        QAudioFormat.SampleFormat.UInt8: ("B", 128),
    }
    if fmt.sampleFormat() not in kinds or fmt.channelCount() < 1 or fmt.sampleRate() < 1:
        raise ValueError("不支援的麥克風音訊格式")
    kind, scale = kinds[fmt.sampleFormat()]
    channels = fmt.channelCount()
    frame = struct.Struct("<" + kind * channels)
    count = len(data) // frame.size
    if count / fmt.sampleRate() < 0.3:
        raise ValueError("錄音太短，請再試一次。")
    result = bytearray()
    energy = 0.0
    for index in range(int(count * 16000 / fmt.sampleRate())):
        values = frame.unpack_from(data, int(index * fmt.sampleRate() / 16000) * frame.size)
        value = sum(values) / channels
        if kind == "B":
            value -= 128
        value /= scale
        if not math.isfinite(value):
            value = 0
        value = max(-1, min(1, value))
        energy += value * value
        result.extend(struct.pack("<h", round(value * 32767)))
    if not result or math.sqrt(energy / (len(result) // 2)) < 0.003:
        raise ValueError("錄音接近靜音，請確認麥克風與輸入音量。")
    return bytes(result)


class DictationPanel(QWidget):
    device_selected = Signal(str)
    text_ready = Signal(str)
    starting = Signal()
    active_changed = Signal(bool)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.compact = False
        self.state = "idle"
        self.closed = False
        self.source = None
        self.device = None
        self.data = bytearray()
        self.temp = None
        self.cancelled = False
        self.output = bytearray()
        self.preferred_device = ""
        self._active_device = ""
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioInputsChanged.connect(self._devices_changed)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._drain)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.record_clock = QElapsedTimer()
        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(100)
        self.countdown_timer.timeout.connect(self._update_countdown)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.record = QPushButton("使用麥克風語音輸入")
        self.record.setIcon(microphone_icon())
        self.record.setIconSize(QSize(22, 22))
        self.record.setAccessibleName("使用麥克風語音輸入")
        self.record.clicked.connect(self.toggle)
        self.cancel_button = QPushButton("取消錄音／辨識")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        self.note = QLabel("本機辨識 · 最長 30 秒 · 確認文字後再傳送")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        row.addWidget(self.record)
        row.addWidget(self.cancel_button)
        self.countdown = QLabel("剩餘 30 秒")
        self.countdown.setObjectName("countdown")
        self.countdown.setMinimumWidth(90)
        self.countdown.setAccessibleName("錄音剩餘時間")
        self.countdown.hide()
        row.addWidget(self.countdown)
        self.spinner = BusyIndicator(self)
        row.addWidget(self.spinner)
        row.addWidget(self.note, 1)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setFixedWidth(64)
        self.level.setTextVisible(False)
        self.level.setAccessibleName("麥克風輸入音量")
        self.level.hide()
        row.addWidget(self.level)
        self._build_settings()
        if sys.platform != "darwin":
            self.record.setEnabled(False)
            self._status("語音輸入目前僅驗證 Mac 版")

    def _build_settings(self):
        self.settings = QDialog(self)
        self.settings.setWindowTitle("麥克風裝置與診斷")
        self.settings.resize(540, 350)
        layout = QVBoxLayout(self.settings)
        note = QLabel("選擇錄音來源；只有按主畫面的麥克風才會錄音。裝置設定不會變更系統權限。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.devices = QComboBox()
        self.devices.setAccessibleName("錄音輸入裝置")
        self.devices.currentIndexChanged.connect(self._select_device)
        layout.addWidget(self.devices)
        self.diagnostics = QLabel()
        self.diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self.diagnostics.setWordWrap(True)
        layout.addWidget(self.diagnostics, 1)
        buttons = QHBoxLayout()
        self.refresh_devices = QPushButton("重新檢查裝置")
        self.refresh_devices.clicked.connect(self.refresh_inputs)
        buttons.addWidget(self.refresh_devices)
        close = QPushButton("完成")
        close.clicked.connect(self.settings.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh_inputs()

    def show_settings(self):
        if self.closed or self.state != "idle":
            return
        self.refresh_inputs()
        self.settings.show()
        self.settings.raise_()

    def set_preferred_device(self, identifier):
        self.preferred_device = identifier
        self.refresh_inputs()

    def refresh_inputs(self):
        inputs = QMediaDevices.audioInputs()
        with QSignalBlocker(self.devices):
            self.devices.clear()
            self.devices.addItem("跟隨系統預設", "")
            for device in inputs:
                self.devices.addItem(device.description(), bytes(device.id()).hex())
            index = self.devices.findData(self.preferred_device)
            if index < 0:
                self.devices.addItem("先前選擇的裝置未連接（請重新選擇）", self.preferred_device)
                index = self.devices.count() - 1
            self.devices.setCurrentIndex(index)
        permission = QCoreApplication.instance().checkPermission(QMicrophonePermission())
        permission_text = {
            Qt.PermissionStatus.Granted: "已允許",
            Qt.PermissionStatus.Denied: "未允許，請到系統設定檢查",
            Qt.PermissionStatus.Undetermined: "尚未要求，開始錄音時才會詢問",
        }[permission]
        engine = shutil.which("whisper-cli") or next(
            (
                str(p)
                for p in (Path("/opt/homebrew/bin/whisper-cli"), Path("/usr/local/bin/whisper-cli"))
                if p.is_file()
            ),
            "",
        )
        self.diagnostics.setText(
            f"可用輸入裝置：{len(inputs)} 個\n麥克風權限：{permission_text}\n"
            f"辨識引擎：{'已找到' if engine else '未安裝'}\n"
            f"辨識模型：{'已找到' if MODEL.is_file() else '未安裝'}\n\n"
            + (
                "錄音時主畫面會顯示輸入音量；此視窗不啟動收音。"
                if inputs
                else "未偵測到麥克風，請接上 USB 麥克風／耳麥，再重新檢查。"
            )
        )

    def _select_device(self, _index):
        if self.state != "idle":
            return
        self.preferred_device = self.devices.currentData() or ""
        self.device_selected.emit(self.preferred_device)

    def _devices_changed(self):
        if self.closed:
            return
        if self.state == "recording" and self._active_device not in {
            bytes(device.id()).hex() for device in QMediaDevices.audioInputs()
        }:
            self.cancel("麥克風已移除，錄音已取消；請重新選擇裝置。")
        self.refresh_inputs()

    def _input_device(self):
        if not self.preferred_device:
            return QMediaDevices.defaultAudioInput()
        return next(
            (
                device
                for device in QMediaDevices.audioInputs()
                if bytes(device.id()).hex() == self.preferred_device
            ),
            None,
        )

    def set_compact(self):
        self.compact = True
        self.note.hide()
        self.record.setText("使用麥克風語音輸入")
        self.record.setToolTip("錄音轉成文字，最長 30 秒；辨識後核對並傳送。")
        self.cancel_button.setText("取消")

    def _status(self, text):
        self.note.setText(text)
        self.note.setToolTip(text)
        self.record.setToolTip(text)
        self.status_changed.emit(text)

    def _set_state(self, state, message):
        self.state = state
        self.countdown.setVisible(state == "recording")
        self.level.setVisible(state == "recording")
        self.devices.setEnabled(state == "idle")
        self.refresh_devices.setEnabled(state == "idle")
        if state != "recording":
            self.level.setValue(0)
        if state != "recording":
            self.countdown_timer.stop()
        self.spinner.set_running(state == "transcribing")
        self._status(message)
        self.record.setText(
            ("停止錄音" if self.compact else "停止並辨識")
            if state == "recording"
            else "使用麥克風語音輸入"
        )
        self.record.setAccessibleName(self.record.text())
        self.record.setEnabled(state in ("idle", "recording") and not self.closed)
        self.cancel_button.setVisible(state != "idle")
        self.active_changed.emit(state != "idle")

    def toggle(self):
        if self.state == "recording":
            self.finish_recording()
            return
        if self.state != "idle" or self.closed:
            return
        self.program = shutil.which("whisper-cli") or next(
            (
                str(p)
                for p in (Path("/opt/homebrew/bin/whisper-cli"), Path("/usr/local/bin/whisper-cli"))
                if p.is_file()
            ),
            "",
        )
        if not self.program or not MODEL.is_file():
            self._status("缺少辨識引擎或模型，請參閱 VOICE_INPUT.md 安裝步驟。")
            return
        device = self._input_device()
        if device is None or device.isNull():
            self._status("找不到所選麥克風。請到「設定 → 麥克風裝置與診斷」檢查或重新選擇。")
            return
        permission = QMicrophonePermission()
        app = QCoreApplication.instance()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Undetermined:
            self._set_state("permission", "請在 macOS 提示中允許麥克風存取")
            app.requestPermission(permission, self, self._permission_ready)
            return
        if status != Qt.PermissionStatus.Granted:
            self._status(
                "麥克風權限未允許。請由 run.command 啟動，並至系統設定 → 隱私權與安全性 → 麥克風檢查。"
            )
            return
        self._active_device = bytes(device.id()).hex()
        self.starting.emit()
        self.fmt = QAudioFormat()
        self.fmt.setSampleRate(16000)
        self.fmt.setChannelCount(1)
        self.fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(self.fmt):
            self.fmt = device.preferredFormat()
        if not self.fmt.isValid() or self.fmt.bytesForDuration(30_000_000) > 32 * 1024 * 1024:
            self._status("麥克風格式超過錄音上限，請在系統設定選擇一般音訊輸入。")
            return
        self.data.clear()
        self.cancelled = False
        self.source = QAudioSource(device, self.fmt, self)
        self._set_state("recording", "正在錄音 · 最長 30 秒 · 再按一次停止並辨識")
        device_io = self.source.start()
        self._check_audio_error()
        if self.state != "recording":
            return
        self.device = device_io
        if self.device is None:
            self.cancel("無法啟動麥克風，請檢查系統權限。")
            return
        self.device.readyRead.connect(self._capture)
        self.record_clock.start()
        self._update_countdown()
        self.countdown_timer.start()
        self.timer.start(30000)

    def _update_countdown(self):
        if self.state == "recording":
            self._check_audio_error()
        if self.state != "recording" or not self.record_clock.isValid():
            return
        remaining = max(0, math.ceil((30000 - self.record_clock.elapsed()) / 1000))
        self.countdown.setText(f"剩餘 {remaining:02d} 秒")
        self.countdown.setProperty("urgent", remaining <= 5)
        self.countdown.style().unpolish(self.countdown)
        self.countdown.style().polish(self.countdown)
        if remaining == 0:
            self.finish_recording()

    def _permission_ready(self, _permission):
        if self.closed or self.state != "permission":
            return
        self._set_state("idle", "麥克風權限已更新")
        self.toggle()

    def _check_audio_error(self):
        # Poll through the existing 100ms countdown timer: PySide6 can fail
        # converting the native QAudio::State signal even for a zero-arg slot.
        if self.source and self.source.error() != QtAudio.Error.NoError:
            self.cancel("錄音失敗，請檢查麥克風權限與裝置。")

    def _capture(self):
        if self.state != "recording" or self.device is None:
            return
        remaining = self.fmt.bytesForDuration(30_000_000) - len(self.data)
        chunk = bytes(self.device.read(max(0, remaining)))
        self.data.extend(chunk)
        self.level.setValue(audio_level(chunk, self.fmt))
        if len(self.data) >= self.fmt.bytesForDuration(30_000_000):
            self.finish_recording()

    def _stop_audio(self):
        self.device = None
        if self.source:
            source, self.source = self.source, None
            source.stop()
            source.deleteLater()

    def finish_recording(self):
        if self.state != "recording":
            return
        self.timer.stop()
        self.countdown_timer.stop()
        self._capture_tail()
        self._stop_audio()
        try:
            pcm = pcm16_mono(self.data, self.fmt)
            self.temp = tempfile.TemporaryDirectory(prefix="labchat-dictation-")
            path = Path(self.temp.name) / "input.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(pcm)
        except (ValueError, OSError, wave.Error) as error:
            self.cancel(str(error))
            return
        self.data.clear()
        self.output.clear()
        self._set_state("transcribing", "正在本機辨識…可取消；完成後請核對文字")
        self.process.start(
            self.program,
            [
                "-m",
                str(MODEL),
                "-f",
                str(path),
                "-l",
                "zh",
                "-otxt",
                "-of",
                str(Path(self.temp.name) / "result"),
                "-nt",
                "-t",
                "4",
            ],
        )
        self.timer.start(180000)

    def _capture_tail(self):
        if self.device:
            remaining = self.fmt.bytesForDuration(30_000_000) - len(self.data)
            self.data.extend(bytes(self.device.read(max(0, remaining))))

    def _drain(self):
        self.output.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.output) > 256000:
            self.cancel("辨識輸出超過限制，已停止。")

    def _finished(self, code, status):
        self.timer.stop()
        text = ""
        if (
            not self.cancelled
            and not self.closed
            and code == 0
            and status == QProcess.ExitStatus.NormalExit
            and self.temp
        ):
            try:
                path = Path(self.temp.name) / "result.txt"
                if path.stat().st_size > 32000:
                    raise ValueError("辨識文字超過限制")
                text = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError, ValueError):
                pass
        cancelled = self.cancelled
        self._cleanup()
        if self.closed:
            return
        if not cancelled:
            self._set_state(
                "idle",
                "辨識完成 · 請核對輸入框文字後再傳送"
                if text
                else "辨識失敗或無文字，請重試；原有輸入未更動。",
            )
            if text:
                self.text_ready.emit(text)
        else:
            self._set_state("idle", self.note.text())

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.cancel("無法啟動辨識引擎，請檢查安裝。")
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _timeout(self):
        if self.state == "recording":
            self.finish_recording()
        else:
            self.cancel("辨識超時，已停止；可縮短錄音再試。")

    def _cleanup(self):
        self.data.clear()
        self.output.clear()
        if self.temp:
            self.temp.cleanup()
            self.temp = None

    def cancel(self, message="已取消 · 錄音不保留"):
        # clicked(bool) must not replace the user-visible message.
        if not isinstance(message, str):
            message = "已取消 · 錄音不保留"
        self.cancelled = True
        self.countdown_timer.stop()
        self.timer.stop()
        self._stop_audio()
        self._status(message)
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.record.setEnabled(False)
            self.process.kill()
        else:
            self._cleanup()
            self._set_state("idle", message)

    def shutdown(self):
        self.closed = True
        self.settings.close()
        self.spinner.set_running(False)
        self.cancel()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.waitForFinished(1000)
        self._cleanup()

"""Compact speech controls with a separate voice-settings dialog."""

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from .speech import SpeechController
from .speech_stream import SentenceBuffer


class SpeechPanel(QFrame):
    def __init__(self, parent=None, *, auto_discover=True):
        super().__init__(parent)
        self.answer = ""
        self.generating = False
        self._pending_auto = False
        self._refreshing = False
        self.preferred_voice = ""
        self._playback_source = ""
        self._stream = SentenceBuffer()
        self._segments = []
        self._stream_limited = False
        self._stream_chars = 0
        self._stream_stopped = False
        self._stream_session = False
        self._generation_mode = None
        self.controller = SpeechController(self)
        self.controller.voices_ready.connect(self._voices_ready)
        self.controller.activity_changed.connect(self._activity_changed)
        self.controller.status_changed.connect(self._status)
        self.controller.failed.connect(self._speech_failed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(10)
        self.mode = QComboBox()
        self.mode.addItem("朗讀關閉", "off")
        self.mode.addItem("分段朗讀", "stream")
        self.mode.addItem("完成後朗讀", "complete")
        self.mode.setToolTip("分段朗讀於完整句子可用時開始；新選擇從下一次提問生效。")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        # Automatic reading choices live in the settings form.
        self.note = QLabel("正在載入中文聲音…")
        self.note.setObjectName("muted")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setMinimumWidth(0)
        self.note.hide()
        self.settings_button = QPushButton("語音設定")
        self.settings_button.clicked.connect(self.show_settings)
        self.settings_button.setParent(self)
        self.settings_button.hide()
        self.play = QPushButton("朗讀")
        self.play.setEnabled(False)
        self.play.clicked.connect(self.read_answer)
        row.addWidget(self.play)
        self.stop_button = QPushButton("停止朗讀")
        self.stop_button.hide()
        self.stop_button.clicked.connect(self.stop_reading)
        row.addWidget(self.stop_button)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._build_settings()
        if auto_discover:
            QTimer.singleShot(0, self.refresh)

    def _build_settings(self):
        self.dialog = QDialog(self)
        self.dialog.setWindowTitle("本機語音設定")
        self.dialog.resize(560, 340)
        self.dialog.setMinimumWidth(480)
        self.dialog.finished.connect(self._dialog_finished)
        layout = QVBoxLayout(self.dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        description = QLabel(
            "使用 macOS 已安裝的中文聲音，文字不會送往雲端。\n音質依聲音而異，可先試聽，再決定展示時使用的音色。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        self.voice = QComboBox()
        self.voice.setMinimumWidth(250)
        self.voice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rate = QComboBox()
        for label, rate in [
            ("舒緩 · 145", 145),
            ("標準 · 175", 175),
            ("輕快 · 205", 205),
            ("快速 · 235", 235),
        ]:
            self.rate.addItem(label, rate)
        self.rate.setCurrentIndex(1)
        self.rate.setToolTip("數值為系統語速參數，不是中文每分鐘字數。變更於下一次播放生效。")
        self.rate.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("自動朗讀", self.mode)
        form.addRow("朗讀聲音", self.voice)
        form.addRow("朗讀語速", self.rate)
        layout.addLayout(form)
        help_text = QLabel(
            "需要更多音色：至 macOS「系統設定 → 輔助使用」的語音朗讀設定下載聲音，完成後按「重新整理」。"
        )
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.settings_status = QLabel("正在載入中文聲音…")
        self.settings_status.setObjectName("muted")
        self.settings_status.setWordWrap(True)
        self.settings_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.settings_status)
        layout.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.clicked.connect(self.refresh)
        self.preview = QPushButton("試聽聲音")
        self.preview.clicked.connect(self.preview_voice)
        self.preview_stop = QPushButton("停止試聽")
        self.preview_stop.clicked.connect(self.controller.stop)
        self.preview_stop.setEnabled(False)
        close = QPushButton("完成")
        close.clicked.connect(self.dialog.accept)
        for button in (self.refresh_button, self.preview, self.preview_stop, close):
            buttons.addWidget(button, 1)
        layout.addLayout(buttons)
        self._update_controls()

    def show_settings(self):
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def refresh(self):
        if self.controller.closed or self.controller.active or self._refreshing or self.generating:
            return
        self._refreshing = True
        self._status("正在更新中文聲音清單…")
        self._update_controls()
        self.controller.refresh_voices()

    def _voices_ready(self, voices):
        self._refreshing = False
        if not voices:
            self.mode.setCurrentIndex(0)
        selected = self.voice.currentData() or self.preferred_voice
        with QSignalBlocker(self.voice):
            self.voice.clear()
            for voice in voices:
                self.voice.addItem(voice.label, voice.name)
            index = self.voice.findData(selected) if selected else -1
            if index >= 0:
                self.voice.setCurrentIndex(index)
        self._status(
            "本機中文語音 · 回覆完成後可朗讀" if voices else "無可用中文聲音 · 請至語音設定下載"
        )
        self._update_controls()
        if self._segments:
            QTimer.singleShot(0, self._play_segment)
        if self._pending_auto:
            QTimer.singleShot(0, self._play_pending)

    def _dialog_finished(self):
        if self._playback_source == "preview":
            self.controller.stop()

    def _status(self, text):
        if self._stream_limited and "上限" not in text:
            text += " · 已達朗讀上限，其餘請閱讀畫面"
        self._status_text = text
        self.note.setToolTip(text)
        self.play.setToolTip(text + " · 自動朗讀模式請至「設定 → 語音與朗讀」。")
        if hasattr(self, "settings_status"):
            self.settings_status.setText(text)
        self._elide_status()

    def _elide_status(self):
        text = getattr(self, "_status_text", "正在載入中文聲音…")
        self.note.setText(
            self.note.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, max(20, self.note.width())
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_status()

    def _activity_changed(self, active):
        self.stop_button.setVisible(active)
        self.play.setVisible(not active)
        self._update_controls()
        if not active:
            self._playback_source = ""
        if not active and self._segments:
            QTimer.singleShot(0, self._play_segment)
        if not active and self._pending_auto:
            QTimer.singleShot(0, self._play_pending)

    def _play_pending(self):
        if self._refreshing:
            return
        pending, self._pending_auto = self._pending_auto, False
        if (
            pending
            and self.mode.currentData() == "complete"
            and self.voice.count()
            and not self.controller.active
        ):
            self.read_answer()

    def _update_controls(self):
        ready = self.voice.count() > 0 and not self._refreshing
        active = self.controller.active
        self.play.setEnabled(
            ready
            and bool(self.answer)
            and not self.generating
            and not active
            and not self._segments
        )
        self.preview.setEnabled(ready and not self.generating and not active)
        self.preview_stop.setEnabled(active)
        self.voice.setEnabled(not active and not self._refreshing and not self.generating)
        self.rate.setEnabled(not active and not self.generating)
        self.mode.setEnabled(ready)
        self.refresh_button.setEnabled(not active and not self._refreshing and not self.generating)

    def _mode_changed(self, _index):
        self.stop_reading()
        if not self.generating:
            self._stream_stopped = False
        self._status("朗讀模式已更新 · 下一次提問生效")

    def stop_reading(self):
        self._pending_auto = False
        self._segments.clear()
        self._stream_stopped = True
        self.controller.stop()

    def _speech_failed(self, message):
        self.stop_reading()
        self._status(message)

    def feed_generation(self, text):
        if self.generating and self._stream_session and not self._stream_stopped:
            self._enqueue(self._stream.feed(text))

    def _enqueue(self, segments):
        for text in segments:
            if self._stream_chars + len(text) > 8000 or len(self._segments) >= 64:
                self._stream_stopped = True
                self._stream_limited = True
                self._status("朗讀內容已達上限 · 其餘請參閱畫面或手動朗讀")
                break
            self._segments.append(text)
            self._stream_chars += len(text)
        self._play_segment()

    def _play_segment(self):
        if (
            self.controller.closed
            or self._refreshing
            or self.controller.active
            or not self.voice.count()
        ):
            return
        if not self._segments:
            return
        if self.generating and sum(map(len, self._segments)) < 16:
            return
        # Merge ready sentences to reduce per-process startup gaps; keep segments bounded.
        text = self._segments.pop(0)
        while self._segments and len(text) + len(self._segments[0]) < 220:
            text += "\n" + self._segments.pop(0)
        self._playback_source = "stream"
        if not self.controller.speak(text, self.voice.currentData(), self.rate.currentData()):
            self.stop_reading()

    def preview_voice(self):
        if self.generating or self._refreshing:
            return
        self._playback_source = "preview"
        self.controller.speak(
            "您好，歡迎使用人工智慧系統實驗室展示工具。我可以為您朗讀回答，協助理解文字與圖片內容。",
            self.voice.currentData(),
            self.rate.currentData(),
        )

    def read_answer(self):
        if (
            not self.generating
            and not self._refreshing
            and self.answer
            and self.voice.count()
            and not self._segments
        ):
            self._playback_source = "reply"
            self.controller.speak(self.answer, self.voice.currentData(), self.rate.currentData())

    def begin_generation(self):
        self.stop_reading()
        self._stream = SentenceBuffer()
        self._stream_limited = False
        self._stream_chars = 0
        self._stream_stopped = False
        self._generation_mode = self.mode.currentData()
        self._stream_session = self._generation_mode == "stream"
        self.generating = True
        self.answer = ""
        self._update_controls()

    def finish_generation(self, answer=""):
        self.generating = False
        self.answer = answer
        self._update_controls()
        if self._stream_session:
            if answer and not self._stream_stopped:
                self._enqueue(self._stream.feed("", final=True))
            elif not answer:
                self.stop_reading()
            self._stream_session = False
            self._generation_mode = None
            self._update_controls()
            return
        mode = self._generation_mode or self.mode.currentData()
        self._generation_mode = None
        if answer and mode == "complete" and not self._stream_stopped:
            if self.controller.active or self._refreshing:
                self._pending_auto = True
            else:
                self.read_answer()

    def reset(self):
        self.stop_reading()
        self._stream_limited = False
        self._generation_mode = None
        self._stream_session = False
        self.generating = False
        self.answer = ""
        self._update_controls()

    def shutdown(self):
        self.stop_reading()
        self.dialog.close()
        self.controller.shutdown()

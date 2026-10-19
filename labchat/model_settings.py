"""Whitelisted local Ollama download UI. Never executes a shell or model-provided commands."""

import re
import shutil
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .config import MODELS
from .model_widgets import ModelCapabilityDelegate


class ModelSettings(QDialog):
    refresh_requested = Signal()
    downloading_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模型設定與下載")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(610, 440)
        self.installed = None
        self.downloading = False
        self.cancelled = False
        self.closed = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.cancel("下載超過 30 分鐘，已停止；可稍後重試。"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        intro = QLabel(
            "選擇模型後可下載，或複製指令到終端機／PowerShell 執行。\n下載需要網路與本機 Ollama 服務；首次請先安裝並啟動 Ollama。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.models = QComboBox()
        self.models.setItemDelegate(ModelCapabilityDelegate(self.models))
        for model in MODELS:
            self.models.addItem(model.label, model.identifier)
        self.models.currentIndexChanged.connect(self._update)
        layout.addWidget(self.models)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.command = QLineEdit()
        self.command.setReadOnly(True)
        self.command.setAccessibleName("模型下載指令")
        layout.addWidget(self.command)
        row = QHBoxLayout()
        copy = QPushButton("複製指令")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.command.text()))
        official = QPushButton("官方模型頁")
        official.clicked.connect(self.open_official)
        refresh = QPushButton("重新檢查安裝")
        refresh.clicked.connect(self.refresh_requested)
        for widget in (copy, official, refresh):
            row.addWidget(widget)
        layout.addLayout(row)
        note = QLabel(
            "8GB 電腦建議先用 2B；4B、圖片與語音同時使用需觀察記憶體。\n參數量不是下載大小；精確檔案大小請看官方頁。下載不會自動切換聊天模型或刪除其他模型。"
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("準備就緒；模型狀態依本機服務回報。")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status, 1)
        row = QHBoxLayout()
        self.download = QPushButton("下載所選模型")
        self.download.clicked.connect(self.start_download)
        self.stop = QPushButton("停止下載")
        self.stop.clicked.connect(self.cancel)
        self.stop.setEnabled(False)
        done = QPushButton("完成")
        done.clicked.connect(self.reject)
        for widget in (self.download, self.stop, done):
            row.addWidget(widget)
        layout.addLayout(row)
        self._update()

    def set_installed(self, models):
        self.installed = models
        self._update()

    def _update(self):
        identifier = self.models.currentData()
        model = next(item for item in MODELS if item.identifier == identifier)
        state = (
            "狀態未確認"
            if self.installed is None
            else ("已安裝" if identifier in self.installed else "未下載")
        )
        capability = "文字＋圖片" if model.vision else "僅文字，不支援圖片"
        self.details.setText(f"{identifier} · {state}\n能力：{capability}\n{model.note}")
        self.command.setText(f"ollama pull {identifier}")
        self.download.setEnabled(
            not self.downloading and self.installed is not None and identifier not in self.installed
        )
        self.models.setEnabled(not self.downloading)
        self.stop.setEnabled(self.downloading)
        self.progress.setVisible(self.downloading)

    def open_official(self):
        # The URL comes only from our fixed model whitelist, never from server text.
        model = next(item for item in MODELS if item.identifier == self.models.currentData())
        family = model.identifier.split(":", 1)[0]
        QDesktopServices.openUrl(QUrl(model.official_url or f"https://ollama.com/library/{family}"))

    def start_download(self):
        if self.closed or self.downloading:
            return
        identifier = self.models.currentData()
        if (
            identifier not in {item.identifier for item in MODELS}
            or self.installed is None
            or identifier in self.installed
        ):
            self.status.setText("請先檢查服務；已安裝模型不重複下載。")
            return
        program = shutil.which("ollama") or next(
            (
                str(p)
                for p in (Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama"))
                if p.is_file()
            ),
            "",
        )
        if not program:
            self.status.setText("找不到 Ollama，請先從 https://ollama.com/download 安裝並啟動。")
            return
        if (
            QMessageBox.question(
                self,
                "下載模型",
                f"將透過本機 Ollama 下載 {identifier}，會使用網路與磁碟空間。\n請先確認官方檔案大小及儲存位置可用空間。繼續？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        env = QProcessEnvironment.systemEnvironment()
        env.insert("OLLAMA_HOST", "127.0.0.1:11434")
        env.insert("OLLAMA_NO_CLOUD", "1")
        env.insert("NO_PROXY", "localhost,127.0.0.1,::1")
        env.insert("no_proxy", "localhost,127.0.0.1,::1")
        self.process.setProcessEnvironment(env)
        self.cancelled = False
        self.downloading = True
        self.status.setText("正在下載… 可停止；Ollama 可能保留部分下載供重試使用。")
        self._update()
        self.downloading_changed.emit(True)
        self.process.start(program, ["pull", identifier])
        self.timer.start(30 * 60 * 1000)

    def _output(self):
        if not self.process.isOpen():
            return
        data = bytes(self.process.readAllStandardOutput())
        text = re.sub(
            r"\x1b\[[0-?]*[ -/]*[@-~]", "", data[-16000:].decode("utf-8", errors="replace")
        )
        lines = [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]
        if lines and not self.cancelled:
            self.status.setText(lines[-1][-320:])

    def _finished(self, code, status):
        self.timer.stop()
        self._output()
        self.downloading = False
        if not self.cancelled and code == 0:
            self.installed = None
        self._update()
        self.downloading_changed.emit(False)
        if not self.cancelled:
            success = code == 0 and status == QProcess.ExitStatus.NormalExit
            self.status.setText(
                "下載完成，正在重新確認安裝狀態。"
                if success
                else "下載失敗；請檢查網路、Ollama 服務與磁碟空間。可複製指令查看詳細錯誤。"
            )
        if not self.closed:
            self.refresh_requested.emit()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.cancelled = True
            self.status.setText("無法啟動 Ollama 下載程序，請檢查安裝。")
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def cancel(self, message="已停止下載 · Ollama 可能保留快取，重試可重用；不會自動刪除模型。"):
        if not isinstance(message, str):
            message = "已停止下載 · Ollama 可能保留快取，重試可重用。"
        if not self.downloading:
            return
        self.cancelled = True
        self.status.setText(message)
        self.timer.stop()
        self.stop.setEnabled(False)
        self.process.kill()

    def reject(self):
        if self.downloading:
            self.cancel()
            self.status.setText("正在停止下載，請稍後再關閉。")
            return
        super().reject()

    def shutdown(self):
        self.closed = True
        self.cancel()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.waitForFinished(1000)

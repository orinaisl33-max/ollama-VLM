"""Visible, read-only local service diagnostics; never loads or downloads models."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .indicators import BusyIndicator


class ServiceStatusDialog(QDialog):
    retry_requested = Signal()
    models_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本機服務檢查")
        self.resize(520, 340)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        row = QHBoxLayout()
        self.spinner = BusyIndicator(self)
        row.addWidget(self.spinner)
        self.heading = QLabel()
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        row.addWidget(self.heading, 1)
        layout.addLayout(row)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        note = QLabel("此功能只確認服務連線與已安裝模型，不會載入、下載模型或傳送對話內容。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.retry = QPushButton("重新檢查")
        self.retry.clicked.connect(self.retry_requested.emit)
        buttons.addWidget(self.retry)
        self.models = QPushButton("模型設定")
        self.models.clicked.connect(self.models_requested.emit)
        buttons.addWidget(self.models)
        close = QPushButton("關閉")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def checking(self, address):
        self.spinner.set_running(True)
        self.retry.setEnabled(False)
        self.heading.setText("正在檢查本機服務…")
        self.details.setText(f"連線位置：{address}\n正在取得已安裝模型清單，最長約 10 秒。")

    def show_result(self, models, error, model_label, installed, address):
        self.spinner.set_running(False)
        self.retry.setEnabled(True)
        if models is None:
            self.heading.setText("檢查未通過 · 無法確認服務狀態")
            result = (error or "無法取得服務狀態。") + (
                "\n請先開啟 Ollama 應用程式；若使用命令列，可執行 ollama serve。"
                "\n若已啟動，請確認本機連線位置與 Ollama 設定，再按「重新檢查」。"
            )
        elif not installed:
            self.heading.setText("服務已連線，所選模型尚未安裝")
            result = (
                f"已安裝模型：{len(models)} 個\n所選模式：{model_label}"
                "\n請開啟「模型設定」下載所選模型，或返回主畫面切換已安裝的模式。"
            )
        else:
            self.heading.setText("檢查完成 · 可以開始對話")
            result = (
                f"已安裝模型：{len(models)} 個\n所選模式：{model_label} · 已安裝"
                "\n首次提問仍可能需要等待模型載入。"
            )
        self.details.setText(
            f"檢查時間：{datetime.now():%H:%M:%S}\n連線位置：{address}\n\n{result}"
        )

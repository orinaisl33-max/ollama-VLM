"""Bounded Markdown reader with no external resource loading or clickable navigation."""

import re

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from .config import MAX_ANSWER_CHARS
from .theme import apply_theme, theme_color, themed_css


class LocalDocument(QTextDocument):
    def loadResource(self, resource_type, url):
        # Deny all model-controlled file, HTTP, data and Qt resource lookups.
        return QByteArray()


class AnswerReader(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text[:MAX_ANSWER_CHARS]
        self.setWindowTitle("閱讀與複製回答")
        self.resize(780, 600)
        apply_theme(self)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.preview = QTextBrowser()
        self.preview.setUndoRedoEnabled(False)
        self.preview.setOpenLinks(False)
        self.preview.setOpenExternalLinks(False)
        document = LocalDocument(self.preview)
        document.setDefaultStyleSheet(
            themed_css(
                "body { font-size:15px; color:#182b36; }"
                "th { background-color:#edf1fc; padding:8px; } td { padding:8px; }"
                "pre { background-color:#f0f3f8; padding:10px; }"
            )
        )
        self.preview.setDocument(document)
        document.setMarkdown(
            self.text,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.SelectionType.Document)
        foreground = QTextCharFormat()
        foreground.setForeground(QColor(theme_color("#182b36")))
        cursor.mergeCharFormat(foreground)
        block = document.begin()
        while block.isValid():
            marker = block.charFormat()
            marker.setForeground(QColor(theme_color("#182b36")))
            QTextCursor(block).setBlockCharFormat(marker)
            block = block.next()
        tabs.addTab(self.preview, "排版閱讀")
        raw = QTextEdit()
        raw.setReadOnly(True)
        raw.setPlainText(self.text)
        tabs.addTab(raw, "原始文字")
        layout.addWidget(tabs, 1)
        layout.addWidget(QLabel("僅供閱讀，不載入外部圖片、不開啟連結、不執行程式碼。"))
        actions = QHBoxLayout()
        copy = QPushButton("複製完整回答")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text))
        actions.addWidget(copy)
        self.blocks = re.findall(r"(?m)^```[^\n]*\n(.*?)^```\s*$", self.text, flags=re.S | re.M)
        self.codes = QComboBox()
        for index, _ in enumerate(self.blocks):
            self.codes.addItem(f"程式碼區塊 {index + 1}")
        self.copy_code = QPushButton("複製程式碼")
        self.copy_code.setEnabled(bool(self.blocks))
        self.codes.setEnabled(bool(self.blocks))
        self.copy_code.clicked.connect(self.copy_selected_code)
        actions.addWidget(self.codes)
        actions.addWidget(self.copy_code)
        close = QPushButton("關閉")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)

    def copy_selected_code(self):
        index = self.codes.currentIndex()
        if 0 <= index < len(self.blocks):
            QApplication.clipboard().setText(self.blocks[index].rstrip("\n"))

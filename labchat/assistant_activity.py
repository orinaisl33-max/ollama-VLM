"""A viewport-anchored progress indicator next to the current assistant heading."""

from PySide6.QtCore import QElapsedTimer, QEvent, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .indicators import BusyIndicator


class AssistantActivity(QWidget):
    def __init__(self, editor):
        super().__init__(editor.viewport())
        self.editor = editor
        self.anchor = None
        self.active = False
        self.receiving = False
        self.clock = QElapsedTimer()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("AI 回覆處理狀態")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.spinner = BusyIndicator(self)
        row.addWidget(self.spinner)
        self.label = QLabel()
        self.label.setObjectName("muted")
        row.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        editor.verticalScrollBar().valueChanged.connect(self.reposition)
        editor.document().documentLayout().documentSizeChanged.connect(self.reposition)
        editor.viewport().installEventFilter(self)
        self.hide()

    def start(self, cursor):
        self.anchor = QTextCursor(cursor)
        self.anchor.setKeepPositionOnInsert(True)
        self.active = True
        self.receiving = False
        self.clock.start()
        self.spinner.set_running(True)
        self.timer.start()
        self.refresh()

    def mark_receiving(self):
        self.receiving = True
        self.refresh()

    def refresh(self):
        if not self.active:
            return
        seconds = max(0, self.clock.elapsed() // 1000)
        phase = "正在產生回答" if self.receiving else "準備模型／等待回應"
        self.label.setText(f"{phase} · {seconds} 秒")
        self.setToolTip(
            "首次或切換模型可能較久；可按「停止生成」。無法由等待時間判定實際載入進度。"
        )
        self.reposition()

    def reposition(self, *_args):
        if not self.active or self.anchor is None:
            return
        rect = self.editor.cursorRect(self.anchor)
        viewport = self.editor.viewport().rect()
        x = rect.right() + 8
        available = viewport.width() - x - 8
        if not viewport.intersects(rect) or available < 24:
            self.hide()
            return
        self.label.setVisible(available >= 200)
        self.adjustSize()
        self.move(x, rect.center().y() - self.height() // 2)
        self.show()
        self.raise_()

    def stop(self):
        self.active = False
        self.timer.stop()
        self.spinner.set_running(False)
        self.anchor = None
        self.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.reposition)
        return super().eventFilter(watched, event)

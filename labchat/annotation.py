"""Interactive approximate grounding and manual annotations on the supplied image."""

import base64
import hashlib
import html
import json
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QIODevice, QPointF, QRectF, QSaveFile, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .attachments import validate_boxes
from .client import ChatClient
from .config import find_model
from .grounding import (
    DEFAULT_AI_BOXES,
    MAX_BOXES,
    Box,
    grounding_messages,
    grounding_schema,
    parse_boxes,
    preview_boxes,
)
from .indicators import BusyIndicator
from .labelme_export import labelme_document
from .security import clean_label
from .theme import apply_theme, local_style, theme_color

COLORS = ("#2454b8", "#ac3f20", "#24743f", "#7b3aaa", "#8c6414", "#087b86")


def paint_boxes(painter, rect, boxes, selected=-1, *, preview=False):
    scale_x, scale_y = rect.width() / 1000, rect.height() / 1000
    painter.setFont(QFont("PingFang TC", 11))
    metrics = painter.fontMetrics()
    labels = []
    for index, box in enumerate(boxes):
        x1, y1, x2, y2 = box.bbox
        area = QRectF(
            rect.left() + x1 * scale_x,
            rect.top() + y1 * scale_y,
            (x2 - x1) * scale_x,
            (y2 - y1) * scale_y,
        )
        color = QColor(COLORS[index % len(COLORS)])
        painter.setPen(QPen(color, 3 if index == selected else 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(area)
        suffix = ("AI預覽" if preview else "AI估計") if box.source == "model" else "人工"
        label = f"{index + 1}. {box.label} · {suffix}"
        width = min(metrics.horizontalAdvance(label) + 12, rect.width())
        label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, max(1, int(width - 12)))
        left = min(max(rect.left(), area.left()), rect.right() - width)
        height = metrics.height() + 8
        labels.append((left, area.top(), width, height, label, color))
    placed = []
    for left, top, width, height, label, color in labels:
        candidates = []
        for offset in (-1, 0, -2, 1, -3, 2, -4, 3):
            y = min(max(rect.top(), top + offset * (height + 3)), rect.bottom() - height)
            candidates.append(QRectF(left, y, width, height))

        def overlap(candidate):
            return sum(
                candidate.intersected(other).width() * candidate.intersected(other).height()
                for other in placed
                if candidate.intersects(other)
            )

        background = min(candidates, key=overlap)
        placed.append(background)
        painter.setPen(QPen(color, 1))
        painter.drawLine(
            QPointF(left, top),
            QPointF(background.left(), background.center().y()),
        )
        painter.fillRect(background, color)
        painter.setPen(QColor("white"))
        painter.drawText(background.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, label)


class AnnotationCanvas(QWidget):
    rectangle_drawn = Signal(object)
    geometry_changed = Signal(object)
    selection_changed = Signal(int)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.boxes = []
        self.preview = None
        self.selected = -1
        self.start = None
        self.end = None
        self.edit_mode = False
        self._drag = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360, 240)
        self.setMouseTracking(True)

    def image_rect(self):
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF(
            (self.width() - size.width()) / 2,
            (self.height() - size.height()) / 2,
            size.width(),
            size.height(),
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme_color("#f0f3f8")))
        rect = self.image_rect()
        painter.drawImage(rect, self.image)
        paint_boxes(
            painter,
            rect,
            self.boxes if self.preview is None else self.preview,
            self.selected,
            preview=self.preview is not None,
        )
        if self.preview is None and self.edit_mode and 0 <= self.selected < len(self.boxes):
            coords = self.boxes[self.selected].bbox
            painter.setPen(QPen(QColor(theme_color("#2b4098")), 2))
            painter.setBrush(QColor("white"))
            for x, y in (
                (coords[0], coords[1]),
                (coords[2], coords[1]),
                (coords[2], coords[3]),
                (coords[0], coords[3]),
            ):
                point = QPointF(
                    rect.left() + x * rect.width() / 1000, rect.top() + y * rect.height() / 1000
                )
                painter.drawRect(QRectF(point.x() - 5, point.y() - 5, 10, 10))
        if self.start is not None and self.end is not None:
            painter.setPen(QPen(QColor(theme_color("#2b4098")), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(self.start, self.end).normalized())

    def mousePressEvent(self, event):
        if self.edit_mode and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            rect = self.image_rect()
            point = event.position()
            if not rect.contains(point):
                return
            nx, ny = (
                (point.x() - rect.left()) / rect.width() * 1000,
                (point.y() - rect.top()) / rect.height() * 1000,
            )
            candidates = [self.selected] if 0 <= self.selected < len(self.boxes) else []
            candidates += [i for i in reversed(range(len(self.boxes))) if i not in candidates]
            for index in candidates:
                x1, y1, x2, y2 = self.boxes[index].bbox
                corner = None
                if index == self.selected:
                    for number, (x, y) in enumerate(((x1, y1), (x2, y1), (x2, y2), (x1, y2))):
                        if (
                            abs(nx - x) * rect.width() / 1000 <= 10
                            and abs(ny - y) * rect.height() / 1000 <= 10
                        ):
                            corner = number
                            break
                if corner is not None or x1 <= nx <= x2 and y1 <= ny <= y2:
                    self.selected = index
                    self.selection_changed.emit(index)
                    self._drag = (list(self.boxes), index, nx, ny, corner)
                    return
            return
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(
            event.position()
        ):
            self.start = event.position()
            self.end = self.start
            self.update()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            before, index, sx, sy, corner = self._drag
            rect = self.image_rect()
            nx = min(
                1000, max(0, round((event.position().x() - rect.left()) / rect.width() * 1000))
            )
            ny = min(
                1000, max(0, round((event.position().y() - rect.top()) / rect.height() * 1000))
            )
            original = before[index]
            x1, y1, x2, y2 = original.bbox
            if corner is None:
                dx, dy = (
                    round(min(1000 - x2, max(-x1, nx - sx))),
                    round(min(1000 - y2, max(-y1, ny - sy))),
                )
                coords = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
            else:
                left = nx if corner in (0, 3) else x1
                right = nx if corner in (1, 2) else x2
                top = ny if corner in (0, 1) else y1
                bottom = ny if corner in (2, 3) else y2
                coords = (min(left, right), min(top, bottom), max(left, right), max(top, bottom))
                if coords[2] - coords[0] < 2 or coords[3] - coords[1] < 2:
                    return
            self.boxes[index] = Box(original.label, coords, "manual")
            self.update()
            return
        if self.start is not None:
            rect = self.image_rect()
            self.end = QPointF(
                min(max(event.position().x(), rect.left()), rect.right()),
                min(max(event.position().y(), rect.top()), rect.bottom()),
            )
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)
            before = self._drag[0]
            self._drag = None
            if [box.bbox for box in self.boxes] != [box.bbox for box in before]:
                self.geometry_changed.emit(before)
            else:
                self.boxes = before
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        self.mouseMoveEvent(event)
        area = QRectF(self.start, self.end).normalized()
        self.start = self.end = None
        self.update()
        if area.width() < 6 or area.height() < 6:
            return
        image = self.image_rect()
        coords = (
            round((area.left() - image.left()) / image.width() * 1000),
            round((area.top() - image.top()) / image.height() * 1000),
            round((area.right() - image.left()) / image.width() * 1000),
            round((area.bottom() - image.top()) / image.height() * 1000),
        )
        if coords[2] > coords[0] and coords[3] > coords[1]:
            self.rectangle_drawn.emit(coords)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self.boxes = self._drag[0]
            self._drag = None
            self.update()
            return
        super().keyPressEvent(event)

    def export_image(self):
        result = self.image.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_boxes(painter, QRectF(0, 0, result.width(), result.height()), self.boxes)
        painter.end()
        return result


class AnnotationDialog(QDialog):
    def __init__(self, encoded_image, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("圖片檢視與物件框選")
        self.setObjectName("annotationDialog")
        apply_theme(self)
        local_style(
            self,
            """
            QDialog#annotationDialog { background: #f4f7f8; }
            QLabel#annotationTitle { color: #182b36; font-size: 23px; font-weight: 700; }
            QLabel#annotationNotice { color: #7c5b23; background: #fff4df;
                                      border: 1px solid #f0dfbb; border-radius: 10px; padding: 10px 12px; }
            QLineEdit { color: #182b36; background: white; border: 1px solid #cbd7e3;
                        border-radius: 9px; padding: 10px 12px; selection-background-color: #dfe5fa; }
            QLineEdit:focus { border-color: #2b4098; }
            QLineEdit:disabled { background: #eef2f6; color: #71818b; }
            QFrame#annotationSidebar { background: white; border: 1px solid #dce5e8; border-radius: 12px; }
            QLabel#listTitle { color: #243986; font-weight: 600; font-size: 15px; }
            QListWidget { background: white; color: #182b36; border: none; outline: none; padding: 2px; }
            QListWidget::item { color: #243b48; padding: 10px 8px; margin: 2px 0; border-radius: 6px; }
            QListWidget::item:hover { background: #f0f3fc; }
            QListWidget::item:selected { color: #22347e; background: #e4eafa; }
            QListWidget:disabled { color: #84939b; }
            QSplitter::handle { background: transparent; width: 12px; }
            QPushButton#deleteBox { color: #a53f3f; }
        """,
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1080, 760)
        self.setMinimumSize(760, 600)
        self.encoded_image = encoded_image
        image = QImage.fromData(base64.b64decode(encoded_image))
        if image.isNull():
            raise ValueError("圖片無法讀取。")
        self.model = model
        configuration = find_model(model)
        self._vision = configuration is None or configuration.vision
        self._grounding = self._vision and (configuration is None or configuration.grounding)
        self._format_fallback = False
        self._request_limit = DEFAULT_AI_BOXES
        self._stream_text = ""
        self._stream_open = False
        self._request_messages = []
        self._closed = False
        self._undo_history = []
        self._redo_history = []
        self.client = ChatClient(self)
        self.client.chunk.connect(self._preview_chunk)
        self.client.completed.connect(self._completed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)
        title = QLabel("影像標註工作區")
        title.setObjectName("annotationTitle")
        layout.addWidget(title)
        notice = QLabel(
            "AI 建議框是模型估計，可能漏框或位置不準。請核對並修正；框數不等於實際物件總數。"
        )
        notice.setWordWrap(True)
        notice.setObjectName("annotationNotice")
        layout.addWidget(notice)
        self.model_label = QLabel(
            f"框選模型：{configuration.label if configuration else model}（{model}）"
        )
        self.model_label.setWordWrap(True)
        self.model_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.model_label)
        controls = QHBoxLayout()
        self.target = QLineEdit()
        self.target.setMaxLength(120)
        self.target.setPlaceholderText("建議指定目標，例如：人物、輪椅；留空僅找少量主要物件")
        self.auto_button = QPushButton("AI 建議框")
        self.auto_button.setObjectName("primary")
        self.auto_button.clicked.connect(self.automatic)
        self.cancel_button = QPushButton("停止定位")
        self.cancel_button.clicked.connect(lambda: self.client.cancel())
        self.cancel_button.hide()
        self.spinner = BusyIndicator()
        self.elapsed_label = QLabel()
        self.elapsed_label.setObjectName("muted")
        self.elapsed_label.setAccessibleName("定位運行時間")
        self.elapsed_label.setToolTip("本次定位已經過的時間，包含相容模式重試；不是預估剩餘時間。")
        self.elapsed_label.hide()
        self.elapsed_clock = QElapsedTimer()
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(250)
        self.elapsed_timer.timeout.connect(self._update_elapsed)
        controls.addWidget(self.target, 1)
        controls.addWidget(self.spinner)
        controls.addWidget(self.elapsed_label)
        controls.addWidget(self.auto_button)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        scope_bar = QHBoxLayout()
        scope_bar.addWidget(QLabel("AI 框數上限"))
        self.box_limit = QSpinBox()
        self.box_limit.setRange(1, 20)
        self.box_limit.setValue(DEFAULT_AI_BOXES)
        self.box_limit.setToolTip("上限不是實際數量；只找單一人物時可設 1–3，降低等待與細碎框。")
        scope_bar.addWidget(self.box_limit)
        scope_hint = QLabel("先指定目標，再少量框選；不需要填滿上限。")
        scope_hint.setWordWrap(True)
        scope_bar.addWidget(scope_hint, 1)
        layout.addLayout(scope_bar)
        edit_bar = QHBoxLayout()
        self.edit_mode = QComboBox()
        self.edit_mode.addItems(["新增框", "移動／調整框（拖曳四角縮放）"])
        self.edit_mode.currentIndexChanged.connect(self._set_edit_mode)
        self.undo_button = QPushButton("復原")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("重做")
        self.redo_button.clicked.connect(self.redo)
        self.import_json = QPushButton("匯入專案 JSON")
        self.import_json.setToolTip("匯入本工具的正規化座標格式；Labelme JSON請在Labelme開啟。")
        self.import_json.clicked.connect(self._import_json)
        for widget in (self.edit_mode, self.undo_button, self.redo_button, self.import_json):
            edit_bar.addWidget(widget)
        layout.addLayout(edit_bar)
        content = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = AnnotationCanvas(image)
        self.canvas.rectangle_drawn.connect(self._manual)
        self.canvas.geometry_changed.connect(self._geometry_changed)
        content.addWidget(self.canvas)
        sidebar = QFrame()
        sidebar.setObjectName("annotationSidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(320)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 16, 12, 12)
        self.list_title = QLabel("物件清單 · 0 個框")
        self.list_title.setObjectName("listTitle")
        side_layout.addWidget(self.list_title)
        self.items = QListWidget()
        self.items.setWordWrap(True)
        self.items.setSpacing(2)
        self.items.currentRowChanged.connect(self._selected)
        self.canvas.selection_changed.connect(self.items.setCurrentRow)
        side_layout.addWidget(self.items, 1)
        self.rename = QPushButton("修改名稱")
        self.rename.clicked.connect(self._rename)
        self.delete = QPushButton("刪除選取")
        self.delete.setObjectName("deleteBox")
        self.delete.clicked.connect(self._delete)
        edits = QHBoxLayout()
        edits.addWidget(self.rename)
        edits.addWidget(self.delete)
        side_layout.addLayout(edits)
        content.addWidget(sidebar)
        content.setChildrenCollapsible(False)
        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 0)
        content.setSizes([760, 250])
        layout.addWidget(content, 1)
        hint = QLabel(
            "新增模式可拖曳畫框；調整模式可移動框或拖曳四角縮放，Esc取消拖動。可復原／重做最近50步。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.export_png = QPushButton("匯出標註 PNG")
        self.export_png.clicked.connect(self._export_png)
        self.export_json = QPushButton("匯出專案 JSON")
        self.export_json.setToolTip("本工具格式，座標0–1000；Labelme請使用另一個匯出按鈕。")
        self.export_json.clicked.connect(self._export_json)
        self.export_labelme = QPushButton("匯出 Labelme JSON")
        self.export_labelme.setToolTip("內嵌未畫框的前處理PNG與像素座標矩形；可直接在Labelme開啟。")
        self.export_labelme.clicked.connect(self._export_labelme)
        for button in (self.export_png, self.export_json, self.export_labelme):
            buttons.addWidget(button)
        buttons.addStretch()
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.status = QLabel("已載入圖片 · 可以手動畫框，或使用 AI 建議框。")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self._refresh()
        if not self._vision:
            self.status.setText("目前模型僅支援文字；仍可手動畫框與匯出，AI 建議框請切換圖文模型。")
        if self._vision and not self._grounding:
            self.status.setText(
                "此模型的 AI 定位未通過驗證；仍可看圖聊天、手動畫框與匯出，AI 建議框請切換其他圖文模型。"
            )
        self._fit_screen()

    def _fit_screen(self):
        screen = self.parentWidget().screen() if self.parentWidget() else self.screen()
        if screen is None:
            return
        area = screen.availableGeometry().adjusted(16, 32, -16, -16)
        self.setMinimumSize(
            min(self.minimumWidth(), area.width()), min(self.minimumHeight(), area.height())
        )
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)

    def _set_edit_mode(self, index):
        self.canvas.edit_mode = index == 1
        self.canvas.start = self.canvas.end = None
        self.canvas.update()

    def _checkpoint(self, before=None):
        self._undo_history.append(list(self.canvas.boxes if before is None else before))
        self._undo_history = self._undo_history[-50:]
        self._redo_history.clear()

    def _geometry_changed(self, before):
        self._checkpoint(before)
        self._refresh()

    def undo(self):
        if not self.client.active and self._undo_history:
            self._redo_history.append(list(self.canvas.boxes))
            self.canvas.boxes = self._undo_history.pop()
            self._refresh()

    def redo(self):
        if not self.client.active and self._redo_history:
            self._undo_history.append(list(self.canvas.boxes))
            self.canvas.boxes = self._redo_history.pop()
            self._refresh()

    def _refresh(self):
        selected = self.items.currentRow()
        self.items.clear()
        boxes = self.canvas.boxes if self.canvas.preview is None else self.canvas.preview
        preview = self.canvas.preview is not None
        for index, box in enumerate(boxes):
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(COLORS[index % len(COLORS)]))
            item = QListWidgetItem(
                QIcon(swatch),
                f"{index + 1}. {box.label}\n"
                + (
                    ("AI 預覽 · 尚未完成" if preview else "AI 建議 · 待核對")
                    if box.source == "model"
                    else "手動標註"
                ),
            )
            item.setToolTip(html.escape(box.label))
            self.items.addItem(item)
        self.list_title.setText(f"{'預覽清單' if preview else '物件清單'} · {len(boxes)} 個框")
        if boxes:
            self.items.setCurrentRow(min(max(0, selected), len(boxes) - 1))
        self.canvas.update()
        self._controls(self.client.active)

    def _controls(self, busy):
        self.spinner.set_running(busy)
        self.auto_button.setVisible(not busy)
        self.auto_button.setEnabled(not busy and self._grounding)
        self.auto_button.setToolTip(
            "AI 估計框，需人工核對。"
            if self._grounding
            else "此模型不提供 AI 定位；可手動畫框與匯出。"
        )
        self.cancel_button.setVisible(busy)
        for widget in (self.target, self.canvas, self.items, self.export_png, self.export_json):
            widget.setEnabled(not busy)
        self.export_labelme.setEnabled(not busy)
        selected = 0 <= self.items.currentRow() < len(self.canvas.boxes)
        self.rename.setEnabled(selected and not busy)
        self.delete.setEnabled(selected and not busy)
        self.undo_button.setEnabled(bool(self._undo_history) and not busy)
        self.redo_button.setEnabled(bool(self._redo_history) and not busy)
        self.import_json.setEnabled(not busy)
        self.edit_mode.setEnabled(not busy)
        self.box_limit.setEnabled(not busy)

    def _selected(self, index):
        self.canvas.selected = index
        self.canvas.update()
        self._controls(self.client.active)

    def _manual(self, coords):
        if len(self.canvas.boxes) >= MAX_BOXES:
            self.status.setText("已達 60 個框，請先刪除不需要的框。")
            return
        name, ok = QInputDialog.getText(self, "新增框", "物件名稱：")
        if ok and clean_label(name):
            self._checkpoint()
            self.canvas.boxes.append(Box(clean_label(name), tuple(coords), "manual"))
            self._refresh()

    def _rename(self):
        index = self.items.currentRow()
        if index < 0:
            return
        box = self.canvas.boxes[index]
        name, ok = QInputDialog.getText(self, "修改名稱", "物件名稱：", text=box.label)
        if ok and clean_label(name):
            self._checkpoint()
            self.canvas.boxes[index] = Box(clean_label(name), box.bbox, "manual")
            self._refresh()

    def _delete(self):
        index = self.items.currentRow()
        if index >= 0:
            self._checkpoint()
            del self.canvas.boxes[index]
            self._refresh()

    def _update_elapsed(self, finished=False):
        if not self.elapsed_clock.isValid():
            return
        seconds = self.elapsed_clock.elapsed() // 1000
        minutes, seconds = divmod(seconds, 60)
        prefix = "本次耗時" if finished else "已運行"
        self.elapsed_label.setText(f"{prefix} {minutes:02d}:{seconds:02d}")

    def automatic(self):
        if self._closed or self.client.active:
            return
        if not self._grounding:
            self.status.setText("此模型不提供 AI 圖片定位，請使用手動畫框或切換其他圖文模型。")
            return
        self._format_fallback = False
        self._stream_text = ""
        self._stream_open = True
        self.canvas.preview = None
        self._request_limit = self.box_limit.value()
        self._request_messages = grounding_messages(
            self.encoded_image, self.target.text(), self._request_limit
        )
        self.elapsed_clock.start()
        self._update_elapsed()
        self.elapsed_label.show()
        self.elapsed_timer.start()
        self.client.start(
            self.model,
            self._request_messages,
            format_schema=grounding_schema(self._request_limit),
            max_tokens=128 + self._request_limit * 96,
            deterministic=True,
        )
        self._controls(True)
        self.status.setText("正在估計物件位置… 小型模型可能需要較長時間，完成後請核對。")

    def _preview_chunk(self, piece):
        if self._closed or not self._stream_open:
            return
        if len(self._stream_text) + len(piece) > 32000:
            return
        self._stream_text += piece
        try:
            boxes = preview_boxes(self._stream_text, self._request_limit)
        except ValueError:
            return
        manual = [box for box in self.canvas.boxes if box.source == "manual"]
        if not boxes or len(manual) + len(boxes) > MAX_BOXES:
            return
        shown = manual + boxes
        if shown == self.canvas.preview:
            return
        self.canvas.preview = shown
        self._refresh()
        self.status.setText(f"已預覽 {len(boxes)} 個 AI 框 · 仍在生成，完成前不會保存或匯出。")

    def _completed(self, result):
        if self._closed:
            return
        self.canvas.preview = None
        self._stream_text = ""
        self._stream_open = False
        if (
            result.status == "error"
            and result.http_status in (400, 501)
            and not self._format_fallback
        ):
            self._format_fallback = True
            self._stream_open = True
            self._refresh()
            self.client.start(
                self.model,
                self._request_messages,
                max_tokens=128 + self._request_limit * 96,
                deterministic=True,
            )
            self._controls(True)
            self.status.setText("此後端不支援指定輸出格式，正在改用相容模式定位…")
            return
        self.elapsed_timer.stop()
        self._update_elapsed(finished=True)
        if result.status == "success" and not result.truncated:
            try:
                boxes = parse_boxes(result.answer)
                if len(boxes) > self._request_limit:
                    raise ValueError("模型超出本次框數上限，原標註保留。請指定目標後重試。")
                manual = [box for box in self.canvas.boxes if box.source == "manual"]
                if len(manual) + len(boxes) > MAX_BOXES:
                    raise ValueError("人工框與 AI 框合計超出 60 個，原標註保留；請先整理人工框。")
                self._checkpoint()
                self.canvas.boxes = manual + boxes
                self.status.setText(
                    f"收到 {len(boxes)} 個 AI 建議框 · 請核對漏框、重複與位置。保留既有人工框。"
                    if boxes
                    else "模型未找到可定位物件，可改用手動畫框。"
                )
            except ValueError as error:
                self.status.setText(str(error))
        elif result.status == "cancelled":
            self.status.setText("已停止定位，原有標註保留。")
        elif result.truncated:
            self.status.setText(
                "模型輸出達長度上限，未套用不完整框。原標註保留；請縮小搜尋目標後重試。"
            )
        else:
            self.status.setText("定位未完成，原有標註保留。可重試或手動畫框。 " + result.error)
        self._refresh()

    def _save(self, path, data):
        file = QSaveFile(path)
        file.setDirectWriteFallback(False)
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            return False
        if isinstance(data, QImage):
            ok = data.save(file, "PNG")
        else:
            ok = file.write(data) == len(data)
        if not ok:
            file.cancelWriting()
            return False
        return file.commit()

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "匯出標註圖片", "物件框選.png", "PNG (*.png)")
        if path and not self._save(path, self.canvas.export_image()):
            QMessageBox.warning(self, "匯出失敗", "無法寫入檔案，請確認路徑與權限。")

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出標註資料", "物件框選.json", "JSON (*.json)"
        )
        payload = {
            "image_size": [self.canvas.image.width(), self.canvas.image.height()],
            "image_sha256": hashlib.sha256(base64.b64decode(self.encoded_image)).hexdigest(),
            "coordinate_system": "xyxy_normalized_0_1000",
            "model": self.model,
            "notice": "Model boxes are approximate; manual review required. No confidence scores.",
            "objects": [box.to_dict() for box in self.canvas.boxes],
        }
        if path and not self._save(
            path, json.dumps(payload, ensure_ascii=False, indent=2).encode()
        ):
            QMessageBox.warning(self, "匯出失敗", "無法寫入檔案，請確認路徑與權限。")

    def _export_labelme(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出Labelme標註（內嵌前處理圖片）", "labelme_annotation.json", "JSON (*.json)"
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".json"
        try:
            if Path(path).suffix.lower() != ".json":
                raise ValueError("請使用.json副檔名。")
            payload = labelme_document(
                self.encoded_image, self.canvas.boxes, Path(path).stem + ".png"
            )
            data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode(
                "utf-8"
            )
            if not self._save(path, data):
                raise ValueError("無法寫入檔案；請檢查路徑、權限與磁碟空間。")
        except ValueError as error:
            QMessageBox.warning(self, "Labelme匯出失敗", str(error))
            return
        self.status.setText(
            "Labelme JSON已匯出 · 內嵌未畫框的前處理PNG（最長1024像素）與像素座標；AI框仍需核對。"
        )

    def import_annotations(self, path):
        with Path(path).open("rb") as source:
            data = source.read(256 * 1024 + 1)
        if len(data) > 256 * 1024:
            raise ValueError("標註檔超過256KiB上限。")
        try:
            payload = json.loads(data.decode("utf-8-sig"))
        except (ValueError, RecursionError) as error:
            raise ValueError("無法解析標註JSON。") from error
        required = {"image_size", "coordinate_system", "objects"}
        allowed = required | {"image_sha256", "model", "notice"}
        if not isinstance(payload, dict) or not required <= set(payload) <= allowed:
            raise ValueError("標註欄位不符。")
        if payload["coordinate_system"] != "xyxy_normalized_0_1000" or payload["image_size"] != [
            self.canvas.image.width(),
            self.canvas.image.height(),
        ]:
            raise ValueError("標註的座標系統或圖片尺寸不符。")
        digest = hashlib.sha256(base64.b64decode(self.encoded_image)).hexdigest()
        if "image_sha256" in payload and payload["image_sha256"] != digest:
            raise ValueError("標註不屬於目前這張圖片，未套用。")
        boxes = validate_boxes(payload["objects"])
        message = "匯入將取代目前全部框選，可用復原還原。"
        if "image_sha256" not in payload:
            message += "\n舊檔無圖片雜湊，只能確認尺寸；請自行核對是否為同一張圖。"
        if (
            QMessageBox.question(
                self,
                "確認匯入標註",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return False
        self._checkpoint()
        self.canvas.boxes = boxes
        self._refresh()
        return True

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入標註", "", "JSON (*.json)")
        if path:
            try:
                self.import_annotations(path)
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, "標註未匯入", str(error))

    def done(self, result):
        self._closed = True
        self._stream_open = False
        self.canvas.preview = None
        self.elapsed_timer.stop()
        self.client.shutdown()
        self.spinner.set_running(False)
        super().done(result)

"""Plain-text archive browser; deletion always requires explicit confirmation."""

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .conversation_io import read_document, write_document
from .conversations import HistoryError
from .theme import apply_theme, local_style


class ConversationDialog(QDialog):
    deleted = Signal(str)
    saving_changed = Signal(bool)
    cleared = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.selected_id = None
        self.setWindowTitle("本機對話紀錄")
        self.resize(580, 500)
        apply_theme(self)
        layout = QVBoxLayout(self)
        note = QLabel("本機保存文字紀錄與草稿（未加密）。\n匯出及刪除前請確認所選紀錄。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setMaxLength(200)
        self.search.setPlaceholderText("搜尋名稱與問答全文…")
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self.filter)
        self.search.textChanged.connect(self._schedule_search)
        layout.addWidget(self.search)
        self.items = QListWidget()
        self.items.setWordWrap(True)
        local_style(
            self.items,
            "QListWidget { background:white; border:1px solid #d5e0e4; border-radius:8px; }"
            "QListWidget::item { padding:12px; border-bottom:1px solid #edf1f5; }"
            "QListWidget::item:selected { background:#e4eafa; color:#243986; }",
        )
        self.items.itemDoubleClicked.connect(self.open_selected)
        self.items.currentItemChanged.connect(self.update_actions)
        layout.addWidget(self.items, 1)
        self.empty_note = QLabel("尚無對話紀錄，完成一次文字或圖片問答後就會自動儲存。")
        self.empty_note.setWordWrap(True)
        layout.addWidget(self.empty_note)
        actions = QHBoxLayout()
        self.open_button = QPushButton("繼續對話")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_selected)
        self.rename_button = QPushButton("重新命名")
        self.rename_button.clicked.connect(self.rename_selected)
        self.delete_button = QPushButton("刪除")
        self.delete_button.clicked.connect(self.delete_selected)
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        for button in (self.open_button, self.rename_button, self.delete_button, close):
            actions.addWidget(button)
        layout.addLayout(actions)
        transfer = QHBoxLayout()
        self.export_button = QPushButton("匯出 JSON／Markdown")
        self.export_button.clicked.connect(self.export_selected)
        self.import_button = QPushButton("匯入 JSON")
        self.import_button.clicked.connect(self.import_file)
        transfer.addWidget(self.export_button)
        transfer.addWidget(self.import_button)
        layout.addLayout(transfer)
        privacy = QHBoxLayout()
        self.saving = QCheckBox("自動保存文字與草稿")
        self.saving.setChecked(store.saving_enabled())
        self.saving.toggled.connect(self.change_saving)
        self.pin = QPushButton("釘選／取消釘選")
        self.pin.clicked.connect(self.pin_selected)
        clear = QPushButton("清除全部")
        clear.clicked.connect(self.clear_records)
        privacy.addWidget(self.saving)
        privacy.addWidget(self.pin)
        privacy.addWidget(clear)
        layout.addLayout(privacy)
        self.pictures = QCheckBox("另外保存附圖與標註（未加密，預設關閉，總量上限100MiB）")
        self.pictures.setChecked(store.pictures_enabled())
        self.pictures.toggled.connect(self.change_pictures)
        layout.addWidget(self.pictures)
        location = QLabel("儲存位置：" + str(store.path))
        location.setTextFormat(Qt.TextFormat.PlainText)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        location.setWordWrap(True)
        layout.addWidget(location)
        self.refresh()

    def refresh(self):
        previous = self.identifier()
        self.items.clear()
        try:
            for record in self.store.list():
                date = datetime.fromtimestamp(record["updated"]).strftime("%Y-%m-%d %H:%M")
                item = QListWidgetItem(
                    ("★ " if record["pinned"] else "") + record["title"] + "\n" + date
                )
                item.setSizeHint(QSize(0, 84))
                item.setData(Qt.ItemDataRole.UserRole, record["id"])
                self.items.addItem(item)
                if record["id"] == previous:
                    self.items.setCurrentItem(item)
        except HistoryError as error:
            QMessageBox.warning(self, "對話紀錄", str(error))
        self.filter()
        self.update_actions()

    def _schedule_search(self):
        if not self.search.text().strip():
            self.filter()
            return
        self.search_timer.start()
        for button in (
            self.open_button,
            self.rename_button,
            self.delete_button,
            self.export_button,
            self.pin,
        ):
            button.setEnabled(False)

    def filter(self):
        self.search_timer.stop()
        query = self.search.text().strip()
        try:
            matches = (
                {record["id"] for record in self.store.list(query)}
                if query
                else {
                    self.items.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.items.count())
                }
            )
        except HistoryError:
            matches = set()
        for index in range(self.items.count()):
            item = self.items.item(index)
            item.setHidden(item.data(Qt.ItemDataRole.UserRole) not in matches)
        self.empty_note.setText(
            "尚無對話紀錄，完成問答並啟用保存後就會建立紀錄。"
            if self.items.count() == 0
            else "找不到符合的對話紀錄。"
        )
        self.empty_note.setVisible(not matches)
        self.update_actions()

    def identifier(self):
        if self.search_timer.isActive():
            return None
        item = self.items.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item and not item.isHidden() else None

    def update_actions(self, *_):
        enabled = self.identifier() is not None
        for button in (self.open_button, self.rename_button, self.delete_button):
            button.setEnabled(enabled)
        if hasattr(self, "export_button"):
            self.export_button.setEnabled(enabled)
        if hasattr(self, "pin"):
            self.pin.setEnabled(enabled)

    def pin_selected(self):
        identifier = self.identifier()
        if identifier:
            try:
                record = self.store.load(identifier)
                self.store.set_pinned(identifier, not record["pinned"])
                self.refresh()
            except HistoryError as error:
                QMessageBox.warning(self, "對話紀錄", str(error))

    def change_saving(self, enabled):
        if (
            QMessageBox.question(
                self,
                "變更自動保存",
                "變更將建立新對話。未保存回覆、附件或標註請先保留；既有紀錄不會自動刪除。是否繼續？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            self.saving.blockSignals(True)
            self.saving.setChecked(not enabled)
            self.saving.blockSignals(False)
            return
        try:
            self.store.set_saving(enabled)
            self.saving_changed.emit(enabled)
        except HistoryError as error:
            self.saving.blockSignals(True)
            self.saving.setChecked(not enabled)
            self.saving.blockSignals(False)
            QMessageBox.warning(self, "設定失敗", str(error))

    def change_pictures(self, enabled):
        try:
            self.store.set_pictures(enabled)
        except HistoryError as error:
            self.pictures.blockSignals(True)
            self.pictures.setChecked(not enabled)
            self.pictures.blockSignals(False)
            QMessageBox.warning(self, "設定失敗", str(error))

    def clear_records(self):
        if (
            QMessageBox.question(
                self,
                "清除全部",
                "確定刪除所有已存對話、草稿、圖片與標註？此操作無法復原。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.store.clear_all()
            self.cleared.emit()
            self.refresh()
        except HistoryError as error:
            QMessageBox.warning(self, "清除失敗", str(error))

    def export_selected(self):
        if not self.identifier():
            return
        path, chosen = QFileDialog.getSaveFileName(
            self, "匯出文字對話", "conversation.json", "JSON (*.json);;Markdown (*.md)"
        )
        if not path:
            return
        suffix = ".md" if chosen.startswith("Markdown") else ".json"
        if not Path(path).suffix:
            path += suffix
        try:
            if (
                Path(path).suffix.lower() != suffix
                or Path(path).resolve() == self.store.path.resolve()
            ):
                raise HistoryError("請使用選定的JSON或Markdown副檔名，勿覆寫對話資料庫。")
            write_document(path, self.store.load(self.identifier()), markdown=suffix == ".md")
        except HistoryError as error:
            QMessageBox.warning(self, "匯出失敗", str(error))
            return
        QMessageBox.information(self, "匯出完成", "已匯出文字對話。檔案未加密，請妥善保存。")

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入文字對話", "", "JSON (*.json)")
        if not path:
            return
        try:
            record = read_document(path)
            question = QMessageBox(self)
            question.setWindowTitle("確認匯入")
            question.setTextFormat(Qt.TextFormat.PlainText)
            question.setText(
                f"名稱：{record['title']}\n共{len(record['turns'])}輪問答。\n將建立新紀錄，不覆寫既有對話。"
            )
            question.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            question.setDefaultButton(QMessageBox.StandardButton.No)
            if question.exec() != QMessageBox.StandardButton.Yes:
                return
            self.store.import_record(record)
            self.refresh()
        except HistoryError as error:
            QMessageBox.warning(self, "匯入失敗", str(error))

    def open_selected(self, *_):
        if self.identifier():
            self.selected_id = self.identifier()
            self.accept()

    def rename_selected(self):
        identifier = self.identifier()
        if not identifier:
            return
        text, accepted = QInputDialog.getText(self, "重新命名", "對話名稱（最多60字）：")
        if accepted:
            try:
                self.store.rename(identifier, text)
            except HistoryError as error:
                QMessageBox.warning(self, "對話紀錄", str(error))
            self.refresh()

    def delete_selected(self):
        identifier = self.identifier()
        if not identifier:
            return
        if (
            QMessageBox.question(
                self,
                "刪除對話",
                "確定刪除這組文字對話？此操作無法復原。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.store.delete(identifier)
        except HistoryError as error:
            QMessageBox.warning(self, "對話紀錄", str(error))
            return
        self.deleted.emit(identifier)
        self.refresh()


class ConversationSidebar(QWidget):
    activated = Signal(str)
    manage_requested = Signal()
    new_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = parent.store if parent else None
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 12, 0)
        self.new_button = QPushButton("＋ 新對話")
        self.new_button.clicked.connect(self.new_requested.emit)
        layout.addWidget(self.new_button)
        self.search = QLineEdit()
        self.search.setMaxLength(200)
        self.search.setPlaceholderText("搜尋對話…")
        self.search.setClearButtonEnabled(True)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self.filter)
        self.search.textChanged.connect(self._schedule_search)
        layout.addWidget(self.search)
        self.items = QListWidget()
        self.items.setWordWrap(True)
        local_style(
            self.items,
            "QListWidget { background:#f7f9fe; border:1px solid #dce5e8; border-radius:9px; padding:5px; outline:none; }"
            "QListWidget::item { color:#243b48; padding:12px 10px; margin:3px 0; border:1px solid #d5e0e4; border-radius:7px; background:white; }"
            "QListWidget::item:hover { background:#eef2fc; border-color:#aab8e2; }"
            "QListWidget::item:selected { background:#dfe5fa; color:#253a86; border:1px solid #2b4098; }",
        )
        self.items.itemClicked.connect(self._activate)
        layout.addWidget(self.items, 1)
        self.manage = QPushButton("管理／匯入匯出")
        self.manage.setToolTip(
            "釘選、更名、搜尋與匯出對話，以及管理保存設定。圖片標註匯出請開啟「框選／匯出」。"
        )
        self.manage.clicked.connect(self.manage_requested.emit)
        layout.addWidget(self.manage)
        note = QLabel("本機儲存 · 未加密")
        note.setObjectName("muted")
        layout.addWidget(note)

    def refresh(self, records, current):
        self.items.clear()
        for record in records:
            item = QListWidgetItem(("★ " if record["pinned"] else "") + record["title"])
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            item.setSizeHint(QSize(0, 68))
            item.setToolTip(html.escape(record["title"]))
            self.items.addItem(item)
            if record["id"] == current:
                self.items.setCurrentItem(item)
        self.filter()

    def _activate(self, item):
        if not self.search_timer.isActive():
            self.activated.emit(item.data(Qt.ItemDataRole.UserRole))

    def _schedule_search(self):
        if self.search.text().strip():
            self.search_timer.start()
        else:
            self.filter()

    def filter(self):
        self.search_timer.stop()
        query = self.search.text().strip().casefold()
        try:
            matches = (
                {record["id"] for record in self.store.list(query)}
                if self.store and query
                else {
                    self.items.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.items.count())
                }
            )
        except HistoryError:
            matches = set()
        for index in range(self.items.count()):
            item = self.items.item(index)
            item.setHidden(item.data(Qt.ItemDataRole.UserRole) not in matches)

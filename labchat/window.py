"""Qt presentation layer; request lifecycle and image decoding live in separate modules."""

import html
import logging
import time
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QStandardPaths, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextFrameFormat,
    QTextLength,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .annotation import AnnotationDialog
from .assistant_activity import AssistantActivity
from .client import ChatClient, ChatResult, ServiceProbe
from .config import (
    APP_TITLE,
    MAX_PROMPT_CHARS,
    MAX_TRANSCRIPT_CHARS,
    MODELS,
    build_messages,
    find_model,
    retain_turn,
)
from .conversation_widgets import ConversationDialog, ConversationSidebar
from .conversations import ConversationStore, HistoryError
from .dictation import DictationPanel
from .images import prepare_image
from .indicators import BusyIndicator
from .model_settings import ModelSettings
from .model_widgets import ModelCapabilityDelegate
from .preferences import DEFAULTS
from .reader import AnswerReader, LocalDocument
from .security import clean_label
from .service_widgets import ServiceStatusDialog
from .speech_widgets import SpeechPanel
from .theme import apply_theme, current_theme, theme_color
from .timestamps import clock_label

logger = logging.getLogger(__name__)


class PromptInput(QTextEdit):
    _composing = False

    def inputMethodEvent(self, event):
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if not self._composing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.window().submit()
                return
        super().keyPressEvent(event)


class Window(QMainWindow):
    def __init__(self, *, history_path=None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(980, 820)
        self.setMinimumSize(720, 680)
        apply_theme(self)
        self._logo_cache = {}
        self._logo = QPixmap(str(Path(__file__).resolve().parents[1] / "logo.png"))
        if not self._logo.isNull():
            self.setWindowIcon(QIcon(self._logo))
        self.client = ChatClient(self)
        self.client.chunk.connect(self._on_chunk)
        self.client.completed.connect(self._on_completed)
        self.probe = ServiceProbe(self.client.network, self)
        self.probe.updated.connect(self._on_service_checked)
        self.service_dialog = ServiceStatusDialog(self)
        self.service_dialog.retry_requested.connect(self.show_service_status)
        self.service_dialog.models_requested.connect(self.open_model_settings)
        self.installed_models = None
        self.history = []
        self._bulk_rendering = False
        self._copy_answer = ""
        self.pending = None
        self.answer = ""
        self._received_output = False
        self.image = None
        self.image_filename = ""
        self.last_image = None
        self.last_image_filename = ""
        self.annotation_dialog = None
        self.annotation_boxes = []
        self._annotation_sequence = None
        self.failed = False
        self._closing = False
        self._sidebar_requested = True
        self.conversation_id = None
        self.archive_failed = False
        self.store_error = ""
        self.store = None
        self._preferences_ready = False
        self._draft_save_failed = False
        if history_path is None:
            history_path = (
                Path(
                    QStandardPaths.writableLocation(
                        QStandardPaths.StandardLocation.GenericDataLocation
                    )
                )
                / "AI-System-Lab"
                / "conversations.sqlite3"
            )
        try:
            self.store = ConversationStore(history_path)
        except HistoryError as error:
            self.store_error = str(error)
        self._queued_text = []
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(40)
        self.render_timer.timeout.connect(self._flush_text)
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(500)
        self.draft_timer.timeout.connect(self._save_draft)
        self._draft_suspended = False
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 16)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.header_logo = QLabel()
        self.header_logo.setObjectName("headerLogo")
        self.header_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_logo.setFixedSize(56, 56)
        self.header_logo.setAccessibleName("實驗室標誌")
        self.header_logo.setVisible(not self._logo.isNull())
        if not self._logo.isNull():
            self.header_logo.setPixmap(self._logo_pixmap(46))
        top.addWidget(self.header_logo)
        brand = QVBoxLayout()
        brand.setSpacing(4)
        brand.addStretch()
        title = QLabel("人工智慧系統實驗室")
        self.brand_title = title
        title.setObjectName("brand")
        subtitle = QLabel("本機 AI 展示工具")
        subtitle.setObjectName("muted")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        brand.addStretch()
        top.addLayout(brand)
        top.addStretch()
        badge = QLabel("●  檢查服務中")
        self.badge = badge
        badge.setToolTip(
            "文字與圖片在本機推論，支援語音朗讀；Mac 支援本機語音輸入；不支援影片或圖片生成。"
        )
        badge.setObjectName("badge")
        badge.setFixedHeight(32)
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.compact_new = QPushButton("＋ 新對話")
        self.compact_new.clicked.connect(self.request_new_conversation)
        self.compact_new.hide()
        top.addWidget(self.compact_new)
        self.appearance_button = QPushButton()
        self.appearance_button.clicked.connect(self.toggle_appearance)
        top.addWidget(self.appearance_button)
        self.appearance_button.hide()
        self._update_appearance_button()
        layout.addLayout(top)

        workspace = QHBoxLayout()
        workspace.setSpacing(0)
        self.workspace_panel = QWidget()
        right_layout = QVBoxLayout(self.workspace_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        layout.addLayout(workspace, 1)

        model_bar = QHBoxLayout()
        model_bar.setSpacing(12)
        model_bar.addWidget(QLabel("模型"))
        self.model = QComboBox()
        self.model.setItemDelegate(ModelCapabilityDelegate(self.model))
        self.model.setMinimumWidth(220)
        for model in MODELS:
            self.model.addItem(model.label, model.identifier)
        self.model.setToolTip("切換前請先確認對應模型已安裝；切換後將建立新對話。")
        model_bar.addWidget(self.model)
        self.model_note = QLabel()
        self.model_note.setObjectName("muted")
        self.model_note.setWordWrap(True)
        model_bar.addWidget(self.model_note, 1)
        self.check_button = QPushButton("檢查服務")
        self.check_button.clicked.connect(self.check_service)
        self.history_button = QPushButton("對話紀錄")
        self.history_button.setToolTip(
            self.store_error
            or "顯示／收合左側對話列；小視窗開啟對話管理。文字與草稿依設定保存，圖片需另行啟用。"
        )
        self.history_button.setEnabled(self.store is not None)
        self.history_button.clicked.connect(self.toggle_sidebar)
        model_bar.addWidget(self.history_button)
        model_bar.addWidget(self.check_button)
        self.check_button.hide()
        self.model_settings_button = QPushButton("模型設定")
        self.model_settings_button.setToolTip("下載模型、複製 Ollama 指令或查看官方模型資訊。")
        self.model_settings_button.clicked.connect(self.open_model_settings)
        model_bar.addWidget(self.model_settings_button)
        self.model_settings_button.hide()
        self.model.currentIndexChanged.connect(self._model_changed)
        self.update_model_note()
        right_layout.addLayout(model_bar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("conversation")
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        self.welcome_layout = welcome_layout
        welcome_layout.setContentsMargins(36, 32, 36, 32)
        welcome_layout.setSpacing(10)
        welcome_layout.addStretch()
        symbol = QLabel("AI" if self._logo.isNull() else "")
        if not self._logo.isNull():
            symbol.setPixmap(self._logo_pixmap(68))
        symbol.setAccessibleName("實驗室標誌")
        self.welcome_mark = symbol
        symbol.setObjectName("welcomeMark")
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(symbol, 0, Qt.AlignmentFlag.AlignHCenter)
        heading = QLabel("探索人工智慧的實際應用")
        heading.setObjectName("welcomeTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(heading)
        description = QLabel("從重點摘要、程式解說到影像觀察。\n選擇下方示範，或直接輸入你的問題。")
        self.welcome_description = description
        description.setObjectName("muted")
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addWidget(description)
        welcome_layout.addSpacing(12)
        suggestions = QHBoxLayout()
        for label, detail, prompt in [
            (
                "重點摘要",
                "整理資訊與待辦事項",
                "請將以下示範會議紀錄整理為「重點摘要」與「待辦事項」，未提供的資訊請標示為未指定：\n"
                "實驗室預計下週展示本機 AI 工具。小林負責準備文字摘要範例，週三前完成；"
                "小陳負責圖片測試，週四前確認結果。展示時間尚未決定，需再與老師確認。",
            ),
            (
                "程式解說",
                "理解邏輯與執行結果",
                "請以 Python 初學者能理解的方式，逐步說明以下程式的邏輯、列出執行結果，"
                "並解釋為何只選取部分數字：\n\n"
                "numbers = [1, 2, 3, 4, 5]\n"
                "squares = [n ** 2 for n in numbers if n % 2 == 0]\n"
                "print(squares)",
            ),
            (
                "影像觀察",
                "辨識畫面與可見細節",
                "請分析我附加的圖片，依序說明：\n1. 畫面主題\n2. 主要物件與位置\n"
                "3. 可辨識的文字\n請區分直接觀察與推測；看不清楚的內容請明確說明，不要補寫。",
            ),
        ]:
            button = QPushButton(label + "  ↗\n" + detail)
            button.setToolTip("填入示範問題，檢閱或編輯後再傳送。")
            button.setObjectName("suggestion")
            button.setMinimumHeight(68)
            button.clicked.connect(lambda checked=False, text=prompt: self.use_suggestion(text))
            suggestions.addWidget(button)
        welcome_layout.addLayout(suggestions)
        welcome_layout.addStretch()
        self.pages.addWidget(welcome)
        self.chat = QTextEdit()
        self.chat.setObjectName("transcript")
        self.chat.setReadOnly(True)
        self.chat.setUndoRedoEnabled(False)
        self.chat.setAcceptRichText(False)
        self.chat.setDocument(LocalDocument(self.chat))
        self.chat.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # Character limits remain enforced by _trim_transcript; Qt block limits do not support frames.
        self.pages.addWidget(self.chat)
        self.assistant_activity = AssistantActivity(self.chat)
        self.sidebar = ConversationSidebar(self)
        self.sidebar.setFixedWidth(252)
        self.sidebar.activated.connect(self._activate_archive)
        self.sidebar.manage_requested.connect(self.open_history)
        self.sidebar.new_requested.connect(self.request_new_conversation)
        self.clear = self.sidebar.new_button
        self.clear.setObjectName("primary")
        self.clear.setToolTip("建立新對話；目前文字草稿依保存設定保留。")
        workspace.addWidget(self.sidebar)
        workspace.addWidget(self.workspace_panel, 1)
        right_layout.addWidget(self.pages, 1)

        self.speech_panel = SpeechPanel(self)

        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(16, 12, 16, 12)
        composer_layout.setSpacing(8)
        self.input = PromptInput()
        self.input.setObjectName("prompt")
        self.input.setAcceptRichText(False)
        self.input.textChanged.connect(self._update_send)
        self.input.textChanged.connect(self._schedule_draft)
        self.input.setPlaceholderText("輸入問題，或按「附加圖片」開始分析…")
        self.input.setFixedHeight(68)
        composer_layout.addWidget(self.input)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.attach = QPushButton("＋ 附加圖片")
        self.attach.setToolTip("支援 PNG、JPEG、WebP，每次一張；圖片僅用於當次提問。")
        self.attach.clicked.connect(self.choose_image)
        self.remove = QPushButton("移除圖片")
        self.remove.clicked.connect(self.remove_image)
        self.remove.hide()
        self.image_label = QLabel("")
        self.image_label.setObjectName("muted")
        self.image_label.setTextFormat(Qt.TextFormat.PlainText)
        self.image_label.setMaximumWidth(120)
        self.send = QPushButton("傳送 ↑")
        self.send.setObjectName("primary")
        self.send.setMinimumWidth(100)
        self.send.clicked.connect(self.submit)
        self.send.setEnabled(False)
        self.stop = QPushButton("停止生成")
        self.stop.setObjectName("stop")
        self.stop.setEnabled(False)
        self.stop.hide()
        self.stop.clicked.connect(self.cancel)
        self.attachment_bar = QWidget()
        attachment_row = QHBoxLayout(self.attachment_bar)
        attachment_row.setContentsMargins(0, 0, 0, 0)
        attachment_row.setSpacing(8)
        self.attachment_bar.hide()
        composer_layout.addWidget(self.attachment_bar)
        actions.addWidget(self.attach)
        self.annotate_button = QPushButton("框選／匯出")
        self.annotate_button.setToolTip(
            "開啟最近圖片，取得 AI 建議框、人工修正，並匯出 PNG、專案 JSON 或 Labelme JSON。新對話會清除最近圖片。"
        )
        self.annotate_button.clicked.connect(self.open_annotation)
        self.annotate_button.hide()
        attachment_row.addWidget(self.annotate_button)
        attachment_row.addWidget(self.image_label, 1)
        attachment_row.addWidget(self.remove)
        actions.addStretch()
        hint = QLabel("Enter 傳送 · Shift + Enter 換行")
        self.keyboard_hint = hint
        hint.setObjectName("keyboardHint")
        actions.addWidget(hint)
        actions.addWidget(self.stop)
        actions.addWidget(self.send)
        composer_layout.addLayout(actions)
        self.dictation = DictationPanel(self)
        self.dictation.set_compact()
        self.dictation.starting.connect(self.speech_panel.stop_reading)
        self.dictation.active_changed.connect(self._dictation_active)
        self.dictation.text_ready.connect(self._dictated_text)
        actions.insertWidget(1, self.dictation)
        actions.insertWidget(2, self.speech_panel)
        self.composer = composer
        right_layout.addWidget(composer)
        self.status = QLabel("操作提示：選擇示範後，檢閱內容並按「傳送」開始。")
        self.status.setObjectName("status")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.dictation.status_changed.connect(self.status.setText)
        self.speech_panel.controller.failed.connect(self.status.setText)
        footer = QVBoxLayout()
        footer.setSpacing(6)
        status_row = QHBoxLayout()
        self.spinner = BusyIndicator()
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.status, 1)
        footer.addLayout(status_row)
        self.picture_button = QPushButton("圖片紀錄")
        self.picture_button.setToolTip("檢視此對話已保存的圖片；圖片保存需先在對話管理中啟用。")
        self.picture_button.setEnabled(False)
        self.picture_button.clicked.connect(self.open_saved_picture)
        self.picture_button.setParent(self.workspace_panel)
        self.picture_button.hide()
        self.reuse_button = QPushButton("附圖再問")
        self.reuse_button.setToolTip("將最近圖片附到下一次提問；追問時不會自動再次傳送圖片。")
        self.reuse_button.setEnabled(False)
        self.reuse_button.clicked.connect(self.reuse_picture)
        self.reuse_button.setParent(self.workspace_panel)
        self.reuse_button.hide()
        self.read_button = QPushButton("閱讀／複製")
        self.read_button.setToolTip(
            "排版閱讀及複製最新回答。匯出完整對話請用左側「管理／匯入匯出」。"
        )
        self.read_button.setEnabled(False)
        self.read_button.clicked.connect(self.read_answer)
        self.read_button.setParent(self.workspace_panel)
        self.read_button.hide()
        self.answer_actions = QPushButton("回答操作 ⋯")
        answer_menu = QMenu(self)
        answer_menu.setToolTipsVisible(True)
        self.answer_menu_items = []
        for label, button in (
            ("閱讀／複製回答", self.read_button),
            ("圖片紀錄", self.picture_button),
            ("附圖再問", self.reuse_button),
        ):
            action = answer_menu.addAction(label)
            action.triggered.connect(button.click)
            self.answer_menu_items.append((action, button))
        answer_menu.aboutToShow.connect(self._sync_answer_menu)
        self.answer_actions.setMenu(answer_menu)
        self.copy_button = QPushButton("複製回答")
        self.copy_button.setToolTip(
            "複製最新完成的回答（⌘⇧C／Ctrl+Shift+C），保留原始文字與程式碼。"
        )
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_answer)
        status_row.addWidget(self.copy_button)
        status_row.addWidget(self.answer_actions)
        right_layout.addLayout(footer)
        self.model_settings = ModelSettings(self)
        self.model_settings.refresh_requested.connect(self.check_service)
        self.settings_button = QPushButton("設定")
        settings_menu = QMenu(self)
        self.voice_settings_action = settings_menu.addAction(
            "語音與朗讀…", self.speech_panel.show_settings
        )
        self.microphone_settings_action = settings_menu.addAction(
            "麥克風裝置與診斷…", self.dictation.show_settings
        )
        self.model_settings_action = settings_menu.addAction(
            "模型下載與說明…", self.open_model_settings
        )
        self.service_action = settings_menu.addAction("檢查本機服務", self.show_service_status)
        self.theme_action = settings_menu.addAction("", self.toggle_appearance)
        self.data_settings_action = settings_menu.addAction("對話與保存設定…", self.open_history)
        settings_menu.aboutToShow.connect(self._sync_settings_menu)
        self.settings_button.setMenu(settings_menu)
        model_bar.addWidget(self.settings_button)
        self._restore_preferences()
        self._set_draft_context(None)
        self._refresh_sidebar()
        self._preferences_ready = True
        for control in (self.speech_panel.voice, self.speech_panel.rate, self.speech_panel.mode):
            control.currentIndexChanged.connect(self._save_preferences)
        self.dictation.device_selected.connect(self._save_preferences)
        self.shortcuts = [
            QShortcut(QKeySequence.StandardKey.New, self, activated=self.request_new_conversation),
            QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.copy_answer),
        ]
        QTimer.singleShot(0, self.check_service)

    def copy_answer(self):
        if self.client.active or not self._copy_answer:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._copy_answer)
        self.status.setText("已複製最新完成回答的原始文字。")

    def _set_copy_answer(self, text):
        self._copy_answer = text
        self.copy_button.setEnabled(bool(text) and not self.client.active)

    def _restore_preferences(self):
        preferences = dict(DEFAULTS)
        if self.store:
            try:
                preferences = self.store.get_preferences()
            except HistoryError as error:
                self.status.setText(str(error))
        with QSignalBlocker(self.model):
            self.model.setCurrentIndex(self.model.findData(preferences["model"]))
        self.update_model_note()
        self.speech_panel.preferred_voice = preferences["voice"]
        self.speech_panel.rate.setCurrentIndex(
            self.speech_panel.rate.findData(preferences["speech_rate"])
        )
        self.speech_panel.mode.setCurrentIndex(
            self.speech_panel.mode.findData(preferences["speech_mode"])
        )
        self.dictation.set_preferred_device(preferences["microphone"])
        apply_theme(self, preferences["appearance"])
        self._update_appearance_button()

    def _save_preferences(self, *_):
        if not self._preferences_ready or self._closing or not self.store:
            return
        panel = self.speech_panel
        voice = panel.voice.currentData() or panel.preferred_voice
        try:
            self.store.save_preferences(
                {
                    "appearance": current_theme(),
                    "model": self.model.currentData(),
                    "voice": voice,
                    "speech_mode": panel.mode.currentData(),
                    "speech_rate": panel.rate.currentData(),
                    "microphone": self.dictation.preferred_device,
                }
            )
            panel.preferred_voice = voice
        except HistoryError as error:
            self.status.setText(str(error))

    def _prepare_leave(self, title, *, include_text=False):
        if self.client.active or self.dictation.state != "idle" or self._closing:
            return False
        if not self._save_draft():
            self.status.setText("草稿未能保存，已停止切換。請先複製保留或排除儲存問題。")
            return False
        text = bool(self.input.toPlainText().strip())
        try:
            unsaved_text = text and (not self.store or not self.store.saving_enabled())
        except HistoryError as error:
            self.status.setText(str(error))
            return False
        if (
            self.image
            or self.annotation_boxes
            or self.archive_failed
            or unsaved_text
            or include_text
            and text
        ):
            return (
                QMessageBox.question(
                    self,
                    title,
                    "切換將移除目前附件與工作區標註，並離開目前回答。"
                    "未保存文字、回答或未匯出標註請先複製／匯出；已保存草稿會保留。是否繼續？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            )
        return True

    def _schedule_draft(self):
        if not self._draft_suspended and not self._closing and hasattr(self, "_draft_key"):
            self.draft_timer.start()

    def _save_draft(self):
        self.draft_timer.stop()
        if self.store is None or not hasattr(self, "_draft_key"):
            self._draft_save_failed = bool(self.input.toPlainText())
            return not self._draft_save_failed
        try:
            if not self.store.saving_enabled():
                self._draft_save_failed = False
                return True
            self.store.save_draft(self._draft_key, self._draft_model, self.input.toPlainText())
            self._draft_save_failed = False
            return True
        except HistoryError as error:
            self._draft_save_failed = True
            self.status.setText(str(error))
            return False

    def _draft_text(self, identifier, model):
        return (
            self.store.get_draft(identifier or "new:" + model)
            if self.store and self.store.saving_enabled()
            else ""
        )

    def _set_draft_context(self, identifier, text=None):
        self.draft_timer.stop()
        model = self.model.currentData()
        try:
            text = self._draft_text(identifier, model) if text is None else text
        except HistoryError as error:
            self.status.setText(str(error))
            return False
        self._draft_model = model
        self._draft_key = identifier or "new:" + model
        self._draft_suspended = True
        try:
            self.input.setPlainText(text)
        finally:
            self._draft_suspended = False
        return True

    def _logo_pixmap(self, size):
        # Render at device resolution so the source remains sharp on Retina displays.
        ratio = self.devicePixelRatioF()
        key = (size, ratio)
        if key in self._logo_cache:
            return self._logo_cache[key]
        pixmap = self._logo.scaled(
            round(size * ratio),
            round(size * ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap.setDevicePixelRatio(ratio)
        self._logo_cache[key] = pixmap
        return pixmap

    def read_answer(self):
        if self.answer and not self.client.active:
            dialog = AnswerReader(self.answer, self)
            dialog.exec()
            dialog.deleteLater()

    def _refresh_sidebar(self):
        try:
            self.sidebar.refresh(self.store.list() if self.store else [], self.conversation_id)
            self.picture_button.setEnabled(
                bool(
                    not self.client.active
                    and self.store
                    and self.conversation_id
                    and self.store.pictures(self.conversation_id)
                )
            )
        except HistoryError as error:
            self.status.setText(str(error))

    def _activate_archive(self, identifier):
        if identifier != self.conversation_id:
            self.load_conversation(identifier)
        self._refresh_sidebar()

    def toggle_sidebar(self):
        if self.client.active or self.dictation.state != "idle":
            return
        if self.width() < 900:
            self.open_history()
        else:
            self._sidebar_requested = not self._sidebar_requested
            self.sidebar.setVisible(self._sidebar_requested)
            self.compact_new.setVisible(not self._sidebar_requested)
            self.history_button.setText("收合對話列" if self._sidebar_requested else "顯示對話列")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "appearance_button"):
            self._update_appearance_button()
        if hasattr(self, "welcome_mark"):
            if hasattr(self, "sidebar"):
                show_sidebar = self.width() >= 900 and self._sidebar_requested
                self.sidebar.setVisible(show_sidebar)
                self.compact_new.setVisible(not show_sidebar)
                self.history_button.setText(
                    ("收合對話列" if show_sidebar else "顯示對話列")
                    if self.width() >= 900
                    else "對話紀錄"
                )
            self.model_note.setVisible(self.width() >= (1180 if self.sidebar.isVisible() else 940))
            small = self.width() < 880
            self.header_logo.setFixedSize(48 if small else 56, 48 if small else 56)
            if not self._logo.isNull():
                self.header_logo.setPixmap(self._logo_pixmap(40 if small else 46))
            self.brand_title.setProperty("compact", self.width() < 880)
            self.brand_title.style().unpolish(self.brand_title)
            self.brand_title.style().polish(self.brand_title)
            compact = self.height() < 900
            self.welcome_mark.setVisible(not compact)
            self.welcome_description.setVisible(self.height() >= 760)
            self.welcome_layout.setContentsMargins(
                36, 12 if compact else 32, 36, 12 if compact else 32
            )
            self.keyboard_hint.setVisible(self.workspace_panel.width() >= 760 and not self.image)

    @property
    def reply(self):
        """Compatibility for callers that inspect whether generation is active."""
        return self.client._reply

    def _sync_settings_menu(self):
        recording = self.dictation.state != "idle"
        self.service_dialog.models.setEnabled(not recording and not self.client.active)
        self.voice_settings_action.setEnabled(not recording)
        self.microphone_settings_action.setEnabled(not recording and not self.client.active)
        self.model_settings_action.setEnabled(not recording and not self.client.active)
        self.data_settings_action.setEnabled(
            not recording and not self.client.active and self.store is not None
        )

    def _sync_answer_menu(self):
        idle = not self.client.active and self.dictation.state == "idle"
        self.read_button.setEnabled(idle and bool(self.answer))
        pictures = []
        picture_note = (
            "尚無已保存圖片；可至「設定 → 對話與保存設定」啟用圖片保存，僅保存之後的圖片問答。"
        )
        if self.store and self.conversation_id:
            try:
                pictures = self.store.pictures(self.conversation_id)
            except HistoryError as error:
                picture_note = str(error)
        self.picture_button.setEnabled(idle and bool(pictures))
        model = find_model(self.model.currentData())
        vision = model is None or model.vision
        self.reuse_button.setEnabled(idle and vision and bool(self.last_image))
        for action, button in self.answer_menu_items:
            if button is self.picture_button:
                action.setText(
                    f"圖片紀錄（{len(pictures)} 張）" if pictures else "圖片紀錄（尚無已存圖片）"
                )
                action.setToolTip("開啟此對話已保存的圖片及標註。" if pictures else picture_note)
            elif button is self.reuse_button:
                reason = (
                    "尚無可用圖片"
                    if not self.last_image
                    else ("需選圖文模型" if not vision else "重新附加圖片")
                )
                action.setText(f"附圖再問（{reason}）")
                action.setToolTip("重新附到輸入區，輸入問題後再傳送；不會自動發問或開啟新視窗。")
            else:
                action.setText("閱讀／複製回答" if self.answer else "閱讀／複製回答（尚無回答）")
            if not idle:
                action.setToolTip("請先完成或停止目前的生成／錄音操作。")
            action.setEnabled(button.isEnabled())

    def _update_appearance_button(self):
        target = "淺色" if current_theme() == "dark" else "深色"
        self.appearance_button.setText(target + "外觀" if self.width() >= 880 else target)
        self.appearance_button.setToolTip("切換為" + target + "外觀（自動保存偏好）")
        self.appearance_button.setAccessibleName("切換為" + target + "外觀")
        if hasattr(self, "theme_action"):
            self.theme_action.setText("切換為" + target + "外觀")

    def toggle_appearance(self):
        apply_theme(self, "light" if current_theme() == "dark" else "dark")
        self._update_appearance_button()
        self._save_preferences()

    def open_model_settings(self):
        if self.client.active or self.dictation.state != "idle" or self._closing:
            return
        index = self.model_settings.models.findData(self.model.currentData())
        self.model_settings.models.setCurrentIndex(index)
        self.model_settings.set_installed(self.installed_models)
        self.model_settings.show()
        self.model_settings.raise_()
        self.model_settings.activateWindow()

    def show_service_status(self):
        if self._closing:
            return
        self.service_dialog.show()
        self.service_dialog.raise_()
        self.service_dialog.activateWindow()
        self.check_service()

    def check_service(self):
        if self._closing:
            return
        self.check_button.setEnabled(False)
        self.service_dialog.checking(self.probe.base_url)
        if not self.client.active and self.dictation.state == "idle":
            self.status.setText("正在檢查本機服務與已安裝模型…")
        self.probe.refresh()

    def _on_service_checked(self, models, error):
        if self._closing:
            return
        self.installed_models = models
        self.service_dialog.show_result(
            models,
            error,
            next(model.label for model in MODELS if model.identifier == self.model.currentData()),
            models is not None and self.model.currentData() in models,
            self.probe.base_url,
        )
        self.model_settings.set_installed(models)
        # Keep labels honest without emitting mode-switch signals or clearing a conversation.
        with QSignalBlocker(self.model):
            for index, model in enumerate(MODELS):
                state = (
                    "狀態未確認"
                    if models is None
                    else ("已安裝" if model.identifier in models else "未下載")
                )
                self.model.setItemText(index, f"{model.label} · {state}")
        self.check_button.setEnabled(True)
        self.badge.setText("●  本機服務已連線" if models is not None else "○  服務未連線")
        self.badge.setProperty("offline", models is None)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.update_model_note()
        if (
            not self.client.active
            and self.dictation.state == "idle"
            and not self.archive_failed
            and not self._draft_save_failed
        ):
            if self.store is None:
                self.status.setText("文字紀錄未儲存 · 請先複製畫面內容；檢查儲存位置與權限。")
            elif error:
                self.status.setText(error + " 啟動後可到「設定 → 檢查本機服務」重試。")
            elif self.model.currentData() not in models:
                self.status.setText("所選模式尚未安裝 · 請先下載對應模型，或選擇已安裝的模式。")
            else:
                self.status.setText(
                    "本機服務與所選模型已就緒 · "
                    + (
                        "可輸入問題或附加圖片。"
                        if find_model(self.model.currentData()).vision
                        else "可輸入文字問題；圖片請切換圖文模型。"
                    )
                )

    def update_model_note(self):
        note = next(model.note for model in MODELS if model.identifier == self.model.currentData())
        self.model_note.setText(note)
        self.model.setToolTip(
            note + " · 下載與指令請開啟「設定 → 模型下載與說明」。切換後建立新對話。"
        )
        if hasattr(self, "input"):
            configuration = find_model(self.model.currentData())
            self.input.setPlaceholderText(
                "輸入問題，或按「附加圖片」開始分析…"
                if configuration.vision
                else "目前為純文字模型；輸入問題，圖片分析請切換圖文模型。"
            )

    def _model_changed(self):
        target = self.model.currentIndex()
        previous = self.model.findData(self._draft_model)
        with QSignalBlocker(self.model):
            self.model.setCurrentIndex(previous)
        if not self._prepare_leave("切換模型"):
            return
        with QSignalBlocker(self.model):
            self.model.setCurrentIndex(target)
        if not self.reset():
            with QSignalBlocker(self.model):
                self.model.setCurrentIndex(previous)
            self.update_model_note()
            return
        self.update_model_note()
        self._save_preferences()
        self.status.setText("模式已切換 · 已建立新對話，請確認該模式的模型已安裝。")

    def _dictation_active(self, active):
        self.service_dialog.models.setEnabled(not active and not self.client.active)
        self.attach.setVisible(not active)
        self.speech_panel.setVisible(not active)
        self.send.setVisible(not active and not self.client.active)
        self.attachment_bar.setEnabled(not active)
        widgets = (
            self.clear,
            self.compact_new,
            self.model,
            self.sidebar,
            self.history_button,
            self.speech_panel,
            self.model_settings_button,
            self.settings_button,
        )
        if active:
            if not hasattr(self, "_dictation_controls"):
                self._dictation_controls = [(widget, widget.isEnabled()) for widget in widgets]
            for widget in widgets:
                widget.setEnabled(False)
        elif hasattr(self, "_dictation_controls"):
            for widget, enabled in self._dictation_controls:
                widget.setEnabled(enabled)
            del self._dictation_controls
        self._update_send()

    def _dictated_text(self, text):
        available = MAX_PROMPT_CHARS - len(self.input.toPlainText()) - 1
        if len(text) > available:
            self.dictation._status("辨識文字超過輸入上限，請縮短原有文字後重試。")
            return
        cursor = self.input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(("\n" if self.input.toPlainText() else "") + text)
        self.input.setTextCursor(cursor)
        self.input.setFocus()

    def _update_send(self):
        configuration = find_model(self.model.currentData())
        vision = configuration is None or configuration.vision
        idle = not self.client.active and (
            not hasattr(self, "dictation") or self.dictation.state == "idle"
        )
        if hasattr(self, "attach"):
            self.attach.setEnabled(idle and vision)
            self.attach.setToolTip(
                "支援 PNG、JPEG、WebP，每次一張；圖片僅用於當次提問。"
                if vision
                else "目前模型僅支援文字；請切換圖文模型後再附加圖片。"
            )
        if hasattr(self, "reuse_button"):
            self.reuse_button.setEnabled(idle and vision and bool(self.last_image))
        if hasattr(self, "attachment_bar"):
            self.attachment_bar.setVisible(bool(self.image or self.last_image))
        if hasattr(self, "send"):
            self.send.setEnabled(
                not self.client.active
                and (not hasattr(self, "dictation") or self.dictation.state == "idle")
                and bool(self.input.toPlainText().strip() or self.image)
                and not (self.image and not vision)
            )

    def use_suggestion(self, text):
        if self.client.active:
            return
        if (
            text.startswith("請分析我附加的圖片")
            and not find_model(self.model.currentData()).vision
        ):
            self.status.setText("影像示範需要圖文模型；請先切換模型，現有輸入已保留。")
            return
        self.input.setPlainText(text)
        if text.startswith("請分析我附加的圖片") and not self.image:
            self.status.setText("影像示範：請先附加一張圖片，再按「傳送」。")
        else:
            self.status.setText("示範已填入 · 可直接傳送，也可編輯成自己的問題。")
        self.input.setFocus()
        self.input.moveCursor(QTextCursor.MoveOperation.End)

    def append(self, text, *, color=None, bold=False):
        if not text:
            return
        self.pages.setCurrentIndex(1)
        scroll = self.chat.verticalScrollBar()
        follow = not self._bulk_rendering and scroll.value() >= scroll.maximum() - 24
        previous = scroll.value() if not self._bulk_rendering else 0
        cursor = QTextCursor(self.chat.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        body_format = QTextCharFormat()
        body_format.setForeground(QColor(color or theme_color("#182b36")))
        body_format.setFontWeight(700 if bold else 400)
        cursor.insertText(text, body_format)
        if not self._bulk_rendering:
            scroll.setValue(scroll.maximum() if follow else previous)

    def _insert_clock(self, cursor, timestamp, *, user=False):
        label = clock_label(timestamp)
        if not label:
            return
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme_color("#2b4098" if user else "#647781")))
        fmt.setFontPointSize(10)
        fmt.setFontWeight(400)
        cursor.clearSelection()
        cursor.insertText("  ·  " + label, fmt)

    def _begin_turn(self, prompt, image_note="", asked_at=None, answered_at=None):
        if not self.chat.document().isEmpty():
            self.append("\n\n")
        cursor = QTextCursor(self.chat.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        box = QTextFrameFormat()
        box.setBackground(QColor(theme_color("#edf3ff")))
        box.setBorder(0)
        box.setPadding(12)
        box.setTopMargin(8)
        box.setBottomMargin(16)
        box.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        frame = cursor.insertFrame(box)
        cursor = frame.firstCursorPosition()
        style = QTextCharFormat()
        style.setForeground(QColor(theme_color("#2b4098")))
        style.setFontWeight(700)
        cursor.insertText(f"你{image_note}", style)
        self._insert_clock(cursor, asked_at, user=True)
        cursor.insertText("\n", style)
        style.setFontWeight(400)
        cursor.insertText(prompt, style)

        self.append("AI 助理", bold=True)
        self._ai_stamp_cursor = QTextCursor(self.chat.document())
        self._ai_stamp_cursor.movePosition(QTextCursor.MoveOperation.End)
        self._ai_stamp_cursor.setKeepPositionOnInsert(True)
        self._insert_clock(QTextCursor(self._ai_stamp_cursor), answered_at)
        self.append("\n")

    def _render_answer(self, text, start=None):
        """Format assistant text only; Markdown cannot fetch resources or parse HTML."""
        scroll = self.chat.verticalScrollBar()
        follow = not self._bulk_rendering and scroll.value() >= scroll.maximum() - 24
        previous = scroll.value() if not self._bulk_rendering else 0
        document = LocalDocument()
        document.setDefaultFont(self.chat.font())
        document.setMarkdown(
            text,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        answer_cursor = QTextCursor(document)
        answer_cursor.select(QTextCursor.SelectionType.Document)
        answer_format = QTextCharFormat()
        answer_format.setForeground(QColor(theme_color("#182b36")))
        answer_cursor.mergeCharFormat(answer_format)
        block = document.begin()
        while block.isValid():
            marker = block.charFormat()
            marker.setForeground(QColor(theme_color("#182b36")))
            QTextCursor(block).setBlockCharFormat(marker)
            block = block.next()
        if start is not None and (
            start.isNull()
            or start.document() != self.chat.document()
            or not 0 <= start.position() < self.chat.document().characterCount()
        ):
            logger.warning("Skipped answer formatting with a stale document cursor")
            return
        cursor = QTextCursor(start) if start is not None else QTextCursor(self.chat.document())
        # The streaming anchor stays fixed, but the edit cursor must advance
        # past inserted Markdown before creating the following paragraph.
        cursor.setKeepPositionOnInsert(False)
        if start is not None:
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertFragment(QTextDocumentFragment(document))
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.setCharFormat(QTextCharFormat())
        if not self._bulk_rendering:
            scroll.setValue(scroll.maximum() if follow else previous)

    def _render_history(self, turns):
        """Keep the same transcript limits, but perform layout only once per load."""
        document = self.chat.document()
        updates = self.chat.updatesEnabled()
        self._bulk_rendering = True
        self.chat.setUpdatesEnabled(False)
        document.setLayoutEnabled(False)
        try:
            for turn in turns:
                self._trim_transcript()
                image_note = " · 圖片提問（附件另行管理）" if turn["has_image"] else ""
                self._begin_turn(
                    turn["prompt"], image_note, turn.get("asked_at"), turn.get("answered_at")
                )
                self._render_answer(turn["answer"])
                self.append("\n")
                self.history = retain_turn(self.history, turn["prompt"], turn["answer"])
        finally:
            self._bulk_rendering = False
            document.setLayoutEnabled(True)
            self.chat.setUpdatesEnabled(updates)
            scroll = self.chat.verticalScrollBar()
            scroll.setValue(scroll.maximum())

    def _on_chunk(self, text):
        if not self._closing:
            if not self._received_output:
                self._received_output = True
                self.status.setText("正在產生回覆 · 可隨時按「停止生成」中止。")
                self.assistant_activity.mark_receiving()
            self.speech_panel.feed_generation(text)
            self._queued_text.append(text)
            if not self.render_timer.isActive():
                self.render_timer.start()

    def _flush_text(self):
        if self._queued_text:
            self.append("".join(self._queued_text))
            self._queued_text.clear()
        else:
            self.render_timer.stop()

    def _clear_transcript(self):
        # Document cursors must not outlive the conversation they refer to.
        self.assistant_activity.stop()
        self.render_timer.stop()
        self._queued_text.clear()
        self._answer_start = None
        self._ai_stamp_cursor = None
        self.chat.clear()

    def reset(self):
        if self.client.active or self.dictation.state != "idle" or self._closing:
            return False
        if not self._save_draft():
            return False
        try:
            draft_text = self._draft_text(None, self.model.currentData())
        except HistoryError as error:
            self.status.setText(str(error))
            return False
        self.assistant_activity.stop()
        self.speech_panel.reset()
        self.conversation_id = None
        self.archive_failed = False
        self.last_image = None
        self.last_image_filename = ""
        self._annotation_sequence = None
        self.reuse_button.setEnabled(False)
        self.annotation_boxes.clear()
        self.history.clear()
        self.answer = ""
        self._set_copy_answer("")
        self.read_button.setEnabled(False)
        self._clear_transcript()
        self.remove_image()
        self.pages.setCurrentIndex(0)
        self._set_draft_context(None, draft_text)
        self._refresh_sidebar()
        self.status.setText("已建立新對話 · 可選擇示範或輸入新的問題。")
        self.input.setFocus()
        return True

    def request_new_conversation(self):
        if self._prepare_leave("建立新對話"):
            self.reset()

    def open_history(self):
        if self.client.active or self._closing or self.store is None:
            return
        dialog = ConversationDialog(self.store, self)
        dialog.deleted.connect(self._history_deleted)
        dialog.saving_changed.connect(self._saving_changed)
        dialog.cleared.connect(self._history_cleared)
        if dialog.exec() and dialog.selected_id:
            self.load_conversation(dialog.selected_id)
        self._refresh_sidebar()
        dialog.deleteLater()

    def _saving_changed(self, enabled):
        self.draft_timer.stop()
        self.conversation_id = None
        self.archive_failed = False
        self.history.clear()
        self._clear_transcript()
        self.answer = ""
        self._set_copy_answer("")
        self.speech_panel.reset()
        self.read_button.setEnabled(False)
        self._annotation_sequence = None
        self.last_image = None
        self.last_image_filename = ""
        self.annotation_boxes.clear()
        self.remove_image()
        self.reuse_button.setEnabled(False)
        self.pages.setCurrentIndex(0)
        self._draft_key = "new:" + self.model.currentData()
        self._draft_model = self.model.currentData()
        self.status.setText(
            "已建立新對話 · "
            + ("自動保存已啟用。" if enabled else "自動保存已停用，既有紀錄仍保留。")
        )
        self._refresh_sidebar()

    def _history_cleared(self):
        self.draft_timer.stop()
        with QSignalBlocker(self.input):
            self.input.clear()
        self._saving_changed(self.store.saving_enabled())
        self.last_image = None
        self.last_image_filename = ""
        self.reuse_button.setEnabled(False)
        self.annotation_boxes.clear()
        self.remove_image()

    def _history_deleted(self, identifier):
        if identifier == self.conversation_id:
            # Remove deleted text from both display and future model context; keep the draft.
            self.conversation_id = None
            self.archive_failed = False
            self.history.clear()
            self._clear_transcript()
            self.answer = ""
            self._set_copy_answer("")
            self.read_button.setEnabled(False)
            self.picture_button.setEnabled(False)
            self.last_image = None
            self.last_image_filename = ""
            self._annotation_sequence = None
            self.annotation_boxes.clear()
            self.reuse_button.setEnabled(False)
            self.remove_image()
            self.speech_panel.reset()
            self.pages.setCurrentIndex(0)
            self.status.setText("對話已刪除 · 可輸入問題開始新對話。")
            self._draft_key = "new:" + self.model.currentData()
            self._draft_model = self.model.currentData()

    def load_conversation(self, identifier):
        if (
            self.client.active
            or self._closing
            or self.store is None
            or self.dictation.state != "idle"
        ):
            return False
        if not self._prepare_leave("切換對話", include_text=True):
            return False
        try:
            record = self.store.load(identifier)
            index = self.model.findData(record["model"])
            if index < 0:
                raise HistoryError("這組對話的模型已不在選單，請先恢復對應設定。")
            draft_text = self._draft_text(identifier, record["model"])
            pictures = self.store.pictures(identifier)
        except HistoryError as error:
            QMessageBox.warning(self, "對話紀錄", str(error))
            return False
        if not self.reset():
            return False
        self.input.clear()
        with QSignalBlocker(self.model):
            self.model.setCurrentIndex(index)
        self.update_model_note()
        self._save_preferences()
        self.conversation_id = identifier
        self._set_draft_context(identifier, draft_text)
        self._annotation_sequence = None
        if pictures:
            self._load_saved_picture(pictures[-1]["sequence"])
        self._render_history(record["turns"])
        self.answer = record["turns"][-1]["answer"] if record["turns"] else ""
        self._set_copy_answer(self.answer)
        self.speech_panel.answer = self.answer
        self.speech_panel._update_controls()
        self.read_button.setEnabled(bool(self.answer))
        self.status.setText(
            "已開啟歷史對話 · 可繼續追問；觀察圖片請重新附加，並確認模型已安裝。"
            if record["turns"]
            else "此對話尚無問答 · 可輸入問題開始。"
        )
        self._refresh_sidebar()
        return True

    def _save_completed(self, pending, answer):
        if self.store is None or self.archive_failed:
            self.status.setText(self.status.text() + " · 文字紀錄未儲存，請先複製保留。")
            return
        try:
            if not self.store.saving_enabled():
                self.status.setText(self.status.text() + " · 自動保存已停用。")
                return
            self.conversation_id = self.store.append(
                self.conversation_id,
                self.model.currentData(),
                pending["content"],
                answer,
                pending["has_image"],
                image=pending.get("saved_image"),
                boxes=pending.get("saved_boxes"),
                asked_at=pending.get("asked_at"),
                answered_at=pending.get("answered_at"),
            )
            if pending.get("saved_image"):
                self._annotation_sequence = self.store.last_sequence
            self.store.save_draft(self._draft_key, self._draft_model, "")
            self._draft_key = self.conversation_id
            self._draft_model = self.model.currentData()
            self._refresh_sidebar()
        except HistoryError as error:
            self.archive_failed = True
            self.input.setPlainText(pending["content"])
            self.status.setText(str(error) + " 請先複製畫面內容；建立新對話後可重試儲存。")

    def remove_image(self):
        self.image = None
        self.image_filename = ""
        self.image_label.clear()
        self.image_label.setToolTip("")
        self.remove.hide()
        self.keyboard_hint.setVisible(self.width() >= 850)
        self._update_send()
        self.annotate_button.setVisible(bool(self.last_image))

    def open_annotation(self):
        encoded = self.image or self.last_image
        if not encoded or self.client.active:
            return
        self.speech_panel.stop_reading()
        if self.annotation_dialog is not None:
            self.annotation_dialog.raise_()
            return
        try:
            dialog = AnnotationDialog(encoded, self.model.currentData(), self)
        except ValueError as error:
            QMessageBox.warning(self, "圖片無法使用", str(error))
            return
        self.annotation_dialog = dialog
        dialog.canvas.boxes = list(self.annotation_boxes)
        dialog._refresh()
        dialog.finished.connect(self._annotation_closed)
        dialog.show()

    def _load_saved_picture(self, sequence):
        try:
            self.last_image, self.annotation_boxes = self.store.load_picture(
                self.conversation_id, sequence
            )
            self.last_image_filename = ""
            self._annotation_sequence = sequence
            self.annotate_button.show()
            self._update_send()
            return True
        except HistoryError as error:
            self.status.setText(str(error))
            return False

    def open_saved_picture(self):
        if self.client.active or self.dictation.state != "idle":
            self.status.setText("請先完成或停止生成／錄音，再開啟圖片紀錄。")
            return
        if self.store is None or not self.conversation_id:
            self.status.setText("目前沒有可讀取的圖片紀錄；請先保存一段附圖問答。")
            return
        try:
            pictures = self.store.pictures(self.conversation_id)
            labels = [
                f"第{index + 1}張 · {clean_label(item['prompt'])}"
                for index, item in enumerate(pictures)
            ]
            if not labels:
                self.status.setText(
                    "此對話尚無已保存圖片。可至「設定 → 對話與保存設定」啟用圖片保存，僅影響後續附圖問答。"
                )
                return
            label, accepted = QInputDialog.getItem(
                self, "已存圖片", "選擇圖片以檢視／編輯標註：", labels, 0, False
            )
            if accepted:
                if self.image or self.annotation_boxes:
                    if (
                        QMessageBox.question(
                            self,
                            "切換圖片",
                            "切換將移除目前附件與記憶體標註。未保存標註請先匯出，是否繼續？",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        != QMessageBox.StandardButton.Yes
                    ):
                        return
                if self._load_saved_picture(pictures[labels.index(label)]["sequence"]):
                    self.remove_image()
                    self.open_annotation()
        except HistoryError as error:
            self.status.setText(str(error))

    def reuse_picture(self):
        if self.client.active or self.dictation.state != "idle":
            self.status.setText("請先完成或停止生成／錄音，再重新附圖。")
            return
        if not self.last_image:
            self.status.setText("沒有可重新附加的圖片，請先按「附加圖片」選圖。")
            return
        if not find_model(self.model.currentData()).vision:
            self.status.setText("目前模型僅支援文字，請切換圖文模型後再附圖。")
            return
        self.image = self.last_image
        self.image_filename = self.last_image_filename
        self.image_label.setText("已重新附圖")
        self.image_label.setToolTip("圖片已附加到下一次提問，請輸入問題後按傳送；不會自動重送。")
        self.keyboard_hint.hide()
        self.remove.show()
        self.annotate_button.show()
        self._update_send()
        self.input.setFocus()
        self.status.setText("圖片已重新附加 · 請在輸入框填寫新問題，再按傳送；尚未發送。")

    def _annotation_closed(self):
        dialog, self.annotation_dialog = self.annotation_dialog, None
        if dialog is not None:
            self.annotation_boxes = list(dialog.canvas.boxes)
            if self._annotation_sequence is not None and self.store and self.conversation_id:
                try:
                    if self.store.saving_enabled() and self.store.pictures_enabled():
                        self.store.save_boxes(
                            self.conversation_id, self._annotation_sequence, self.annotation_boxes
                        )
                    else:
                        self.status.setText("本次標註僅保留於記憶體；保存功能已關閉，請匯出保留。")
                except HistoryError as error:
                    self.status.setText(str(error))
            dialog.deleteLater()

    def choose_image(self):
        if not find_model(self.model.currentData()).vision:
            self.status.setText("目前模型僅支援文字，請切換圖文模型後再附圖。")
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "選擇圖片", "", "圖片 (*.png *.jpg *.jpeg *.webp)"
        )
        if not name:
            return
        try:
            encoded = prepare_image(name)
        except ValueError as error:
            QMessageBox.warning(self, "圖片無法使用", str(error))
            return
        self.image = encoded
        self._annotation_sequence = None
        self.reuse_button.setEnabled(True)
        self.last_image = encoded
        self.annotation_boxes.clear()
        self.annotate_button.show()
        filename = Path(name).name
        self.image_filename = self.last_image_filename = filename
        self.image_label.setText(
            self.image_label.fontMetrics().elidedText(filename, Qt.TextElideMode.ElideMiddle, 115)
        )
        self.image_label.setToolTip(html.escape(filename))
        self.remove.show()
        self.keyboard_hint.hide()
        self._update_send()
        self.status.setText("圖片已附加 · 可補充問題，或直接傳送取得影像描述。")

    def busy(self, value):
        self.service_dialog.models.setEnabled(not value and self.dictation.state == "idle")
        self.model_settings_button.setEnabled(not value)
        self.dictation.setEnabled(not value)
        self.spinner.set_running(value)
        if not value:
            self.assistant_activity.stop()
        self.annotate_button.setEnabled(not value)
        self.history_button.setEnabled(not value and self.store is not None)
        self.sidebar.setEnabled(not value and self.store is not None)
        self.copy_button.setEnabled(not value and bool(self._copy_answer))
        self.read_button.setEnabled(not value and bool(self.answer))
        self.picture_button.setEnabled(not value and bool(self.conversation_id))
        self.reuse_button.setEnabled(not value and bool(self.last_image))
        for widget in (
            self.send,
            self.clear,
            self.compact_new,
            self.model,
            self.attach,
            self.remove,
            self.input,
        ):
            widget.setEnabled(not value)
        self.stop.setEnabled(value)
        self.stop.setVisible(value)
        self.send.setVisible(not value)
        self._update_send()

    def submit(self):
        if (
            self._closing
            or self.client.active
            or self.dictation.state != "idle"
            or self.model_settings.downloading
        ):
            return
        prompt = self.input.toPlainText().strip()
        if not (prompt or self.image):
            return
        if self.image and not find_model(self.model.currentData()).vision:
            self.status.setText("所選模型不支援圖片；附件與輸入已保留，請切換圖文模型。")
            return
        if (
            self.installed_models is not None
            and self.model.currentData() not in self.installed_models
        ):
            self.status.setText("所選模型尚未下載，請至「模型設定」下載後再傳送。")
            self.open_model_settings()
            return
        if len(prompt) > MAX_PROMPT_CHARS:
            QMessageBox.warning(self, "內容過長", f"單次問題請控制在 {MAX_PROMPT_CHARS} 字以內。")
            return
        if prompt.startswith("請分析我附加的圖片") and not self.image:
            self.status.setText("請先按「附加圖片」選擇圖片，再傳送影像示範。")
            self.attach.setFocus()
            return
        prompt = prompt or "請以繁體中文描述這張圖片。"
        self._save_draft()
        self.speech_panel.begin_generation()
        self.pending = {"content": prompt, "has_image": bool(self.image), "asked_at": time.time()}
        if self.image and self.store:
            try:
                if self.store.saving_enabled() and self.store.pictures_enabled():
                    self.pending["saved_image"] = self.image
                    self.pending["saved_boxes"] = list(self.annotation_boxes)
            except HistoryError as error:
                self.status.setText(str(error))
        self.answer = ""
        self._received_output = False
        self.failed = False
        self._queued_text.clear()
        messages = build_messages(self.history, prompt, self.image, model=self.model.currentData())
        self._trim_transcript()
        self.pages.setCurrentIndex(1)
        image_note = ""
        if self.image:
            image_note = " · 已附加圖片"
            if self.image_filename:
                image_note += f"（{self.image_filename}）"
        self._begin_turn(prompt, image_note, self.pending["asked_at"])
        cursor = QTextCursor(self.chat.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat.setTextCursor(cursor)
        self._answer_start = QTextCursor(cursor)
        self._answer_start.setKeepPositionOnInsert(True)
        self.busy(True)
        heading_cursor = QTextCursor(cursor)
        heading_cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock)
        heading_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.assistant_activity.start(heading_cursor)
        self.status.setText("正在準備回覆… 首次使用或切換模式時，載入時間可能較長。")
        self.client.start(self.model.currentData(), messages)
        self._update_send()

    def _trim_transcript(self):
        document = self.chat.document()
        if document.characterCount() > MAX_TRANSCRIPT_CHARS:
            cursor = QTextCursor(document)
            cursor.setPosition(0)
            cursor.setPosition(
                document.characterCount() - MAX_TRANSCRIPT_CHARS // 2,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()

    def cancel(self):
        self.speech_panel.stop_reading()
        self.client.cancel()

    def _on_completed(self, result: ChatResult):
        self.render_timer.stop()
        if self._closing:
            return
        self._flush_text()
        self.assistant_activity.stop()
        if result.status == "success":
            self._set_copy_answer(result.answer)
        if result.status == "success" and self.pending:
            self.pending["answered_at"] = time.time()
            self._insert_clock(QTextCursor(self._ai_stamp_cursor), self.pending["answered_at"])
        self.answer = result.answer
        start = getattr(self, "_answer_start", None)
        if start is not None:
            self._render_answer(result.answer, start)
            self._answer_start = None
        self.failed = result.status != "success"
        pending = self.pending
        self.pending = None
        if result.status == "success" and pending:
            self.history = retain_turn(self.history, pending["content"], result.answer)
            self.input.clear()
            self.remove_image()
            if result.truncated:
                self.append("\n[回覆已達長度上限，可輸入「請繼續」取得後續內容。]")
                self.status.setText("已達回覆長度上限 · 可繼續追問。")
            else:
                self.status.setText(
                    "回覆完成 · 再次觀察同一張圖片時，請重新附加。"
                    if pending["has_image"]
                    else "回覆完成 · 可繼續追問，或建立新對話切換主題。"
                )
        elif result.status == "cancelled":
            self.append("\n[已停止，這次回覆未加入對話紀錄。]")
            self.status.setText("已停止生成 · 輸入內容已保留，可修改後重新傳送。")
        elif result.status == "timeout":
            self.append("\n[等待逾時，這次回覆未加入對話紀錄。]")
            self.status.setText("等待回覆逾時 · 請確認本機服務正常後重新傳送。")
        else:
            self.append("\n[請求失敗] " + result.error)
            self.status.setText("請求未完成 · 輸入與圖片已保留，可修正後重新傳送。")
        self.append("\n")
        if result.status == "success" and pending:
            self._save_completed(pending, result.answer)
        self.busy(False)
        self.speech_panel.finish_generation(result.answer if result.status == "success" else "")
        self.input.setFocus()

    def shutdown(self):
        if self._closing:
            return
        self._save_draft()
        self._closing = True
        self.spinner.set_running(False)
        self.assistant_activity.stop()
        if self.annotation_dialog is not None:
            self.annotation_dialog.reject()
        self.last_image = None
        self.last_image_filename = ""
        self.reuse_button.setEnabled(False)
        self.annotation_boxes.clear()
        self.render_timer.stop()
        self._queued_text.clear()
        self.model_settings.shutdown()
        self.dictation.shutdown()
        self.speech_panel.shutdown()
        self.service_dialog.spinner.set_running(False)
        self.service_dialog.close()
        self.probe.shutdown()
        self.client.shutdown()
        if self.store is not None:
            self.store.close()
        self.image = None
        self.image_filename = ""
        self.pending = None
        self.history.clear()

    def closeEvent(self, event):
        if not self._closing and not self._save_draft():
            if (
                QMessageBox.question(
                    self,
                    "草稿未保存",
                    "草稿未能保存，關閉可能遺失最後輸入。請先複製保留；仍要關閉嗎？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                event.ignore()
                return
        self.shutdown()
        event.accept()

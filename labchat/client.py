"""One asynchronous chat request at a time, with a single terminal result."""

import json
import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .config import BASE_URL, IDLE_TIMEOUT_MS, MAX_ANSWER_CHARS, TOTAL_TIMEOUT_MS, find_model
from .protocol import ProtocolError, StreamDecoder
from .security import local_base_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    status: str
    answer: str = ""
    error: str = ""
    truncated: bool = False
    http_status: int | None = None


class ChatClient(QObject):
    chunk = Signal(str)
    completed = Signal(object)

    def __init__(
        self,
        parent=None,
        *,
        base_url=BASE_URL,
        idle_timeout_ms=IDLE_TIMEOUT_MS,
        total_timeout_ms=TOTAL_TIMEOUT_MS,
    ):
        super().__init__(parent)
        self.base_url = base_url
        self.closed = False
        self.network = QNetworkAccessManager(self)
        # This application only contacts the local server; ignore system HTTP proxies.
        from PySide6.QtNetwork import QNetworkProxy

        self.network.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.idle_timeout_ms = idle_timeout_ms
        self.total_timeout_ms = total_timeout_ms
        self.idle_timer = QTimer(self)
        self.total_timer = QTimer(self)
        for timer in (self.idle_timer, self.total_timer):
            timer.setSingleShot(True)
        self.idle_timer.timeout.connect(lambda: self.cancel("timeout"))
        self.total_timer.timeout.connect(lambda: self.cancel("timeout"))
        self._reply = None
        self._reset()

    @property
    def base_url(self):
        return self._base_url

    @base_url.setter
    def base_url(self, value):
        self._base_url = local_base_url(value)

    @property
    def active(self) -> bool:
        return self._reply is not None

    def _reset(self):
        self.decoder = StreamDecoder()
        self.parts = []
        self.answer_chars = 0
        self.done = False
        self.truncated = False
        self.reason = ""
        self.error = ""

    def start(
        self, model: str, messages: list[dict], *, format_schema=None, max_tokens=1024
    ) -> None:
        if self.closed:
            raise RuntimeError("The chat client has been shut down")
        if self.active:
            raise RuntimeError("A chat request is already active")
        configuration = find_model(model)
        if (
            configuration is not None
            and not configuration.vision
            and any(message.get("images") for message in messages)
        ):
            raise ValueError("所選模型僅支援文字，不傳送圖片。")
        self._reset()
        request = QNetworkRequest(QUrl(self.base_url + "/api/chat"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,
            "keep_alive": "2m",
            "options": {
                "num_ctx": 4096,
                "num_predict": max(1, min(4096, max_tokens)),
                "temperature": 0.1 if any(message.get("images") for message in messages) else 0.3,
            },
        }
        if format_schema is not None:
            payload["format"] = format_schema
        self._reply = self.network.post(request, json.dumps(payload).encode("utf-8"))
        self._reply.setReadBufferSize(128 * 1024)
        self._reply.readyRead.connect(self._receive)
        self._reply.finished.connect(self._finished)
        self.idle_timer.start(self.idle_timeout_ms)
        self.total_timer.start(self.total_timeout_ms)

    def cancel(self, reason="cancelled") -> None:
        if not self.active or self.reason:
            return
        self.reason = reason
        self._stop_timers()
        self._reply.abort()

    def shutdown(self) -> None:
        """Disconnect before abort: closing a window must never commit a partial turn."""
        self.closed = True
        self._stop_timers()
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.readyRead.disconnect(self._receive)
            reply.finished.disconnect(self._finished)
            reply.abort()
            reply.deleteLater()

    def _stop_timers(self):
        self.idle_timer.stop()
        self.total_timer.stop()

    def _fail(self, message: str):
        self.error = message
        self.cancel("error")

    def _receive(self):
        if self._reply is None or self.reason:
            return
        data = bytes(self._reply.readAll())
        if not data:
            return
        self.idle_timer.start(self.idle_timeout_ms)
        status = self._reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        # HTTP error bodies may be HTML or JSON; do not parse them as chat tokens.
        if status is not None and status != 200:
            return
        self._consume(data)

    def _consume(self, data: bytes, final=False):
        reply = self._reply
        try:
            for event in self.decoder.feed(data, final):
                if self.reason or self._reply is not reply:
                    return
                if self.done:
                    raise ProtocolError("完成訊息後仍收到額外資料。")
                if "error" in event:
                    self._fail("模型服務錯誤：" + event["error"][:300])
                    return
                piece = event.get("message", {}).get("content", "")
                if self.answer_chars + len(piece) > MAX_ANSWER_CHARS:
                    self._fail("回覆超出顯示長度限制，請縮小問題範圍。")
                    return
                if piece:
                    self.parts.append(piece)
                    self.answer_chars += len(piece)
                    self.chunk.emit(piece)
                    if self._reply is not reply or self.reason:
                        return
                self.done = event.get("done", False)
                self.truncated = event.get("done_reason") == "length"
        except ProtocolError as error:
            self._fail(str(error))

    def _finished(self):
        reply = self._reply
        if reply is None:
            return
        http_status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        # _consume can abort a reply; reason is always assigned before aborting.
        if not self.reason:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status is not None and status != 200:
                self.reason = "error"
                self.error = (
                    "所選模式的模型尚未安裝，請先下載對應模型。"
                    if status == 404
                    else f"本機服務回傳 HTTP {status}，請稍後再試。"
                )
            elif reply.error() != QNetworkReply.NetworkError.NoError:
                self.reason = "error"
                self.error = "無法連接或連線中斷，請確認本機 Ollama 服務正常。"
            else:
                data = bytes(reply.readAll())
                self._consume(data, final=True)
        # An abort during final parsing may synchronously re-enter this method.
        if self._reply is not reply:
            return
        self._stop_timers()
        answer = "".join(self.parts)
        status = self.reason or "success"
        error = self.error
        if status == "success" and (not self.done or not answer.strip()):
            status = "error"
            error = "回覆中斷或沒有有效內容，請重新傳送。"
        result = ChatResult(status, answer, error, self.truncated, http_status)
        self._reply = None
        reply.deleteLater()
        logger.info("Chat completed status=%s truncated=%s", status, self.truncated)
        self.completed.emit(result)


class ServiceProbe(QObject):
    """Small, cancellable model-list check; never blocks the UI event loop."""

    updated = Signal(object, str)

    def __init__(
        self, network: QNetworkAccessManager, parent=None, *, base_url=BASE_URL, timeout_ms=10000
    ):
        super().__init__(parent)
        self.network = network
        self.base_url = base_url
        self.closed = False
        self.reply = None
        self.data = bytearray()
        self.too_large = False
        self.timeout_ms = timeout_ms
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)

    @property
    def base_url(self):
        return self._base_url

    @base_url.setter
    def base_url(self, value):
        self._base_url = local_base_url(value)

    def _timeout(self):
        if self.reply is not None:
            self.reply.abort()

    def refresh(self):
        if self.closed or self.reply is not None:
            return
        request = QNetworkRequest(QUrl(self.base_url + "/api/tags"))
        request.setTransferTimeout(5000)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        self.data.clear()
        self.too_large = False
        self.reply = self.network.get(request)
        self.reply.setReadBufferSize(64 * 1024)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finish)
        self.deadline.start(self.timeout_ms)

    def _read(self):
        if self.reply is None or self.too_large or not self.reply.isOpen():
            return
        self.data.extend(bytes(self.reply.readAll()))
        if len(self.data) > 1024 * 1024:
            self.too_large = True
            self.reply.abort()

    def _finish(self):
        self.deadline.stop()
        reply = self.reply
        if reply is None:
            return
        self._read()
        if self.reply is not reply:
            return
        models, error = None, ""
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if (
                self.too_large
                or reply.error() != QNetworkReply.NetworkError.NoError
                or status != 200
            ):
                raise ValueError("無法取得本機服務狀態，請確認 Ollama 已啟動。")
            payload = json.loads(self.data)
            if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
                raise ValueError("本機服務的模型清單格式無效。")
            models = set()
            for item in payload["models"]:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    raise ValueError("本機服務的模型清單格式無效。")
                models.add(item["name"])
        except (ValueError, UnicodeDecodeError, RecursionError) as exception:
            models = None
            error = str(exception)[:160]
        self.reply = None
        reply.deleteLater()
        self.updated.emit(models, error)

    def shutdown(self):
        self.closed = True
        self.deadline.stop()
        if self.reply is not None:
            reply, self.reply = self.reply, None
            reply.readyRead.disconnect(self._read)
            reply.finished.disconnect(self._finish)
            reply.abort()
            reply.deleteLater()

"""Bounded NDJSON parsing, independent of Qt and network packet boundaries."""

import json

from .security import ensure_unicode

MAX_LINE_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 16 * 1024 * 1024


class ProtocolError(ValueError):
    pass


class StreamDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.received = 0

    def feed(self, data: bytes, final: bool = False) -> list[dict]:
        self.received += len(data)
        if self.received > MAX_STREAM_BYTES:
            raise ProtocolError("回應資料超出大小限制。")
        self.buffer.extend(data)
        lines = self.buffer.split(b"\n")
        self.buffer = bytearray(lines.pop())
        if final and self.buffer:
            lines.append(bytes(self.buffer))
            self.buffer.clear()
        if len(self.buffer) > MAX_LINE_BYTES:
            raise ProtocolError("串流單筆資料超出大小限制。")
        events = []
        for line in lines:
            if len(line) > MAX_LINE_BYTES:
                raise ProtocolError("串流單筆資料超出大小限制。")
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError, RecursionError) as error:
                raise ProtocolError("本機服務回傳的資料格式無法解析。") from error
            if not isinstance(event, dict):
                raise ProtocolError("本機服務回傳了無效的資料類型。")
            if "error" in event:
                if not isinstance(event["error"], str):
                    raise ProtocolError("服務錯誤訊息格式無效。")
                try:
                    ensure_unicode(event["error"])
                except ValueError as error:
                    raise ProtocolError(str(error)) from error
            else:
                message = event.get("message", {})
                if not isinstance(message, dict) or not isinstance(message.get("content", ""), str):
                    raise ProtocolError("回覆文字格式無效。")
                try:
                    ensure_unicode(message.get("content", ""))
                except ValueError as error:
                    raise ProtocolError(str(error)) from error
                if "done" in event and not isinstance(event["done"], bool):
                    raise ProtocolError("完成狀態格式無效。")
                if not message and "done" not in event:
                    raise ProtocolError("缺少串流回覆欄位。")
            events.append(event)
        return events

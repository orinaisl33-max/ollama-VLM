"""Validation at process/network/text boundaries; no model output is executable."""

import unicodedata
from urllib.parse import urlsplit


def local_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        valid = (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and (port is None or 1 <= port <= 65535)
        )
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("只允許使用本機 HTTP 服務位址。") from error
    if not valid:
        raise ValueError("只允許使用本機 HTTP 服務位址。")
    return value.rstrip("/")


def ensure_unicode(text: str) -> None:
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("回應含有無效文字編碼。") from error


def clean_label(text: str) -> str:
    # Remove bidi/control/surrogate characters that can spoof or break a displayed label.
    cleaned = "".join(
        char
        for char in unicodedata.normalize("NFC", text)
        if not unicodedata.category(char).startswith("C")
    )
    return " ".join(cleaned.split())[:60]

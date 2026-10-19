"""Strict, bounded conversation interchange. Imported identifiers and paths are never trusted."""

import html
import json
import re
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

from .config import MAX_ANSWER_CHARS, MAX_PROMPT_CHARS, MODELS
from .conversations import MAX_ARCHIVE_CHARS, MAX_TURNS, HistoryError
from .security import clean_label, ensure_unicode
from .timestamps import clock_label, validate_timestamp

FORMAT = "ai-system-lab-conversation"
MAX_IMPORT_BYTES = 16 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _fenced_text(text):
    fence = "`" * max(3, max((len(run) + 1 for run in re.findall(r"`+", text)), default=3))
    return fence + "text\n" + html.escape(text) + "\n" + fence


def validate_document(document):
    try:
        if not isinstance(document, dict) or set(document) != {
            "format",
            "version",
            "title",
            "model",
            "turns",
        }:
            raise ValueError
        if (
            document["format"] != FORMAT
            or type(document["version"]) is not int
            or document["version"] not in (1, 2)
        ):
            raise ValueError
        if document["model"] not in {model.identifier for model in MODELS}:
            raise ValueError
        if not isinstance(document["title"], str) or not 1 <= len(document["title"]) <= 200:
            raise ValueError
        turns = document["turns"]
        if not isinstance(turns, list) or not 1 <= len(turns) <= MAX_TURNS:
            raise ValueError
        normalized = []
        total = 0
        for turn in turns:
            fields = {"prompt", "answer", "has_image"}
            if document["version"] == 2:
                fields |= {"asked_at", "answered_at"}
            if not isinstance(turn, dict) or set(turn) != fields:
                raise ValueError
            if type(turn["has_image"]) is not bool:
                raise ValueError
            for field, limit in (("prompt", MAX_PROMPT_CHARS), ("answer", MAX_ANSWER_CHARS)):
                text = turn[field]
                if (
                    not isinstance(text, str)
                    or not text.strip()
                    or len(text) > limit
                    or "\x00" in text
                ):
                    raise ValueError
                ensure_unicode(text)
                total += len(text)
            normalized.append(
                {
                    **turn,
                    "asked_at": validate_timestamp(turn.get("asked_at")),
                    "answered_at": validate_timestamp(turn.get("answered_at")),
                }
            )
        if total > MAX_ARCHIVE_CHARS:
            raise ValueError
        title = clean_label(document["title"])
        if not title:
            raise ValueError
        return {"title": title, "model": document["model"], "turns": normalized}
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise HistoryError("對話檔格式、版本、模型或容量不符合規定，未匯入任何資料。") from error


def export_document(record):
    document = {
        "format": FORMAT,
        "version": 2,
        "title": record["title"],
        "model": record["model"],
        "turns": [
            {
                "prompt": turn["prompt"],
                "answer": turn["answer"],
                "has_image": bool(turn["has_image"]),
                "asked_at": turn.get("asked_at"),
                "answered_at": turn.get("answered_at"),
            }
            for turn in record["turns"]
        ],
    }
    validate_document(document)
    return document


def read_document(path):
    try:
        with Path(path).open("rb") as source:
            data = source.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise ValueError
        document = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        return validate_document(document)
    except (OSError, ValueError, RecursionError) as error:
        raise HistoryError("無法讀取對話JSON，請確認UTF-8格式、檔案大小及內容。") from error


def write_document(path, record, *, markdown=False):
    document = export_document(record)
    if markdown:
        # Fence untrusted model text so Markdown viewers do not load its image links.
        sections = [
            "# 對話紀錄\n\n" + _fenced_text(document["title"]),
            "模型：" + document["model"],
            "此檔供閱讀，還原請使用JSON。圖片與標註不包含在文字匯出中。",
        ]
        for turn in document["turns"]:
            note = "（當時有附圖，圖片未匯出）" if turn["has_image"] else ""
            asked = clock_label(turn["asked_at"])
            answered = clock_label(turn["answered_at"])
            for role, text in (
                ("你" + note + (" · " + asked if asked else ""), turn["prompt"]),
                ("AI 助理" + (" · " + answered if answered else ""), turn["answer"]),
            ):
                sections.append("## " + role + "\n\n" + _fenced_text(text))
        data = ("\n\n".join(sections) + "\n").encode("utf-8")
    else:
        data = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    target = QSaveFile(str(path))
    target.setDirectWriteFallback(False)
    if not target.open(QIODevice.OpenModeFlag.WriteOnly):
        raise HistoryError("無法建立匯出檔，請檢查路徑與權限。")
    if target.write(data) != len(data) or not target.commit():
        target.cancelWriting()
        raise HistoryError("匯出失敗，既有目標檔不應被部分內容取代。")

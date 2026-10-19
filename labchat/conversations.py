"""Transactional local conversations, drafts, privacy settings and opt-in attachments."""

import base64
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from .config import MAX_ANSWER_CHARS, MAX_PROMPT_CHARS
from .security import clean_label, ensure_unicode
from .timestamps import validate_timestamp

MAX_CONVERSATIONS = 200
MAX_TURNS = 200
MAX_ARCHIVE_CHARS = 2_000_000
MAX_TOTAL_CHARS = 20_000_000
MAX_DRAFT_CHARS = 16_000


class HistoryError(Exception):
    """A recoverable archive error; never expose chat text in diagnostic messages."""


class ConversationStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.connection = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path, timeout=0.25)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA trusted_schema=OFF")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA secure_delete=ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4, 5):
                raise HistoryError("對話資料版本較新，請使用相容版本開啟；原檔未覆寫。")
            tables = {
                row[0]
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables and not {"conversations", "turns"} <= tables:
                raise HistoryError("資料庫結構無法辨識，未進行升級；請先保留原檔。")
            required_columns = {
                "conversations": {"id", "title", "model", "created", "updated"},
                "turns": {"sequence", "conversation_id", "prompt", "answer", "has_image"},
                "drafts": {"key", "model", "content"},
                "settings": {"key", "value"},
                "attachments": {"turn_sequence", "png", "boxes"},
            }
            if version == 5:
                required_columns["turns"] |= {"asked_at", "answered_at"}
            for table, required in required_columns.items():
                if table in tables:
                    # Table names are constant program identifiers, never user input.
                    columns = {
                        row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")
                    }
                    if not required <= columns:
                        raise HistoryError("資料庫欄位不符，未進行升級；原有資料保留。")
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS conversations "
                    "(id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL, "
                    "created REAL NOT NULL, updated REAL NOT NULL)"
                )
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS turns "
                    "(sequence INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL "
                    "REFERENCES conversations(id) ON DELETE CASCADE, "
                    "prompt TEXT NOT NULL, answer TEXT NOT NULL, has_image INTEGER NOT NULL)"
                )
                self.connection.execute(
                    "CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id)"
                )
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS drafts "
                    "(key TEXT PRIMARY KEY, model TEXT NOT NULL, content TEXT NOT NULL)"
                )
                columns = {
                    row[1] for row in self.connection.execute("PRAGMA table_info(conversations)")
                }
                if "pinned" not in columns:
                    self.connection.execute(
                        "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                    )
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)"
                )
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS attachments "
                    "(turn_sequence INTEGER PRIMARY KEY REFERENCES turns(sequence) ON DELETE CASCADE,"
                    "png BLOB NOT NULL,boxes TEXT NOT NULL)"
                )
                turn_columns = {
                    row[1] for row in self.connection.execute("PRAGMA table_info(turns)")
                }
                for name in ("asked_at", "answered_at"):
                    if name not in turn_columns:
                        self.connection.execute(f"ALTER TABLE turns ADD COLUMN {name} REAL")
                self.connection.execute("PRAGMA user_version=5")
            if os.name == "posix":
                self.path.chmod(0o600)
        except (sqlite3.Error, OSError, HistoryError) as error:
            self.close()
            if isinstance(error, HistoryError):
                raise
            raise HistoryError(
                "無法開啟本機對話資料；聊天仍可使用，請檢查儲存位置與權限。"
            ) from error

    def _db(self):
        if self.connection is None:
            raise HistoryError("對話資料已關閉。")
        return self.connection

    def list(self, query=""):
        try:
            return [
                dict(row)
                for row in self._db().execute(
                    "SELECT id,title,model,updated,pinned FROM conversations c WHERE "
                    "?='' OR INSTR(LOWER(title),LOWER(?))>0 OR EXISTS "
                    "(SELECT 1 FROM turns t WHERE t.conversation_id=c.id AND "
                    "(INSTR(LOWER(prompt),LOWER(?))>0 OR INSTR(LOWER(answer),LOWER(?))>0)) "
                    "ORDER BY pinned DESC,updated DESC,id",
                    (query, query, query, query),
                )
            ]
        except sqlite3.Error as error:
            raise HistoryError("無法讀取對話清單，原有資料未變更。") from error

    def append(
        self,
        identifier,
        model,
        prompt,
        answer,
        has_image=False,
        *,
        image=None,
        boxes=None,
        asked_at=None,
        answered_at=None,
    ):
        png = None
        if image is not None:
            from .attachments import image_bytes, validate_boxes

            try:
                png = image_bytes(image)
                boxes = validate_boxes(boxes or [])
            except ValueError as error:
                raise HistoryError(str(error)) from error
        try:
            asked_at = validate_timestamp(asked_at)
            answered_at = validate_timestamp(answered_at)
            ensure_unicode(prompt)
            ensure_unicode(answer)
            ensure_unicode(model)
            if (
                not prompt.strip()
                or not answer.strip()
                or len(prompt) > MAX_PROMPT_CHARS
                or len(answer) > MAX_ANSWER_CHARS
                or "\x00" in prompt
                or "\x00" in answer
                or not isinstance(model, str)
                or not model
                or len(model) > 100
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError) as error:
            raise HistoryError("這次回覆格式不適合儲存，未寫入對話資料。") from error
        db = self._db()
        try:
            with db:
                # Serialize the capacity check and write across multiple app windows.
                db.execute("BEGIN IMMEDIATE")
                if identifier is None:
                    if (
                        db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
                        >= MAX_CONVERSATIONS
                    ):
                        raise HistoryError("對話紀錄已達200組，請先刪除不需要的紀錄。")
                    identifier = uuid.uuid4().hex
                    now = time.time()
                    db.execute(
                        "INSERT INTO conversations(id,title,model,created,updated) VALUES (?,?,?,?,?)",
                        (identifier, clean_label(prompt) or "圖片對話", model, now, now),
                    )
                else:
                    row = db.execute(
                        "SELECT model FROM conversations WHERE id=?", (identifier,)
                    ).fetchone()
                    if row is None or row["model"] != model:
                        raise HistoryError("對話已刪除或模式不符，請建立新對話後再儲存。")
                count, size = db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(LENGTH(prompt)+LENGTH(answer)),0) "
                    "FROM turns WHERE conversation_id=?",
                    (identifier,),
                ).fetchone()
                total = db.execute(
                    "SELECT COALESCE(SUM(LENGTH(prompt)+LENGTH(answer)),0) FROM turns"
                ).fetchone()[0]
                added = len(prompt) + len(answer)
                if count >= MAX_TURNS or size + added > MAX_ARCHIVE_CHARS:
                    raise HistoryError("此對話已達儲存上限，請建立新對話。既有紀錄保留。")
                if total + added > MAX_TOTAL_CHARS:
                    raise HistoryError("本機對話總量已達上限，請先刪除不需要的紀錄。")
                cursor = db.execute(
                    "INSERT INTO turns(conversation_id,prompt,answer,has_image,asked_at,answered_at) VALUES (?,?,?,?,?,?)",
                    (identifier, prompt, answer, int(bool(has_image)), asked_at, answered_at),
                )
                sequence = cursor.lastrowid
                if png is not None:
                    from .attachments import MAX_ATTACHMENT_BYTES

                    total_bytes = db.execute(
                        "SELECT COALESCE(SUM(LENGTH(png)),0) FROM attachments"
                    ).fetchone()[0]
                    if total_bytes + len(png) > MAX_ATTACHMENT_BYTES:
                        raise HistoryError("圖片保存總量已達100MiB上限，請先清理紀錄。這次未寫入。")
                    db.execute(
                        "INSERT INTO attachments VALUES (?,?,?)",
                        (
                            sequence,
                            png,
                            json.dumps([box.to_dict() for box in boxes], ensure_ascii=False),
                        ),
                    )
                db.execute(
                    "UPDATE conversations SET updated=? WHERE id=?", (time.time(), identifier)
                )
            self.last_sequence = sequence
            return identifier
        except sqlite3.Error as error:
            raise HistoryError(
                "對話未能儲存，請檢查磁碟空間或稍後重試。畫面內容仍保留。"
            ) from error

    def load(self, identifier):
        try:
            db = self._db()
            with db:
                db.execute("BEGIN")
                row = db.execute("SELECT * FROM conversations WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    raise HistoryError("這組對話已不存在，請重新整理清單。")
                turns = [
                    dict(item)
                    for item in db.execute(
                        "SELECT prompt,answer,has_image,asked_at,answered_at FROM turns WHERE conversation_id=? ORDER BY sequence",
                        (identifier,),
                    )
                ]
            for turn in turns:
                turn["asked_at"] = validate_timestamp(turn["asked_at"])
                turn["answered_at"] = validate_timestamp(turn["answered_at"])
            return {**dict(row), "turns": turns}
        except (sqlite3.Error, ValueError) as error:
            raise HistoryError("無法讀取這組對話，原有資料未變更。") from error

    def rename(self, identifier, title):
        title = clean_label(title)
        if not title:
            raise HistoryError("請輸入有效的對話名稱。")
        try:
            with self._db() as db:
                if (
                    db.execute(
                        "UPDATE conversations SET title=? WHERE id=?", (title, identifier)
                    ).rowcount
                    != 1
                ):
                    raise HistoryError("這組對話已不存在。")
        except sqlite3.Error as error:
            raise HistoryError("無法修改對話名稱。") from error

    def import_record(self, record):
        # Validation happens again at the persistence boundary, not only in the file dialog.
        from .conversation_io import FORMAT, validate_document

        timed = (
            isinstance(record, dict)
            and isinstance(record.get("turns"), list)
            and any(
                isinstance(turn, dict) and ("asked_at" in turn or "answered_at" in turn)
                for turn in record["turns"]
            )
        )
        record = validate_document({"format": FORMAT, "version": 2 if timed else 1, **record})
        db = self._db()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                count = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
                total = db.execute(
                    "SELECT COALESCE(SUM(LENGTH(prompt)+LENGTH(answer)),0) FROM turns"
                ).fetchone()[0]
                added = sum(len(turn["prompt"]) + len(turn["answer"]) for turn in record["turns"])
                if count >= MAX_CONVERSATIONS or total + added > MAX_TOTAL_CHARS:
                    raise HistoryError("匯入將超過紀錄容量，請先清理；原有資料未變更。")
                identifier = uuid.uuid4().hex
                now = time.time()
                db.execute(
                    "INSERT INTO conversations(id,title,model,created,updated) VALUES (?,?,?,?,?)",
                    (
                        identifier,
                        record["title"],
                        record["model"],
                        now,
                        now,
                    ),
                )
                db.executemany(
                    "INSERT INTO turns(conversation_id,prompt,answer,has_image,asked_at,answered_at) VALUES (?,?,?,?,?,?)",
                    [
                        (
                            identifier,
                            turn["prompt"],
                            turn["answer"],
                            int(turn["has_image"]),
                            turn["asked_at"],
                            turn["answered_at"],
                        )
                        for turn in record["turns"]
                    ],
                )
            return identifier
        except sqlite3.Error as error:
            raise HistoryError("匯入失敗，這次匯入已回滾，原有資料保留。") from error

    def delete(self, identifier):
        try:
            with self._db() as db:
                db.execute("DELETE FROM conversations WHERE id=?", (identifier,))
                db.execute("DELETE FROM drafts WHERE key=?", (identifier,))
        except sqlite3.Error as error:
            raise HistoryError("無法刪除對話，請稍後重試。") from error

    def save_draft(self, key, model, text):
        from .config import MODELS

        try:
            ensure_unicode(text)
            if len(text) > MAX_DRAFT_CHARS or "\x00" in text:
                raise ValueError
            if model not in {item.identifier for item in MODELS}:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as error:
            raise HistoryError("草稿格式不符或超過16000字，請先複製保留。") from error
        try:
            with self._db() as db:
                if key != "new:" + model:
                    row = db.execute(
                        "SELECT model FROM conversations WHERE id=?", (key,)
                    ).fetchone()
                    if row is None or row["model"] != model:
                        raise HistoryError("草稿所屬對話已不存在，請先複製保留。")
                if text:
                    db.execute(
                        "INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(key) DO UPDATE "
                        "SET model=excluded.model,content=excluded.content",
                        (key, model, text),
                    )
                else:
                    db.execute("DELETE FROM drafts WHERE key=?", (key,))
        except sqlite3.Error as error:
            raise HistoryError("草稿未能儲存，請先複製保留，再檢查磁碟與權限。") from error

    def get_draft(self, key):
        try:
            row = self._db().execute("SELECT content FROM drafts WHERE key=?", (key,)).fetchone()
            return row[0] if row else ""
        except sqlite3.Error as error:
            raise HistoryError("無法讀取草稿，原有資料未變更。") from error

    def set_pinned(self, identifier, value):
        try:
            with self._db() as db:
                db.execute(
                    "UPDATE conversations SET pinned=? WHERE id=?", (int(bool(value)), identifier)
                )
        except sqlite3.Error as error:
            raise HistoryError("無法變更釘選狀態。") from error

    def pictures_enabled(self):
        try:
            row = self._db().execute("SELECT value FROM settings WHERE key='pictures'").fetchone()
            return row is not None and row[0] == "on"
        except sqlite3.Error as error:
            raise HistoryError("無法讀取圖片保存設定。") from error

    def set_pictures(self, enabled):
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO settings VALUES ('pictures',?) ON CONFLICT(key) DO UPDATE "
                    "SET value=excluded.value",
                    ("on" if enabled else "off",),
                )
        except sqlite3.Error as error:
            raise HistoryError("無法變更圖片保存設定。") from error

    def pictures(self, identifier):
        try:
            return [
                dict(row)
                for row in self._db().execute(
                    "SELECT t.sequence,t.prompt FROM turns t JOIN attachments a ON a.turn_sequence=t.sequence "
                    "WHERE t.conversation_id=? ORDER BY t.sequence",
                    (identifier,),
                )
            ]
        except sqlite3.Error as error:
            raise HistoryError("無法讀取已存圖片清單。") from error

    def load_picture(self, identifier, sequence):
        from .attachments import MAX_PNG_BYTES, image_bytes, validate_boxes

        try:
            row = (
                self._db()
                .execute(
                    "SELECT a.png,a.boxes FROM attachments a JOIN turns t "
                    "ON t.sequence=a.turn_sequence WHERE t.conversation_id=? AND t.sequence=? "
                    "AND LENGTH(a.png)<=? AND LENGTH(a.boxes)<=65536",
                    (identifier, sequence, MAX_PNG_BYTES),
                )
                .fetchone()
            )
            if row is None:
                raise HistoryError("此圖片已不存在。")
            if not isinstance(row["png"], bytes) or not isinstance(row["boxes"], str):
                raise ValueError("Invalid stored attachment types")
            encoded = base64.b64encode(row["png"]).decode("ascii")
            image_bytes(encoded)
            return encoded, validate_boxes(json.loads(row["boxes"]))
        except (sqlite3.Error, ValueError, TypeError, RecursionError) as error:
            raise HistoryError("已存圖片或標註無法讀取，原檔未變更。") from error

    def save_boxes(self, identifier, sequence, boxes):
        from .attachments import validate_boxes

        try:
            boxes = validate_boxes(boxes)
            with self._db() as db:
                cursor = db.execute(
                    "UPDATE attachments SET boxes=? WHERE turn_sequence=? AND EXISTS "
                    "(SELECT 1 FROM turns WHERE sequence=? AND conversation_id=?)",
                    (
                        json.dumps([box.to_dict() for box in boxes], ensure_ascii=False),
                        sequence,
                        sequence,
                        identifier,
                    ),
                )
                if cursor.rowcount != 1:
                    raise HistoryError("圖片已不存在，請先匯出標註保存。")
        except (sqlite3.Error, ValueError) as error:
            raise HistoryError("標註未能保存，請先匯出PNG或JSON。") from error

    def saving_enabled(self):
        try:
            row = self._db().execute("SELECT value FROM settings WHERE key='saving'").fetchone()
            return row is None or row[0] != "off"
        except sqlite3.Error as error:
            raise HistoryError("無法讀取儲存設定。") from error

    def get_preferences(self):
        from .preferences import validate_preferences

        try:
            row = (
                self._db()
                .execute("SELECT value FROM settings WHERE key='ui_preferences'")
                .fetchone()
            )
            if row is not None and (not isinstance(row[0], str) or len(row[0]) > 4096):
                raise ValueError
            return validate_preferences(json.loads(row[0]) if row else {})
        except (sqlite3.Error, ValueError, TypeError, RecursionError) as error:
            raise HistoryError("無法讀取操作偏好，請檢查設定；原有資料未變更。") from error

    def save_preferences(self, value):
        from .preferences import validate_preferences

        try:
            data = json.dumps(validate_preferences(value), ensure_ascii=False)
            with self._db() as db:
                db.execute(
                    "INSERT INTO settings VALUES ('ui_preferences',?) ON CONFLICT(key) "
                    "DO UPDATE SET value=excluded.value",
                    (data,),
                )
        except (sqlite3.Error, ValueError, TypeError) as error:
            raise HistoryError("操作偏好未能保存；聊天資料未變更。") from error

    def set_saving(self, enabled):
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO settings VALUES ('saving',?) ON CONFLICT(key) DO UPDATE "
                    "SET value=excluded.value",
                    ("on" if enabled else "off",),
                )
        except sqlite3.Error as error:
            raise HistoryError("無法變更儲存設定。") from error

    def clear_all(self):
        try:
            with self._db() as db:
                db.execute("DELETE FROM conversations")
                db.execute("DELETE FROM drafts")
        except sqlite3.Error as error:
            raise HistoryError("無法清除紀錄，這次操作已回滾。") from error

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

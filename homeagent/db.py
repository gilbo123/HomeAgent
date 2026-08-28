"""SQLite persistence for chats and messages.

Design notes:
    * One connection per ``ChatDatabase`` instance, created with
      ``check_same_thread=False`` and guarded by a re-entrant lock, so it
      is safe to share across the ThreadingHTTPServer worker threads.
    * Foreign keys are enforced; deleting a chat cascades to its
      messages.
    * All timestamps are unix epoch seconds.

Only the latest user turn's images are sent to Ollama (see
``build_model_messages``) — older turns are re-sent as plain text so we
don't re-upload every photo on every request.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    model      TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    model       TEXT,
    images      TEXT,            -- JSON list of stored filenames (user rows only)
    response_ms INTEGER,         -- latency of the assistant reply, ms
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
"""


class ChatNotFoundError(LookupError):
    """Raised when an operation targets a chat id that does not exist."""


class ChatDatabase:
    """Thread-safe access to the chats/messages tables."""

    def __init__(self, db_path: str, history_limit: int, upload_dir: str) -> None:
        self._db_path = db_path
        self._history_limit = history_limit
        self._upload_dir = upload_dir
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ chats

    def list_chats(self) -> list[dict[str, Any]]:
        """All chats, newest activity first, with a message count."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS n
                FROM chats c
                ORDER BY c.updated_at DESC, c.created_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_chat(self, chat_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return (chat, messages in id order). Raises ChatNotFoundError."""
        with self._lock:
            chat = self._conn.execute(
                "SELECT * FROM chats WHERE id = ?", (chat_id,)
            ).fetchone()
            if chat is None:
                raise ChatNotFoundError(chat_id)
            msgs = self._conn.execute(
                "SELECT role, content, model, images, response_ms, created_at "
                "FROM messages WHERE chat_id = ? ORDER BY id",
                (chat_id,),
            ).fetchall()
        return dict(chat), [dict(m) for m in msgs]

    def create_chat(self, model: str) -> dict[str, Any]:
        now = int(time.time())
        chat = {
            "id": uuid.uuid4().hex,
            "title": "New chat",
            "model": model,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO chats (id, title, model, created_at, updated_at) "
                "VALUES (:id, :title, :model, :created_at, :updated_at)",
                chat,
            )
        return chat

    def delete_chat(self, chat_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

    # ---------------------------------------------------------------- messages

    def add_user_message(self, chat_id: str, text: str, images: list[str]) -> None:
        """Store a user turn. The first message titles the chat."""
        now = int(time.time())
        with self._lock, self._conn:
            count = self._conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE chat_id = ?", (chat_id,)
            ).fetchone()["c"]
            if count == 0:
                title = re.sub(r"\s+", " ", text).strip()[:60] or "Chat with images"
                self._conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
            self._conn.execute(
                """
                INSERT INTO messages (chat_id, role, content, images, created_at)
                VALUES (?, 'user', ?, ?, ?)
                """,
                (chat_id, text, json.dumps(images), now),
            )
            self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))

    def add_assistant_message(self, chat_id: str, content: str, model: str, response_ms: int) -> None:
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO messages (chat_id, role, content, model, response_ms, created_at)
                VALUES (?, 'assistant', ?, ?, ?, ?)
                """,
                (chat_id, content, model, response_ms, now),
            )
            self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))

    def build_model_messages(self, chat_id: str) -> list[dict[str, Any]]:
        """Build the Ollama ``messages`` array for this chat.

        Only the *last* user message carries an ``images`` list (base64),
        because older photos are already reflected in the assistant's
        earlier replies.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, images FROM messages "
                "WHERE chat_id = ? ORDER BY id",
                (chat_id,),
            ).fetchall()
        tail = rows[-self._history_limit:]

        def last_user_index() -> int:
            for i in range(len(tail) - 1, -1, -1):
                if tail[i]["role"] == "user":
                    return i
            return -1

        last_user = last_user_index()
        messages: list[dict[str, Any]] = []
        for i, row in enumerate(tail):
            if row["role"] not in ("user", "assistant") or not row["content"]:
                continue
            msg: dict[str, Any] = {"role": row["role"], "content": row["content"]}
            if row["role"] == "user" and i == last_user:
                images = self._load_images(row["images"])
                if images:
                    msg["images"] = images
            messages.append(msg)
        return messages

    def _load_images(self, images_json: str | None) -> list[str]:
        """Base64-encode the stored image files referenced by a user row."""
        try:
            names = json.loads(images_json or "[]")
        except ValueError:
            return []
        out: list[str] = []
        for name in names:
            path = os.path.join(self._upload_dir, name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    out.append(base64.b64encode(f.read()).decode("ascii"))
        return out

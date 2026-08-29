"""MongoDB persistence for chats and messages (pymongo).

Design notes:
    * One ``pymongo.MongoClient`` per ``ChatDatabase`` instance. The client
      is thread-safe (it owns a connection pool internally), so it can be
      shared freely across the ThreadingHTTPServer worker threads with no
      lock of our own.
    * Two collections: ``chats`` and ``messages``. ``messages`` stores the
      parent ``chat_id``; deleting a chat also removes its messages.
    * All timestamps are unix epoch seconds (int).
    * Chat ids are 32-char lowercase hex strings (``uuid4().hex``) — stored
      as a string, indexed, and used directly by the HTTP layer.

Only the latest user turn's images are sent to Ollama (see
``build_model_messages``) — older turns are re-sent as plain text so we
don't re-upload every photo on every request.
"""

from __future__ import annotations

import base64
import os
import re
import time
import uuid
from typing import Any

from pymongo import MongoClient
from pymongo.errors import (
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)


class ChatNotFoundError(LookupError):
    """Raised when an operation targets a chat id that does not exist."""


def _doc(d: dict[str, Any]) -> dict[str, Any]:
    """Return ``d`` without Mongo's internal ``_id`` (not part of our API)."""
    return {k: v for k, v in d.items() if k != "_id"}


class ChatDatabase:
    """Thread-safe access to the ``chats`` / ``messages`` collections."""

    def __init__(self, mongo_uri: str, db_name: str,
                 history_limit: int, upload_dir: str) -> None:
        self._history_limit = history_limit
        self._upload_dir = upload_dir
        # Fail fast (5s) if mongod isn't up, rather than hanging forever.
        self._client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self._db = self._client[db_name]
        self._chats = self._db["chats"]
        self._messages = self._db["messages"]
        self._ensure_indexes()

    # -------------------------------------------------------------- lifecycle

    def _ensure_indexes(self) -> None:
        """Create (idempotently) the indexes the queries rely on."""
        try:
            # Also acts as a liveness check: raises if mongod is unreachable.
            self._chats.create_index("id", unique=True)
            self._chats.create_index([("updated_at", -1), ("created_at", -1)])
            self._messages.create_index([("chat_id", 1), ("created_at", 1)])
        except ServerSelectionTimeoutError as e:
            raise RuntimeError(
                "cannot reach MongoDB at the configured URI (is mongod running?)"
            ) from e
        except (OperationFailure, PyMongoError) as e:
            raise RuntimeError(f"MongoDB index setup failed: {e}") from e

    def list_chats(self) -> list[dict[str, Any]]:
        """All chats, newest activity first (with a stored message count).

        Empty placeholder chats (no messages, still the default title) are
        dropped: they should never appear in the history list.
        """
        chats = [_doc(d) for d in
                 self._chats.find().sort([("updated_at", -1), ("created_at", -1)])]
        stale = [c["id"] for c in chats
                 if not c.get("n") and str(c.get("title")) == "New chat"]
        if stale:
            self._drop_empty(stale)
            return [c for c in chats if c["id"] not in set(stale)]
        return chats

    def _drop_empty(self, chat_ids: list[str]) -> None:
        """Remove placeholder chats that were never used (no messages)."""
        ids = list(chat_ids)
        if not ids:
            return
        try:
            self._chats.delete_many({"id": {"$in": ids}})
            self._messages.delete_many({"chat_id": {"$in": ids}})
        except PyMongoError:
            pass  # best effort — the client simply won't list them

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ chats

    def get_chat(self, chat_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return (chat, messages in id order). Raises ChatNotFoundError."""
        chat = self._chats.find_one({"id": chat_id})
        if chat is None:
            raise ChatNotFoundError(chat_id)
        msgs = list(
            self._messages
            .find({"chat_id": chat_id})
            .sort([("created_at", 1)])
        )
        return _doc(chat), [_doc(m) for m in msgs]

    def create_chat(self, model: str) -> dict[str, Any]:
        now = int(time.time())
        chat = {
            "id": uuid.uuid4().hex,
            "title": "New chat",
            "model": model,
            "created_at": now,
            "updated_at": now,
            "n": 0,  # running message count (denormalised, see _bump)
        }
        self._chats.insert_one(chat)
        return _doc(chat)

    def delete_chat(self, chat_id: str) -> None:
        self._chats.delete_one({"id": chat_id})
        self._messages.delete_many({"chat_id": chat_id})

    # ---------------------------------------------------------------- messages

    def add_user_message(self, chat_id: str, text: str, images: list[str]) -> None:
        """Store a user turn. The first message titles the chat."""
        now = int(time.time())
        self._messages.insert_one({
            "chat_id": chat_id,
            "role": "user",
            "content": text,
            "images": list(images),
            "created_at": now,
        })
        self._bump(chat_id, now, title_if_first=text)

    def add_assistant_message(self, chat_id: str, content: str, model: str, response_ms: int) -> None:
        now = int(time.time())
        self._messages.insert_one({
            "chat_id": chat_id,
            "role": "assistant",
            "content": content,
            "model": model,
            "response_ms": response_ms,
            "created_at": now,
        })
        self._bump(chat_id, now)

    def _bump(self, chat_id: str, now: int,
              title_if_first: str | None = None) -> None:
        """Refresh a chat's ``updated_at`` and message count; set the title on
        the first message (which is always a user message)."""
        update: dict[str, Any] = {
            "$set": {"updated_at": now},
            "$inc": {"n": 1},
        }
        if title_if_first is not None:
            chat = self._chats.find_one({"id": chat_id})
            if chat and chat.get("n", 0) == 0:
                title = re.sub(r"\s+", " ", title_if_first).strip()[:60] or "Chat with images"
                update["$set"]["title"] = title
        self._chats.update_one({"id": chat_id}, update)

    def build_model_messages(self, chat_id: str) -> list[dict[str, Any]]:
        """Build the Ollama ``messages`` array for this chat.

        Only the *last* user message carries an ``images`` list (base64),
        because older photos are already reflected in the assistant's
        earlier replies.
        """
        rows = [
            {"role": d.get("role"), "content": d.get("content"), "images": d.get("images")}
            for d in self._messages
            .find({"chat_id": chat_id}, {"role": 1, "content": 1, "images": 1})
            .sort([("created_at", 1)])
        ]
        tail = rows[-self._history_limit:] if self._history_limit else rows

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

    def _load_images(self, names: list[str] | None) -> list[str]:
        """Base64-encode the stored image files referenced by a user row."""
        out: list[str] = []
        for name in names or []:
            path = os.path.join(self._upload_dir, name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    out.append(base64.b64encode(f.read()).decode("ascii"))
        return out

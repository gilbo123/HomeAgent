"""HTTP server: routing + the App facade that ties services together.

Routing (kept deliberately flat and explicit):

    GET    /                          index.html
    GET    /api/models                models list from Ollama
    GET    /api/chats                 chat list
    GET    /api/chats/<id>            chat + messages
    GET    /uploads/<name>            uploaded image
    POST   /api/chats                 create chat            {model?}
    POST   /api/upload                upload image           multipart/form-data
    POST   /api/chats/<id>/messages   send turn, NDJSON out  {text, images[]}
    POST   /api/incognito             unsaved turn, NDJSON   {model?, text, images[], messages[]}
    DELETE /api/chats/<id>            delete chat

Design notes:
    * :class:`App` is the single object the handler needs; it owns the
      ``Config`` and the services (db / ollama / uploads). Tests can build
      an :class:`App` with stubs — the handler never imports globals.
    * The handler is defined here as ``make_handler(app)`` so every
      instance carries its own app reference (no module-level state).
    * Streaming: we emit NDJSON line by line and keep consuming the
      Ollama stream even if the browser disconnects, so the assistant
      reply is always saved (and not lost mid-response).
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler
from typing import Any

from . import __version__
from .app import App
from .db import ChatNotFoundError
from .uploads import UploadError, UploadTooLarge, UnsupportedImage

CHAT_ID_RE = re.compile(r"[\w-]+")


# --------------------------------------------------------------------------
# Handler factory
# --------------------------------------------------------------------------

def make_handler(app: App):
    """Return a BaseHTTPRequestHandler class bound to ``app``."""

    class Handler(BaseHTTPRequestHandler):
        server_version = f"HomeAgent/{__version__}"

        # ------------------------------------------------------------ utils

        def log_message(self, format, *args):  # one tidy line per request
            print("[%s] %s" % (time.strftime("%H:%M:%S"), format % args), flush=True)

        def _send_json(self, code: int, obj: Any) -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error_json(self, code: int, msg: str) -> None:
            self._send_json(code, {"error": msg})

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def _read_json(self) -> dict[str, Any]:
            try:
                payload = json.loads(self._read_body() or b"{}")
                return payload if isinstance(payload, dict) else {}
            except ValueError:
                return {}

        def _serve_file(self, path: str, content_type: str, cache: str = "no-cache") -> None:
            if not os.path.isfile(path):
                self._send_error_json(404, "Not found")
                return
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(data)

        def _route(self, method: str) -> None:
            """Dispatch a request; wrap every route in one try/except so
            no handler error produces an HTML traceback page."""
            path = self.path.split("?", 1)[0]
            try:
                self._route_inner(method, path)
            except Exception as e:  # noqa: BLE001 — last-resort guard
                code = 500
                try:
                    self._send_error_json(code, str(e))
                except Exception:  # response already started (e.g. mid-stream)
                    pass

        # --------------------------------------------------------- routing

        def _route_inner(self, method: str, path: str) -> None:
            if method == "GET":
                if path == "/":
                    return self._serve_file(os.fspath(app.index_html), "text/html; charset=utf-8")
                if path in ("/style.css", "/app.js"):
                    ctype = ("text/css; charset=utf-8" if path.endswith(".css")
                             else "application/javascript; charset=utf-8")
                    p = os.path.join(os.fspath(app.static_dir), path.lstrip("/"))
                    return self._serve_file(p, ctype)
                if path == "/api/models":
                    return self._get_models()
                if path == "/api/chats":
                    return self._send_json(200, {
                        "chats": app.db.list_chats(),
                        "default_model": app.cfg.default_model,
                    })
                m = re.fullmatch(r"/api/chats/(" + CHAT_ID_RE.pattern + r")", path)
                if m:
                    return self._get_chat(m.group(1))
                m = re.fullmatch(r"/uploads/([0-9a-f]{32}\.[a-z0-9]{2,5})", path, re.IGNORECASE)
                if m:
                    stored = m.group(1)
                    p = app.uploads.path_for(stored)
                    if p:
                        # Uploaded images are content-addressed, so a long
                        # client cache is safe and avoids re-fetching on scroll.
                        return self._serve_file(p, app.uploads.content_type_for(stored),
                                                cache="public, max-age=86400")
                    return self._send_error_json(404, "Not found")
            elif method == "POST":
                if path == "/api/chats":
                    return self._create_chat()
                if path == "/api/incognito":
                    return self._incognito()
                if path == "/api/upload":
                    return self._upload()
                m = re.fullmatch(r"/api/chats/(" + CHAT_ID_RE.pattern + r")/messages", path)
                if m:
                    return self._send_message(m.group(1))
            elif method == "DELETE":
                m = re.fullmatch(r"/api/chats/(" + CHAT_ID_RE.pattern + r")", path)
                if m:
                    return self._delete_chat(m.group(1))

            self._send_error_json(404, "Not found")

        do_GET = lambda self: self._route("GET")       # noqa: E731
        do_POST = lambda self: self._route("POST")     # noqa: E731
        do_DELETE = lambda self: self._route("DELETE") # noqa: E731

        # -------------------------------------------------------------- GET

        def _get_models(self) -> None:
            try:
                models = app.ollama.list_models()
            except Exception as e:  # noqa: BLE001 — Ollama down
                # Still return the configured default so the UI has a picker.
                return self._send_json(502, {
                    "error": f"Ollama unreachable: {e}",
                    "models": [app.cfg.default_model],
                    "default": app.cfg.default_model,
                })
            self._send_json(200, {
                "models": models,
                "default": app.cfg.default_model,
                "ollama": app.cfg.ollama_host,
            })

        def _get_chat(self, chat_id: str) -> None:
            try:
                chat, messages = app.db.get_chat(chat_id)
            except ChatNotFoundError:
                return self._send_error_json(404, "Chat not found")
            self._send_json(200, {"chat": chat, "messages": messages})

        # ------------------------------------------------------------- POST

        def _create_chat(self) -> None:
            payload = self._read_json()
            model = (payload.get("model") or app.cfg.default_model).strip() or app.cfg.default_model
            self._send_json(201, {"chat": app.db.create_chat(model)})

        def _incognito(self) -> None:
            """Answer one turn using context the *client* keeps in memory.

            Nothing is written to the database: the request carries the
            incognito history (plain text turns) plus the new user turn, we
            stream the model reply back, and that's it.
            """
            import base64

            payload = self._read_json()
            text = (payload.get("text") or "").strip()
            images = payload.get("images") or []
            if not isinstance(images, list):
                images = []

            def _name(v: Any) -> str:
                v = str(v).strip()
                return v.removeprefix("/uploads/") if v.startswith("/uploads/") else v

            images = [n for v in images if (n := _name(v)) and app.uploads.path_for(n)]
            if not text and not images:
                return self._send_error_json(400, "Empty message")

            model = (payload.get("model") or app.cfg.default_model).strip() or app.cfg.default_model

            # Sanitise the in-memory history the client sent us.
            messages: list[dict[str, Any]] = []
            for m in (payload.get("messages") or []):
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                content = str(m.get("content") or "").strip()
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            if app.cfg.history_limit:
                messages = messages[-app.cfg.history_limit:]

            user_msg: dict[str, Any] = {"role": "user", "content": text or "(image)"}
            b64: list[str] = []
            for n in images:
                p = app.uploads.path_for(n)
                if p and os.path.isfile(p):
                    with open(p, "rb") as f:
                        b64.append(base64.b64encode(f.read()).decode("ascii"))
            if b64:
                user_msg["images"] = b64
            messages.append(user_msg)

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def push(ev: dict) -> bool:
                try:
                    self.wfile.write((json.dumps(ev) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError):
                    return False

            for ev in app.ollama.stream_chat(messages, model):
                if not push(ev):
                    break
                if ev["type"] in ("done", "error"):
                    break

        def _upload(self) -> None:
            content_type = self.headers.get("Content-Type", "")
            try:
                name = app.uploads.store(self._read_body(), content_type)
            except UploadTooLarge as e:
                return self._send_error_json(413, str(e))
            except UnsupportedImage as e:
                return self._send_error_json(415, str(e))
            except UploadError as e:
                return self._send_error_json(400, str(e))
            self._send_json(201, {"url": f"/uploads/{name}", "name": name, "id": name.split(".")[0]})

        def _delete_chat(self, chat_id: str) -> None:
            app.db.delete_chat(chat_id)
            self._send_json(200, {"ok": True})

        def _send_message(self, chat_id: str) -> None:
            try:
                app.db.get_chat(chat_id)  # exists?
            except ChatNotFoundError:
                return self._send_error_json(404, "Chat not found")

            payload = self._read_json()
            text = (payload.get("text") or "").strip()
            images = payload.get("images") or []
            if not isinstance(images, list):
                images = []
            # The client may send either a "/uploads/<name>" URL or a bare
            # stored name; normalise to the name, then only keep files that
            # actually exist (prevents path traversal / unknown refs).
            def _name(v: Any) -> str:
                v = str(v).strip()
                return v.removeprefix("/uploads/") if v.startswith("/uploads/") else v

            images = [n for v in images if (n := _name(v)) and app.uploads.path_for(n)]
            if not text and not images:
                return self._send_error_json(400, "Empty message")

            chat, _ = app.db.get_chat(chat_id)
            model = chat["model"] or app.cfg.default_model
            app.db.add_user_message(chat_id, text, images)
            messages = app.db.build_model_messages(chat_id)

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def push(ev: dict) -> bool:
                """Write one NDJSON event. Returns False if client is gone."""
                try:
                    self.wfile.write((json.dumps(ev) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError):
                    return False

            started = time.monotonic()
            acc: list[str] = []
            for ev in app.ollama.stream_chat(messages, model):
                if ev["type"] == "delta":
                    acc.append(ev["content"])
                if not push(ev):
                    break  # client left — but keep draining so we save below
                if ev["type"] in ("done", "error"):
                    break
            ms = int((time.monotonic() - started) * 1000)
            if acc:
                try:
                    app.db.add_assistant_message(chat_id, "".join(acc), model, ms)
                except Exception as e:  # noqa: BLE001
                    print(f"[!] failed to save assistant message: {e}", flush=True)

    return Handler

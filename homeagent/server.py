"""HTTP server: routing + the App facade that ties services together.

Routing (kept deliberately flat and explicit):

    GET    /                          index.html
    POST   /auth/guest                guest session (memory only, incognito only)
    GET    /api/providers             configured model providers           [guest ok]
    GET    /api/models?provider=<id>  that provider's models (empty if down) [guest ok]
    GET    /uploads/<name>            uploaded image                       [guest ok]
    POST   /api/upload                upload image  multipart/form-data    [guest ok]
    POST   /api/incognito             unsaved turn, NDJSON                 [guest ok]
                                      {provider, model, text, images[], messages[]}
    GET    /api/chats                 chat list
    GET    /api/chats/<id>            chat + messages
    POST   /api/chats                 create chat            {provider, model}
    POST   /api/chats/<id>/messages   send turn, NDJSON out  {provider?, model?, text, images[]}
    DELETE /api/chats/<id>            delete chat

Design notes:
    * :class:`App` is the single object the handler needs; it owns the
      ``Config`` and the services (db / ollama / agent / uploads). Tests can
      build an :class:`App` with stubs — the handler never imports globals.
    * The handler is defined here as ``make_handler(app)`` so every
      instance carries its own app reference (no module-level state).
    * Streaming: turns are produced by :class:`~homeagent.agent.Agent` and
      emitted as NDJSON line by line. If the browser disconnects (or the
      user presses stop) generation stops and the partial reply is saved.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs

from . import __version__
from .accounts import AuthError
from .app import App
from .db import ChatNotFoundError
from .uploads import UploadError, UploadTooLarge, UnsupportedImage

CHAT_ID_RE = re.compile(r"[\w-]+")


class BodyTooLarge(Exception):
    """Request body exceeds the configured cap."""


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
            # One image plus multipart / JSON overhead.
            if length > (app.cfg.max_image_mb + 1) * 1024 * 1024:
                raise BodyTooLarge(f"Request too large (max {app.cfg.max_image_mb} MB)")
            return self.rfile.read(length) if length else b""

        def _read_json(self) -> dict[str, Any]:
            try:
                payload = json.loads(self._read_body() or b"{}")
                return payload if isinstance(payload, dict) else {}
            except ValueError:
                return {}

        # --------------------------------------------------- session / auth

        def _cookie_value(self, name: str) -> str:
            raw = self.headers.get("Cookie", "")
            for part in raw.split(";"):
                bit = part.strip()
                if bit.startswith(name + "="):
                    return bit[len(name) + 1:].strip()
            return ""

        def _session(self) -> dict[str, Any] | None:
            """The live session behind the cookie (``username``, ``guest``?), or None."""
            token = self._cookie_value("ha_session")
            return app.users.lookup_session(token) if token else None

        def _require_user(self, allow_guest: bool = False) -> str | None:
            """Return the username, or send 401/403 and return None.

            Guests have no stored identity, so routes that read or write
            chat history are closed to them (``allow_guest=False``).
            """
            sess = self._session()
            if not sess:
                self._send_error_json(401, "not signed in")
                return None
            if sess.get("guest") and not allow_guest:
                self._send_error_json(403, "guest accounts can only use incognito chat")
                return None
            return sess["username"]

        def _send_cookie(self, name: str, value: str, max_age: int | None) -> None:
            base = f"{name}={value}; Path=/; HttpOnly; SameSite=Lax"
            if max_age is not None:
                base += f"; Max-Age={max_age}"
            else:
                base += "; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_header("Set-Cookie", base)

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
            path, _, query = self.path.partition("?")
            self._query = {k: v[-1] for k, v in parse_qs(query).items()}
            try:
                self._route_inner(method, path)
            except BodyTooLarge as e:
                self.close_connection = True  # the unread body is still on the socket
                self._send_error_json(413, str(e))
            except Exception as e:  # noqa: BLE001 — last-resort guard
                try:
                    self._send_error_json(500, str(e))
                except Exception:  # response already started (e.g. mid-stream)
                    pass

        # --------------------------------------------------------- routing

        def _route_inner(self, method: str, path: str) -> None:
            # ----- Public routes (reachable logged-in or out) -----
            if method == "GET":
                if path == "/":
                    return self._serve_file(os.fspath(app.index_html), "text/html; charset=utf-8")
                if path in ("/style.css", "/app.js"):
                    ctype = ("text/css; charset=utf-8" if path.endswith(".css")
                             else "application/javascript; charset=utf-8")
                    p = os.path.join(os.fspath(app.static_dir), path.lstrip("/"))
                    return self._serve_file(p, ctype)
                if path == "/auth/me":
                    return self._auth_me()
                if path == "/auth/users":
                    return self._auth_users()
            elif method == "POST":
                if path == "/auth/login":
                    return self._auth_login()
                if path == "/auth/guest":
                    return self._auth_guest()
                if path == "/auth/logout":
                    return self._auth_logout()
                if path == "/auth/set-or-reset":
                    return self._auth_set_or_reset()
                if path == "/auth/verify-code":
                    return self._auth_verify_code()

            # ----- Session routes open to guests (no history involved) -----
            guest_ok = {
                ("GET", "/api/providers"): self._get_providers,
                ("GET", "/api/models"): self._get_models,
                ("POST", "/api/incognito"): self._incognito,
                ("POST", "/api/upload"): self._upload,
            }
            handler = guest_ok.get((method, path))
            if handler:
                return handler() if self._require_user(allow_guest=True) else None
            if method == "GET":
                m = re.fullmatch(r"/uploads/([0-9a-f]{32}\.[a-z0-9]{2,5})", path, re.IGNORECASE)
                if m:
                    if not self._require_user(allow_guest=True):
                        return
                    stored = m.group(1)
                    # NB: the upload ID is 32-hex UUID (unguessable) and it is
                    # only surfaced in the chat of the user who uploaded it,
                    # which is already per-owner-scoped in the DB — requiring a
                    # session here is sufficient privacy; a full owner column
                    # on uploads would be overkill for a single-host app.
                    p = app.uploads.path_for(stored)
                    if p:
                        return self._serve_file(p, app.uploads.content_type_for(stored),
                                                cache="public, max-age=86400")
                    return self._send_error_json(404, "Not found")

            # ----- Chat history routes (registered users only) -----
            chat = re.fullmatch(r"/api/chats/(" + CHAT_ID_RE.pattern + r")", path)
            chat_msgs = re.fullmatch(r"/api/chats/(" + CHAT_ID_RE.pattern + r")/messages", path)
            if path == "/api/chats" or chat or chat_msgs:
                user = self._require_user()
                if not user:
                    return
                if method == "GET" and path == "/api/chats":
                    return self._send_json(200, {"chats": app.db.list_chats(user)})
                if method == "POST" and path == "/api/chats":
                    return self._create_chat(user)
                if method == "GET" and chat:
                    return self._get_chat(chat.group(1), user)
                if method == "DELETE" and chat:
                    return self._delete_chat(chat.group(1), user)
                if method == "POST" and chat_msgs:
                    return self._send_message(chat_msgs.group(1), user)

            self._send_error_json(404, "Not found")

        do_GET = lambda self: self._route("GET")       # noqa: E731
        do_POST = lambda self: self._route("POST")     # noqa: E731
        do_DELETE = lambda self: self._route("DELETE") # noqa: E731

        # ------------------------------------------------------------- auth

        def _send_session(self, token: str, ttl: int) -> None:
            """Reply ``{}`` and set the session cookie."""
            self.send_response(200)
            self._send_cookie("ha_session", token, ttl)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def _auth_me(self) -> None:
            """Report the signed-in user, if any (no 401 when signed out)."""
            sess = self._session()
            if not sess:
                return self._send_json(200, {"user": None})
            if sess.get("guest"):
                return self._send_json(200, {"user": {"username": sess["username"], "guest": True}})
            user = sess["username"]
            self._send_json(200, {"user": app.users.get_public(user) or {"username": user}})

        def _auth_guest(self) -> None:
            """Sign in as the guest: memory-only session, incognito chat only."""
            self._send_session(*app.users.create_guest_session())

        def _auth_users(self) -> None:
            """Lightweight list of accounts, for the login-splash tiles."""
            self._send_json(200, {"users": app.users.list_users()})

        def _auth_login(self) -> None:
            payload = self._read_json()
            username = (payload.get("username") or "").strip()
            password = payload.get("password") or ""
            if not username or not app.users.try_login(username, password):
                return self._send_error_json(401, "wrong username or password")
            try:
                token, ttl = app.users.create_session(username)
            except AuthError as e:
                return self._send_error_json(403, str(e))
            self._send_session(token, ttl)

        def _auth_logout(self) -> None:
            token = self._cookie_value("ha_session")
            if token:
                app.users.delete_session(token)
            self.send_response(200)
            self._send_cookie("ha_session", "", None)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def _auth_set_or_reset(self) -> None:
            payload = self._read_json()
            try:
                code, (em_ok, em_msg), is_new = app.users.request_set_or_reset(
                    (payload.get("username") or ""),
                    (payload.get("email") or ""),
                    (payload.get("password") or ""),
                    (payload.get("confirm") or ""),
                )
            except AuthError as e:
                return self._send_error_json(400, str(e))
            # PRIVACY: when SMTP is configured and the send succeeded, the code
            # lives in the inbox — we do NOT return it to the browser so it can
            # never be read off a shared screen. The on-screen fallback code is
            # only handed over when email is off OR the send failed.
            email_cfg = app.users.email_enabled
            if email_cfg and em_ok:
                delivered = "inbox"
            elif email_cfg and not em_ok:
                # Requested email but failed — surface the error so the user
                # can diagnose the SMTP config, and still hand over the code
                # as a documented fallback (a failure must not be silent).
                delivered = "fallback-after-error"
            else:
                delivered = "off"
            self._send_json(200, {
                "code": code if delivered != "inbox" else None,
                "is_new": is_new,
                "email_configured": email_cfg,
                "email_sent": em_ok,
                "email_note": em_msg,
                "delivery": delivered,
            })

        def _auth_verify_code(self) -> None:
            """POST /auth/verify-code — finalize a set/reset and sign in.

            Body: ``{"code": "A2B3C4"}``. The code was delivered by email (or
            shown on-screen as the documented fallback), so no private link is
            ever displayed to the browser. On success the session cookie is
            set and the client redirects to ``/``.
            """
            payload = self._read_json()
            try:
                user = app.users.verify_code(
                    (payload.get("code") or "").strip(),
                    claim_unowned=app.db.claim_unowned,
                )
            except AuthError as e:
                return self._send_error_json(400, str(e))
            try:
                token2, ttl = app.users.create_session(user["username"])
            except AuthError as e:
                return self._send_error_json(403, str(e))
            self._send_session(token2, ttl)

        # -------------------------------------------------------------- GET

        def _get_providers(self) -> None:
            self._send_json(200, {
                "providers": app.providers.public(),
                "default": app.providers.default_id,
            })

        def _get_models(self) -> None:
            """Models of ``?provider=<id>``; an unreachable server lists none."""
            provider = app.providers.get(self._query.get("provider"))
            out: dict[str, Any] = {"provider": provider.id, "url": provider.url}
            try:
                models = provider.client.list_models()
            except Exception as e:  # noqa: BLE001 — server down / not installed
                return self._send_json(200, {**out, "online": False, "models": [],
                                             "default": "", "error": str(e)})
            default = app.cfg.default_model if app.cfg.default_model in models else ""
            self._send_json(200, {**out, "online": True, "models": models,
                                  "default": default or (models[0] if models else "")})

        def _get_chat(self, chat_id: str, owner: str) -> None:
            try:
                chat, messages = app.db.get_chat(chat_id, owner)
            except ChatNotFoundError:
                return self._send_error_json(404, "Chat not found")
            self._send_json(200, {"chat": chat, "messages": messages})

        # ------------------------------------------------------------- POST

        def _create_chat(self, owner: str) -> None:
            provider, model = self._pick_model(self._read_json())
            if not model:
                return self._send_error_json(400, "No model selected")
            self._send_json(201, {"chat": app.db.create_chat(model, owner, provider.id)})

        def _image_names(self, payload: dict[str, Any]) -> list[str]:
            """Stored upload names referenced by the request.

            The client may send a "/uploads/<name>" URL or a bare stored name;
            only names of files that actually exist are kept (prevents path
            traversal / unknown refs).
            """
            raw = payload.get("images") or []
            if not isinstance(raw, list):
                return []
            names = (str(v).strip().removeprefix("/uploads/") for v in raw)
            return [n for n in names if n and app.uploads.path_for(n)]

        def _pick_model(self, payload: dict[str, Any],
                        chat: dict[str, Any] | None = None) -> tuple[Any, str]:
            """(provider, model) from the request, falling back to the chat's."""
            chat = chat or {}
            provider = app.providers.get(str(payload.get("provider") or chat.get("provider") or ""))
            model = str(payload.get("model") or "").strip() or str(chat.get("model") or "")
            return provider, model

        def _stream_turn(self, provider: Any, messages: list[dict[str, Any]],
                         model: str) -> dict[str, Any]:
            """Run one agent turn, streaming NDJSON events to the browser.

            Returns what was produced (content, thinking, tool calls, elapsed
            ms) so the caller can persist it. Stops early if the client leaves.
            """
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            started = time.monotonic()
            content: list[str] = []
            thinking: list[str] = []
            tools: list[dict[str, Any]] = []
            for ev in app.agent.run(provider.client, messages, model):
                kind = ev["type"]
                if kind == "delta":
                    content.append(ev["content"])
                elif kind == "think_delta":
                    thinking.append(ev["content"])
                elif kind == "tool":
                    tools.append({"name": ev["name"], "arguments": ev["arguments"], "ok": None})
                elif kind == "tool_result" and tools:
                    tools[-1]["ok"] = ev["ok"]
                try:
                    self.wfile.write((json.dumps(ev) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
            return {
                "content": "".join(content),
                "thinking": "".join(thinking),
                "tools": tools,
                "ms": int((time.monotonic() - started) * 1000),
            }

        def _incognito(self) -> None:
            """Answer one turn using context the *client* keeps in memory.

            Nothing is written to the database: the request carries the
            incognito history (plain text turns) plus the new user turn, we
            stream the model reply back, and that's it.
            """
            payload = self._read_json()
            text = (payload.get("text") or "").strip()
            images = self._image_names(payload)
            if not text and not images:
                return self._send_error_json(400, "Empty message")

            provider, model = self._pick_model(payload)
            if not model:
                return self._send_error_json(400, "No model selected")

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
                with open(app.uploads.path_for(n), "rb") as f:
                    b64.append(base64.b64encode(f.read()).decode("ascii"))
            if b64:
                user_msg["images"] = b64
            messages.append(user_msg)

            self._stream_turn(provider, messages, model)

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

        def _delete_chat(self, chat_id: str, owner: str) -> None:
            app.db.delete_chat(chat_id, owner)
            self._send_json(200, {"ok": True})

        def _send_message(self, chat_id: str, owner: str) -> None:
            try:
                chat, _ = app.db.get_chat(chat_id, owner)
            except ChatNotFoundError:
                return self._send_error_json(404, "Chat not found")

            payload = self._read_json()
            text = (payload.get("text") or "").strip()
            images = self._image_names(payload)
            if not text and not images:
                return self._send_error_json(400, "Empty message")

            provider, model = self._pick_model(payload, chat)
            if not model:
                return self._send_error_json(400, "No model selected")
            if (provider.id, model) != (chat.get("provider"), chat.get("model")):
                app.db.set_chat_model(chat_id, owner, provider.id, model)
            app.db.add_user_message(chat_id, text, images)
            out = self._stream_turn(provider, app.db.build_model_messages(chat_id), model)
            if out["content"] or out["thinking"]:
                try:
                    app.db.add_assistant_message(chat_id, out["content"], model, out["ms"],
                                                 thinking=out["thinking"], tools=out["tools"])
                except Exception as e:  # noqa: BLE001
                    print(f"[!] failed to save assistant message: {e}", flush=True)

    return Handler

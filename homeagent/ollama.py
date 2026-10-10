"""Minimal Ollama HTTP client (stdlib only).

Responsibilities:
    * list available models and their capabilities (``/api/tags``)
    * stream one chat completion (``/api/chat``) as a generator of small
      JSON-ready events, which the HTTP layer forwards as NDJSON

Event shapes yielded by :meth:`OllamaClient.stream_chat`:
    {"type": "think_delta", "content": str} — a chunk of the model's thinking
    {"type": "delta", "content": str}       — a chunk of model output
    {"type": "tool_calls", "calls": list}   — the model wants tools run
                                              (Ollama ``tool_calls`` verbatim)
    {"type": "done", "duration_ms": int}    — completion finished
    {"type": "error", "error": str}         — something went wrong
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from typing import Any, Generator
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

_CAPS_TTL_S = 120.0


class OllamaError(RuntimeError):
    """Ollama unreachable or returned an unusable response."""


class OllamaClient:
    def __init__(self, host: str, default_model: str, temperature: float) -> None:
        self.host = host.rstrip("/")
        self.default_model = default_model
        self.temperature = temperature
        self._caps: tuple[float, dict[str, frozenset[str]]] | None = None
        self._caps_lock = threading.Lock()

    # -------------------------------------------------------------- models

    def _tags(self) -> list[dict[str, Any]]:
        try:
            with urlrequest.urlopen(self.host + "/api/tags", timeout=5) as r:
                data = json.loads(r.read())
        except (URLError, OSError, ValueError) as e:
            raise OllamaError(str(e)) from e
        return [m for m in data.get("models", []) if m.get("name")]

    def list_models(self) -> list[str]:
        """Return model names (e.g. ``"qwen3.8:27b"``). Raises :class:`OllamaError`."""
        models = self._tags()
        self._store_caps(models)
        return [m["name"] for m in models]

    def capabilities(self) -> dict[str, frozenset[str]]:
        """Model name -> capabilities (``thinking``, ``tools``, ``vision``, …).

        Cached briefly. Best-effort: older Ollama omits ``capabilities`` and
        the request may fail; either way the model just gets no extras, which
        is safe because models reject features they don't support.
        """
        with self._caps_lock:
            cached = self._caps
        if cached and time.monotonic() - cached[0] < _CAPS_TTL_S:
            return cached[1]
        try:
            return self._store_caps(self._tags())
        except OllamaError:
            return cached[1] if cached else {}

    def supports(self, model: str, capability: str) -> bool:
        return capability in self.capabilities().get(model, frozenset())

    def _store_caps(self, models: list[dict[str, Any]]) -> dict[str, frozenset[str]]:
        caps = {m["name"]: frozenset(m.get("capabilities") or []) for m in models}
        with self._caps_lock:
            self._caps = (time.monotonic(), caps)
        return caps

    # -------------------------------------------------------------- chat

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        think: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """POST one chat completion and yield the events described above.

        ``think`` and ``tools`` must only be sent to models that support them.
        """
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        if think:
            payload["think"] = True
        if tools:
            payload["tools"] = tools
        req = urlrequest.Request(
            self.host + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urlrequest.urlopen(req, timeout=None)
        except HTTPError as e:
            yield {"type": "error", "error": f"Ollama error: {_http_error_text(e)}"}
            return
        except (URLError, OSError) as e:
            yield {
                "type": "error",
                "error": f"Cannot reach Ollama at {self.host} ({e}). Is `ollama serve` running?",
            }
            return

        tool_calls: list[dict[str, Any]] = []
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue  # ignore anything that isn't JSON
                if obj.get("error"):
                    yield {"type": "error", "error": str(obj["error"])}
                    return
                message = obj.get("message") or {}
                if message.get("thinking"):
                    yield {"type": "think_delta", "content": message["thinking"]}
                if message.get("content"):
                    yield {"type": "delta", "content": message["content"]}
                tool_calls.extend(message.get("tool_calls") or [])
                if obj.get("done"):
                    if tool_calls:
                        yield {"type": "tool_calls", "calls": tool_calls}
                    yield {
                        "type": "done",
                        "duration_ms": int(obj.get("total_duration", 0)) // 1_000_000,
                    }
                    return
        except (OSError, http.client.HTTPException) as e:
            yield {"type": "error", "error": f"Lost connection to Ollama mid-reply ({e})"}
        finally:
            resp.close()


def _http_error_text(e: HTTPError) -> str:
    try:
        return str(json.loads(e.read()).get("error") or e.reason)
    except Exception:  # noqa: BLE001
        return f"HTTP {e.code} {e.reason}"

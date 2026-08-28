"""Minimal Ollama HTTP client (stdlib only).

Two responsibilities:
    * list available models (``/api/tags``)
    * stream a chat completion (``/api/chat``) as a generator of
      small JSON-ready events, which the HTTP layer forwards verbatim
      as NDJSON to the browser.

Event shapes yielded by :meth:`OllamaClient.stream_chat`:
    {"type": "delta", "content": str}      — a chunk of model output
    {"type": "done", "duration_ms": int}   — completion finished
    {"type": "error", "error": str}        — something went wrong
"""

from __future__ import annotations

import json
from typing import Any, Generator
from urllib import request as urlrequest
from urllib.error import URLError


class OllamaClient:
    def __init__(self, host: str, default_model: str, temperature: float) -> None:
        self.host = host.rstrip("/")
        self.default_model = default_model
        self.temperature = temperature

    # -------------------------------------------------------------- models

    def list_models(self) -> list[str]:
        """Return model names from ``/api/tags`` (e.g. ``"qwen3.8:27b"``).

        Raises:
            OllamaError: if the server cannot be reached or replies oddly.
        """
        with self._get("/api/tags", timeout=5) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", []) if m.get("name")]

    def reachable(self) -> bool:
        """Cheap liveness check used by the /api/models endpoint."""
        try:
            return bool(self.list_models())
        except OllamaError:
            return False

    # -------------------------------------------------------------- chat

    def stream_chat(
        self, messages: list[dict[str, Any]], model: str | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """POST a chat completion and yield delta/done/error events.

        ``model`` defaults to the configured default model when omitted.
        """
        body = json.dumps(
            {
                "model": model or self.default_model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": self.temperature},
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            self.host + "/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urlrequest.urlopen(req, timeout=None)
        except (URLError, OSError) as e:
            yield {
                "type": "error",
                "error": f"Cannot reach Ollama at {self.host} ({e}). Is `ollama serve` running?",
            }
            return

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
                if obj.get("done"):
                    yield {
                        "type": "done",
                        "duration_ms": int(obj.get("total_duration", 0)) // 1_000_000,
                    }
                    return
                content = (obj.get("message") or {}).get("content") or ""
                if content:
                    yield {"type": "delta", "content": content}
        finally:
            resp.close()

    # -------------------------------------------------------------- helpers

    def _get(self, path: str, timeout: float):
        return urlrequest.urlopen(self.host + path, timeout=timeout)


class OllamaError(RuntimeError):
    """Ollama unreachable or returned an unusable response."""

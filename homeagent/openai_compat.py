"""Client for OpenAI-compatible servers (Strata, vLLM, LM Studio, …), stdlib only.

Mirrors :class:`homeagent.ollama.OllamaClient`'s interface so the agent can
drive either: ``list_models`` / ``capabilities`` / ``supports`` /
``stream_chat`` yielding the same event shapes. Messages arrive in the
Ollama shape the rest of the app uses and are translated here:

    * ``images`` (bare base64)  -> ``image_url`` content parts (data URLs)
    * tool call ``arguments`` dict -> JSON string, with ``type: function``
    * ``role: tool`` messages carry ``tool_call_id``

Streaming uses server-sent events (``data: {...}`` / ``data: [DONE]``).
Reasoning text arrives as ``reasoning_content`` (vLLM, LM Studio,
llama.cpp-based servers) or ``reasoning``; it is surfaced as ``think_delta``.

There is no portable capability endpoint, so tools are assumed supported
until a server rejects a request that includes them; the request is then
retried once without tools and the model is remembered as tool-less.
"""

from __future__ import annotations

import base64
import http.client
import json
import threading
import time
from typing import Any, Generator
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


class ProviderError(RuntimeError):
    """Server unreachable or returned an unusable response."""


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, temperature: float) -> None:
        self.host = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self._no_tools: set[str] = set()
        self._lock = threading.Lock()

    # -------------------------------------------------------------- models

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def list_models(self) -> list[str]:
        req = urlrequest.Request(self.host + "/models", headers=self._headers())
        try:
            with urlrequest.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
        except (URLError, OSError, ValueError) as e:
            raise ProviderError(str(e)) from e
        return [m["id"] for m in data.get("data", []) if m.get("id")]

    def capabilities(self) -> dict[str, frozenset[str]]:
        return {}

    def supports(self, model: str, capability: str) -> bool:
        if capability == "tools":
            with self._lock:
                return model not in self._no_tools
        # Reasoning is shown when the server sends it, but there is no
        # portable switch for it, so "thinking" is never requested.
        return False

    # -------------------------------------------------------------- chat

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        think: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_to_openai(m) for m in messages],
            "stream": True,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
        started = time.monotonic()
        try:
            resp = self._post(payload)
        except HTTPError as e:
            if not tools or not 400 <= e.code < 500:
                yield {"type": "error", "error": f"{self.host}: {_http_error_text(e)}"}
                return
            payload.pop("tools")
            try:
                resp = self._post(payload)
            except HTTPError as e2:
                yield {"type": "error", "error": f"{self.host}: {_http_error_text(e2)}"}
                return
            except (URLError, OSError) as e2:
                yield {"type": "error", "error": f"Cannot reach {self.host} ({e2})"}
                return
            with self._lock:
                self._no_tools.add(str(model))
        except (URLError, OSError) as e:
            yield {"type": "error", "error": f"Cannot reach {self.host} ({e})"}
            return

        calls: dict[int, dict[str, str]] = {}
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if obj.get("error"):
                    err = obj["error"]
                    yield {"type": "error",
                           "error": str(err.get("message") if isinstance(err, dict) else err)}
                    return
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield {"type": "think_delta", "content": reasoning}
                    if delta.get("content"):
                        yield {"type": "delta", "content": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(int(tc.get("index") or 0),
                                                {"id": "", "name": "", "args": ""})
                        fn = tc.get("function") or {}
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        if fn.get("name") and not slot["name"]:
                            slot["name"] = fn["name"]
                        slot["args"] += fn.get("arguments") or ""
        except (OSError, http.client.HTTPException) as e:
            yield {"type": "error", "error": f"Lost connection to {self.host} mid-reply ({e})"}
            return
        finally:
            resp.close()

        if calls:
            yield {"type": "tool_calls", "calls": [
                {"id": s["id"] or f"call_{i}",
                 "function": {"name": s["name"], "arguments": _loads_obj(s["args"])}}
                for i, s in sorted(calls.items())
            ]}
        yield {"type": "done", "duration_ms": int((time.monotonic() - started) * 1000)}

    def _post(self, payload: dict[str, Any]):
        req = urlrequest.Request(
            self.host + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={**self._headers(), "Accept": "text/event-stream"},
            method="POST",
        )
        return urlrequest.urlopen(req, timeout=None)


# --------------------------------------------------------------------------
# Message translation
# --------------------------------------------------------------------------

_MAGIC = [
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"BM", "image/bmp"),
]


def _image_mime(b64: str) -> str:
    head = base64.b64decode(b64[:24] + "=" * (-len(b64[:24]) % 4), validate=False)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    return "image/png"


def _to_openai(m: dict[str, Any]) -> dict[str, Any]:
    role = m.get("role")
    if role == "tool":
        return {"role": "tool", "tool_call_id": m.get("tool_call_id", ""),
                "content": m.get("content") or ""}
    out: dict[str, Any] = {"role": role, "content": m.get("content") or ""}
    if m.get("images"):
        out["content"] = [{"type": "text", "text": out["content"]}] + [
            {"type": "image_url", "image_url": {"url": f"data:{_image_mime(b)};base64,{b}"}}
            for b in m["images"]
        ]
    if m.get("tool_calls"):
        out["tool_calls"] = [
            {
                "id": c.get("id", ""),
                "type": "function",
                "function": {
                    "name": (c.get("function") or {}).get("name", ""),
                    "arguments": json.dumps((c.get("function") or {}).get("arguments") or {}),
                },
            }
            for c in m["tool_calls"]
        ]
    return out


def _loads_obj(raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _http_error_text(e: HTTPError) -> str:
    try:
        body = json.loads(e.read())
        err = body.get("error") or body.get("message") or body.get("detail")
        if isinstance(err, dict):
            err = err.get("message")
        return str(err or f"HTTP {e.code} {e.reason}")
    except Exception:  # noqa: BLE001
        return f"HTTP {e.code} {e.reason}"

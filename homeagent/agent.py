"""One assistant turn: system prompt + the model <-> tools loop.

:meth:`Agent.run` streams events to the HTTP layer. On top of the
:mod:`homeagent.ollama` events (``think_delta`` / ``delta`` / ``error``) it
emits:

    {"type": "tool", "name": str, "arguments": dict}  — a tool is being run
    {"type": "tool_result", "name": str, "ok": bool}  — it finished
    {"type": "done", "duration_ms": int}              — the whole turn ended

The loop: ask the model; if it answers with ``tool_calls``, run each tool,
append the results as ``role: tool`` messages and ask again — until the
model replies without tool calls (or ``MAX_TOOL_ROUNDS`` is reached, after
which tools are withheld so it must answer).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Generator

from .tools import ToolRegistry

MAX_TOOL_ROUNDS = 5


class Agent:
    def __init__(self, tools: ToolRegistry, *,
                 tools_enabled: bool, thinking: bool, default_location: str) -> None:
        self.tools = tools
        self.tools_enabled = tools_enabled
        self.thinking = thinking
        self.default_location = default_location

    def system_prompt(self, use_tools: bool) -> str:
        now = datetime.now().astimezone()
        lines = [
            "You are Home Agent, a helpful assistant running locally on the user's "
            "own hardware.",
            f"Current date and time: {now:%A %d %B %Y, %H:%M %Z}.",
            f"The user's default location is {self.default_location}.",
        ]
        if use_tools:
            names = self.tools.names
            lines.append(
                f"You can call these tools: {', '.join(names)}. Home Agent runs them "
                "for you with full internet access. Use them whenever a question needs "
                "live or recent information instead of guessing or relying on training data."
            )
            if "web_search" in names:
                lines.append("When you use web_search results, cite the source URLs.")
            else:
                lines.append(
                    "Web search is not configured (it needs BRAVE_API_KEY in prod.env); "
                    "if asked for current information beyond the weather, say so."
                )
        else:
            lines.append(
                "You have no tools or internet access in this chat. If asked for live "
                "information, say plainly that this model has no tool access here — "
                "do not invent a reason such as network blocking."
            )
        return "\n".join(lines)

    def run(self, client: Any, history: list[dict[str, Any]],
            model: str) -> Generator[dict[str, Any], None, None]:
        """Stream one turn. ``client`` is the provider's client (Ollama or
        OpenAI-compatible — same interface)."""
        think = self.thinking and client.supports(model, "thinking")
        use_tools = (self.tools_enabled and bool(self.tools)
                     and client.supports(model, "tools"))
        messages = [{"role": "system", "content": self.system_prompt(use_tools)}, *history]

        total_ms = 0
        wrote_text = False
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            specs = self.tools.specs() if use_tools and round_no < MAX_TOOL_ROUNDS else None
            content: list[str] = []
            thinking: list[str] = []
            calls: list[dict[str, Any]] = []
            for ev in client.stream_chat(messages, model, think=think, tools=specs):
                kind = ev["type"]
                if kind == "error":
                    yield ev
                    return
                if kind == "done":
                    total_ms += ev["duration_ms"]
                    break
                if kind == "tool_calls":
                    calls = ev["calls"]
                    continue
                if kind == "delta":
                    if not content and wrote_text:
                        ev = {"type": "delta", "content": "\n\n" + ev["content"]}
                    content.append(ev["content"])
                    wrote_text = True
                elif kind == "think_delta":
                    thinking.append(ev["content"])
                yield ev

            if not calls:
                yield {"type": "done", "duration_ms": total_ms}
                return

            # OpenAI-style servers pair each result with its call by id.
            calls = [{**c, "id": c.get("id") or f"call_{round_no}_{i}"}
                     for i, c in enumerate(calls)]
            assistant: dict[str, Any] = {"role": "assistant", "content": "".join(content),
                                         "tool_calls": calls}
            if thinking:
                assistant["thinking"] = "".join(thinking)
            messages.append(assistant)
            for call in calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                args = _parse_args(fn.get("arguments"))
                yield {"type": "tool", "name": name, "arguments": args}
                result = self.tools.call(name, args)
                yield {"type": "tool_result", "name": name, "ok": not _is_error(result)}
                messages.append({"role": "tool", "tool_name": name,
                                 "tool_call_id": call["id"], "content": result})

        yield {"type": "done", "duration_ms": total_ms}


def _parse_args(raw: Any) -> dict[str, Any]:
    """Ollama sends a dict; some models emit a JSON string instead."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _is_error(result: str) -> bool:
    try:
        return isinstance(obj := json.loads(result), dict) and "error" in obj
    except ValueError:
        return False

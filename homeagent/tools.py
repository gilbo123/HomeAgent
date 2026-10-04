"""Tools the model can call through Ollama's native tool-calling (stdlib only).

Each :class:`Tool` pairs a JSON-schema description (sent to Ollama in the
``tools`` field) with a Python function that runs it. Tool functions take
the model's argument dict and return a string — usually compact JSON — that
goes back to the model as a ``role: tool`` message.

Tools never raise into the chat loop: :meth:`ToolRegistry.call` turns any
failure into an ``{"error": ...}`` result so the model can explain it.

Providers:
    * weather    — Open-Meteo (https://open-meteo.com), free, no API key
    * web search — Brave Search API (https://brave.com/search/api/), free
                   tier, needs ``BRAVE_API_KEY``; the tool is only offered
                   when a key is configured
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from . import __version__

_UA = f"HomeAgent/{__version__}"
_TIMEOUT = 12  # seconds per outbound request


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any]], str]

    def spec(self) -> dict[str, Any]:
        """The Ollama/OpenAI-style ``{"type": "function", ...}`` declaration."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def __bool__(self) -> bool:
        return bool(self._tools)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def call(self, name: str, args: dict[str, Any] | None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool {name!r}"})
        try:
            return tool.run(args if isinstance(args, dict) else {})
        except HTTPError as e:
            detail = e.read(500).decode("utf-8", "replace").strip()
            return json.dumps({"error": f"{name}: HTTP {e.code} {e.reason} {detail}".strip()})
        except (URLError, OSError) as e:
            return json.dumps({"error": f"{name}: network error ({e})"})
        except Exception as e:  # noqa: BLE001 — a tool bug must not kill the chat
            return json.dumps({"error": f"{name}: {e}"})


def build_tools(default_location: str, brave_api_key: str) -> ToolRegistry:
    """Assemble the tools that are usable with the given configuration."""
    tools = [_weather_tool(default_location)]
    if brave_api_key:
        tools.append(_web_search_tool(brave_api_key))
    return ToolRegistry(tools)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _get_json(url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    req = urlrequest.Request(
        url + "?" + urlencode(params),
        headers={"User-Agent": _UA, "Accept": "application/json", **(headers or {})},
    )
    with urlrequest.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read())


# --------------------------------------------------------------------------
# Weather (Open-Meteo)
# --------------------------------------------------------------------------

# WMO weather interpretation codes, as used by Open-Meteo.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "light snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with hail",
}


def _geocode(location: str) -> dict[str, Any] | None:
    """Resolve "Town, State, Country" to the best Open-Meteo geocoding hit.

    The geocoder only matches the place name, so the extra comma-separated
    parts are used to pick among same-named places (Brisbane AU vs Brisbane CA).
    """
    name, *qualifiers = [p.strip() for p in location.split(",") if p.strip()]
    data = _get_json("https://geocoding-api.open-meteo.com/v1/search",
                     {"name": name, "count": 10, "language": "en", "format": "json"})
    results = data.get("results") or []
    if not results:
        return None
    wanted = [q.lower() for q in qualifiers]

    def score(r: dict[str, Any]) -> int:
        fields = " ".join(str(r.get(k, "")) for k in
                          ("admin1", "admin2", "country", "country_code")).lower()
        return sum(q in fields for q in wanted)

    return max(results, key=score)  # max() keeps the first (most populous) on ties


def _weather(default_location: str, args: dict[str, Any]) -> str:
    location = str(args.get("location") or "").strip() or default_location
    try:
        days = max(1, min(int(args.get("days") or 3), 7))
    except (TypeError, ValueError):
        days = 3
    place = _geocode(location)
    if place is None:
        return json.dumps({"error": f"could not find a place called {location!r}"})

    data = _get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": "auto",
        "forecast_days": days,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "precipitation,weather_code,wind_speed_10m,wind_direction_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,precipitation_sum,uv_index_max",
    })
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    forecast = [
        {
            "date": date,
            "conditions": _WMO.get(daily["weather_code"][i], "unknown"),
            "max_c": daily["temperature_2m_max"][i],
            "min_c": daily["temperature_2m_min"][i],
            "rain_chance_pct": daily["precipitation_probability_max"][i],
            "rain_mm": daily["precipitation_sum"][i],
            "uv_index_max": daily["uv_index_max"][i],
        }
        for i, date in enumerate(daily.get("time") or [])
    ]
    return json.dumps({
        "location": ", ".join(str(place[k]) for k in ("name", "admin1", "country") if place.get(k)),
        "timezone": data.get("timezone"),
        "current": {
            "time": cur.get("time"),
            "conditions": _WMO.get(cur.get("weather_code"), "unknown"),
            "temperature_c": cur.get("temperature_2m"),
            "feels_like_c": cur.get("apparent_temperature"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "precipitation_mm": cur.get("precipitation"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "wind_direction_deg": cur.get("wind_direction_10m"),
        },
        "forecast": forecast,
        "source": "Open-Meteo",
    })


def _weather_tool(default_location: str) -> Tool:
    return Tool(
        name="get_weather",
        description=(
            "Get current weather conditions and a daily forecast for a place. "
            f"If the user does not name a place, omit `location` to use {default_location}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Place name, optionally with state/country, "
                                   "e.g. 'Sydney, Australia'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of forecast days starting with today, 1-7 "
                                   "(default 3). Tomorrow needs at least 2.",
                },
            },
        },
        run=lambda args: _weather(default_location, args),
    )


# --------------------------------------------------------------------------
# Web search (Brave Search API)
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(s: str) -> str:
    """Brave returns titles/snippets as HTML fragments (<strong>, &#x27;)."""
    return html.unescape(_TAG_RE.sub("", s or ""))


def _web_search(api_key: str, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "missing search query"})
    try:
        count = max(1, min(int(args.get("count") or 5), 10))
    except (TypeError, ValueError):
        count = 5
    data = _get_json("https://api.search.brave.com/res/v1/web/search",
                     {"q": query, "count": count},
                     headers={"X-Subscription-Token": api_key})
    results = [
        {
            "title": _plain(r.get("title", "")),
            "url": r.get("url"),
            "snippet": _plain(r.get("description", "")),
            **({"age": r["age"]} if r.get("age") else {}),
        }
        for r in (data.get("web") or {}).get("results", [])[:count]
    ]
    return json.dumps({"query": query, "results": results, "source": "Brave Search"})


def _web_search_tool(api_key: str) -> Tool:
    return Tool(
        name="web_search",
        description=(
            "Search the web for current information: news, recent events, prices, "
            "opening hours, facts that may have changed after your training data. "
            "Returns titles, URLs and snippets."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "count": {"type": "integer", "description": "Number of results, 1-10 (default 5)."},
            },
            "required": ["query"],
        },
        run=lambda args: _web_search(api_key, args),
    )

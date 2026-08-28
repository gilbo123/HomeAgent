"""Configuration for Home Agent.

Everything is read from a single TOML file (``homeagent.toml``).
**No environment variables are used anywhere** — if you need to change
a setting, edit the file and restart.

Relative paths in the config file are resolved relative to the
directory containing the config file (i.e. the project root), so the
app behaves the same no matter where it is launched from.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from typing import Any


class ConfigError(ValueError):
    """Raised when the config file is missing or contains invalid values."""


# --------------------------------------------------------------------------
# Defaults — any key may be omitted from homeagent.toml and these apply.
# --------------------------------------------------------------------------
DEFAULTS: dict[str, dict[str, Any]] = {
    "server": {
        "host": "192.168..1.200",        # interface to bind
        "port": 8321,               # TCP port
        "open_browser": True,       # auto-open the UI on startup
    },
    "ollama": {
        "host": "http://127.0.0.1:11434",  # base URL of the Ollama server
        "model": "qwen3.8:27b",            # default model for new chats
        "temperature": 0.7,                # sampling temperature
        "history_limit": 100,              # max messages sent back as context
    },
    "storage": {
        "mongo_uri": "mongodb://127.0.0.1:27017/",  # MongoDB connection string
        "mongo_db": "homeagent",                  # database name for chats/messages
        "upload_dir": "/tmp/homeagent/uploads",   # directory for uploaded images (ephemeral)
        "max_image_mb": 20,                       # per-upload size cap
    },
    "ui": {
        "static_dir": "homeagent/static",  # bundled web UI (index.html, css, js)
    },
}


@dataclass(frozen=True)
class Config:
    """Validated, immutable runtime configuration."""

    host: str
    port: int
    open_browser: bool

    ollama_host: str
    default_model: str
    temperature: float
    history_limit: int


    static_dir: str
    mongo_uri: str
    mongo_db: str
    upload_dir: str
    max_image_mb: int


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` onto ``base`` (both plain dicts)."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _require(section: dict, name: str, converter,
             expected: type | tuple[type, ...], ctx: str):
    """Pull a key out of a section, convert and sanity-check it."""
    if name not in section:
        raise ConfigError(f"missing required key: {ctx}.{name}")
    value = section[name]
    if not isinstance(value, expected):
        types = expected if isinstance(expected, tuple) else (expected,)
        want = " or ".join(t.__name__ for t in types)
        raise ConfigError(
            f"{ctx}.{name} must be a {want}, got {type(value).__name__}"
        )
    return converter(value)


def _resolve(path: str, base_dir: str) -> str:
    """Resolve a possibly-relative path against the config file's directory."""
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))


def load_config(path: str) -> Config:
    """Load and validate ``homeagent.toml`` at ``path``.

    Raises:
        ConfigError: file missing, unreadable, or contains invalid values.
    """
    if not os.path.isfile(path):
        raise ConfigError(f"config file not found: {path}")
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e

    cfg = _deep_merge(DEFAULTS, raw)
    base_dir = os.path.dirname(os.path.abspath(path))

    host = _require(cfg["server"], "host", str, str, "server")
    port = _require(cfg["server"], "port", int, int, "server")
    if not (1 <= port <= 65535):
        raise ConfigError(f"server.port out of range: {port}")
    open_browser = _require(cfg["server"], "open_browser", bool, bool, "server")

    ollama_host = _require(cfg["ollama"], "host", str, str, "ollama")
    if not ollama_host.startswith(("http://", "https://")):
        ollama_host = "http://" + ollama_host  # be forgiving: "host:11434" is OK
    model = _require(cfg["ollama"], "model", str, str, "ollama")
    if not model.strip():
        raise ConfigError("ollama.model must not be empty")
    temperature = _require(cfg["ollama"], "temperature", float, (int, float), "ollama")
    if not (0.0 <= float(temperature) <= 2.0):
        raise ConfigError(f"ollama.temperature out of range: {temperature}")
    history_limit = _require(cfg["ollama"], "history_limit", int, int, "ollama")
    if history_limit < 2:
        raise ConfigError(f"ollama.history_limit must be >= 2, got {history_limit}")

    mongo_uri = _require(cfg["storage"], "mongo_uri", str, str, "storage")
    if not mongo_uri.strip():
        raise ConfigError("storage.mongo_uri must not be empty")
    mongo_db = _require(cfg["storage"], "mongo_db", str, str, "storage")
    if not mongo_db.strip():
        raise ConfigError("storage.mongo_db must not be empty")
    upload_dir = _require(cfg["storage"], "upload_dir", str, str, "storage")
    max_image_mb = _require(cfg["storage"], "max_image_mb", int, int, "storage")
    if max_image_mb < 1:
        raise ConfigError(f"storage.max_image_mb must be >= 1, got {max_image_mb}")
    static_dir = _require(cfg["ui"], "static_dir", str, str, "ui")


    return Config(
        host=host,
        port=port,
        open_browser=open_browser,
        ollama_host=ollama_host.rstrip("/"),
        default_model=model.strip(),
        temperature=float(temperature),
        history_limit=history_limit,
        mongo_uri=mongo_uri.strip().rstrip("/") + "/",
        mongo_db=mongo_db.strip(),
        static_dir=_resolve(static_dir, base_dir),
        upload_dir=_resolve(upload_dir, base_dir),
        max_image_mb=max_image_mb,
    )

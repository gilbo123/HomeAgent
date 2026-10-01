"""Configuration for Home Agent — this file is the ONE place settings live.

Values are resolved at import time from (highest priority first):

1. real process environment variables,
2. ``prod.env`` in the project root  (untracked — holds *secrets*),
3. ``.env`` in the project root      (tracked — example/default template).

Neither env file needs to exist: safe defaults apply (SMTP disabled, local
MongoDB). To change a value, set it in ``prod.env`` (or export it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration — all values are defined in CONFIG below."""

    # server
    host: str
    port: int
    open_browser: bool

    # ollama
    ollama_host: str
    default_model: str
    temperature: float
    history_limit: int
    thinking: bool

    # storage
    static_dir: str
    mongo_uri: str
    mongo_db: str
    upload_dir: str
    max_image_mb: int

    # email  (host = "" disables sending; the verification code then shows on-screen)
    email_host: str
    email_port: int
    email_username: str
    email_password: str
    email_from: str
    email_use_tls: bool


_HERE = os.path.abspath(os.path.dirname(__file__))          # .../homeagent
_ROOT = os.path.dirname(_HERE)                               # project root


def _load_env_file(path: str) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` env file. Missing file / bad lines are ignored."""
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if not key:
                    continue
                # Allow `KEY=VALUE`, `KEY="VALUE"`, `KEY='VALUE'`, `export KEY=VALUE`
                value = value.strip()
                if value[:1] not in ('"', "'"):
                    # unquoted: strip inline comment  (KEY=8321  # listen port)
                    hash_pos = value.find(" #")
                    if hash_pos != -1:
                        value = value[:hash_pos].rstrip()
                elif value[-1:] == value[:1] and len(value) >= 2:
                    value = value[1:-1]
                values[key] = value
    except FileNotFoundError:
        pass
    return values


def _install_env_files() -> None:
    """Merge env files into os.environ.

    ``prod.env`` is loaded first (untracked, holds real values) and then
    ``.env`` (tracked template) only fills keys ``prod.env`` left unset.
    ``setdefault`` keeps real environment variables winning over both.
    """
    for name in ("prod.env", ".env"):
        for key, value in _load_env_file(os.path.join(_ROOT, name)).items():
            os.environ.setdefault(key, value)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


_install_env_files()

CONFIG: Config = Config(
    # -- server -------------------------------------------------------------
    host=_env("HOST", "0.0.0.0"),                # bind address; 127.0.0.1 for localhost-only
    port=int(_env("PORT", "8321")),              # listen port
    open_browser=_env_bool("OPEN_BROWSER", False),  # auto-open the UI on startup

    # -- ollama -------------------------------------------------------------
    ollama_host=_env("OLLAMA_HOST", "http://127.0.0.1:11434"),  # base URL of the Ollama server
    default_model=_env("DEFAULT_MODEL", "qwen3.8:27b"),         # default model for new chats
    temperature=float(_env("TEMPERATURE", "0.7")),              # sampling temperature
    history_limit=int(_env("HISTORY_LIMIT", "60")),             # max context turns
    thinking=_env_bool("THINKING", True),                       # model thinking mode

    # -- storage ------------------------------------------------------------
    static_dir=os.path.join(_HERE, "static"),    # bundled web UI
    mongo_uri=_env("MONGO_URI", "mongodb://127.0.0.1:27017/"),  # connection string (no hardcoded creds)
    mongo_db=_env("MONGO_DB", "homeagent"),      # db name for chats/sessions/users
    upload_dir=_env("UPLOAD_DIR", "/tmp/homeagent/uploads"),     # upload images
    max_image_mb=int(_env("MAX_IMAGE_MB", "20")),                # per-image upload cap

    # -- email (credentials come from prod.env, never from code) ------------
    email_host=_env("EMAIL_HOST", ""),           # "" = disable (on-screen fallback)
    email_port=int(_env("EMAIL_PORT", "587")),   # 587 = STARTTLS, 465 = implicit TLS
    email_username=_env("EMAIL_USERNAME", ""),
    email_password=_env("EMAIL_PASSWORD", ""),
    email_from=_env("EMAIL_FROM", ""),
    email_use_tls=_env_bool("EMAIL_USE_TLS", True),
)


def load_config(path: str | None = None) -> Config:
    """Backwards-compat shim. ``path`` is ignored — CONFIG is the only source.

    Kept because ``main.py`` calls this to preserve the CLI surface.
    """
    return CONFIG

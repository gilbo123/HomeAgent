"""Configuration for Home Agent — this file is the ONE place settings live.

Edit the values below, restart the app. There is no other config file,
no env vars, no TOML. If you want a different value, change it here.
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


# ============================================================================
# THE CONFIG — edit these values, that's it.
# ============================================================================
_HERE = os.path.abspath(os.path.dirname(__file__))          # .../homeagent
_ROOT = os.path.dirname(_HERE)                               # project root

CONFIG: Config = Config(
    # -- server -------------------------------------------------------------
    host="0.0.0.0",                              # bind address; 127.0.0.1 for localhost-only
    port=8321,                                   # listen port
    open_browser=False,                          # auto-open the UI on startup

    # -- ollama -------------------------------------------------------------
    ollama_host="http://192.168.1.200:11434",    # base URL of the Ollama server
    default_model="qwen3.8:27b",                 # default model for new chats
    temperature=0.7,                             # sampling temperature
    history_limit=60,                            # max turns of context sent to the model
    thinking=True,                               # enable thinking mode when the model supports it

    # -- storage ------------------------------------------------------------
    static_dir=os.path.join(_HERE, "static"),    # bundled web UI
    mongo_uri="mongodb://127.0.0.1:27017/",      # MongoDB connection string
    mongo_db="homeagent",                        # db name for chats/sessions/users
    upload_dir="/tmp/homeagent/uploads",         # where uploaded images are stored
    max_image_mb=20,                             # per-image upload cap

    # -- email (single source; no toml) -------------------------------------
    email_host="smtp.gmail.com",                 # "" = disable (on-screen fallback)
    email_port=587,                              # 587 = STARTTLS, 465 = implicit TLS
    email_username="homestack04@gmail.com",
    email_password="qwvjiuqaeagjgmwe",
    email_from="homestack04@gmail.com",
    email_use_tls=True,
)


def load_config(path: str | None = None) -> Config:
    """Backwards-compat shim. ``path`` is ignored — CONFIG is the only source.

    Kept because ``main.py`` calls this to preserve the CLI surface.
    """
    return CONFIG

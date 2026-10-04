"""Composition root for the HomeAgent web app.

This is the ONLY module that wires everything together (dependency
injection):

    Config -> ChatDatabase + UserStore + UploadStore
           -> OllamaClient + OpenAI-compatible clients -> ProviderRegistry
           -> ToolRegistry -> Agent
           -> App -> Handler factory -> ThreadingHTTPServer

Nothing else in the package knows about the others' construction —
each collaborator receives exactly the dependencies it needs.

Configuration is read by homeagent/config.py from env files: the tracked
.env template plus the untracked prod.env secrets file (real environment
variables override both). See the README "Configuration" section.

Run directly:  ``python -m homeagent.main``
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from http.server import ThreadingHTTPServer

from . import __version__
from .accounts import EmailSettings, UserStore
from .agent import Agent
from .app import App
from .config import CONFIG, Config
from .db import ChatDatabase
from .ollama import OllamaClient
from .providers import build_providers
from .server import make_handler
from .tools import build_tools
from .uploads import UploadStore

log = logging.getLogger("homeagent.main")


def build_app(config: Config) -> App:
    """Wire the collaborator graph from a :class:`Config`.

    Kept as a standalone function so tests can build the full graph
    against a temporary config without importing :mod:`main`.
    """
    db = ChatDatabase(
        mongo_uri=config.mongo_uri,
        db_name=config.mongo_db,
        history_limit=config.history_limit,
        upload_dir=config.upload_dir,
    )
    # Email settings for the optional set/reset flow (the verification code
    # is delivered by email rather than a link).
    email = EmailSettings(
        host=config.email_host,
        port=config.email_port,
        username=config.email_username,
        password=config.email_password,
        from_addr=config.email_from,
        use_tls=config.email_use_tls,
    )
    users = UserStore(
        mongo_uri=config.mongo_uri,
        db_name=config.mongo_db,
        email=email,
    )
    ollama = OllamaClient(
        host=config.ollama_host,
        default_model=config.default_model,
        temperature=config.temperature,
    )
    providers = build_providers(
        ollama,
        [
            ("strata", "Strata", config.strata_url, config.strata_api_key),
            ("vllm", "vLLM", config.vllm_url, config.vllm_api_key),
            ("lmstudio", "LM Studio", config.lmstudio_url, config.lmstudio_api_key),
        ],
        temperature=config.temperature,
        default_id=config.default_provider,
    )
    agent = Agent(
        build_tools(config.default_location, config.brave_api_key),
        tools_enabled=config.tools_enabled,
        thinking=config.thinking,
        default_location=config.default_location,
    )
    uploads = UploadStore(
        upload_dir=str(config.upload_dir),
        max_image_mb=config.max_image_mb,
    )
    return App(
        cfg=config,
        db=db,
        providers=providers,
        agent=agent,
        uploads=uploads,
        users=users,
        static_dir=config.static_dir,
    )


def create_server(app: App) -> ThreadingHTTPServer:
    """Bind the request-handler factory to the app and create the server.

    ``ThreadingHTTPServer`` handles each request in its own thread;
    the shared collaborators (MongoDB client with its own connection
    pool, file stores, urllib client) are all safe for this usage.
    """
    return ThreadingHTTPServer(
        (app.cfg.host, app.cfg.port), make_handler(app),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code.

    The argparse block is kept so ``--help`` still works, but there is
    nothing to point at — CONFIG in homeagent/config.py is the source.
    """
    parser = argparse.ArgumentParser(prog="homeagent", description=__doc__)
    # Intentionally no --config flag: settings come from .env / prod.env.
    parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = CONFIG

    try:
        app = build_app(config)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    server = create_server(app)

    browser_host = "127.0.0.1" if config.host in ("0.0.0.0", "::") else config.host
    url = f"http://{browser_host}:{config.port}"
    print(f"HomeAgent v{__version__}")
    print(f"  listening on : {url}")
    for p in app.providers.public():
        mark = "  (default)" if p["id"] == app.providers.default_id else ""
        print(f"  {p['label'].lower():<13}: {p['url']}{mark}")
    print(f"  model        : {config.default_model}")
    print(f"  database     : {config.mongo_uri}{config.mongo_db}")
    print(f"  uploads      : {config.upload_dir}")
    tools = app.agent.tools.names if config.tools_enabled else []
    print(f"  tools        : {', '.join(tools) or 'off'}"
          + ("" if config.brave_api_key or not config.tools_enabled
             else "  (web_search off: set BRAVE_API_KEY)"))
    print(f"  press Ctrl+C to stop")

    if config.open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down…")
    finally:
        server.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Composition root for the HomeAgent web app.

This is the ONLY module that wires everything together (dependency
injection):

    Config -> ChatDatabase + OllamaClient + UploadStore -> App
                                                        -> Handler factory
                                                        -> ThreadingHTTPServer

Nothing else in the package knows about the others' construction —
each collaborator receives exactly the dependencies it needs.

Run directly:  ``python -m homeagent.main --config homeagent.toml``
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from http.server import ThreadingHTTPServer
from . import __version__
from .app import App
from .config import Config, ConfigError, load_config
from .db import ChatDatabase
from .ollama import OllamaClient
from .server import make_handler
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
    ollama = OllamaClient(
        host=config.ollama_host,
        default_model=config.default_model,
        temperature=config.temperature,
    )
    uploads = UploadStore(
        upload_dir=str(config.upload_dir),
        max_image_mb=config.max_image_mb,
    )
    return App(
        cfg=config,
        db=db,
        ollama=ollama,
        uploads=uploads,
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
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="homeagent", description=__doc__)
    parser.add_argument(
        "-c", "--config",
        default="homeagent.toml",
        help="Path to the TOML config file (default: ./homeagent.toml)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

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
    print(f"  ollama       : {config.ollama_host}")
    print(f"  model        : {config.default_model}")
    print(f"  database     : {config.mongo_uri}{config.mongo_db}")
    print(f"  uploads      : {config.upload_dir}")
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

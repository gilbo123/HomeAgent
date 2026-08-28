"""Home Agent — a local web chat UI for Ollama models.

Package layout:
    config.py   configuration loading (homeagent.toml, no env vars)
    db.py       MongoDB (pymongo) chat/message persistence (ChatDatabase)
    ollama.py   Ollama HTTP client (OllamaClient)
    uploads.py  image upload store (UploadStore)
    server.py   HTTP app + routing (App)
    main.py     entrypoint — wires the pieces together (dependency injection)
"""

__version__ = "2.0"

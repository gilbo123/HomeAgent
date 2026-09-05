"""Home Agent — a local web chat UI for Ollama models.

Package layout:
    config.py   single CONFIG constant (the one place settings live)
    accounts.py users, sessions, password activation, optional SMTP (UserStore)
    db.py       MongoDB (pymongo) chat/message persistence (ChatDatabase)
    ollama.py   Ollama HTTP client (OllamaClient)
    uploads.py  image upload store (UploadStore)
    server.py   HTTP app + routing (App)
    main.py     entrypoint — wires the pieces together (dependency injection)
"""

__version__ = "2.1"

"""Home Agent — a local web chat UI for Ollama models.

Package layout:
    config.py   single CONFIG constant (the one place settings live)
    accounts.py users, sessions, password activation, optional SMTP (UserStore)
    db.py       MongoDB (pymongo) chat/message persistence (ChatDatabase)
    ollama.py   Ollama HTTP client (OllamaClient)
    openai_compat.py  OpenAI-compatible client: Strata, vLLM, LM Studio
    providers.py      the selectable model providers (ProviderRegistry)
    agent.py    one assistant turn: system prompt + tool loop (Agent)
    tools.py    tools the model can call: weather, web search (ToolRegistry)
    uploads.py  image upload store (UploadStore)
    app.py      the DI facade handed to every request (App)
    server.py   HTTP handler factory + routing
    main.py     entrypoint — wires the pieces together (dependency injection)
"""

__version__ = "2.2"

# 🏠 Home Agent

A self-hosted web chat UI for [Ollama](https://ollama.com) models running on
your own machine. Talk to `qwen3.8:27b` (or any model you've pulled) through a
professional single-page interface — no cloud, no accounts, zero pip installs.

![stack](https://img.shields.io/badge/python-stdlib%20only-5b8cff)
![db](https://img.shields.io/badge/storage-mongodb-7aa2ff)
![arch](https://img.shields.io/badge/architecture-modular%20%2B%20DI-9b59ff)

## Features

- **Professional dark UI** — static header / sidebar / composer; only the chat
  panel scrolls.
- **Streaming responses** with a live **response timer** (seconds + ms shown per
  message), and a **stop** button mid-generation.
- **Chat history in MongoDB** — chats persist across restarts, sidebar lists
  every conversation with delete.
- **Image input** — attach or drag-and-drop images; sent to vision-capable
  models (e.g. `qwen3.8` with vision). Stored under `/tmp/homeagent/uploads/`.
- **Any Ollama model** — model picker lists every model `ollama` has pulled;
  `qwen3.8:27b` is the default (configurable).
- **Code rendering** — fenced ``` blocks become syntax-styled panels with a
  copy button; inline `code`, **bold**, *italic*, lists, tables, links.
- **ASCII-table upgrade** — boxed `+---+ | x |` tables in the answer are
  automatically rendered as real HTML tables.
- **Roomy composer** — the input grows up to ~9 lines before scrolling, so long
  prompts aren't clipped.
- **Single script** — `./run.sh` and you're done.
- **Modular, DI-based code** — small single-responsibility modules, a frozen
  `Config` dataclass, and a composition root. **No environment variables** —
  all configuration lives in one TOML file.

## Requirements

- Python 3.11+ (uses `pymongo` — preinstalled in the `chat` virtualenv)
- MongoDB running locally (e.g. `mongod`)
- Ollama running locally with at least one model pulled,
  e.g. `ollama pull qwen3.8:27b`

## Run

```bash
./run.sh
```

The browser (optionally) opens `http://127.0.0.1:8321`. The script checks that
Ollama is reachable and warns if it isn't.

## Configuration

**All** settings live in [`homeagent.toml`](homeagent.toml) — there are *no*
environment variables anywhere. Missing keys fall back to safe defaults.

```toml
[server]
host = "127.0.0.1"            # bind address
port = 8321                   # listen port
open_browser = false          # auto-open the UI on start

[ollama]
host = "http://192.168.1.200:11434"  # Ollama endpoint
model = "qwen3.8:27b"       # default model for new chats
temperature = 0.7           # sampling temperature
history_limit = 60          # max context messages sent to the model per turn

[storage]
mongo_uri  = "mongodb://127.0.0.1:27017/"  # MongoDB connection string
mongo_db   = "homeagent"                   # database name
upload_dir = "/tmp/homeagent/uploads"      # directory for uploaded images
max_image_mb = 20                          # per-image upload size limit (MB)
```

Use a different file with `./run.sh --config /path/to/other.toml`.

## Architecture

```
homeagent/
├── __init__.py    # version + package docstring
├── app.py         # App facade — the DI object handed to every request
├── config.py      # frozen Config dataclass + TOML loader + validation
├── db.py          # ChatDatabase (MongoDB: chats + messages, cascade, history)
├── ollama.py      # OllamaClient (list models, NDJSON chat streaming)
├── server.py      # HTTP handler factory (routes, JSON, NDJSON stream, uploads)
├── uploads.py     # UploadStore (multipart parse, MIME allow-list, storage)
├── main.py        # composition root — wires everything, runs the server
└── index.html     # the entire UI (HTML + CSS + JS, no build step)
```

Each module does one job and receives its dependencies explicitly:
`Config` → `ChatDatabase` / `OllamaClient` / `UploadStore` → `App` → handler
factory. No module-level globals, no hidden coupling.

## Files

| Path                  | Purpose                                    |
|-----------------------|--------------------------------------------|
| `homeagent/`          | The application package (see above)        |
| `homeagent.toml`      | All runtime configuration (the only knob)  |
| `run.sh`              | Launcher with Ollama health check          |
| `~/.virtualenvs/chat` | Python env with `pymongo` (auto-detected)  |
| `/tmp/homeagent/`     | Upload dir + logs (created on first run)   |

## API (if you want to script it)

- `GET  /api/chats` — list chats
- `POST /api/chats` — create chat `{"model": "qwen3.8:27b"}`
- `GET  /api/chats/<id>` — chat + messages
- `DELETE /api/chats/<id>` — delete chat
- `POST /api/chats/<id>/messages` — send message, **NDJSON stream** back:
  `{"type":"delta","content":"…"}` … `{"type":"done","duration_ms":…}`
- `POST /api/upload` — multipart image upload → `{"url":"/uploads/<id>.png"}`
- `GET  /api/models` — models pulled on Ollama + default

## Security notes

- Binds to `127.0.0.1` by default. If you expose it on a LAN
  (`host = "0.0.0.0"` in the TOML), put it behind a reverse proxy with auth —
  the API has none.
- Uploaded images are stored with random UUID filenames; the DB stores only
  filenames, not base64 blobs.

## License

See [LICENSE](LICENSE).

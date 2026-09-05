# 🏠 Home Agent

A self-hosted web chat UI for [Ollama](https://ollama.com) models running on
your own machine. Talk to `qwen3.8:27b` (or any model you've pulled) through a
professional single-page interface — no cloud, zero pip installs.

![stack](https://img.shields.io/badge/python-stdlib%20only-5b8cff)
![db](https://img.shields.io/badge/storage-mongodb-7aa2ff)
![arch](https://img.shields.io/badge/architecture-modular%20%2B%20DI-9b59ff)

## Features

- **User profiles & per-user privacy** — a splash screen where each user picks
  their username tile and enters a password; every chat is scoped to its owner
  so one account never sees another's history (see [Users & privacy](#users--privacy)).
- **New-chat-by-default** — each session opens on a blank chat; your history is
  in the sidebar and loads only when you click a conversation.
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
  all configuration lives in a single Python module (`homeagent/config.py`).

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

**All** settings live in a single Python module —
[`homeagent/config.py`](homeagent/config.py) — and there are *no* environment
variables anywhere. Change a value there and restart; done. There is no
second file and no env-var fallback to keep in sync with.

```python
# homeagent/config.py
CONFIG = Config(
    host="0.0.0.0",                          # bind address
    port=8321,                               # listen port
    open_browser=False,                      # auto-open the UI on start

    ollama_host="http://192.168.1.200:11434",# Ollama endpoint
    default_model="qwen3.8:27b",             # default model for new chats
    temperature=0.7,                         # sampling temperature
    history_limit=60,                        # context messages per turn

    mongo_uri="mongodb://127.0.0.1:27017/",  # MongoDB connection string
    mongo_db="homeagent",                    # database name
    upload_dir="/tmp/homeagent/uploads",     # directory for uploaded images
    max_image_mb=20,                         # per-image upload size limit (MB)

    # Optional SMTP for password set/reset activation links. When
    # email_username is empty sending is disabled and the link is shown
    # on-screen (still works end-to-end).
    email_host="smtp.gmail.com",
    email_port=587,
    email_username="you@gmail.com",          # e.g. an app-specific Gmail
    email_password="app-password…",       # e.g. a Gmail App Password
    email_from="you@gmail.com",              # default: email_username
    email_use_tls=True,                      # 587→STARTTLS, 465→SMTP_SSL
)
```

> The app's own config is a Python constant, not a file you parse. Edit it
> and `./run.sh` picks it up on the next start.

## Architecture

```
homeagent/
├── __init__.py    # version + package docstring
├── app.py         # App facade — the DI object handed to every request
├── accounts.py    # UserStore (profiles, sessions, activation, optional SMTP)
├── config.py      # frozen Config dataclass + CONFIG constant (one file)
├── db.py          # ChatDatabase (MongoDB: per-owner chats + messages)
├── ollama.py      # OllamaClient (list models, NDJSON chat streaming)
├── server.py      # HTTP handler factory (auth + data routes, streams, uploads)
├── uploads.py     # UploadStore (multipart parse, MIME allow-list, storage)
├── main.py        # composition root — wires everything, runs the server
└── static/        # the UI (index.html, style.css, app.js; no build step)
```

Each module does one job and receives its dependencies explicitly:
`Config` → `ChatDatabase` / `UserStore` / `OllamaClient` / `UploadStore` →
`App` → handler factory. No module-level globals, no hidden coupling.

## Files

| Path                  | Purpose                                    |
|-----------------------|--------------------------------------------|
| `homeagent/`          | The application package (see above)        |
| `homeagent/static/`   | The web UI: `index.html`, `style.css`, `app.js` |
| `homeagent/config.py` | All runtime configuration (the only knob)  |
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

### Auth endpoints (public; the `/api/*` + `/uploads/*` routes require a session)

- `GET  /auth/me` — the signed-in user, or `{"user": null}`
- `GET  /auth/users` — lightweight list of accounts (for the splash tiles)
- `POST /auth/login` — `{"username","password"}` → sets the session cookie
- `POST /auth/logout` — clears the session
- `POST /auth/set-or-reset` — request a set/reset link
  → `{"token","is_new","email_sent","email_note"}`
- `GET  /auth/activate?token=…` — finalize the link, sign in, redirect to `/`

## Users & privacy

- **Splash screen** — the first thing you see is a tile of every username
  with a single password field, plus a "Set or reset password" link.
- **Set / reset is one flow** — four fields (username, email, password,
  confirm). When email is configured, the activation link is sent to the
  inbox *only* (not shown on-screen) so nobody shoulder-surfing can finish
  the reset. The on-screen link appears only as an explicitly-warned
  fallback when email is unconfigured or the send failed — so the flow
  always works, but the private path is the default.
- **Per-user history** — every chat is stored with an `owner`, and every
  `chats`/`messages` query is scoped to the signed-in user. One account can
  never list, read, or delete another's chats.
- **Migration** — the *first* account to activate inherits any chats that
  pre-date auth (they had no owner), so an existing install doesn't lose
  history.

## Security notes

- Passwords are hashed with `hashlib.scrypt` (a memory-hard KDF) plus a
  per-password random salt; plaintext is never stored.
- Sessions are 256-bit random bearer tokens in an `HttpOnly; SameSite=Lax`
  cookie; activation links are one-shot, hour-bounded tokens.
- Uploaded images use unguessable UUID filenames; the DB stores only
  filenames, not base64 blobs. Both `/uploads/*` and all `/api/*` data routes
  require a signed-in session.
- Binds to `0.0.0.0` by default (LAN-reachable). Because the app is
  now authenticated, LAN use is fine; for public exposure, put it behind
  TLS.

## License

See [LICENSE](LICENSE).

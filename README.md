# 🏠 Home Agent

A self-hosted web chat UI for [Ollama](https://ollama.com) models running on
your own machine. Talk to `qwen3.8:27b` (or any model you've pulled) through a
professional single-page interface — no cloud, one dependency (`pymongo`),
managed by [uv](https://docs.astral.sh/uv/).

![stack](https://img.shields.io/badge/python-stdlib%20%2B%20pymongo-5b8cff)
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
- **Tools: live weather + web search** — tool-capable models (Ollama
  `tools` capability, e.g. `qwen3.5` / `qwen3.8`) can call `get_weather`
  (Open-Meteo, no key) and `web_search` (Brave Search API, free key) via
  Ollama's native tool-calling. Each call shows as a line in the reply
  (see [Tools](#tools)).
- **Guest sign-in** — a *Guest* tile on the splash screen: no password, no
  account in the database, always incognito (nothing is saved, no history).
- **Model providers** — a *Provider* dropdown: Ollama plus any
  OpenAI-compatible server — [Strata](https://github.com/Niko1221/Strata)
  (`:8080`), [vLLM](https://docs.vllm.ai) (`:8000`),
  [LM Studio](https://lmstudio.ai) (`:1234`). The model list shows what that
  server offers, and is empty when it's offline. Each chat remembers its
  provider + model; switching mid-chat applies from the next message.
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
  `Config` dataclass, and a composition root.
- **No secrets in code** — credentials live in an untracked `prod.env` file;
  a placeholder template is provided in the tracked `.env`.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`) — it provides
  Python 3.11+ and installs `pymongo` from `uv.lock`
- MongoDB running locally (e.g. `mongod`)
- Ollama running locally with at least one model pulled,
  e.g. `ollama pull qwen3.8:27b`

## Run

```bash
./run.sh
```

The first run creates `.venv/` from `uv.lock` (or run `uv sync` yourself).
The browser (optionally) opens `http://127.0.0.1:8321`. The script checks that
Ollama is reachable and warns if it isn't. Without uv, point it at any
Python 3.11+ that has `pymongo`: `PY=/path/to/python ./run.sh`.

## Configuration

**All** settings are read by [`homeagent/config.py`](homeagent/config.py)
from environment-style files, resolved in this priority order (highest
first):

1. real process environment variables,
2. `prod.env` in the project root — **untracked**, put your *secrets* here,
3. `.env` in the project root — the **tracked** template with safe
   placeholder values.

Neither file is required: without them the app still runs with safe
defaults (SMTP disabled, local MongoDB). The full set of keys:

```ini
# server
HOST=0.0.0.0            # bind address; 127.0.0.1 for localhost-only
PORT=8321               # listen port
OPEN_BROWSER=false      # auto-open the UI on startup

# ollama
OLLAMA_HOST=http://127.0.0.1:11434   # Ollama endpoint
DEFAULT_MODEL=qwen3.8:27b            # default model for new chats
TEMPERATURE=0.7                      # sampling temperature
HISTORY_LIMIT=60                     # context messages per turn
THINKING=true                        # enable thinking mode when supported

# other providers (OpenAI-compatible; empty URL = hidden)
DEFAULT_PROVIDER=ollama              # ollama | strata | vllm | lmstudio
STRATA_URL=http://127.0.0.1:8080/v1
STRATA_API_KEY=                      # only if started with --api-key
VLLM_URL=http://127.0.0.1:8000/v1
VLLM_API_KEY=
LMSTUDIO_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=

# tools
TOOLS_ENABLED=true                   # offer tools to tool-capable models
DEFAULT_LOCATION=Brisbane, Queensland, Australia   # weather default
BRAVE_API_KEY=                       # put in prod.env; "" = no web_search

# storage
MONGO_URI=mongodb://127.0.0.1:27017/ # MongoDB connection string
MONGO_DB=homeagent                   # database name
UPLOAD_DIR=/tmp/homeagent/uploads    # directory for uploaded images
MAX_IMAGE_MB=20                      # per-image upload size limit (MB)

# email — optional SMTP for password set/reset verification codes.
# When EMAIL_HOST is empty, sending is disabled and the code is shown
# on-screen instead (the flow still works end-to-end).
EMAIL_HOST=smtp.gmail.com            # "" = disable
EMAIL_PORT=587                       # 587→STARTTLS, 465→SMTP_SSL
EMAIL_USERNAME=you@gmail.com         # e.g. an app-specific Gmail
EMAIL_PASSWORD=your-gma…word # e.g. a Gmail App Password
EMAIL_FROM=you@gmail.com             # default: EMAIL_USERNAME
EMAIL_USE_TLS=true
```

> **Never commit real credentials.** Copy your secrets into `prod.env`
> (it is git-ignored; the tracked `.env` holds placeholders only), then
> `./run.sh` picks them up on the next start.

## Model providers

Ollama is always available. The OpenAI-compatible providers talk to
`<URL>/models` and `<URL>/chat/completions` (streamed); `host:port` alone
is accepted and gets `http://…/v1` added. The URLs are resolved from the
machine running Home Agent, so `127.0.0.1` means "the server box".

| Provider  | Default URL                 | Notes |
|-----------|-----------------------------|-------|
| Strata    | `http://127.0.0.1:8080/v1`  | any model name works; set `STRATA_API_KEY` if Strata runs with `--api-key` |
| vLLM      | `http://127.0.0.1:8000/v1`  | tools need `--enable-auto-tool-choice --tool-call-parser …`; without them Home Agent retries without tools |
| LM Studio | `http://127.0.0.1:1234/v1`  | start the local server in LM Studio's Developer tab |

Thinking text is shown when the server streams `reasoning_content`;
thinking can only be switched on/off for Ollama models.

## Tools

Models that report the `tools` capability are offered these functions;
Home Agent runs them server-side and feeds the results back until the
model answers (at most 5 tool rounds per turn):

| Tool          | Provider                                   | Key needed |
|---------------|--------------------------------------------|------------|
| `get_weather` | [Open-Meteo](https://open-meteo.com)       | no         |
| `web_search`  | [Brave Search API](https://brave.com/search/api/) | yes, free tier |

To enable web search, create a free Brave Search API key and add it to
`prod.env`:

```ini
BRAVE_API_KEY=your-key-here
```

Every turn also gets a system prompt with the current date/time, the
default location and the available tools, so the model knows what it can
look up. Models without tool support are told they have no internet
access, so they say so instead of inventing a reason.

## Architecture

```
homeagent/
├── __init__.py    # version + package docstring
├── app.py         # App facade — the DI object handed to every request
├── accounts.py    # UserStore (profiles, sessions, activation, optional SMTP)
├── config.py      # frozen Config dataclass — values come from .env / prod.env
├── db.py          # ChatDatabase (MongoDB: per-owner chats + messages)
├── ollama.py      # OllamaClient (models + capabilities, NDJSON chat streaming)
├── openai_compat.py # OpenAICompatClient (Strata / vLLM / LM Studio, SSE streaming)
├── providers.py   # ProviderRegistry (the Provider dropdown's servers)
├── agent.py       # Agent (system prompt + model <-> tools loop for one turn)
├── tools.py       # ToolRegistry + get_weather / web_search
├── server.py      # HTTP handler factory (auth + data routes, streams, uploads)
├── uploads.py     # UploadStore (multipart parse, MIME allow-list, storage)
├── main.py        # composition root — wires everything, runs the server
└── static/        # the UI (index.html, style.css, app.js; no build step)
```

Each module does one job and receives its dependencies explicitly:
`Config` → `ChatDatabase` / `UserStore` / `OllamaClient` / `UploadStore`,
`OllamaClient` + `OpenAICompatClient`s → `ProviderRegistry`,
`ToolRegistry` → `Agent` → `App` → handler factory. No module-level globals, no hidden coupling.

## Files

| Path                  | Purpose                                    |
|-----------------------|--------------------------------------------|
| `homeagent/`          | The application package (see above)        |
| `homeagent/static/`   | The web UI: `index.html`, `style.css`, `app.js` |
| `homeagent/config.py` | Reads runtime configuration from env files     |
| `.env`                | Tracked configuration template (placeholders)  |
| `prod.env`            | Untracked secrets (git-ignored, not in repo)   |
| `run.sh`              | Launcher with Ollama health check              |
| `pyproject.toml`, `uv.lock` | Dependencies (uv); `.venv/` is created on first run |
| `/tmp/homeagent/`     | Upload dir + logs (created on first run)   |

## API (if you want to script it)

- `GET  /api/chats` — list chats
- `POST /api/chats` — create chat `{"provider": "ollama", "model": "qwen3.8:27b"}`
- `GET  /api/chats/<id>` — chat + messages
- `DELETE /api/chats/<id>` — delete chat
- `POST /api/chats/<id>/messages` — send message, **NDJSON stream** back:
  `{"type":"delta","content":"…"}` … `{"type":"done","duration_ms":…}`,
  plus `think_delta`, `tool` (`{"name","arguments"}`), `tool_result`
  (`{"name","ok"}`) and `error` events
- `POST /api/upload` — multipart image upload → `{"url":"/uploads/<id>.png"}`
- `GET  /api/providers` — configured providers + the default
- `GET  /api/models?provider=<id>` — that provider's models
  (`{"online", "models", "default"}`; empty when offline)
- `POST /api/incognito` — unsaved turn, NDJSON
  `{"provider","model","text","images","messages"}`

### Auth endpoints (public; the `/api/*` + `/uploads/*` routes require a session)

- `GET  /auth/me` — the signed-in user, or `{"user": null}`
- `GET  /auth/users` — lightweight list of accounts (for the splash tiles)
- `POST /auth/login` — `{"username","password"}` → sets the session cookie
- `POST /auth/guest` — guest session cookie (memory only; incognito routes only)
- `POST /auth/logout` — clears the session
- `POST /auth/set-or-reset` — request a set/reset verification code
  → `{"code"|null,"is_new","email_sent","email_note","delivery"}`
- `POST /auth/verify-code` — `{"code"}` — finalize the set/reset and set the session cookie

## Users & privacy

- **Splash screen** — the first thing you see is a tile of every username
  with a single password field, plus a "Set or reset password" link.
- **Set / reset is one flow** — four fields (username, email, password,
  confirm). A one-time 6-character verification code is emailed (it works
  from any device — nothing to click, no link anywhere). When the email
  can't be sent, the code is shown on-screen *only* — an explicitly-warned
  fallback so the flow always works.
- **Per-user history** — every chat is stored with an `owner`, and every
  `chats`/`messages` query is scoped to the signed-in user. One account can
  never list, read, or delete another's chats.
- **Guest** — the *Guest* tile signs in without a password. There is no
  guest user in the database and its session lives only in server memory
  (a restart signs guests out). Guests are always incognito: the history
  routes (`/api/chats*`) answer 403, and the name `guest` can't be
  registered.
- **Migration** — the *first* account to activate inherits any chats that
  pre-date auth (they had no owner), so an existing install doesn't lose
  history.

## Security notes

- Passwords are hashed with `hashlib.scrypt` (a memory-hard KDF) plus a
  per-password random salt; plaintext is never stored.
- Sessions are 192-bit random bearer tokens in an `HttpOnly; SameSite=Lax`
  cookie; verification codes are one-shot, hour-bounded, and delivered
  by email.
- Uploaded images use unguessable UUID filenames; the DB stores only
  filenames, not base64 blobs. Both `/uploads/*` and all `/api/*` data routes
  require a signed-in session.
- Binds to `0.0.0.0` by default (LAN-reachable). Because the app is
  now authenticated, LAN use is fine; for public exposure, put it behind
  TLS.

## License

See [LICENSE](LICENSE).

# Functionality — HomeAgent

_Project type: unknown_

## Overview

A self-hosted web chat UI for [Ollama](https://ollama.com) models running on your own machine. Talk to `qwen3.8:27b` (or any model you've pulled) through a professional single-page interface — no cloud, zero pip installs.

## How to target work

Match the user's request to a module below, then open only that module's paths.
Examples: "update the UI" → `ui`. "fix the API" → `api` or `server`. "change the schema" → `db` / `models`.

## Modules

<!-- reignit:modules:start -->

### homeagent (`homeagent/`)

Owns the whole app. Configuration is a single Python module:
`homeagent/config.py` exposes a frozen `CONFIG: Config` constant — that is
the ONE place settings live. No env vars, no TOML, no loader.

Roles:
- `config.py` — the single config source (`CONFIG` constant; frozen `Config`
  dataclass). `load_config()` is a back-compat shim that just returns `CONFIG`.
- `accounts.py` — `UserStore`: users, scrypt-hashed passwords, HTTP sessions,
  one-shot hour-bounded activation tokens, optional SMTP (465→SMTP_SSL,
  587/others→STARTTLS). Sets the delivery mode
  (`inbox` | `fallback-after-error` | `off`) for the activation token.
- `db.py` — `ChatDatabase`: per-owner chats + messages in MongoDB
  (pymongo); `claim_unowned(owner)` for the first user to adopt
  pre-auth data.
- `ollama.py` — `OllamaClient`: list models, NDJSON `/api/chat` streaming.
- `uploads.py` — `UploadStore`: multipart image upload, UUID filenames.
- `app.py` — `App`: the DI facade handed to every request (holds config,
  db, ollama, uploads, users, static dir).
- `server.py` — handler factory; auth-public routes (`/`, static,
  `/auth/*`, `/uploads/*`) + guarded `/api/*` routes. Streams chat
  responses to the browser.
- `main.py` — composition root; `build_app(CONFIG)` wires everything;
  `python -m homeagent.main`.
- `static/` — UI (`index.html`, `style.css`, `app.js`); the splash tiles
  + set/reset flow read `d.delivery` to decide whether to show a link.

Key paths:
- `homeagent/config.py`            # ONE config file — edit this
- `homeagent/accounts.py`
- `homeagent/db.py`
- `homeagent/main.py`
- `homeagent/ollama.py`
- `homeagent/server.py`
- `homeagent/uploads.py`
- `homeagent/static/app.js`
- `homeagent/static/index.html`
- `homeagent/static/style.css`

<!-- reignit:modules:end -->

# Functionality — HomeAgent

_Project type: Python web app (stdlib `http.server` + `pymongo`) — self-hosted chat UI for local Ollama models_

## Overview

A self-hosted web chat UI for [Ollama](https://ollama.com) models running on your own machine. Talk to `qwen3.8:27b` (or any model you've pulled) through a professional single-page interface — no cloud, no accounts, zero pip installs.

Backend is a threaded `http.server` (no framework); persistence is MongoDB via `pymongo`; configuration is a single `homeagent.toml` (no env vars); the UI is a static single-page app served from `homeagent/static/`.

## How to target work

Match the user's request to a module below, then open only that module's paths.
Examples: "update the UI" → `ui`. "fix the API" → `api` or `server`. "change the schema" → `db` / `models`.

## Modules

<!-- reignit:modules:start -->

### homeagent (`homeagent/`)

The whole application. A modular, dependency-injected package: one small single-responsibility module each, wired together by a composition root. Request flow: `main` builds the collaborator graph → `server` routes HTTP → `ollama` streams the model reply → `db` persists chats → `uploads` handles images → `app` is the facade the handler reads.

Key paths (with roles):
- `homeagent/main.py` — **composition root & CLI entry** (`python -m homeagent.main --config ...`); builds `Config → ChatDatabase + OllamaClient + UploadStore → App`, creates the `ThreadingHTTPServer`, auto-opens the browser.
- `homeagent/server.py` — **HTTP routing + `App` facade**; flat explicit routes (`/`, `/api/models`, `/api/chats`, `/api/chats/<id>`, `/api/chats/<id>/messages`, `/api/incognito`, `/api/upload`, `/uploads/<name>`), emits **NDJSON** streaming, keeps consuming the model stream after a browser disconnect so the reply is always saved; caches which models support thinking.
- `homeagent/ollama.py` — **stdlib Ollama client**; lists models (`/api/tags`) and streams chat completions (`/api/chat`) as `think_delta` / `delta` / `done` / `error` events.
- `homeagent/db.py` — **MongoDB persistence**; `chats` + `messages` collections, `uuid4().hex` ids, epoch-second timestamps, cascading delete; `build_model_messages` resends only the latest turn's images as base64 (older turns as plain text).
- `homeagent/uploads.py` — **image upload store**; stdlib multipart parsing, random 32-hex names, MIME+extension allow-list (png/jpeg/gif/webp/bmp) and size cap.
- `homeagent/config.py` — **configuration**; load + validate `homeagent.toml` (tomllib) over a `DEFAULTS` dict; returns a frozen `Config` dataclass; relative paths resolved against the config file's dir.
- `homeagent/app.py` — **facade** (`cfg`, `db`, `ollama`, `uploads`, `static_dir`) handed to every request so the handler never touches module-level state.
- `homeagent/__init__.py` — package version + docstring.
- `homeagent/static/app.js` — frontend logic (streaming, model picker, composer, code/ASCII-table rendering).
- `homeagent/static/index.html` — single-page UI structure.
- `homeagent/static/style.css` — dark theme styling.

## Key behaviors worth knowing

- **Streaming** — responses stream as NDJSON with a live timer and a stop button; the reply is saved to Mongo even if the client disconnects mid-stream.
- **Thinking mode** — per-request toggle; enabled only for models Ollama reports as thinking-capable (capped, best-effort capability probe).
- **Incognito** — `POST /api/incognito` runs an unsaved one-off turn (no chat persisted).
- **Images** — uploaded images are base64-embedded only for the latest user turn to keep context small; stored under `upload_dir` (default `/tmp/homeagent/uploads`).

<!-- reignit:modules:end -->

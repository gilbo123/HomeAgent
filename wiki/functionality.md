# Functionality — HomeAgent

_Project type: unknown_

## Overview

A self-hosted web chat UI for [Ollama](https://ollama.com) models running on your own machine. Talk to `qwen3.8:27b` (or any model you've pulled) through a professional single-page interface — no cloud, zero pip installs.

## How to target work

Match the user's request to a module below, then open only that module's paths.
Examples: "update the UI" → `ui`. "fix the API" → `api` or `server`. "change the schema" → `db` / `models`.

## Auth flow (current)

- Sign-in: username tile + password → `POST /auth/login` → `Ha_session` cookie.
- **Set/reset password (no link):** four fields → server stores pending
  password + 6-char verification code (1 h TTL, one-shot) → code emailed →
  user enters it on the page → `POST /auth/verify-code` → cookie set, reload.
  Code shown on-screen **only** if email is off or the send failed (anti-lockout).
- `accounts.py` = UserStore (users/sessions/`activations` collections,
  scrypt passwords, code generation, best-effort SMTP).
- `db.py::claim_unowned` migrates pre-auth chats to the first account on verify.

## Modules

<!-- reignit:modules:start -->

### homeagent (`homeagent/`)

Owns `homeagent/`. Describe this module's role here.

Key paths:
- `homeagent/static/app.js`
- `homeagent/static/index.html`
- `homeagent/static/style.css`
- `homeagent/__init__.py`
- `homeagent/accounts.py`
- `homeagent/app.py`
- `homeagent/config.py`
- `homeagent/db.py`
- `homeagent/main.py`
- `homeagent/ollama.py`
- `homeagent/server.py`
- `homeagent/uploads.py`

<!-- reignit:modules:end -->

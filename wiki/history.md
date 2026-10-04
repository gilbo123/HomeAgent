# History

Completed work only — newest first. Active checklist lives in `wiki/current.md`.

### 2026-10-05 — Guest sign-in + model providers
- **Guest tile** on the splash: `POST /auth/guest` → memory-only session in
  `UserStore` (no user doc, restart signs guests out). `_require_user(allow_guest)`
  gates routes: guests get providers/models/upload/incognito; `/api/chats*`
  → 403. UI forces incognito, hides the toggle and history. `guest` is a
  reserved username.
- **Providers**: `openai_compat.py` (OpenAI-compatible SSE client: images as
  data URLs, tool-call ids, `reasoning_content` → thinking, retry-without-tools
  when a server rejects them) + `providers.py` registry. Config
  `STRATA_URL` / `VLLM_URL` / `LMSTUDIO_URL` (+ `_API_KEY`), `DEFAULT_PROVIDER`.
  `Agent.run(client, …)` is provider-agnostic.
- UI: Provider dropdown; `/api/models?provider=` → empty list when offline,
  Send disabled without a model. Chats store `provider`; changing
  provider/model mid-chat is saved (`db.set_chat_model`).
- Verified the OpenAI-compatible path against Ollama's own `/v1` (tools,
  reasoning, image) and the guest flow in the browser. Strata / vLLM /
  LM Studio themselves untested (they run on the server box).
- Fix: tool-call CSS had reused the composer's `.tools` class → `.toolcalls`.

### 2026-10-05 — Tools (weather + web search), uv, cleanup
- Root cause of "my ISP blocks agentic requests": the app never sent tools to
  Ollama, so the model had no way to go online and made up an excuse.
  Outbound access was verified fine (Open-Meteo, DuckDuckGo, GitHub).
- New `tools.py` (`get_weather` via Open-Meteo, `web_search` via Brave Search
  API, `BRAVE_API_KEY`) and `agent.py` (system prompt + tool loop) using
  Ollama native tool-calling — no MCP layer.
- UI shows each tool call (pending / done / failed) above the answer; saved
  with the message.
- uv project: `pyproject.toml` + `uv.lock`; `run.sh` uses `uv run`
  (the old `~/.virtualenvs/chat` env no longer existed).
- Cleanup: `.gitignore` inline comments (git doesn't support them);
  `delete_chat` only deletes messages of a chat the owner actually deleted;
  `list_chats` filters empty chats in the query and sweeps only ones older
  than 1 h; thinking/tools capability cache moved onto `OllamaClient`;
  stream helpers deduplicated; imports at top; request body cap (413);
  `OLLAMA_HOST` without a scheme is normalised in `config.py`; Ollama HTTP
  errors reported verbatim; dead `load_config` removed.
- Security: the Gmail app password and an older Google password were still in
  git history — rewritten with `git filter-repo` (backup bundle in `/tmp`).
  Both passwords must be rotated regardless (the repo is public).

### 2026-10-01 — Secrets out of code, into `prod.env`
- Gmail SMTP credentials were hardcoded in **two** tracked files
  (`homeagent/config.py` and `EmailSettings` defaults in `homeagent/accounts.py`)
  — now removed entirely; verified with `git grep` that no credential remains
  in tracked sources.
- `homeagent/config.py` now resolves all CONFIG values at import time:
  real env vars > `prod.env` (untracked) > `.env` (tracked template).
  Includes a tiny stdlib env-file parser (supports inline `#` comments,
  quoted values).
- **Design (confirmed by user):** the tracked `.env` template STAYS in the
  repo (I briefly deleted it per a follow-up, then restored it — it is NOT
  accidental, keep it). `prod.env` (git-ignored) holds the real Gmail creds
  + LAN Ollama host.
- `.gitignore`: `prod.env` ignored; `.env` un-ignored via `!.env`.
- README "Configuration" section rewritten; stale "no env vars" comments
  in `run.sh` and `main.py` updated.
- Verified: real values load from `prod.env`; without it, safe template
  defaults apply (SMTP shows on-screen fallback); real env vars always win.
- Note: your development shell exports `OLLAMA_HOST=192.168.1.200:11434`
  itself, which overrides both env files by design.

### 2026-09-26 — Send button no longer red at rest
- `enterApp()` called `setSend(false)` — the red "stop working" state — on
  startup, so the send button looked like STOP with an empty input.
- Now `enterApp()` calls `setSend(true)`: normal ➤ state, disabled until text
  or images are attached. Red `■` Stop state only appears mid-stream as before.

### 2026-09-26 — Code entry stays on the set/reset page
- User had nowhere to type the verification code: when the email delivered,
  the success box hid the code input and only offered "← Back to sign in".
- `index.html`: code box (`srCodeWrap`) no longer `hidden` by default and the
  "Back to sign in" link is removed from the success state.
- `app.js`: `submitSetReset` keeps the box visible in all delivery modes;
  hint text tells where the code came from (inbox / pre-filled fallback);
  pre-fill only on the email-off / send-failed fallback, as before.

### 2026-09-26 — Activation link → email verification code
- Replaced the browser-click `GET /auth/activate?token=…` flow with a
  **6-char verification code** sent in the email (works from any device):
  - `accounts.py`: `new_code()` (secrets, no 0/O/1/I/L); email carries the
    code, never a URL; `activate(token)` → `verify_code(code)` (1 h TTL,
    one-shot, latest code per username wins); first-user chat claim logic kept;
    `EmailSettings.base_url` removed; SMTP default aligned to the
    `homestack04@gmail.com` app account.
  - `server.py`: `POST /auth/verify-code` sets the session cookie directly
    (no redirect); `/auth/activate` route removed; code hidden from the
    browser when email delivered, shown only as an explicitly-warned anti-lockout
    fallback (email off or send failed).
  - `index.html` / `app.js`: success box now has a code field + "Verify &
    finish" button replacing the copy-link box.
  - `main.py`, `config.py`, `README.md` updated to match.
- SMTP debug: Gmail rejected the old password with `534 5.7.9 Application-
  specific password required`. User generated a Gmail app password; after
  syncing it into `config.py` + `EmailSettings`, a live test send through the
  app's own `send_activation_email` succeeded (`RESULT: True | sent`).

### 2026-09-05 — Wiki initialized
- Created `wiki/current.md`, `functionality.md`, `history.md`.
- Project type: unknown.
- Existing project scanned for a module map.

Recent commits at init (for orientation):
- e52523e feat - added user profiles
- 1fc491a feat - added reignit
- 4b6a400 feat - added thinking and incognito mode
- 8c098df fix - working with images and memory again
- 8701854 fix - working with images and memory again
- 1bf2bb6 fix - working with images and memory again
- 3ed79e3 fix - working with images and memory again
- 7a2ebc6 fix - working with images and memory again

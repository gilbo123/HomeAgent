# History

Agent mode: update **Current work** before code changes; check items off after each step.

## Current work

<!-- reignit:current:start -->

_Status: idle_

_No active task. When work starts, set goal + checklist here before editing code._

<!-- reignit:current:end -->

## Log (newest first)

### 2026-09-05 — Config consolidation + activation privacy fix
- **One config, one file.** `homeagent/config.py` is now the single source:
  a frozen `Config` dataclass + `CONFIG` constant. `homeagent.toml` removed
  from the repo (and from `main.py`, `run.sh`, README, `__init__.py`).
  `main.py` imports `CONFIG` directly; `run.sh` reads the Ollama host from
  `homeagent.config`. `load_config(path=None)` stays only as a back-compat
  no-op shim.
- **Activation privacy model.** Server-side delivery modes:
  `inbox` (token withheld, link only in the mail),
  `fallback-after-error` (token returned, on-screen link with an explicit
  warning about the failed send), `off` (token returned, on-screen link
  only). `app.js` branches on `d.delivery`; the `inbox` case hides
  `#srLinkWrap` entirely.
- **SMTP hardening.** `accounts.py` now picks 465→`SMTP_SSL`, 587/other→
  `SMTP` + `starttls()` after `ehlo`, 20 s timeout, explicit `quit()`.
  Real Gmail app password now lives in `homeagent/config.py` (tracked
  file — user should consider gitignore / rotate if this ever goes public).

### 2026-09-05 — Wiki initialized
- Created `wiki/functionality.md` and `wiki/history.md`.
- Project type: unknown.
- Existing project scanned for a module map.

Recent commits at init (for orientation):
- 1fc491a feat - added reignit
- 4b6a400 feat - added thinking and incognito mode
- 8c098df fix - working with images and memory again
- 8701854 fix - working with images and memory again
- 1bf2bb6 fix - working with images and memory again
- 3ed79e3 fix - working with images and memory again
- 7a2ebc6 fix - working with images and memory again
- fa8875e fix - working with images and memory again

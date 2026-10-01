# History

Completed work only — newest first. Active checklist lives in `wiki/current.md`.

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

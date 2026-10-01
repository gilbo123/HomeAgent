"""Users, sessions, and account activation.

Design notes
-----------
* One MongoDB database (the one from ``Config``) holds three collections:

    - ``users``       one document per human, keyed by unique ``username``.
    - ``sessions``    opaque bearer tokens, one per logged-in browser.
    - ``activations`` short-lived codes that finalize a set/reset password flow.

* Passwords are hashed with stdlib :mod:`hashlib.scrypt` (a memory-hard KDF) and
  a random per-password 16-byte salt. We never store the plaintext anywhere.

* The set-or-reset flow is two-step:

    1. ``request_set_or_reset(username, email, password)`` — validates the
       inputs (new username, or existing username with matching email) and
       stores a pending password under a fresh short verification code.
    2. ``verify_code(code)`` — the user types the code on the set/reset page
       (they read it from the email — or from the on-screen fallback when
       SMTP is off/failed); the password becomes live and, if this is the
       first user, any pre-existing unowned chats are claimed under them
       (migration).

  Both set and reset go through the same path, as requested. The code is
  typed into the app rather than clicked as a URL, so it works identically
  from any device and the browser never displays a private link.

* Session cookies are :class:`secrets`-generated opaque tokens, ``HttpOnly``
  and ``SameSite=Lax``. Sessions expire after seven days.

* Email delivery is optional and uses stdlib :mod:`smtplib`. When the config
  does not set an SMTP host (or the send fails), the verification code is
  shown on-screen for this exact session instead (still fully functional).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import time
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any

from pymongo import MongoClient, errors


# Token lifetimes
SESSION_TTL_S = 7 * 24 * 3600  # one week
ACTIVATION_TTL_S = 3600        # one hour


# ------------------------------------------------------------------- helpers

def _scrypt(password: str, salt: bytes, n: int = 1 << 14,
            r: int = 8, p: int = 1) -> bytes:
    """Run :func:`hashlib.scrypt` with the parameters we store on the user doc.

    The parameters are deliberately modest (N=16384, r=8, p=1, 32-byte digest)
    — enough for a single-user home server, but still meaningful against
    offline brute-force if the database leaks.
    """
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=64 * (1 << 20),   # 64 MiB maxmem keeps this comfortable for one call
    )


def hash_password(password: str) -> dict[str, Any]:
    """Return a ``{hash, salt, n, r, p}`` dict (hash/salt stored as hex).

    The salt is generated here and returned alongside the digest so the caller
    stores exactly the salt that was used — verification always matches.
    """
    salt = os.urandom(16)
    n, r, p = 1 << 14, 8, 1
    digest = _scrypt(password, salt, n, r, p)
    return {"hash": digest.hex(), "salt": salt.hex(), "n": n, "r": r, "p": p}


def verify_password(password: str, stored: dict[str, Any]) -> bool:
    try:
        digest = bytes.fromhex(stored["hash"])
        salt = bytes.fromhex(stored["salt"])
        n = int(stored["n"]); r = int(stored["r"]); p = int(stored["p"])
        candidate = _scrypt(password, salt, n, r, p)
    except Exception:
        return False
    return hmac.compare_digest(candidate, digest)


def new_token() -> str:
    """Return a fresh high-entropy, URL-safe hex token."""
    return secrets.token_hex(24)


def new_code() -> str:
    """Return a fresh 6-char human-friendly verification code.

    Uses ``secrets`` so the choice is non-predictable; the alphabet excludes
    look-alike characters (0/O, 1/I/L) because the user types it in by hand.
    """
    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # no 0/O/1/I/L
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _clean_email(addr: str) -> str:
    return (addr or "").strip().lower()


def _valid_email(addr: str) -> bool:
    # Small pragmatic check — one "@", both sides non-empty, no spaces, a dot
    # after the "@". Not a DNS check, and we don't care about edge case RFCs
    # on a local machine.
    a = _clean_email(addr)
    if not a or " " in a or a.count("@") != 1:
        return False
    user, _, domain = a.partition("@")
    return bool(user) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def _doc(d: dict[str, Any]) -> dict[str, Any]:
    """Public view of a user/session doc: strip ``_id`` and secrets."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if k in ("_id", "salt", "hash", "n", "r", "p", "pending", "has_pending"):
            continue
        out[k] = v
    return out


class AuthError(Exception):
    """User-facing auth error (message is safe to send to the browser)."""


class InvalidRequest(AuthError):
    """4xx — bad input (missing email, wrong email for username, etc)."""


class NotActivated(AuthError):
    """Password still in pending state — the verification code must be entered first."""


# --------------------------------------------------------------- Email helper

@dataclass(frozen=True)
class EmailSettings:
    """Immutable view of the SMTP config, or ``disabled=True`` when empty."""

    # All values are injected from homeagent.config (which reads prod.env).
    # Defaults are empty = SMTP disabled, so no credentials live in code.
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    use_tls: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.host)


def send_activation_email(settings: EmailSettings, to: str,
                          username: str, code: str) -> tuple[bool, str]:
    """Best-effort SMTP send. Returns (ok, message). Never raises.

    Uses stdlib only — no new dependencies.
    """
    if not settings.enabled:
        return False, "smtp not configured"
    try:
        msg = MIMEText(
            f"Hi {username},\n\n"
            "You asked to set or reset your Home Agent password.\n"
            "Enter this verification code on the Home Agent page to finish:\n\n"
            f"    {code}\n\n"
            "The code works for about one hour.\n\n"
            "If you did not ask for this, someone else may be trying to set a\n"
            "password for this account — you can safely ignore this email.\n\n"
            f"— Home Agent on {settings.host}:{settings.port}",
        )
        msg["Subject"] = f"Home Agent — verification code for {username}: {code}"
        msg["From"] = settings.from_addr or settings.username
        msg["To"] = to
        raw = msg.as_string()
        from_addr = settings.from_addr or settings.username
        # Port 465 = implicit TLS (SMTP_SSL). 587 or any other TLS port =
        # STARTTLS after connect.
        if settings.use_tls and settings.port == 465:
            s: smtplib.SMTP = smtplib.SMTP_SSL(settings.host, settings.port, timeout=20)
        else:
            s = smtplib.SMTP(settings.host, settings.port, timeout=20)
            if settings.use_tls:
                s.ehlo()
                s.starttls()
                s.ehlo()
        try:
            if settings.username:
                s.login(settings.username, settings.password)
            s.sendmail(from_addr, [to], raw)
        finally:
            try:
                s.quit()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        return True, "sent"
    except Exception as e:  # noqa: BLE001 — email is best-effort by design
        return False, f"smtp failed: {e}"


# --------------------------------------------------------------- UserStore

class UserStore:
    """Thread-safe (pymongo-backed) user / session / activation store."""

    def __init__(
        self,
        mongo_uri: str,
        db_name: str,
        email: EmailSettings | None = None,
    ) -> None:
        self._email = email or EmailSettings()
        # Fail fast (5s) if mongod isn't up, matching db.py's behaviour.
        self._client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self._db = self._client[db_name]
        self._users = self._db["users"]
        self._sessions = self._db["sessions"]
        self._activations = self._db["activations"]
        self._index()

    def _index(self) -> None:
        try:
            self._users.create_index("username", unique=True)
            self._sessions.create_index([("expires_at", 1)], expireAfterSeconds=0)
            self._activations.create_index([("expires_at", 1)], expireAfterSeconds=0)
        except errors.ServerSelectionTimeoutError as e:
            raise RuntimeError(
                "cannot reach MongoDB at the configured URI (is mongod running?)"
            ) from e
        except (errors.OperationFailure, errors.PyMongoError) as e:
            raise RuntimeError(f"UserStore index setup failed: {e}") from e

    # ------------------------------------------------------------- queries

    def list_users(self) -> list[dict[str, Any]]:
        """Lightweight user list for the login splash (username + state only;
        never password/salt/email)."""
        out: list[dict[str, Any]] = []
        for u in self._users.find(
            {}, {"username": 1, "activated": 1}
        ).sort([("created_at", 1)]):
            out.append({"username": u.get("username"), "activated": bool(u.get("activated"))})
        return out

    def get_public(self, username: str) -> dict[str, Any] | None:
        u = self._users.find_one({"username": (username or "").strip()})
        if u is None:
            return None
        d = _doc(u)
        d["activated"] = bool(u.get("activated"))
        return d

    def has_pending(self, username: str) -> bool:
        u = self._users.find_one({"username": (username or "").strip()},
                                 {"has_pending": 1})
        return bool(u and u.get("has_pending"))

    # --------------------------------------------------------- set / reset

    def request_set_or_reset(self, username: str, email_addr: str,
                             password: str,
                             confirm: str) -> tuple[str, tuple[bool, str], bool]:
        """Store a pending password and return (code, email_result, is_new_user).

        Raises :class:`InvalidRequest` on bad input.
        """
        username = (username or "").strip()
        email_addr = _clean_email(email_addr)
        if not username or len(username) < 2 or len(username) > 40:
            raise InvalidRequest("username must be 2-40 characters")
        if not _valid_email(email_addr):
            raise InvalidRequest("email looks invalid")
        if not password or len(password) < 8:
            raise InvalidRequest("password must be at least 8 characters")
        if password != confirm:
            raise InvalidRequest("passwords do not match")

        existing = self._users.find_one({"username": username}, {"email": 1})
        is_new = existing is None
        if existing is not None and _clean_email(existing.get("email", "")) != email_addr:
            raise InvalidRequest("email does not match the stored account")
        # A reset is always allowed (that's the point of "set OR reset"); a new
        # username simply gets the supplied email as its identity.

        now = int(time.time())
        code = new_code()
        pending = hash_password(password)   # {hash, salt, n, r, p} — consistent pair
        common = {
            "email": email_addr,
            "has_pending": True,
            "activated": False,
            "pending": pending,
            "created_at": now,
            "updated_at": now,
        }
        if is_new:
            self._users.insert_one({"username": username, **common})
        else:
            self._users.update_one({"username": username}, {"$set": common})

        # Verification record lives in its own collection so we can TTL-expire
        # it independently of the user doc. One code per username keeps a
        # re-requested reset from leaving an old (already-shown) code valid.
        self._activations.delete_many({"username": username})
        self._activations.insert_one({
            "code": code,
            "username": username,
            "created_at": now,
            "expires_at": now + ACTIVATION_TTL_S,
        })

        # Email (best-effort) — the email carries the code, never a URL.
        email_result = send_activation_email(
            self._email, email_addr, username, code,
        )
        return code, email_result, is_new

    def verify_code(self, code: str,
                    claim_unowned=None) -> dict[str, Any]:
        """Finalize a pending password from the verification code. Returns a
        user-shaped public view.

        If this is the first user and ``claim_unowned`` is supplied, pre-auth
        (unowned) chats are migrated under them — the callback is expected to
        be ``ChatDatabase.claim_unowned(owner)``.
        """
        code = (code or "").strip().upper()
        if not code:
            raise InvalidRequest("missing verification code")
        act = self._activations.find_one({"code": code})
        if act is None:
            raise InvalidRequest("invalid or expired verification code")
        now = int(time.time())
        if act.get("expires_at", 0) < now:
            raise InvalidRequest("verification code has expired; set-or-reset again")
        user = self._users.find_one({"username": act["username"]})
        if not user or not user.get("has_pending") or not user.get("pending"):
            raise InvalidRequest("no pending password for this user")

        first_user = self._users.count_documents({}) == 1
        self._users.update_one(
            {"username": act["username"]},
            {
                "$set": {
                    "salt": user["pending"]["salt"],
                    "hash": user["pending"]["hash"],
                    "n": user["pending"]["n"],
                    "r": user["pending"]["r"],
                    "p": user["pending"]["p"],
                    "activated": True,
                    "updated_at": now,
                },
                "$unset": {"pending": 1, "has_pending": 1},
            },
        )
        self._activations.delete_one({"code": code})

        # If this is the very first account, adopt any pre-auth (unowned)
        # chats so an existing install doesn't lose its history. Claiming is
        # idempotent, so a no-op for everyone after the first user.
        migrated = 0
        if first_user and claim_unowned is not None:
            try:
                migrated = int(claim_unowned(act["username"])) or 0
            except Exception:  # noqa: BLE001 — migration must never block sign-in
                migrated = 0
        out = self.get_public(act["username"]) or {}
        out["migrated"] = first_user
        out["claimed_chats"] = migrated
        return out

    # --------------------------------------------------------- login / auth

    def try_login(self, username: str, password: str) -> bool:
        """Verify an activated account's password.

        A missing user and a not-yet-activated account both return False so we
        don't reveal which case occurred (no account-enumeration signalling).
        """
        u = self._users.find_one({"username": (username or "").strip()})
        if not u or not u.get("activated"):
            return False
        return verify_password(password, u)

    # ------------------------------------------------------------ sessions

    def create_session(self, username: str) -> tuple[str, int]:
        u = self._users.find_one({"username": username})
        if not u or not u.get("activated"):
            raise NotActivated(
                "account not activated yet — enter the verification code"
            )
        now = int(time.time())
        token = new_token()
        self._sessions.insert_one({
            "token": token,
            "username": username,
            "created_at": now,
            "expires_at": now + SESSION_TTL_S,
            "last_seen": now,
        })
        return token, SESSION_TTL_S

    def lookup_session(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        s = self._sessions.find_one({"token": token})
        if not s:
            return None
        if s.get("expires_at", 0) < int(time.time()):
            self._sessions.delete_one({"token": token})
            return None
        # cheap rolling extension — refresh last_seen, don't move the expiry
        try:
            self._sessions.update_one({"token": token},
                                      {"$set": {"last_seen": int(time.time())}})
        except errors.PyMongoError:
            pass
        return _doc(s)

    def delete_session(self, token: str) -> None:
        try:
            self._sessions.delete_one({"token": token})
        except errors.PyMongoError:
            pass

    @property
    def email_enabled(self) -> bool:
        """True when an SMTP host is configured — i.e. email is the private
        channel for set/reset. The client uses this to decide whether to show
        the verification code on-screen (no) or hand it over to the inbox (yes)."""
        return bool(self._email and self._email.enabled)

    # ------------------------------------------------------------- cleanup

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

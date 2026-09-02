"""Authentication.

Demo-grade *storage*, production-grade *cryptography*. That distinction is
deliberate and is stated in the docs rather than glossed over:

* Passwords are never stored. Each account keeps a random 16-byte salt and a
  PBKDF2-HMAC-SHA256 derivation at 200,000 iterations (the OWASP floor), and
  verification is constant-time.
* Sessions are compact HMAC-SHA256 signed tokens carrying a subject and an
  expiry. A tampered or expired token fails verification; there is no server
  state to desynchronise.
* The **user store is a JSON file**, which is the part that is demo-grade. It
  is fine for a single-node hackathon deployment and is a small, well-isolated
  swap for Postgres later - only :class:`UserStore` would change.

Nothing here uses a third-party dependency, so it cannot break the demo by
failing to install.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import settings

log = logging.getLogger("satquery.auth")

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
DIGEST = "sha256"

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

#: Shipped so a judge can sign in immediately without creating an account.
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "satquery2026"


class AuthError(Exception):
    """Raised for any credential or token problem. Message is user-safe."""


class StorageError(AuthError):
    """The account store itself is unavailable. Distinct from a bad credential.

    Kept a subclass of :class:`AuthError` so existing callers still catch it,
    but the API maps it to 503 rather than 400 - the request was fine, the
    server's disk was not, and the user should be told to retry rather than to
    fix their input.
    """


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Return ``(salt_hex, hash_hex)``."""
    salt = salt or secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(DIGEST, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), dk.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(DIGEST, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(dk.hex(), hash_hex)


def password_problems(password: str) -> list[str]:
    """Report every problem at once rather than one per attempt."""
    out: list[str] = []
    if len(password) < 8:
        out.append("be at least 8 characters long")
    if len(password) > 128:
        out.append("be no longer than 128 characters")
    if not re.search(r"[A-Za-z]", password):
        out.append("contain at least one letter")
    if not re.search(r"\d", password):
        out.append("contain at least one number")
    return out


def username_problem(username: str) -> str | None:
    """A specific, actionable reason the username is unusable, or None."""
    u = (username or "").strip()
    if not u:
        return "Please choose a username."
    if len(u) < 3:
        return "Username must be at least 3 characters long."
    if len(u) > 32:
        return "Username must be 32 characters or fewer."
    if not USERNAME_RE.match(u):
        return ("Username may only contain letters, digits, dot, underscore or hyphen "
                "- no spaces or other symbols.")
    return None


# --------------------------------------------------------------------------
# Session tokens
# --------------------------------------------------------------------------
def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret() -> bytes:
    """Signing key: from the environment, else persisted once on disk."""
    env = os.getenv("SATQUERY_SESSION_SECRET")
    if env:
        return env.encode("utf-8")
    path = settings.data_dir / ".session_secret"
    if path.exists():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    try:
        path.write_bytes(key)
        if os.name == "posix":
            os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def issue_token(username: str, ttl_seconds: int | None = None) -> tuple[str, int]:
    """Return ``(token, expires_at_epoch)``."""
    ttl = ttl_seconds or settings.session_ttl_seconds
    exp = int(time.time()) + ttl
    payload = _b64u(json.dumps({"sub": username, "exp": exp}, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}", exp


def verify_token(token: str) -> str:
    """Return the username, or raise :class:`AuthError`."""
    if not token or "." not in token:
        raise AuthError("Malformed session token.")
    payload, _, sig = token.rpartition(".")
    expected = _b64u(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise AuthError("Session token signature is invalid.")
    try:
        data = json.loads(_b64u_decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Session token payload is unreadable.") from exc
    if int(data.get("exp", 0)) < time.time():
        raise AuthError("Session has expired. Please sign in again.")
    sub = data.get("sub")
    if not sub:
        raise AuthError("Session token has no subject.")
    return str(sub)


# --------------------------------------------------------------------------
# User store
# --------------------------------------------------------------------------
@dataclass
class User:
    username: str
    display_name: str
    email: str | None
    organisation: str | None
    created_at: str
    last_login: str | None = None
    is_demo: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "organisation": self.organisation,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "is_demo": self.is_demo,
        }


class UserStore:
    """JSON-backed account store, guarded by a process lock.

    Single-node only, by design. Swapping this class for a database is the
    whole of the work needed to make the auth layer production-grade.
    """

    def __init__(self, path=None):
        self.path = path or (settings.data_dir / "users.json")
        self._lock = threading.RLock()
        self._cache: dict[str, dict] | None = None
        #: (mtime, size) of the file the cache was built from.
        self._stamp: tuple[float, int] | None = None

    # -- persistence --------------------------------------------------
    def _file_stamp(self) -> tuple[float, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_mtime, st.st_size)

    def _load(self) -> dict[str, dict]:
        """Return the account map, re-reading the file when it has changed.

        Caching purely in memory made the store authoritative over the file,
        so an account added or removed on disk - by an operator, a restore, or
        a second process - stayed invisible until restart, and the next write
        silently reinstated the old contents. Stamping the cache with the
        file's mtime and size keeps the file the source of truth at the cost
        of one stat() per read.
        """
        stamp = self._file_stamp()
        if self._cache is not None and stamp == self._stamp:
            return self._cache
        data: dict[str, dict] = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {k: v for k, v in raw.items() if isinstance(v, dict)}
                else:
                    raise ValueError("account store is not a JSON object")
            except (ValueError, OSError) as exc:
                # A corrupt store must not take the whole sign-in system down.
                # Preserve the damaged file so it can be inspected, and carry
                # on with an empty store which the demo seed will repopulate.
                log.error("users.json could not be read (%s); quarantining it.", exc)
                try:
                    self.path.replace(self.path.with_suffix(
                        f".corrupt-{int(time.time())}.json"))
                except OSError:
                    pass
                data = {}
        self._cache = data
        self._stamp = self._file_stamp()
        return self._cache

    def _save(self) -> None:
        """Persist the store, tolerating a transiently locked file.

        The data directory frequently lives inside a synced folder (OneDrive,
        Dropbox) or is being watched by an indexer. On Windows either can hold
        a brief exclusive handle on ``users.json``, and a naive ``replace()``
        then raises ``PermissionError`` - which, in the request path, surfaced
        to the user as a bare "Internal Server Error" on an otherwise perfectly
        valid sign-up. Retry briefly, then fall back to writing in place.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._cache or {}, indent=2)
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        last: Exception | None = None
        for attempt in range(5):
            try:
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(self.path)
                self._stamp = self._file_stamp()
                return
            except OSError as exc:
                last = exc
                time.sleep(0.06 * (attempt + 1))
        # Atomic replacement kept failing; a direct write is less safe but far
        # better than losing the account the user just created.
        try:
            self.path.write_text(payload, encoding="utf-8")
            self._stamp = self._file_stamp()
            log.warning("users.json written non-atomically after %s", last)
            return
        except OSError as exc:
            raise StorageError(
                "The account store could not be written to disk "
                f"({type(exc).__name__}). Check that the data directory "
                f"({self.path.parent}) exists and is writable."
            ) from exc
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # -- queries ------------------------------------------------------
    def exists(self, username: str) -> bool:
        return username.strip().lower() in self._load()

    def email_taken(self, email: str) -> bool:
        e = (email or "").strip().lower()
        if not e:
            return False
        return any((rec.get("email") or "").lower() == e for rec in self._load().values())

    def _find(self, identifier: str) -> dict | None:
        """Resolve a username *or* an email address to a stored record."""
        key = (identifier or "").strip().lower()
        if not key:
            return None
        users = self._load()
        rec = users.get(key)
        if rec is not None:
            return rec
        if "@" in key:
            for candidate in users.values():
                if (candidate.get("email") or "").lower() == key:
                    return candidate
        return None

    def get(self, username: str) -> User | None:
        rec = self._load().get(username.lower())
        if not rec:
            return None
        return User(
            username=rec["username"],
            display_name=rec.get("display_name") or rec["username"],
            email=rec.get("email"),
            organisation=rec.get("organisation"),
            created_at=rec.get("created_at", ""),
            last_login=rec.get("last_login"),
            is_demo=bool(rec.get("is_demo")),
        )

    def count(self) -> int:
        return len(self._load())

    # -- mutations ----------------------------------------------------
    def create(self, username: str, password: str, display_name: str | None = None,
               email: str | None = None, organisation: str | None = None,
               is_demo: bool = False) -> User:
        username = (username or "").strip()
        problem = username_problem(username)
        if problem:
            raise AuthError(problem)
        if email:
            email = email.strip()
            if not EMAIL_RE.match(email):
                raise AuthError("That email address does not look valid.")
        else:
            email = None
        problems = password_problems(password or "")
        if problems:
            raise AuthError("Password must " + ", ".join(problems) + ".")

        with self._lock:
            users = self._load()
            if username.lower() in users:
                raise AuthError(
                    f"The username '{username}' is already taken. Try another one, "
                    "or sign in if the account is yours.")
            if email and self.email_taken(email):
                raise AuthError(
                    f"An account already exists for {email}. Sign in instead, or "
                    "register with a different email address.")
            salt, digest = hash_password(password)
            users[username.lower()] = {
                "username": username,
                "display_name": (display_name or username).strip()[:64],
                "email": email,
                "organisation": (organisation or "").strip()[:96] or None,
                "salt": salt,
                "hash": digest,
                "iterations": PBKDF2_ITERATIONS,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_login": None,
                "is_demo": is_demo,
            }
            self._save()
        user = self.get(username)
        assert user is not None
        return user

    def authenticate(self, identifier: str, password: str) -> User:
        """Verify a username *or* email plus password, and return the account."""
        rec = self._find(identifier)
        if rec is None:
            # Spend comparable time on a missing user so the response time does
            # not reveal whether the account exists.
            hash_password(password or "")
            raise AuthError(
                "Incorrect username or password. If you have not registered yet, "
                "create an account first.")
        if not verify_password(password or "", rec.get("salt", ""), rec.get("hash", "")):
            raise AuthError("Incorrect username or password.")
        with self._lock:
            rec["last_login"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                self._save()
            except StorageError as exc:
                # Recording the login stamp is bookkeeping. Failing to write it
                # is not a reason to refuse a correct password.
                log.warning("last_login not persisted: %s", exc)
        user = self.get(rec["username"])
        assert user is not None
        return user

    def ensure_demo_account(self) -> None:
        """Seed the shipped demo login so a judge can sign in immediately.

        Purely additive: it is one row alongside every account real users
        create, not a gate. Set ``SATQUERY_SEED_DEMO_USER=false`` to omit it.
        """
        if not settings.seed_demo_user or self.exists(DEMO_USERNAME):
            return
        try:
            self.create(
                DEMO_USERNAME, DEMO_PASSWORD,
                display_name="Demo Analyst",
                organisation="Team Avengers - SIH 2026",
                is_demo=True,
            )
        except AuthError as exc:
            log.warning("demo account could not be seeded: %s", exc)


_store: UserStore | None = None


def get_store() -> UserStore:
    global _store
    if _store is None:
        _store = UserStore()
        _store.ensure_demo_account()
    return _store

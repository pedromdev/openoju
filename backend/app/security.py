from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# ---------------------------------------------------------------------------
# API keys: oju_<prefix>_<secret>
# ---------------------------------------------------------------------------


def _api_key_pepper() -> bytes:
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("OJU_SECRET_KEY is required for API key hashing")
    return settings.secret_key.encode("utf-8")


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, secret_hash)."""
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    full = f"oju_{prefix}_{secret}"
    return full, prefix, api_key_secret_hash(secret)


def api_key_secret_hash(secret: str) -> str:
    return hmac.new(_api_key_pepper(), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def split_api_key(full_key: str) -> tuple[str, str] | None:
    parts = full_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "oju":
        return None
    prefix, secret = parts[1], parts[2]
    if not prefix or not secret:
        return None
    return prefix, secret


# ---------------------------------------------------------------------------
# Symmetric encryption for secrets at rest
# ---------------------------------------------------------------------------


def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.fernet_key:
        raise RuntimeError("OJU_FERNET_KEY is required to store secrets")
    return Fernet(settings.fernet_key.encode("utf-8"))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("segredo criptografado inválido") from exc


# ---------------------------------------------------------------------------
# Login rate limiting (in-process)
# ---------------------------------------------------------------------------


class SlidingWindowLimiter:
    """Small in-memory limiter.

    Adequate for a single API process. Deployments with multiple replicas must
    move the counter to a shared store.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, window_s: int, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        cutoff = now - window_s
        while hits and hits[0] < cutoff:
            hits.popleft()
        return hits

    def blocked(self, key: str, *, attempts: int, window_s: int) -> bool:
        now = time.monotonic()
        hits = self._prune(key, window_s, now)
        return len(hits) >= attempts

    def hit(self, key: str, *, window_s: int) -> None:
        now = time.monotonic()
        self._prune(key, window_s, now).append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter()


def session_expiry(hours: int) -> datetime:
    return utcnow() + timedelta(hours=hours)

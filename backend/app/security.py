"""Password hashing, JWT issuing/verification and token storage helpers.

Passwords are hashed with bcrypt (cost from settings). JWTs are HS256 signed
with a server-side secret; refresh tokens are opaque random strings persisted
in the database so sessions can be listed and revoked (see models.RefreshToken).
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from .config import settings

_HASH_PREFIX = "bcrypt$"


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    digest = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return _HASH_PREFIX + digest.decode("ascii")


def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        if stored.startswith(_HASH_PREFIX):
            return bcrypt.checkpw(plain.encode("utf-8"), stored[len(_HASH_PREFIX):].encode("ascii"))
        # Legacy/argon2 fallbacks are rejected loudly rather than silently accepted.
        return False
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    """Deterministic password policy. Returns a list of unmet requirements."""
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"at least {settings.password_min_length} characters")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a number")
    if not any(c in string.punctuation for c in password):
        problems.append("a symbol")
    lowered = password.lower()
    for weak in ("password", "niecp", "123456", "qwerty", "admin"):
        if weak in lowered:
            problems.append("must not contain common weak words")
            break
    return problems


def password_strength(password: str) -> dict[str, Any]:
    problems = password_problems(password)
    score = max(0, 5 - len(problems))
    return {
        "score": score,
        "max_score": 5,
        "label": ["very weak", "weak", "fair", "good", "strong", "excellent"][score],
        "unmet": problems,
        "acceptable": not problems,
    }


# --------------------------------------------------------------------- tokens
def create_access_token(subject: str, claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "typ": "access",
        "jti": secrets.token_urlsafe(12),
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def create_reset_token() -> tuple[str, str]:
    """Returns (raw_token, hashed_token). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_reset_token(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def expires_in_seconds(days: int | None = None) -> datetime:
    days = settings.refresh_token_days if days is None else days
    return datetime.now(timezone.utc) + timedelta(days=days)


def generate_otp(digits: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(digits))

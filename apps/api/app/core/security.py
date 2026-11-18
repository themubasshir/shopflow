from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

_hasher = PasswordHasher(time_cost=settings.password_hash_time_cost)
_DUMMY_HASH = _hasher.hash("shopflow-dummy-password")

TokenType = Literal["access"]


class TokenError(Exception):
    """Raised when a bearer token is missing, malformed or expired."""


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time verification: always runs a hash check, even for unknown users."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def create_access_token(
    subject: str,
    *,
    shop_id: str,
    role: str,
    permissions: list[str],
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "shop_id": shop_id,
        "role": role,
        "permissions": permissions,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:  # pragma: no cover - covered through API tests
        raise TokenError("Invalid or expired access token") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise TokenError("Invalid access token payload")
    return payload

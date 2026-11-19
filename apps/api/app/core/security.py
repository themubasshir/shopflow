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
    session_id: str | None = None,
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
    # jti ties the token to an auth_sessions row so logout / account disable
    # can revoke it before the (long) access-token lifetime would expire.
    if session_id:
        payload["jti"] = session_id
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:  # pragma: no cover - covered through API tests
        raise TokenError("Invalid or expired access token") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise TokenError("Invalid access token payload")
    return payload


# --- Phase 2D-2: render grants ----------------------------------------------

RENDER_GRANT_TTL_SECONDS = 90


def create_render_grant(
    *,
    kind: str,
    language: str,
    job_id: str,
    invoice_id: str | None = None,
    printer_name: str | None = None,
    paper_width_mm: int | None = None,
    dots_width: int | None = None,
) -> str:
    """Mint a short-lived, single-purpose JWT authorizing one PDF render.

    The agent presents this to the web layer's canonical render route. The web
    layer verifies it server-to-server and renders exactly the named document —
    it cannot mint or widen the grant. ``kind`` is ``invoice`` (the saved receipt
    for ``invoice_id``) or ``test_page`` (a printer calibration page that names
    no invoice, carrying only the calibration numbers needed to draw it).
    ``type`` is ``render`` so a render grant is never accepted as an access
    token, and ``sub`` reuses the job id for traceability.
    """
    payload: dict[str, Any] = {
        "sub": f"print-job:{job_id}",
        "type": "render",
        "kind": kind,
        "language": language,
        "job_id": job_id,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(seconds=RENDER_GRANT_TTL_SECONDS)).timestamp()),
    }
    if invoice_id is not None:
        payload["invoice_id"] = invoice_id
    if printer_name is not None:
        payload["printer_name"] = printer_name
    if paper_width_mm is not None:
        payload["paper_width_mm"] = paper_width_mm
    if dots_width is not None:
        payload["dots_width"] = dots_width
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_render_grant(token: str) -> dict[str, Any]:
    """Verify a render grant and return its scoped claims.

    An invoice grant must name its invoice; a test-page grant must not, so a
    malformed token can never turn into an arbitrary-invoice render.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired render grant") from exc
    kind = payload.get("kind")
    if payload.get("type") != "render" or not payload.get("job_id"):
        raise TokenError("Invalid render grant")
    if kind == "invoice" and not payload.get("invoice_id"):
        raise TokenError("Invalid render grant")
    if kind == "test_page" and payload.get("invoice_id"):
        raise TokenError("Invalid render grant")
    if kind not in {"invoice", "test_page"}:
        raise TokenError("Invalid render grant")
    return payload

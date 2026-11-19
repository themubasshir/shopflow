from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import AuthSession, Role, Shop, User, UserCounter

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Authenticated caller context.

    ``assigned_counter_ids`` holds the counters this user may bill at. It is
    populated from ``user_counters`` for cashiers; owners/managers may bill at
    any active counter and so carry ``None`` ("unrestricted").
    """

    user_id: uuid.UUID
    shop_id: uuid.UUID
    email: str
    name: str
    role_code: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    assigned_counter_ids: frozenset[uuid.UUID] | None = None
    session_id: uuid.UUID | None = None
    is_demo: bool = False

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )

    def require_write(self, permission: str) -> None:
        if self.is_demo:
            raise HTTPException(status_code=401, detail="Authentication required")
        self.require(permission)

    @property
    def can_manage_counters(self) -> bool:
        """True when the principal may bill at any counter (not restricted to
        a per-user assignment)."""
        return self.assigned_counter_ids is None


def _assigned_counters(db: Session, user_id: uuid.UUID, role_code: str) -> frozenset | None:
    """Return the counters a user may bill at, or ``None`` for unrestricted.

    Owners and managers can work any active counter, so they have no
    restriction. Cashiers (and any other role) are limited to rows in
    ``user_counters`` — an empty set means "assigned to nothing".
    """
    if role_code in {"owner", "manager"}:
        return None
    rows = db.scalars(select(UserCounter.counter_id).where(UserCounter.user_id == user_id)).all()
    return frozenset(rows)


def _session_is_live(db: Session, jti: str | None, user_id: uuid.UUID) -> bool:
    """A token is only live while its auth_sessions row exists and is not
    revoked. Tokens minted before Phase 2B have no jti and are rejected."""
    if not jti:
        return False
    try:
        sid = uuid.UUID(jti)
    except ValueError:
        return False
    session = db.get(AuthSession, sid)
    if session is None or session.user_id != user_id:
        return False
    if session.revoked_at is not None:
        return False
    return session.expires_at > datetime.now(UTC)


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    """Resolve the caller for READ endpoints.

    Authenticated callers get their real principal. Without a bearer token the
    Phase 1 demo manager is injected — but only while ``settings.demo_mode``
    is on, so production never silently authorizes a read.
    """
    shop = db.scalar(select(Shop).where(Shop.is_active.is_(True)).order_by(Shop.created_at))
    if shop is None:
        raise HTTPException(status_code=503, detail="No shop configured yet")

    if credentials is None:
        if not settings.demo_mode or not shop.is_demo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        # Demo mode: no auth header -> manager role on the first shop.
        role = db.scalar(
            select(Role)
            .where(Role.shop_id == shop.id, Role.code == "manager")
            .order_by(Role.created_at)
        )
        user = db.scalar(
            select(User)
            .where(User.shop_id == shop.id, User.is_active.is_(True))
            .order_by(User.created_at)
        )
        if user is None or role is None:
            raise HTTPException(status_code=503, detail="Seed data missing")
        return Principal(
            user_id=user.id,
            shop_id=shop.id,
            email=user.email,
            name=user.name,
            role_code=role.code,
            permissions=frozenset(p for p in (role.permissions or []) if p.endswith(":read")),
            assigned_counter_ids=_assigned_counters(db, user.id, role.code),
            is_demo=True,
        )

    return get_authenticated_principal(_decode(credentials), db)


def _decode(credentials: HTTPAuthorizationCredentials) -> dict:
    try:
        return decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_authenticated(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dependency for write endpoints: a real JWT is mandatory — no demo fallback."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return _decode(credentials)


def get_authenticated_principal(
    payload: dict = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> Principal:
    """Resolve a Principal strictly from a valid, *live* token.

    Verifies the user is still an active member of the claimed shop AND that
    the session (``jti``) has not been revoked by logout or account disable.
    """
    user_id = uuid.UUID(payload["sub"])
    user = db.get(User, user_id)
    if user is None or not user.is_active or str(user.shop_id) != payload.get("shop_id"):
        raise HTTPException(status_code=401, detail="Invalid or inactive account")
    if not _session_is_live(db, payload.get("jti"), user_id):
        raise HTTPException(status_code=401, detail="Session expired or signed out")
    role = db.get(Role, user.role_id)
    role_code = role.code if role else payload.get("role", "cashier")
    return Principal(
        user_id=user.id,
        shop_id=user.shop_id,
        email=user.email,
        name=user.name,
        role_code=role_code,
        permissions=frozenset((role.permissions if role else []) or []),
        assigned_counter_ids=_assigned_counters(db, user.id, role_code),
        session_id=uuid.UUID(payload["jti"]) if payload.get("jti") else None,
    )


def assert_counter_allowed(principal: Principal, counter_id: uuid.UUID) -> None:
    """Reject a billing request for a counter the caller is not assigned to.

    The counter id from the request body is never trusted — owners/managers
    (``assigned_counter_ids is None``) may use any counter, others must match
    an explicit ``user_counters`` row.
    """
    if principal.assigned_counter_ids is None:
        return
    if counter_id not in principal.assigned_counter_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not assigned to this counter",
        )

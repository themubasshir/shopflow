from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import Role, Shop, User

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Authenticated caller context. Demo mode injects a manager principal."""

    user_id: uuid.UUID
    shop_id: uuid.UUID
    email: str
    name: str
    role_code: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_demo: bool = False

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    shop = db.scalar(select(Shop).where(Shop.is_active.is_(True)).order_by(Shop.created_at))
    if shop is None:
        raise HTTPException(status_code=503, detail="No shop configured yet")

    if credentials is None:
        # Phase 1 demo mode: no auth configured -> manager role on the first shop.
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
            permissions=frozenset(role.permissions or []),
            is_demo=True,
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return Principal(
        user_id=uuid.UUID(payload["sub"]),
        shop_id=uuid.UUID(payload["shop_id"]),
        email=payload.get("email", ""),
        name=payload.get("name", ""),
        role_code=payload.get("role", "cashier"),
        permissions=frozenset(payload.get("permissions") or []),
    )


def require_authenticated(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dependency for write endpoints: a real JWT is mandatory — no demo fallback."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        return decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_authenticated_principal(
    payload: dict = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> Principal:
    """Resolve a Principal strictly from a valid JWT, and verify the user is
    still an active member of the claimed shop."""
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active or str(user.shop_id) != payload.get("shop_id"):
        raise HTTPException(status_code=401, detail="Invalid or inactive account")
    role = db.get(Role, user.role_id)
    return Principal(
        user_id=user.id,
        shop_id=user.shop_id,
        email=user.email,
        name=user.name,
        role_code=role.code if role else payload.get("role", "cashier"),
        permissions=frozenset((role.permissions if role else []) or []),
    )

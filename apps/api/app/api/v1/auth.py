from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.api.deps import (
    Principal,
    get_authenticated_principal,
    get_principal,
)
from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import AuditLog, AuthSession, Role, User
from app.schemas.shop import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    TokenOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force guard for the staff login (per email+IP sliding window).
_login_limiter = SlidingWindowLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)


def _client_ip(request: Request) -> str:
    # The web app proxies same-origin; use the direct peer.
    return request.client.host if request.client else "unknown"


def _audit(
    db: Session,
    *,
    shop_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    after: dict | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            shop_id=shop_id,
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            after=after,
            ip_address=ip,
        )
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    ip = _client_ip(request)
    key = f"{body.email.lower()}|{ip}"
    if _login_limiter.check(key) <= 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(_login_limiter.retry_after(key))},
        )

    user = db.scalar(select(User).options(selectinload(User.role)).where(User.email == body.email))
    # verify_password always runs a hash check to blunt user-enumeration timing.
    if user is None or not verify_password(body.password, user.password_hash):
        _login_limiter.hit(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        _login_limiter.hit(key)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    role: Role = user.role
    session = AuthSession(
        shop_id=user.shop_id,
        user_id=user.id,
        jti=uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    db.flush()

    user.last_login_at = datetime.now(UTC)
    _audit(
        db,
        shop_id=user.shop_id,
        actor_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        ip=ip,
    )
    db.commit()

    token = create_access_token(
        str(user.id),
        shop_id=str(user.shop_id),
        role=role.code,
        permissions=list(role.permissions or []),
        session_id=str(session.id),
    )
    return TokenOut(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    """Revoke the caller's session so the token dies immediately."""
    if principal.session_id is not None:
        session = db.get(AuthSession, principal.session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
    _audit(
        db,
        shop_id=principal.shop_id,
        actor_id=principal.user_id,
        action="auth.logout",
        entity_type="user",
        entity_id=principal.user_id,
    )
    db.commit()


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordRequest,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    """Change the caller's own password. Requires the current password and
    revokes every other live session so an old token cannot keep working."""
    user = db.get(User, principal.user_id)
    if user is None or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    try:
        user.password_hash = hash_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Keep this session alive; sign out every other device/session.
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.id != principal.session_id,
        )
        .values(revoked_at=datetime.now(UTC))
    )
    _audit(
        db,
        shop_id=principal.shop_id,
        actor_id=principal.user_id,
        action="auth.password_change",
        entity_type="user",
        entity_id=principal.user_id,
    )
    db.commit()


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> MeOut:
    user = db.get(User, principal.user_id)
    assigned = (
        [str(c) for c in sorted(principal.assigned_counter_ids, key=str)]
        if principal.assigned_counter_ids is not None
        else None
    )
    return MeOut(
        id=principal.user_id,
        name=principal.name,
        email=principal.email,
        preferred_locale=user.preferred_locale if user else "en",
        role=principal.role_code,
        permissions=sorted(principal.permissions),
        assigned_counter_ids=assigned,
        is_demo=principal.is_demo,
    )

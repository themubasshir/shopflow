from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal, get_principal
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import Role, User
from app.schemas.shop import LoginRequest, MeOut, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).options(selectinload(User.role)).where(User.email == body.email))
    # verify_password always runs a hash check to blunt user-enumeration timing.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    role: Role = user.role
    token = create_access_token(
        str(user.id),
        shop_id=str(user.shop_id),
        role=role.code,
        permissions=list(role.permissions or []),
    )
    return TokenOut(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(get_principal)) -> MeOut:
    return MeOut(
        id=principal.user_id,
        name=principal.name,
        email=principal.email,
        preferred_locale="en",
        role=principal.role_code,
        permissions=sorted(principal.permissions),
    )

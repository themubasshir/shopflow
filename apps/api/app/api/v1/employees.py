"""Employee management (Phase 2B) — owner-facing staff administration.

All endpoints require ``employees:manage`` (owner by default; a manager can be
granted it). Password hashes are never returned; reset only stores a new hash.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal, get_authenticated_principal
from app.core.errors import NotFoundError, ValidationError
from app.core.security import hash_password
from app.db.session import get_db
from app.models import AuditLog, AuthSession, Counter, Role, User, UserCounter
from app.schemas.shop import (
    CounterAssignRequest,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    ResetPasswordRequest,
    RoleOut,
)

router = APIRouter(prefix="/employees", tags=["employees"])

_MANAGE = "employees:manage"


def _audit(
    db: Session, principal: Principal, action: str, entity_id: uuid.UUID, after: dict
) -> None:
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action=action,
            entity_type="user",
            entity_id=entity_id,
            after=after,
        )
    )


def _to_out(db: Session, user: User) -> EmployeeOut:
    counters = db.scalars(
        select(UserCounter.counter_id).where(UserCounter.user_id == user.id)
    ).all()
    role = user.role
    return EmployeeOut(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role_code=role.code if role else "",
        role_name_en=role.name_en if role else "",
        role_name_bn=role.name_bn if role else "",
        is_active=user.is_active,
        preferred_locale=user.preferred_locale,
        last_login_at=user.last_login_at,
        assigned_counter_ids=list(counters),
        created_at=user.created_at,
    )


def _guard_target(principal: Principal, target: User) -> None:
    """An employee may not disable/reset/edit the shop's owner unless they are
    the owner; and never themselves via the admin path."""
    if target.id == principal.user_id:
        raise ValidationError(
            "Use your account menu to change your own profile",
            details={"code": "self_admin"},
        )
    target_role = target.role.code if target.role else ""
    if target_role == "owner" and principal.role_code != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can manage an owner account",
        )


def _get_user(db: Session, principal: Principal, user_id: uuid.UUID) -> User:
    user = db.scalar(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id, User.shop_id == principal.shop_id)
    )
    if user is None:
        raise NotFoundError("Employee not found")
    return user


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[EmployeeOut]:
    principal.require(_MANAGE)
    rows = db.scalars(
        select(User)
        .options(selectinload(User.role))
        .where(User.shop_id == principal.shop_id)
        .order_by(User.is_active.desc(), User.name)
    ).all()
    return [_to_out(db, u) for u in rows]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[RoleOut]:
    principal.require(_MANAGE)
    rows = db.scalars(
        select(Role).where(Role.shop_id == principal.shop_id).order_by(Role.code)
    ).all()
    return [RoleOut(id=r.id, code=r.code, name_en=r.name_en, name_bn=r.name_bn) for r in rows]


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    principal.require(_MANAGE)
    role = db.get(Role, body.role_id)
    if role is None or role.shop_id != principal.shop_id:
        raise ValidationError("Unknown role", details={"field": "role_id"})
    # Privilege escalation: a non-owner cannot create another owner.
    if role.code == "owner" and principal.role_code != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can create an owner account",
        )
    exists = db.scalar(
        select(User.id).where(User.shop_id == principal.shop_id, User.email == body.email)
    )
    if exists:
        raise ValidationError("Email is already in use", details={"field": "email"})

    try:
        password_hash = hash_password(body.password)
    except ValueError as exc:
        raise ValidationError(str(exc), details={"field": "password"}) from exc

    user = User(
        shop_id=principal.shop_id,
        role_id=role.id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        password_hash=password_hash,
        preferred_locale=body.preferred_locale,
        is_active=True,
    )
    db.add(user)
    db.flush()
    _assign_counters(db, user, body.counter_ids, principal)
    _audit(db, principal, "employee.create", user.id, {"email": user.email, "role": role.code})
    db.commit()
    return _to_out(db, user)


@router.patch("/{user_id}", response_model=EmployeeOut)
def update_employee(
    user_id: uuid.UUID,
    body: EmployeeUpdate,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    principal.require(_MANAGE)
    user = _get_user(db, principal, user_id)
    _guard_target(principal, user)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("role_id"):
        role = db.get(Role, changes["role_id"])
        if role is None or role.shop_id != principal.shop_id:
            raise ValidationError("Unknown role", details={"field": "role_id"})
        if role.code == "owner" and principal.role_code != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can grant the owner role",
            )
        user.role_id = role.id
    if changes.get("name"):
        user.name = changes["name"]
    if "phone" in changes:
        user.phone = changes["phone"]
    if changes.get("preferred_locale"):
        user.preferred_locale = changes["preferred_locale"]
    _audit(db, principal, "employee.update", user.id, changes)
    db.commit()
    return _to_out(db, user)


@router.post("/{user_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable_employee(
    user_id: uuid.UUID,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    """Deactivate an account without deleting history. Immediately revokes all
    of the employee's live sessions so an issued token stops working."""
    principal.require(_MANAGE)
    user = _get_user(db, principal, user_id)
    _guard_target(principal, user)
    user.is_active = False
    _revoke_all_sessions(db, user.id)
    _audit(db, principal, "employee.disable", user.id, {"email": user.email})
    db.commit()


@router.post("/{user_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
def enable_employee(
    user_id: uuid.UUID,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    principal.require(_MANAGE)
    user = _get_user(db, principal, user_id)
    _guard_target(principal, user)
    user.is_active = True
    _audit(db, principal, "employee.enable", user.id, {"email": user.email})
    db.commit()


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    body: ResetPasswordRequest,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> None:
    """Owner-controlled reset: stores a new hash and signs the employee out."""
    principal.require(_MANAGE)
    user = _get_user(db, principal, user_id)
    _guard_target(principal, user)
    try:
        user.password_hash = hash_password(body.new_password)
    except ValueError as exc:
        raise ValidationError(str(exc), details={"field": "new_password"}) from exc
    _revoke_all_sessions(db, user.id)
    _audit(db, principal, "employee.reset_password", user.id, {"email": user.email})
    db.commit()


@router.put("/{user_id}/counters", response_model=EmployeeOut)
def assign_counters(
    user_id: uuid.UUID,
    body: CounterAssignRequest,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> EmployeeOut:
    principal.require(_MANAGE)
    user = _get_user(db, principal, user_id)
    _guard_target(principal, user)
    _assign_counters(db, user, body.counter_ids, principal)
    _audit(
        db,
        principal,
        "employee.assign_counters",
        user.id,
        {"counter_ids": [str(c) for c in body.counter_ids]},
    )
    db.commit()
    return _to_out(db, user)


def _assign_counters(
    db: Session, user: User, counter_ids: list[uuid.UUID], principal: Principal
) -> None:
    # Validate every counter belongs to this shop and is active.
    if counter_ids:
        valid = set(
            db.scalars(
                select(Counter.id).where(
                    Counter.id.in_(counter_ids),
                    Counter.shop_id == principal.shop_id,
                )
            ).all()
        )
        bad = [c for c in counter_ids if c not in valid]
        if bad:
            raise ValidationError("Unknown counter", details={"counter_ids": [str(c) for c in bad]})
    # Replace the assignment set.
    for row in db.scalars(
        select(UserCounter).where(UserCounter.user_id == user.id)
    ).all():
        db.delete(row)
    for cid in counter_ids:
        db.add(UserCounter(shop_id=user.shop_id, user_id=user.id, counter_id=cid))
    db.flush()


def _revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )

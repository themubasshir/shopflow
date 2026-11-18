"""Counter management (Phase 2B) — activate/deactivate and view staff
assignments. Requires ``counters:manage`` (owner)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import AuditLog, Counter, User, UserCounter
from app.schemas.shop import CounterOut, CounterUpdate

router = APIRouter(prefix="/manage/counters", tags=["counters"])

_MANAGE = "counters:manage"


@router.get("", response_model=list[CounterOut])
def list_all_counters(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[CounterOut]:
    """All counters for the shop, active and inactive (management view)."""
    principal.require(_MANAGE)
    rows = db.scalars(
        select(Counter).where(Counter.shop_id == principal.shop_id).order_by(Counter.sort_order)
    ).all()
    return [
        CounterOut(
            id=c.id, code=c.code, name_en=c.name_en, name_bn=c.name_bn, is_active=c.is_active
        )
        for c in rows
    ]


@router.patch("/{counter_id}", response_model=CounterOut)
def update_counter(
    counter_id: uuid.UUID,
    body: CounterUpdate,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> CounterOut:
    """Activate or deactivate a counter. Deactivating stops it appearing on the
    billing selector and blocks new bills at it."""
    principal.require(_MANAGE)
    counter = db.get(Counter, counter_id)
    if counter is None or counter.shop_id != principal.shop_id:
        raise NotFoundError("Counter not found")
    counter.is_active = body.is_active
    if body.name_en:
        counter.name_en = body.name_en
    if body.name_bn:
        counter.name_bn = body.name_bn
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action="counter.update",
            entity_type="counter",
            entity_id=counter.id,
            after={"is_active": body.is_active},
        )
    )
    db.commit()
    return CounterOut(
        id=counter.id,
        code=counter.code,
        name_en=counter.name_en,
        name_bn=counter.name_bn,
        is_active=counter.is_active,
    )


@router.get("/{counter_id}/staff", response_model=list[dict])
def counter_staff(
    counter_id: uuid.UUID,
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[dict]:
    principal.require(_MANAGE)
    counter = db.get(Counter, counter_id)
    if counter is None or counter.shop_id != principal.shop_id:
        raise NotFoundError("Counter not found")
    rows = db.execute(
        select(User.name, User.email, User.is_active)
        .join(UserCounter, UserCounter.user_id == User.id)
        .where(UserCounter.counter_id == counter_id)
    ).all()
    return [{"name": n, "email": e, "is_active": a} for n, e, a in rows]

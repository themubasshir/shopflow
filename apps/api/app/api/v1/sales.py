from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import (
    Principal,
    get_authenticated_principal,
    get_principal,
)
from app.db.session import get_db
from app.models import Counter, Customer, Invoice, LoyaltyAccount
from app.schemas.common import Paginated
from app.schemas.reports import LoyaltyAccountOut
from app.schemas.sales import (
    InvoiceCreate,
    InvoiceCreateOut,
    InvoiceOut,
)
from app.schemas.shop import CounterOut
from app.services.billing import finalize_invoice
from app.services.loyalty import can_redeem
from app.services.loyalty_accounts import POLICY

router = APIRouter(tags=["sales"])


@router.get("/counters", response_model=list[CounterOut])
def list_counters(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[CounterOut]:
    """Active checkout counters for the caller's shop (billing screen)."""
    rows = db.execute(
        select(Counter)
        .where(Counter.shop_id == principal.shop_id, Counter.is_active.is_(True))
        .order_by(Counter.sort_order)
    ).scalars()
    return [
        CounterOut(
            id=c.id, code=c.code, name_en=c.name_en, name_bn=c.name_bn, is_active=c.is_active
        )
        for c in rows
    ]


@router.get("/loyalty/accounts", response_model=Paginated[LoyaltyAccountOut])
def list_loyalty_accounts(
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Paginated[LoyaltyAccountOut]:
    principal.require("loyalty:read")
    can_view_history = (
        principal.assigned_counter_ids is None and "reports:read" in principal.permissions
    )
    stmt = (
        select(LoyaltyAccount, Customer)
        .join(Customer, LoyaltyAccount.customer_id == Customer.id)
        .where(LoyaltyAccount.shop_id == principal.shop_id, Customer.shop_id == principal.shop_id)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(LoyaltyAccount.points_balance.desc(), LoyaltyAccount.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Paginated(
        items=[
            LoyaltyAccountOut(
                customer_id=c.id,
                customer_name=c.name,
                customer_name_bn=c.name_bn,
                phone=c.phone,
                points_balance=a.points_balance,
                lifetime_earned=a.lifetime_earned if can_view_history else 0,
                lifetime_redeemed=a.lifetime_redeemed if can_view_history else 0,
                can_redeem=c.is_active and a.is_active and can_redeem(a.points_balance, POLICY),
            )
            for a, c in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/invoices", response_model=Paginated[InvoiceOut])
def list_invoices(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Paginated[InvoiceOut]:
    principal.require("sales:read")
    stmt = (
        select(Invoice, Counter.code)
        .join(Counter, Invoice.counter_id == Counter.id)
        .where(Invoice.shop_id == principal.shop_id)
    )
    # Cashiers (and anyone restricted to assigned counters) only see the
    # invoice history for their own counters — not the whole shop's book.
    if principal.assigned_counter_ids is not None:
        if not principal.assigned_counter_ids:
            return Paginated(items=[], total=0, limit=limit, offset=offset)
        stmt = stmt.where(Invoice.counter_id.in_(principal.assigned_counter_ids))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.options(selectinload(Invoice.items), selectinload(Invoice.payments))
        .order_by(Invoice.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Paginated(
        items=[
            InvoiceOut(
                id=i.id,
                invoice_number=i.invoice_number,
                counter_code=code,
                customer_name=None,
                status=i.status,
                subtotal=i.subtotal,
                discount_total=i.discount_total,
                loyalty_discount=i.loyalty_discount,
                tax_total=i.tax_total,
                total=i.total,
                paid_total=i.paid_total,
                due_total=i.due_total,
                finalized_at=i.finalized_at,
                created_at=i.created_at,
                payment_methods=[p.method for p in i.payments],
            )
            for i, code in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/invoices",
    response_model=InvoiceCreateOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": InvoiceCreateOut, "description": "Idempotent replay"}},
)
def create_invoice(
    body: InvoiceCreate,
    response: Response,
    idempotency_key: str = Header(min_length=8, max_length=120, alias="Idempotency-Key"),
    principal: Principal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> InvoiceCreateOut:
    """Finalize a bill atomically: stock deduction, payment, loyalty earn and
    the idempotency record all commit — or roll back — together. Cashier
    identity comes from the JWT; counter must belong to the caller's shop."""
    out = finalize_invoice(db, principal, body, idempotency_key)
    if out.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return out

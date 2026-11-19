from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal, get_authenticated_principal
from app.db.session import get_db
from app.models import Purchase, Supplier, SupplierLedger
from app.schemas.common import Paginated
from app.schemas.purchasing import (
    PurchaseOut,
    PurchaseWrite,
    Reason,
    ReceiveWrite,
    SupplierEntry,
    SupplierOut,
    SupplierPaymentWrite,
    SupplierWrite,
)
from app.services.purchasing import (
    cancel_purchase,
    create_purchase,
    pay_purchase,
    purchase_by_id,
    purchase_result,
    receive_purchase,
    reverse_purchase,
    save_supplier,
    supplier_by_id,
    supplier_result,
)
from app.services.stock import inventory_access

router = APIRouter(tags=["purchasing"])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Principal, Depends(get_authenticated_principal)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str, Query(max_length=160)]


def window(db, stmt, limit, offset):
    count = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return rows, count


@router.get("/suppliers", response_model=Paginated[SupplierOut])
def list_suppliers(
    db: Db,
    principal: Caller,
    q: Search = "",
    active: bool | None = None,
    limit: Limit = 40,
    offset: Offset = 0,
):
    inventory_access(principal)
    stmt = select(Supplier).where(Supplier.shop_id == principal.shop_id)
    if active is not None:
        stmt = stmt.where(Supplier.is_active == active)
    if q.strip():
        stmt = stmt.where(
            or_(
                *(
                    field.icontains(q.strip(), autoescape=True)
                    for field in (
                        Supplier.name,
                        Supplier.name_bn,
                        Supplier.phone,
                    )
                )
            )
        )
    rows, count = window(db, stmt.order_by(Supplier.name, Supplier.id), limit, offset)
    return Paginated(
        items=[supplier_result(db, s) for s in rows], total=count, limit=limit, offset=offset
    )


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def add_supplier(body: SupplierWrite, db: Db, principal: Caller):
    return save_supplier(db, principal, body)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def supplier_detail(supplier_id: UUID, db: Db, principal: Caller):
    inventory_access(principal)
    return supplier_result(db, supplier_by_id(db, principal, supplier_id))


@router.put("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: UUID, body: SupplierWrite, db: Db, principal: Caller):
    return save_supplier(db, principal, body, supplier_id)


@router.get("/suppliers/{supplier_id}/ledger", response_model=Paginated[SupplierEntry])
def supplier_ledger(
    supplier_id: UUID, db: Db, principal: Caller, limit: Limit = 40, offset: Offset = 0
):
    inventory_access(principal)
    supplier_by_id(db, principal, supplier_id)
    stmt = (
        select(SupplierLedger)
        .where(SupplierLedger.supplier_id == supplier_id)
        .order_by(
            SupplierLedger.created_at.desc(),
            SupplierLedger.id,
        )
    )
    rows, count = window(db, stmt, limit, offset)
    return Paginated(
        items=[SupplierEntry.model_validate(p) for p in rows],
        total=count,
        limit=limit,
        offset=offset,
    )


@router.get("/purchases", response_model=Paginated[PurchaseOut])
def list_purchases(
    db: Db,
    principal: Caller,
    q: Search = "",
    supplier_id: UUID | None = None,
    limit: Limit = 40,
    offset: Offset = 0,
):
    inventory_access(principal)
    stmt = (
        select(Purchase)
        .where(Purchase.shop_id == principal.shop_id)
        .options(selectinload(Purchase.items))
    )
    if supplier_id is not None:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)
    if q.strip():
        stmt = stmt.where(
            or_(
                Purchase.purchase_number.icontains(q.strip(), autoescape=True),
                Purchase.supplier_invoice_number.icontains(q.strip(), autoescape=True),
            )
        )
    rows, count = window(db, stmt.order_by(Purchase.created_at.desc(), Purchase.id), limit, offset)
    return Paginated(
        items=[purchase_result(p) for p in rows], total=count, limit=limit, offset=offset
    )


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
def purchase_detail(purchase_id: UUID, db: Db, principal: Caller):
    inventory_access(principal)
    return purchase_result(purchase_by_id(db, principal, purchase_id))


@router.post("/purchases", response_model=PurchaseOut, status_code=201)
def add_purchase(body: PurchaseWrite, db: Db, principal: Caller, key: Key):
    return create_purchase(db, principal, body, key)


@router.post("/purchases/{purchase_id}/receive", response_model=PurchaseOut)
def receive(purchase_id: UUID, body: ReceiveWrite, db: Db, principal: Caller, key: Key):
    return receive_purchase(db, principal, purchase_id, body, key)


@router.post("/purchases/{purchase_id}/payments", response_model=PurchaseOut)
def payment(purchase_id: UUID, body: SupplierPaymentWrite, db: Db, principal: Caller, key: Key):
    return pay_purchase(db, principal, purchase_id, body, key)


@router.post("/purchases/{purchase_id}/cancel", response_model=PurchaseOut)
def cancel(purchase_id: UUID, body: Reason, db: Db, principal: Caller, key: Key):
    return cancel_purchase(db, principal, purchase_id, body.reason, key)


@router.post("/purchases/{purchase_id}/reverse", response_model=PurchaseOut)
def reverse(purchase_id: UUID, body: Reason, db: Db, principal: Caller, key: Key):
    return reverse_purchase(db, principal, purchase_id, body.reason, key)

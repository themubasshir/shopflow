from datetime import UTC, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_authenticated_principal
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import MedicineBatch, Product, ProductUnit, StockMovement
from app.schemas.catalog import ProductUnitOut
from app.schemas.common import Paginated
from app.schemas.purchasing import (
    BatchOut,
    BatchState,
    MovementOut,
    StockChange,
    StockValue,
    ThresholdWrite,
)
from app.services.inventory import adjust_stock, set_batch_state, set_threshold, stock_value
from app.services.stock import expiry_status, inventory_access, shop_date

router = APIRouter(prefix="/inventory", tags=["inventory"])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Principal, Depends(get_authenticated_principal)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/batches", response_model=Paginated[BatchOut])
def list_batches(
    db: Db,
    principal: Caller,
    q: Annotated[str, Query(max_length=160)] = "",
    window: Literal["all", "30", "60", "90", "expired", "quarantined"] = "all",
    product_id: UUID | None = None,
    batch_id: UUID | None = None,
    limit: Limit = 40,
    offset: Offset = 0,
):
    inventory_access(principal)
    today = shop_date(db, principal.shop_id)
    base_price = (
        select(ProductUnit.selling_price)
        .where(ProductUnit.product_id == Product.id, ProductUnit.is_base.is_(True))
        .correlate(Product)
        .scalar_subquery()
    )
    stmt = (
        select(MedicineBatch, Product, base_price)
        .join(Product, Product.id == MedicineBatch.product_id)
        .where(
            MedicineBatch.shop_id == principal.shop_id,
            Product.shop_id == principal.shop_id,
        )
    )
    if product_id:
        stmt = stmt.where(MedicineBatch.product_id == product_id)
    if batch_id:
        stmt = stmt.where(MedicineBatch.id == batch_id)
    if q.strip():
        stmt = stmt.where(
            or_(
                *(
                    field.icontains(q.strip(), autoescape=True)
                    for field in (
                        MedicineBatch.batch_number,
                        Product.name_en,
                        Product.name_bn,
                    )
                )
            )
        )
    if window == "quarantined":
        stmt = stmt.where(MedicineBatch.quarantined.is_(True), MedicineBatch.quantity_on_hand > 0)
    elif window == "expired":
        stmt = stmt.where(MedicineBatch.expiry_date <= today, MedicineBatch.quantity_on_hand > 0)
    elif window != "all":
        stmt = stmt.where(
            MedicineBatch.expiry_date > today,
            MedicineBatch.expiry_date <= today + timedelta(days=int(window)),
            MedicineBatch.quantity_on_hand > 0,
        )
    count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(MedicineBatch.expiry_date, MedicineBatch.id).limit(limit).offset(offset)
    )
    return Paginated(
        items=[
            BatchOut(
                id=batch.id,
                product_id=p.id,
                supplier_id=batch.supplier_id,
                product_name=p.name_en,
                product_name_bn=p.name_bn,
                batch_number=batch.batch_number,
                expiry_date=batch.expiry_date,
                manufacture_date=batch.manufacture_date,
                received_at=batch.received_at.replace(tzinfo=UTC) if batch.received_at else None,
                quantity_received=batch.quantity_received,
                quantity_on_hand=batch.quantity_on_hand,
                purchase_cost=batch.purchase_cost,
                price_reference=price,
                days_to_expiry=(batch.expiry_date - today).days,
                status=expiry_status(batch, today),
            )
            for batch, p, price in rows
        ],
        total=count,
        limit=limit,
        offset=offset,
    )


@router.get("/movements", response_model=Paginated[MovementOut])
def list_movements(
    db: Db,
    principal: Caller,
    product_id: UUID | None = None,
    limit: Limit = 40,
    offset: Offset = 0,
):
    inventory_access(principal)
    stmt = select(StockMovement).where(StockMovement.shop_id == principal.shop_id)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(StockMovement.created_at.desc(), StockMovement.id).limit(limit).offset(offset)
    )
    return Paginated(
        items=[MovementOut.model_validate(m) for m in rows], total=count, limit=limit, offset=offset
    )


@router.get("/products/{product_id}/units", response_model=list[ProductUnitOut])
def product_units(product_id: UUID, db: Db, principal: Caller):
    inventory_access(principal)
    if not db.scalar(
        select(Product.id).where(Product.id == product_id, Product.shop_id == principal.shop_id)
    ):
        raise NotFoundError("Product not found")
    return list(
        db.scalars(
            select(ProductUnit)
            .where(ProductUnit.product_id == product_id)
            .order_by(
                ProductUnit.is_base.desc(),
                ProductUnit.name,
                ProductUnit.id,
            )
        )
    )


@router.get("/products/{product_id}/valuation", response_model=StockValue)
def valuation(product_id: UUID, db: Db, principal: Caller):
    inventory_access(principal)
    return stock_value(db, principal.shop_id, product_id)


@router.post("/adjustments", response_model=StockValue)
def adjustment(body: StockChange, db: Db, principal: Caller, key: Key):
    return adjust_stock(db, principal, body, key)


@router.put("/batches/{batch_id}/state", response_model=StockValue)
def batch_state(batch_id: UUID, body: BatchState, db: Db, principal: Caller, key: Key):
    return set_batch_state(db, principal, batch_id, body, key)


@router.put("/products/{product_id}/threshold", response_model=StockValue)
def threshold(product_id: UUID, body: ThresholdWrite, db: Db, principal: Caller, key: Key):
    return set_threshold(db, principal, product_id, body, key)

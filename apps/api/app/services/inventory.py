from collections.abc import Callable
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import NotFoundError, ValidationError
from app.models import MedicineBatch, Product, StockLot, StockMovement
from app.schemas.purchasing import BatchState, StockChange, StockValue, ThresholdWrite
from app.services.idempotency import fingerprint, reserve_request
from app.services.purchasing import audit
from app.services.stock import (
    MAX_MONEY,
    MONEY,
    ZERO,
    available_stock,
    base_quantity,
    find_batch,
    inventory_access,
    lock_products,
    post_stock,
    shop_date,
)


def stock_value(db: Session, shop_id: UUID, product_id: UUID) -> StockValue:
    saleable = available_stock(shop_date(db, shop_id))
    recorded = (
        select(func.coalesce(func.sum(StockMovement.quantity), 0))
        .where(
            StockMovement.product_id == Product.id,
            StockMovement.shop_id == Product.shop_id,
        )
        .correlate(Product)
        .scalar_subquery()
    )
    value = (
        select(
            func.coalesce(
                func.sum(
                    StockLot.cost_amount * StockLot.quantity_remaining / StockLot.quantity_received
                ),
                0,
            )
        )
        .where(StockLot.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )
    valued_quantity = (
        select(func.coalesce(func.sum(StockLot.quantity_remaining), 0))
        .where(
            StockLot.product_id == Product.id,
            StockLot.cost_amount.is_not(None),
        )
        .correlate(Product)
        .scalar_subquery()
    )
    row = db.execute(
        select(Product, saleable, recorded, value, valued_quantity).where(
            Product.id == product_id,
            Product.shop_id == shop_id,
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Product not found")
    product, available, ledger, total, valued = row
    return StockValue(
        product_id=product_id,
        quantity_on_hand=product.stock_on_hand,
        available=available,
        ledger_quantity=ledger,
        value=total.quantize(MONEY),
        unvalued_quantity=product.stock_on_hand - valued,
        low_stock_threshold=product.low_stock_threshold,
    )


def _change(
    db: Session,
    principal: Principal,
    key: str,
    action: str,
    body: dict,
    operation: Callable[[], UUID],
) -> StockValue:
    inventory_access(principal, write=True)
    try:
        record = reserve_request(
            db, principal.shop_id, key, fingerprint({"action": action, "body": body})
        )
        if record.response_body is not None:
            result = StockValue.model_validate(record.response_body)
        else:
            product_id = operation()
            db.flush()
            result = stock_value(db, principal.shop_id, product_id)
            record.response_body = result.model_dump(mode="json")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def adjust_stock(db: Session, principal: Principal, body: StockChange, key: str) -> StockValue:
    def adjust():
        product = lock_products(db, principal.shop_id, [body.product_id]).get(body.product_id)
        if product is None:
            raise NotFoundError("Product not found")
        batch = find_batch(db, principal.shop_id, body.batch_id) if body.batch_id else None
        if product.is_medicine != bool(batch) or (batch and batch.product_id != product.id):
            raise ValidationError("A matching batch is required for medicine stock changes")
        if body.action == "add" and batch:
            raise ValidationError("Use purchase receiving to add medicine stock")
        if body.unit_cost is not None and body.action != "add":
            raise ValidationError("Unit cost only applies to stock additions")
        if body.action in {"dispose", "supplier_return"}:
            if batch is None or not (
                batch.quarantined or batch.expiry_date <= shop_date(db, principal.shop_id)
            ):
                raise ValidationError(
                    "Disposal or supplier return requires expired or quarantined stock"
                )
            if body.action == "supplier_return" and batch.supplier_id is None:
                raise ValidationError("This batch has no recorded supplier")
        qty = base_quantity(product, body.quantity, 1)
        ref = uuid4()
        lot = None
        if body.action == "add":
            cost = (body.unit_cost * qty).quantize(MONEY) if body.unit_cost is not None else None
            if cost is not None and cost > MAX_MONEY:
                raise ValidationError("Stock adjustment value exceeds the supported limit")
            lot = StockLot(
                product_id=product.id,
                quantity_received=qty,
                quantity_remaining=qty,
                cost_amount=cost,
            )
            db.add(lot)
            db.flush()
        kind = {"damage": "damage", "dispose": "damage", "supplier_return": "return"}.get(
            body.action, "adjustment"
        )
        post_stock(
            db,
            principal,
            product,
            qty if body.action == "add" else -qty,
            movement_type=kind,
            reference_type=body.action,
            reference_id=ref,
            batch=batch,
            lot=lot,
            note=body.reason,
        )
        audit(
            db,
            principal,
            "stock." + body.action,
            "product",
            product.id,
            batch_id=str(batch.id) if batch else None,
            reason=body.reason,
            quantity=str(qty),
            movement_reference=str(ref),
        )
        return product.id

    return _change(db, principal, key, "stock.adjust", body.model_dump(mode="json"), adjust)


def set_batch_state(db: Session, principal: Principal, batch_id: UUID, body: BatchState, key: str):
    def change():
        product_id = db.scalar(
            select(MedicineBatch.product_id).where(
                MedicineBatch.id == batch_id,
                MedicineBatch.shop_id == principal.shop_id,
            )
        )
        if product_id is None:
            raise NotFoundError("Medicine batch not found")
        lock_products(db, principal.shop_id, [product_id])
        batch = find_batch(db, principal.shop_id, batch_id)
        if not body.quarantined and batch.expiry_date <= shop_date(db, principal.shop_id):
            raise ValidationError("Expired batches cannot be released")
        batch.quarantined = body.quarantined
        audit(
            db,
            principal,
            "batch.quarantine" if body.quarantined else "batch.release",
            "medicine_batch",
            batch.id,
            reason=body.reason,
        )
        return product_id

    return _change(
        db,
        principal,
        key,
        "batch.state",
        {"id": str(batch_id), **body.model_dump(mode="json")},
        change,
    )


def set_threshold(
    db: Session, principal: Principal, product_id: UUID, body: ThresholdWrite, key: str
):
    def change():
        product = lock_products(db, principal.shop_id, [product_id]).get(product_id)
        if product is None:
            raise NotFoundError("Product not found")
        if body.quantity > ZERO:
            base_quantity(product, body.quantity, 1)
        product.low_stock_threshold = body.quantity
        audit(db, principal, "stock.threshold", "product", product.id, quantity=str(body.quantity))
        return product_id

    return _change(
        db,
        principal,
        key,
        "stock.threshold",
        {"id": str(product_id), **body.model_dump(mode="json")},
        change,
    )

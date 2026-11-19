from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    AuditLog,
    MedicineBatch,
    Product,
    Purchase,
    PurchaseItem,
    StockLot,
    Supplier,
    SupplierLedger,
    SupplierProduct,
)
from app.schemas.purchasing import (
    PurchaseOut,
    PurchaseWrite,
    ReceiveWrite,
    SupplierOut,
    SupplierPaymentWrite,
    SupplierWrite,
)
from app.services.idempotency import fingerprint, reserve_request
from app.services.stock import (
    MAX_MONEY,
    MAX_QUANTITY,
    MONEY,
    ZERO,
    base_quantity,
    inventory_access,
    lock_products,
    post_stock,
    shop_date,
)


def audit(db: Session, principal: Principal, action: str, entity: str, id: UUID, **data):
    db.add(
        AuditLog(
            shop_id=principal.shop_id,
            actor_user_id=principal.user_id,
            action=action,
            entity_type=entity,
            entity_id=id,
            after=data,
        )
    )


def supplier_by_id(db: Session, principal: Principal, supplier_id: UUID, *, lock=False) -> Supplier:
    stmt = select(Supplier).where(Supplier.id == supplier_id, Supplier.shop_id == principal.shop_id)
    supplier = db.scalar(stmt.with_for_update(key_share=True) if lock else stmt)
    if supplier is None:
        raise NotFoundError("Supplier not found")
    return supplier


def supplier_result(db: Session, supplier: Supplier) -> SupplierOut:
    products = db.scalars(
        select(SupplierProduct.product_id)
        .where(
            SupplierProduct.supplier_id == supplier.id,
        )
        .order_by(SupplierProduct.product_id)
    ).all()
    balance = db.scalar(
        select(func.coalesce(func.sum(SupplierLedger.amount), 0)).where(
            SupplierLedger.supplier_id == supplier.id,
        )
    )
    return SupplierOut(
        id=supplier.id,
        name=supplier.name,
        name_bn=supplier.name_bn,
        phone=supplier.phone,
        address=supplier.address,
        is_active=supplier.is_active,
        product_ids=list(products),
        balance=balance,
    )


def save_supplier(
    db: Session,
    principal: Principal,
    body: SupplierWrite,
    supplier_id: UUID | None = None,
) -> SupplierOut:
    inventory_access(principal, write=True)
    if supplier_id:
        supplier = supplier_by_id(db, principal, supplier_id, lock=True)
        changed = "supplier.update"
    else:
        supplier = Supplier(shop_id=principal.shop_id)
        db.add(supplier)
        changed = "supplier.create"
    for key, value in body.model_dump(exclude={"product_ids"}).items():
        setattr(supplier, key, value)
    ids = set(body.product_ids)
    known = set(
        db.scalars(
            select(Product.id).where(Product.shop_id == principal.shop_id, Product.id.in_(ids))
        )
    )
    if ids != known:
        raise ValidationError("One or more products do not belong to this shop")
    db.flush()
    db.execute(delete(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id))
    db.add_all(
        SupplierProduct(supplier_id=supplier.id, product_id=product_id)
        for product_id in sorted(ids)
    )
    audit(db, principal, changed, "supplier", supplier.id, active=body.is_active)
    db.flush()
    result = supplier_result(db, supplier)
    db.commit()
    return result


def purchase_result(purchase: Purchase) -> PurchaseOut:
    out = PurchaseOut.model_validate(purchase)
    if purchase.status in {"received", "partially_received"}:
        out.outstanding = purchase.received_total - purchase.paid_total
    return out


def purchase_by_id(db: Session, principal: Principal, purchase_id: UUID, *, lock=False):
    stmt = (
        select(Purchase)
        .where(
            Purchase.shop_id == principal.shop_id,
            Purchase.id == purchase_id,
        )
        .options(selectinload(Purchase.items))
    )
    purchase = db.scalar(stmt.with_for_update(key_share=True) if lock else stmt)
    if purchase is None:
        raise NotFoundError("Purchase not found")
    return purchase


def _idempotent_purchase(
    db: Session,
    principal: Principal,
    key: str,
    action: str,
    payload: dict,
    operation: Callable[[], Purchase],
) -> PurchaseOut:
    inventory_access(principal, write=True)
    try:
        record = reserve_request(
            db,
            principal.shop_id,
            key,
            fingerprint({"action": action, "payload": payload}),
        )
        if record.response_body is not None:
            result = PurchaseOut.model_validate(record.response_body)
        else:
            purchase = operation()
            db.flush()
            result = purchase_result(purchase)
            record.response_body = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == "uq_purchases_supplier_reference"
        ):
            raise ConflictError("Supplier invoice number is already in use") from exc
        raise
    except Exception:
        db.rollback()
        raise


def create_purchase(db: Session, principal: Principal, body: PurchaseWrite, key: str):
    def create():
        supplier = supplier_by_id(db, principal, body.supplier_id, lock=True)
        if not supplier.is_active:
            raise ValidationError("Supplier is inactive")
        products = lock_products(db, principal.shop_id, {row.product_id for row in body.items})
        today = shop_date(db, principal.shop_id)
        items = []
        subtotal = ZERO
        for row in body.items:
            product = products.get(row.product_id)
            if product is None or not product.is_active:
                raise NotFoundError("Active product not found")
            unit = next(
                (
                    u
                    for u in product.units
                    if (u.id == row.product_unit_id if row.product_unit_id else u.is_base)
                ),
                None,
            )
            if unit is None:
                raise ValidationError("Selling unit does not belong to this product")
            if product.is_medicine:
                if not row.batch_number or not row.expiry_date:
                    raise ValidationError("Medicine lines require a batch number and expiry date")
                if row.expiry_date <= today or (
                    row.manufacture_date
                    and (row.manufacture_date > today or row.manufacture_date >= row.expiry_date)
                ):
                    raise ValidationError("Medicine manufacture or expiry date is invalid")
            elif row.batch_number or row.expiry_date or row.manufacture_date:
                raise ValidationError("Batch fields apply only to medicines")
            gross = (row.quantity * row.unit_cost).quantize(MONEY)
            subtotal += gross
            items.append(
                PurchaseItem(
                    product_id=product.id,
                    product_unit_id=unit.id,
                    quantity=row.quantity,
                    conversion_factor=unit.conversion_factor,
                    ordered_base=base_quantity(product, row.quantity, unit.conversion_factor),
                    unit_cost=row.unit_cost,
                    line_total=gross,
                    received_base=ZERO,
                    batch_number=row.batch_number.upper() if row.batch_number else None,
                    expiry_date=row.expiry_date,
                    manufacture_date=row.manufacture_date,
                )
            )
        if subtotal > MAX_MONEY or body.discount_total > subtotal:
            raise ValidationError("Purchase totals exceed the supported amount or discount")
        net = subtotal - body.discount_total
        gross_so_far = allocated = ZERO
        for item in items:
            gross_so_far += item.line_total
            target = (net * gross_so_far / subtotal).quantize(MONEY) if subtotal else ZERO
            item.net_total = target - allocated
            allocated = target
        purchase = Purchase(
            shop_id=principal.shop_id,
            supplier_id=supplier.id,
            created_by=principal.user_id,
            purchase_number="PO-" + uuid4().hex.upper(),
            supplier_invoice_number=body.supplier_invoice_number,
            status="draft",
            subtotal=subtotal,
            discount_total=body.discount_total,
            total=net,
            received_total=ZERO,
            paid_total=ZERO,
            items=items,
        )
        db.add(purchase)
        db.flush()
        audit(db, principal, "purchase.create", "purchase", purchase.id)
        return purchase

    return _idempotent_purchase(
        db, principal, key, "purchase.create", body.model_dump(mode="json"), create
    )


def _batch_for_receipt(db, principal, purchase, item, today, received_at):
    if item.expiry_date <= today:
        raise ValidationError("Expired medicine cannot be received into saleable stock")
    candidates = db.scalars(
        select(MedicineBatch)
        .where(
            MedicineBatch.shop_id == principal.shop_id,
            MedicineBatch.product_id == item.product_id,
            func.upper(func.btrim(MedicineBatch.batch_number)) == item.batch_number,
        )
        .order_by(MedicineBatch.id)
        .with_for_update(key_share=True)
    ).all()
    if candidates:
        batch = candidates[0]
        if len(candidates) != 1 or (
            batch.expiry_date != item.expiry_date
            or (batch.supplier_id is not None and batch.supplier_id != purchase.supplier_id)
            or (
                item.manufacture_date
                and batch.manufacture_date
                and item.manufacture_date != batch.manufacture_date
            )
        ):
            raise ConflictError("Manufacturer batch already exists with conflicting details")
        if batch.quarantined or not batch.is_active:
            raise ConflictError("Release or resolve the existing batch before receiving it")
        if batch.supplier_id is None:
            batch.supplier_id = purchase.supplier_id
        if batch.manufacture_date is None:
            batch.manufacture_date = item.manufacture_date
        return batch
    batch = MedicineBatch(
        shop_id=principal.shop_id,
        product_id=item.product_id,
        supplier_id=purchase.supplier_id,
        batch_number=item.batch_number,
        expiry_date=item.expiry_date,
        manufacture_date=item.manufacture_date,
        received_at=received_at.replace(tzinfo=None),
        quantity_on_hand=ZERO,
        quantity_received=ZERO,
        purchase_cost=(item.unit_cost / item.conversion_factor).quantize(MONEY),
    )
    db.add(batch)
    db.flush()
    return batch


def receive_purchase(
    db: Session, principal: Principal, purchase_id: UUID, body: ReceiveWrite, key: str
):
    def receive():
        purchase = purchase_by_id(db, principal, purchase_id, lock=True)
        if purchase.status not in {"draft", "partially_received"}:
            raise ConflictError("Only open purchases can receive stock")
        selected = {row.purchase_item_id: row.quantity for row in body.items}
        if len(selected) != len(body.items):
            raise ValidationError("Each purchase item may appear only once")
        lines = {item.id: item for item in purchase.items if item.id in selected}
        if selected.keys() != lines.keys():
            raise ValidationError("Receipt includes items from another purchase")
        products = lock_products(db, principal.shop_id, {i.product_id for i in lines.values()})
        today = shop_date(db, principal.shop_id)
        when = datetime.now(UTC)
        receipt_id = uuid4()
        amount = ZERO
        for item in sorted(
            lines.values(), key=lambda line: (line.product_id, line.batch_number or "", line.id)
        ):
            product = products[item.product_id]
            if not product.is_active or item.ordered_base is None or item.net_total is None:
                raise ConflictError("This line is inactive or has no saved ordering unit")
            base = base_quantity(product, selected[item.id], item.conversion_factor)
            new_received = item.received_base + base
            if new_received > item.ordered_base:
                raise ValidationError("Receiving quantity exceeds the outstanding order quantity")
            cost = (item.net_total * new_received / item.ordered_base).quantize(MONEY) - (
                item.net_total * item.received_base / item.ordered_base
            ).quantize(MONEY)
            batch = (
                _batch_for_receipt(db, principal, purchase, item, today, when)
                if product.is_medicine
                else None
            )
            if batch:
                if batch.quantity_received + base > MAX_QUANTITY:
                    raise ValidationError("Batch received quantity exceeds the supported limit")
                batch.quantity_received += base
            lot = StockLot(
                purchase_item_id=item.id,
                product_id=product.id,
                batch_id=batch.id if batch else None,
                quantity_received=base,
                quantity_remaining=base,
                cost_amount=cost,
            )
            db.add(lot)
            db.flush()
            post_stock(
                db,
                principal,
                product,
                base,
                movement_type="purchase",
                reference_type="purchase_receipt",
                reference_id=receipt_id,
                batch=batch,
                lot=lot,
            )
            db.execute(
                insert(SupplierProduct)
                .values(
                    supplier_id=purchase.supplier_id,
                    product_id=product.id,
                )
                .on_conflict_do_nothing()
            )
            item.received_base = new_received
            amount += cost
        purchase.received_total += amount
        purchase.purchased_at = purchase.purchased_at or when
        purchase.status = (
            "received"
            if all(i.received_base == i.ordered_base for i in purchase.items)
            else "partially_received"
        )
        if amount:
            db.add(
                SupplierLedger(
                    supplier_id=purchase.supplier_id,
                    purchase_id=purchase.id,
                    kind="receipt",
                    amount=amount,
                    reference=str(receipt_id),
                    created_by=principal.user_id,
                )
            )
        audit(
            db,
            principal,
            "purchase.receive",
            "purchase",
            purchase.id,
            receipt_id=str(receipt_id),
            amount=str(amount),
        )
        return purchase

    return _idempotent_purchase(
        db,
        principal,
        key,
        "purchase.receive",
        {
            "id": str(purchase_id),
            **body.model_dump(mode="json"),
        },
        receive,
    )


def pay_purchase(
    db: Session, principal: Principal, purchase_id: UUID, body: SupplierPaymentWrite, key: str
):
    def pay():
        purchase = purchase_by_id(db, principal, purchase_id, lock=True)
        if (
            purchase.status not in {"received", "partially_received"}
            or body.amount > purchase.received_total - purchase.paid_total
        ):
            raise ValidationError("Payment exceeds the recorded supplier balance")
        purchase.paid_total += body.amount
        db.add(
            SupplierLedger(
                supplier_id=purchase.supplier_id,
                purchase_id=purchase.id,
                kind="payment",
                amount=-body.amount,
                method=body.method,
                reference=body.reference,
                created_by=principal.user_id,
            )
        )
        audit(
            db,
            principal,
            "purchase.payment",
            "purchase",
            purchase.id,
            amount=str(body.amount),
            method=body.method,
        )
        return purchase

    return _idempotent_purchase(
        db,
        principal,
        key,
        "purchase.payment",
        {
            "id": str(purchase_id),
            **body.model_dump(mode="json"),
        },
        pay,
    )


def cancel_purchase(db: Session, principal: Principal, purchase_id: UUID, reason: str, key: str):
    def cancel():
        purchase = purchase_by_id(db, principal, purchase_id, lock=True)
        if purchase.status != "draft":
            raise ConflictError("Only an unreceived draft can be cancelled")
        purchase.status = "voided"
        audit(db, principal, "purchase.cancel", "purchase", purchase.id, reason=reason)
        return purchase

    return _idempotent_purchase(
        db, principal, key, "purchase.cancel", {"id": str(purchase_id), "reason": reason}, cancel
    )


def reverse_purchase(db: Session, principal: Principal, purchase_id: UUID, reason: str, key: str):
    def reverse():
        purchase = purchase_by_id(db, principal, purchase_id, lock=True)
        if purchase.status not in {"received", "partially_received"} or purchase.paid_total:
            raise ConflictError("Only unpaid received purchases can be reversed")
        item_ids = {item.id for item in purchase.items}
        products = lock_products(
            db, principal.shop_id, {item.product_id for item in purchase.items}
        )
        batch_ids = select(StockLot.batch_id).where(StockLot.purchase_item_id.in_(item_ids))
        batches = {
            batch.id: batch
            for batch in db.scalars(
                select(MedicineBatch)
                .where(MedicineBatch.id.in_(batch_ids))
                .order_by(MedicineBatch.product_id, MedicineBatch.id)
                .with_for_update(key_share=True)
            )
        }
        lots = db.scalars(
            select(StockLot)
            .where(StockLot.purchase_item_id.in_(item_ids))
            .order_by(StockLot.id)
            .with_for_update(key_share=True)
        ).all()
        if not lots or any(lot.quantity_remaining != lot.quantity_received for lot in lots):
            raise ConflictError(
                "Purchase stock is already used or its original lots are unavailable"
            )
        for lot in lots:
            post_stock(
                db,
                principal,
                products[lot.product_id],
                -lot.quantity_received,
                movement_type="return",
                reference_type="purchase_reversal",
                reference_id=purchase.id,
                note=reason,
                batch=batches.get(lot.batch_id),
                lot=lot,
            )
        if purchase.received_total:
            db.add(
                SupplierLedger(
                    supplier_id=purchase.supplier_id,
                    purchase_id=purchase.id,
                    kind="reversal",
                    amount=-purchase.received_total,
                    created_by=principal.user_id,
                )
            )
        purchase.status = "reversed"
        audit(db, principal, "purchase.reverse", "purchase", purchase.id, reason=reason)
        return purchase

    return _idempotent_purchase(
        db, principal, key, "purchase.reverse", {"id": str(purchase_id), "reason": reason}, reverse
    )

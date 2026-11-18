"""Transaction-safe invoice finalization (Phase 2A).

Everything in ``finalize_invoice`` runs inside ONE database transaction:
price resolution, stock locking + deduction, invoice/payment/loyalty writes,
and the idempotency record. Any failure rolls back every effect.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal
from app.core.errors import (
    ConflictError,
    IdempotencyConflictError,
    InsufficientStockError,
    NotFoundError,
    ValidationError,
)
from app.models import (
    AuditLog,
    Counter,
    Customer,
    IdempotencyRecord,
    Invoice,
    InvoiceCounter,
    InvoiceItem,
    LoyaltyAccount,
    LoyaltyRule,
    LoyaltyTransaction,
    Payment,
    Product,
    StockMovement,
)
from app.schemas.sales import InvoiceCreate, InvoiceCreateOut, InvoiceItemOut, PaymentOut
from app.services.loyalty import LoyaltyPolicy, points_earned

MONEY_Q = Decimal("0.01")
# Base units that are countable pieces — fractional qty is meaningless.
_DISCRETE_UNITS = {"piece", "pack", "strip", "box", "bottle", "sachet"}


def request_fingerprint(body: InvoiceCreate) -> str:
    """Stable hash of the validated request payload for idempotency comparison."""
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _existing_idempotent_response(
    db: Session, shop_id: uuid.UUID, key: str, fingerprint: str
) -> InvoiceCreateOut | None:
    record = db.execute(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.shop_id == shop_id,
            IdempotencyRecord.idempotency_key == key,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise IdempotencyConflictError(
            "Idempotency key was already used with a different payload",
            details={"idempotency_key": key},
        )
    if record.response_body:
        return InvoiceCreateOut.model_validate({**record.response_body, "idempotent_replay": True})
    return None  # in-flight record without response -> fall through to insert below


def _lock_products(
    db: Session, shop_id: uuid.UUID, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Product]:
    """Lock product rows in deterministic (sorted id) order to avoid deadlocks.

    Locks via a scalar subquery (`product.id IN (SELECT ... FOR UPDATE)`), which
    lets us keep `selectinload` for units/category — `joinedload` produces an
    OUTER JOIN that PostgreSQL rejects alongside `FOR UPDATE`.
    """
    locked_ids = (
        select(Product.id)
        .where(Product.shop_id == shop_id, Product.id.in_(product_ids))
        .order_by(Product.id)
        .with_for_update()
        .scalar_subquery()
    )
    rows = (
        db.execute(
            select(Product)
            .options(selectinload(Product.units), selectinload(Product.category))
            .where(Product.id.in_(locked_ids))
            .order_by(Product.id)
        )
        .scalars()
        .all()
    )
    return {p.id: p for p in rows}


def finalize_invoice(
    db: Session,
    principal: Principal,
    body: InvoiceCreate,
    idempotency_key: str,
) -> InvoiceCreateOut:
    shop_id = principal.shop_id
    fingerprint = request_fingerprint(body)

    # ---- Idempotency: replay or reject before doing any work -------------
    replay = _existing_idempotent_response(db, shop_id, idempotency_key, fingerprint)
    if replay is not None:
        return replay

    # ---- Validate counter & customer against the caller's shop -----------
    counter = db.execute(
        select(Counter).where(
            Counter.id == body.counter_id,
            Counter.shop_id == shop_id,
            Counter.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if counter is None:
        raise NotFoundError("Counter not found", details={"counter_id": str(body.counter_id)})

    customer: Customer | None = None
    if body.customer_id is not None:
        customer = db.execute(
            select(Customer).where(
                Customer.id == body.customer_id,
                Customer.shop_id == shop_id,
                Customer.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundError(
                "Customer not found", details={"customer_id": str(body.customer_id)}
            )

    # ---- Lock products (deduplicated, sorted) and validate ----------------
    product_ids = sorted({line.product_id for line in body.items})
    products = _lock_products(db, shop_id, product_ids)
    for pid in product_ids:
        if pid not in products:
            raise NotFoundError("Product not found", details={"product_id": str(pid)})
        if not products[pid].is_active:
            raise ValidationError("Product is not sellable", details={"product_id": str(pid)})

    # ---- Merge duplicate lines, price server-side, verify stock ----------
    # Merge duplicate product+unit lines so stock deduction is exact.
    merged: dict[tuple[uuid.UUID, uuid.UUID | None], dict] = {}
    for line in body.items:
        k = (line.product_id, line.product_unit_id)
        m = merged.setdefault(k, {"quantity": Decimal(0), "line_discount": Decimal(0)})
        m["quantity"] += line.quantity
        m["line_discount"] += line.line_discount

    items_data: list[dict] = []
    subtotal = Decimal("0")
    eligible_total = Decimal("0")
    for (pid, unit_id), m in merged.items():
        product = products[pid]
        quantity = m["quantity"]
        unit = None
        if unit_id is not None:
            unit = next((u for u in product.units if u.id == unit_id), None)
            if unit is None:
                raise ValidationError(
                    "Product unit not found for product",
                    details={"product_id": str(pid), "product_unit_id": str(unit_id)},
                )
        else:
            unit = next((u for u in product.units if u.is_base), None)
            if unit is None:
                raise ValidationError(
                    "Product has no base selling unit",
                    details={"product_id": str(pid)},
                )

        base_qty = (quantity * unit.conversion_factor).quantize(Decimal("0.001"))
        if product.unit in _DISCRETE_UNITS and base_qty != base_qty.to_integral_value():
            raise ValidationError(
                "Fractional quantity is not allowed for this unit",
                details={
                    "product_id": str(pid),
                    "quantity": str(quantity),
                    "unit": product.unit,
                },
            )

        unit_price = unit.selling_price.quantize(MONEY_Q)
        line_discount = m["line_discount"].quantize(MONEY_Q)
        line_total = (quantity * unit_price).quantize(MONEY_Q)
        if line_discount > line_total:
            raise ValidationError(
                "Line discount exceeds line total",
                details={"product_id": str(pid)},
            )
        line_total_after = line_total - line_discount

        if product.stock_on_hand < base_qty:
            raise InsufficientStockError(
                "Insufficient stock",
                details={
                    "product_id": str(pid),
                    "requested": str(base_qty),
                    "available": str(product.stock_on_hand),
                },
            )

        loyalty_amount = line_total_after if product.category.loyalty_eligible else Decimal("0")
        eligible_total += loyalty_amount
        subtotal += line_total

        items_data.append(
            {
                "product": product,
                "unit": unit,
                "quantity": quantity,
                "base_qty": base_qty,
                "unit_price": unit_price,
                "line_discount": line_discount,
                "line_total": line_total_after,
                "loyalty_eligible_amount": loyalty_amount,
            }
        )

    discount_total = body.discount_total.quantize(MONEY_Q)
    if discount_total > subtotal:
        raise ValidationError("Invoice discount exceeds subtotal")
    total = (subtotal - discount_total).quantize(MONEY_Q)
    if total <= 0:
        raise ValidationError("Invoice total must be positive")

    # ---- Payments: must exactly cover the total ---------------------------
    if all(p.amount is None for p in body.payments):
        if len(body.payments) != 1:
            raise ValidationError("Split payments require explicit amounts")
        payment_amounts = [total]
    else:
        payment_amounts = [p.amount for p in body.payments]
        paid_sum = sum(payment_amounts, Decimal("0")).quantize(MONEY_Q)
        if paid_sum != total:
            raise ValidationError(
                "Payments must exactly equal the invoice total",
                details={"total": str(total), "payments": str(paid_sum)},
            )

    # ---- Apply stock deduction (rows already locked) ----------------------
    invoice = Invoice(
        shop_id=shop_id,
        counter_id=counter.id,
        customer_id=customer.id if customer else None,
        invoice_number="",
        status="finalized",
        subtotal=subtotal,
        discount_total=discount_total,
        loyalty_discount=Decimal("0"),
        tax_total=Decimal("0"),
        total=total,
        paid_total=total,
        due_total=Decimal("0"),
        loyalty_points_earned=0,
        loyalty_points_redeemed=0,
        idempotency_key=idempotency_key,
        created_by=principal.user_id,
        finalized_at=datetime.now(UTC),
    )
    db.add(invoice)
    db.flush()  # get invoice.id

    # Concurrency-safe daily sequence: lock the per-(shop,date) counter row.
    date_key = datetime.now(UTC).strftime("%y%m%d")
    counter_row = db.execute(
        select(InvoiceCounter)
        .where(
            InvoiceCounter.shop_id == shop_id,
            InvoiceCounter.counter_date == date_key,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if counter_row is None:
        # Seed the sequence from today's highest existing suffix so pre-existing
        # (e.g. seeded) invoice numbers never collide with new ones.
        prefix = f"INV-{date_key}-"
        max_existing = db.scalar(
            select(func.max(Invoice.invoice_number)).where(
                Invoice.shop_id == shop_id,
                Invoice.invoice_number.like(f"{prefix}%"),
            )
        )
        start = int(max_existing.rsplit("-", 1)[1]) if max_existing else 0
        counter_row = InvoiceCounter(shop_id=shop_id, counter_date=date_key, last_seq=start)
        db.add(counter_row)
        db.flush()
        # Re-read under lock so a concurrent insert serialized on the PK.
        counter_row = db.execute(
            select(InvoiceCounter)
            .where(
                InvoiceCounter.shop_id == shop_id,
                InvoiceCounter.counter_date == date_key,
            )
            .with_for_update()
        ).scalar_one()
    counter_row.last_seq += 1
    invoice.invoice_number = f"INV-{date_key}-{counter_row.last_seq:04d}"

    for d in items_data:
        product = d["product"]
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_unit_id=d["unit"].id,
                description=product.name_en,
                quantity=d["quantity"],
                unit_price=d["unit_price"],
                line_discount=d["line_discount"],
                tax_rate=product.tax_rate,
                line_total=d["line_total"],
                loyalty_eligible_amount=d["loyalty_eligible_amount"],
            )
        )
        product.stock_on_hand -= d["base_qty"]  # locked row; CHECK >= 0 backstops
        db.add(
            StockMovement(
                shop_id=shop_id,
                product_id=product.id,
                counter_id=counter.id,
                movement_type="sale",
                quantity=-d["base_qty"],
                reference_type="invoice",
                reference_id=invoice.id,
                created_by=principal.user_id,
            )
        )

    for payment, amount in zip(body.payments, payment_amounts, strict=True):
        db.add(
            Payment(
                invoice_id=invoice.id,
                method=payment.method,
                amount=amount,
                reference=payment.reference,
                received_by=principal.user_id,
            )
        )

    # ---- Loyalty earn (only when a loyalty account exists) ----------------
    points = 0
    account: LoyaltyAccount | None = None
    if customer is not None:
        account = db.execute(
            select(LoyaltyAccount)
            .where(
                LoyaltyAccount.customer_id == customer.id,
                LoyaltyAccount.is_active.is_(True),
            )
            .with_for_update()
        ).scalar_one_or_none()
    if account is not None:
        rule = db.scalar(
            select(LoyaltyRule).where(
                LoyaltyRule.shop_id == shop_id, LoyaltyRule.is_active.is_(True)
            )
        )
        policy = (
            LoyaltyPolicy(
                points_per_100_bdt=rule.points_per_100_bdt,
                min_redeem_balance=rule.min_redeem_balance,
                redeem_step_points=rule.redeem_step_points,
                point_value_bdt=rule.point_value_bdt,
            )
            if rule
            else LoyaltyPolicy()
        )
        eligible_after_discount = (
            eligible_total - discount_total
            if rule is None or rule.earn_on_eligible_category_only
            else subtotal - discount_total
        )
        eligible_after_discount = max(eligible_after_discount, Decimal("0"))
        points = points_earned(eligible_after_discount, policy)
        if points > 0:
            account.points_balance += points
            account.lifetime_earned += points
            db.add(
                LoyaltyTransaction(
                    account_id=account.id,
                    invoice_id=invoice.id,
                    transaction_type="earn",
                    points=points,
                    balance_after=account.points_balance,
                    created_by=principal.user_id,
                )
            )
        invoice.loyalty_points_earned = points

    out = InvoiceCreateOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        counter_code=counter.code,
        customer_name=customer.name if customer else None,
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=Decimal("0"),
        total=total,
        paid_total=total,
        due_total=Decimal("0"),
        loyalty_points_earned=points,
        loyalty_points_balance=account.points_balance if account else None,
        finalized_at=invoice.finalized_at,
        items=[
            InvoiceItemOut(
                id=uuid.uuid4(),  # placeholder id; replaced after flush below
                product_id=d["product"].id,
                description=d["product"].name_en,
                quantity=d["quantity"],
                unit_price=d["unit_price"],
                line_discount=d["line_discount"],
                line_total=d["line_total"],
            )
            for d in items_data
        ],
        payments=[
            PaymentOut(
                id=uuid.uuid4(),
                method=p.method,
                amount=a,
                reference=p.reference,
                paid_at=invoice.finalized_at,
            )
            for p, a in zip(body.payments, payment_amounts, strict=True)
        ],
        idempotent_replay=False,
    )

    # Persist the replay payload inside the SAME transaction.
    db.add(
        IdempotencyRecord(
            shop_id=shop_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            response_status=201,
            response_body=out.model_dump(mode="json"),
        )
    )
    db.add(
        AuditLog(
            shop_id=shop_id,
            actor_user_id=principal.user_id,
            action="invoice.finalize",
            entity_type="invoice",
            entity_id=invoice.id,
            after={"invoice_number": invoice.invoice_number, "total": str(total)},
        )
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Invoice could not be created (conflict)", details={}) from exc

    # Replace placeholder item/payment ids with real persisted ids.
    db.refresh(invoice)
    out.items = [
        InvoiceItemOut(
            id=i.id,
            product_id=i.product_id,
            description=i.description,
            quantity=i.quantity,
            unit_price=i.unit_price,
            line_discount=i.line_discount,
            line_total=i.line_total,
        )
        for i in invoice.items
    ]
    out.payments = [
        PaymentOut(
            id=p.id, method=p.method, amount=p.amount, reference=p.reference, paid_at=p.paid_at
        )
        for p in invoice.payments
    ]
    # Store the final response (with real ids) as the replay payload.
    record = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.shop_id == shop_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if record is not None:
        record.response_body = out.model_dump(mode="json")
        db.commit()

    return out

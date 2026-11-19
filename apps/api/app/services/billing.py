"""Atomic checkout: reserve the request, lock inventory and loyalty, then post the sale."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal, assert_counter_allowed
from app.core.errors import ConflictError, InsufficientStockError, NotFoundError, ValidationError
from app.models import (
    AuditLog,
    Counter,
    CustomerLedgerEntry,
    Invoice,
    InvoiceCounter,
    InvoiceItem,
    Payment,
    Product,
    StockMovement,
)
from app.schemas.sales import InvoiceCreate, InvoiceCreateOut, InvoiceItemOut, PaymentOut
from app.services.customers import get_customer
from app.services.idempotency import fingerprint, reserve_request
from app.services.loyalty_accounts import (
    award_qualified_points,
    lock_account,
    record_redemption,
    redemption_discount,
    rule_snapshot,
)
from app.services.receipts import capture_receipt_identity
from app.services.receivables import OverpaymentError, check_credit_limit

MONEY_Q = Decimal("0.01")
_DISCRETE_UNITS = {"piece", "pack", "strip", "box", "bottle", "sachet"}


def request_fingerprint(body: InvoiceCreate) -> str:
    payload = body.model_dump(mode="json")
    # Phase 2A/2B requests had neither field. Preserve their original hashes.
    if not body.allow_due:
        payload.pop("allow_due")
    if not body.redeem_points:
        payload.pop("redeem_points")
    return fingerprint(payload)


def _lock_products(db: Session, shop_id: UUID, product_ids: list[UUID]) -> dict[UUID, Product]:
    rows = db.scalars(
        select(Product)
        .options(selectinload(Product.units), selectinload(Product.category))
        .where(Product.shop_id == shop_id, Product.id.in_(product_ids))
        .order_by(Product.id)
        .with_for_update(key_share=True)
    ).all()
    return {product.id: product for product in rows}


def _price_items(
    db: Session, shop_id: UUID, body: InvoiceCreate
) -> tuple[list[tuple[Product, Decimal, InvoiceItem]], Decimal, Decimal, Decimal]:
    product_ids = sorted({line.product_id for line in body.items})
    products = _lock_products(db, shop_id, product_ids)
    for pid in product_ids:
        if pid not in products:
            raise NotFoundError("Product not found", details={"product_id": str(pid)})
        if not products[pid].is_active:
            raise ValidationError("Product is not sellable", details={"product_id": str(pid)})

    merged = defaultdict(lambda: (Decimal(0), Decimal(0)))
    for line in body.items:
        key = (line.product_id, line.product_unit_id)
        quantity, discount = merged[key]
        merged[key] = (quantity + line.quantity, discount + line.line_discount)

    items = []
    requested = defaultdict(Decimal)
    subtotal = line_discounts = eligible_total = Decimal("0.00")
    for (pid, unit_id), (quantity, discount) in merged.items():
        product = products[pid]
        unit = next((u for u in product.units if (u.id == unit_id if unit_id else u.is_base)), None)
        if unit is None:
            raise ValidationError(
                "Product has no matching selling unit", details={"product_id": str(pid)}
            )
        base_qty = (quantity * unit.conversion_factor).quantize(Decimal("0.001"))
        if base_qty <= 0:
            raise ValidationError("Quantity is below the supported stock precision")
        if product.unit in _DISCRETE_UNITS and base_qty != base_qty.to_integral_value():
            raise ValidationError(
                "Fractional quantity is not allowed for this unit", details={"product_id": str(pid)}
            )
        requested[pid] += base_qty

        raw_total = quantity * unit.selling_price
        line_total = raw_total.quantize(MONEY_Q)
        if discount > min(raw_total, line_total):
            raise ValidationError(
                "Line discount exceeds line total", details={"product_id": str(pid)}
            )
        net = line_total - discount
        eligible = (
            net
            if product.loyalty_eligible and product.category.loyalty_eligible
            else Decimal("0.00")
        )
        subtotal += line_total
        line_discounts += discount
        eligible_total += eligible
        items.append(
            (
                product,
                base_qty,
                InvoiceItem(
                    product_id=pid,
                    product_unit_id=unit.id,
                    description=product.name_en,
                    receipt_details={
                        "name_bn": product.name_bn,
                        "unit_en": unit.name,
                        "unit_bn": unit.name_bn,
                        "position": len(items),
                    },
                    quantity=quantity,
                    unit_price=unit.selling_price,
                    line_discount=discount,
                    tax_rate=product.tax_rate,
                    line_total=net,
                    loyalty_eligible_amount=eligible,
                ),
            )
        )

    for pid, base_qty in requested.items():
        available = products[pid].stock_on_hand
        if available < base_qty:
            raise InsufficientStockError(
                "Insufficient stock",
                details={
                    "product_id": str(pid),
                    "requested": str(base_qty),
                    "available": str(available),
                },
            )
    return items, subtotal, line_discounts, eligible_total


def _next_invoice_number(db: Session, shop_id: UUID, finalized_at: datetime) -> str:
    date_key = finalized_at.strftime("%y%m%d")
    prefix = f"INV-{date_key}-"
    advance = (
        update(InvoiceCounter)
        .where(InvoiceCounter.shop_id == shop_id, InvoiceCounter.counter_date == date_key)
        .values(last_seq=InvoiceCounter.last_seq + 1)
        .returning(InvoiceCounter.last_seq)
    )
    seq = db.scalar(advance)
    if seq is None:
        starting_seq = db.scalar(
            select(
                func.coalesce(
                    func.max(cast(func.substr(Invoice.invoice_number, len(prefix) + 1), Integer)), 0
                )
            ).where(Invoice.shop_id == shop_id, Invoice.invoice_number.op("~")(f"^{prefix}[0-9]+$"))
        )
        db.execute(
            insert(InvoiceCounter)
            .values(shop_id=shop_id, counter_date=date_key, last_seq=starting_seq)
            .on_conflict_do_nothing(index_elements=["shop_id", "counter_date"])
        )
        seq = db.scalar(advance)
    return f"{prefix}{seq:04d}"


def _payment_amounts(body: InvoiceCreate, total: Decimal) -> list[Decimal]:
    if len(body.payments) == 1 and body.payments[0].amount is None:
        return [total]
    if any(payment.amount is None for payment in body.payments):
        raise ValidationError("Split payments require explicit amounts")
    amounts = [payment.amount for payment in body.payments]
    paid = sum(amounts, Decimal("0.00"))
    if paid > total:
        raise OverpaymentError("Payments cannot exceed the invoice total")
    if paid < total and not body.allow_due:
        raise ValidationError(
            "Payments must exactly equal the invoice total",
            details={"total": str(total), "payments": str(paid)},
        )
    return amounts


def finalize_invoice(
    db: Session, principal: Principal, body: InvoiceCreate, idempotency_key: str
) -> InvoiceCreateOut:
    principal.require_write("sales:write")
    assert_counter_allowed(principal, body.counter_id)
    if body.redeem_points:
        principal.require_write("loyalty:write")
    try:
        result = _finalize_invoice(db, principal, body, idempotency_key)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Invoice could not be created (conflict)") from exc
    except Exception:
        db.rollback()
        raise
    return result


def _finalize_invoice(
    db: Session, principal: Principal, body: InvoiceCreate, key: str
) -> InvoiceCreateOut:
    shop_id = principal.shop_id
    record = reserve_request(db, shop_id, key, request_fingerprint(body))
    if record.response_body is not None:
        return InvoiceCreateOut.model_validate({**record.response_body, "idempotent_replay": True})

    counter = db.scalar(
        select(Counter).where(
            Counter.id == body.counter_id, Counter.shop_id == shop_id, Counter.is_active.is_(True)
        )
    )
    if counter is None:
        raise NotFoundError("Counter not found", details={"counter_id": str(body.counter_id)})
    customer = None
    if body.customer_id is not None:
        customer = get_customer(db, shop_id, body.customer_id, lock=True)
        if not customer.is_active:
            raise NotFoundError("Active customer not found")

    items, subtotal, line_discounts, eligible = _price_items(db, shop_id, body)
    manual_discount = body.discount_total.quantize(MONEY_Q)
    discount_total = line_discounts + manual_discount
    before_loyalty = subtotal - discount_total
    if before_loyalty <= 0:
        raise ValidationError("Invoice total before loyalty must be positive")
    # Apply invoice-level discounts to eligible spend first, as in Phase 2A.
    eligible = max(eligible - manual_discount, Decimal("0.00"))

    account = lock_account(db, customer, create=True) if customer else None
    discount = redemption_discount(account, body.redeem_points, eligible)
    total = before_loyalty - discount
    amounts = _payment_amounts(body, total)
    paid = sum(amounts, Decimal("0.00"))
    due = total - paid
    if due:
        if customer is None or not customer.phone:
            raise ValidationError(
                "A registered customer with a mobile number is required for credit sales"
            )
        check_credit_limit(db, customer, due)

    finalized_at = datetime.now(UTC)
    invoice = Invoice(
        shop_id=shop_id,
        counter_id=counter.id,
        customer_id=body.customer_id,
        invoice_number=_next_invoice_number(db, shop_id, finalized_at),
        status="finalized",
        subtotal=subtotal,
        discount_total=discount_total,
        loyalty_discount=discount,
        tax_total=Decimal("0.00"),
        total=total,
        paid_total=paid,
        due_total=due,
        receipt_identity=capture_receipt_identity(db, principal, counter, customer),
        loyalty_points_earned=0,
        loyalty_points_redeemed=body.redeem_points,
        loyalty_rule_snapshot=rule_snapshot(db, shop_id) if account else None,
        loyalty_earn_base=eligible - discount if account else None,
        idempotency_key=key,
        created_by=principal.user_id,
        finalized_at=finalized_at,
        items=[item for _, _, item in items],
        payments=[
            Payment(
                method=p.method,
                amount=amount,
                reference=p.reference,
                received_by=principal.user_id,
                paid_at=finalized_at,
            )
            for p, amount in zip(body.payments, amounts, strict=True)
            if amount
        ],
    )
    db.add(invoice)
    db.flush()
    for product, base_qty, _ in items:
        product.stock_on_hand -= base_qty
        db.add(
            StockMovement(
                shop_id=shop_id,
                product_id=product.id,
                counter_id=counter.id,
                movement_type="sale",
                quantity=-base_qty,
                reference_type="invoice",
                reference_id=invoice.id,
                created_by=principal.user_id,
            )
        )
    if account and body.redeem_points:
        record_redemption(db, account, invoice, principal.user_id)
    points = award_qualified_points(db, account, invoice, principal.user_id)
    invoice.receipt_points_balance = account.points_balance if account else None
    if due:
        db.add(CustomerLedgerEntry(customer_id=customer.id, invoice_id=invoice.id, amount=due))
    db.add(
        AuditLog(
            shop_id=shop_id,
            actor_user_id=principal.user_id,
            action="invoice.finalize",
            entity_type="invoice",
            entity_id=invoice.id,
            after={"invoice_number": invoice.invoice_number, "total": str(total), "due": str(due)},
        )
    )
    result = InvoiceCreateOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        counter_code=counter.code,
        customer_name=customer.name if customer else None,
        subtotal=subtotal,
        discount_total=discount_total,
        loyalty_discount=discount,
        tax_total=invoice.tax_total,
        total=total,
        paid_total=paid,
        due_total=due,
        loyalty_points_earned=points,
        loyalty_points_redeemed=body.redeem_points,
        loyalty_points_balance=account.points_balance if account else None,
        finalized_at=finalized_at,
        items=[InvoiceItemOut.model_validate(item) for item in invoice.items],
        payments=[PaymentOut.model_validate(payment) for payment in invoice.payments],
    )
    record.response_status = 201
    record.response_body = result.model_dump(mode="json")
    return result

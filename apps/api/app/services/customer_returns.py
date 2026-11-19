from collections import Counter, defaultdict
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, assert_counter_allowed
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    CustomerRefundSettlement,
    CustomerReturn,
    CustomerReturnLine,
    Invoice,
    InvoiceBatchAllocation,
    InvoiceItem,
    LoyaltyTransaction,
    MedicineBatch,
    Payment,
    ProductUnit,
    ReturnStockPortion,
    ReturnStockResolution,
    StockLot,
    StockMovement,
)
from app.models.sales import CustomerLedgerEntry
from app.schemas.returns import (
    InvoiceReturnsOut,
    RefundComplete,
    ResolveReturnStock,
    ReturnLineOut,
    ReturnOption,
    ReturnOut,
    ReturnWrite,
    StockResolutionOut,
)
from app.services.customers import get_customer
from app.services.financial_posting import post_financial
from app.services.loyalty_accounts import award_qualified_points, lock_account
from app.services.purchasing import audit
from app.services.receivables import balance_query
from app.services.return_pricing import original_values, points_share, return_delta
from app.services.stock import QUANTITY, ZERO, base_quantity, lock_products, post_stock, shop_date


def _invoice(db: Session, principal: Principal, invoice_id: UUID, *, lock: bool = False) -> Invoice:
    stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.shop_id == principal.shop_id,
        Invoice.status == "finalized",
    )
    invoice = db.scalar(stmt.with_for_update(key_share=True) if lock else stmt)
    if invoice is None:
        raise NotFoundError("Finalized invoice not found")
    assert_counter_allowed(principal, invoice.counter_id)
    return invoice


def _require_write(principal: Principal) -> None:
    principal.require_write("sales:write")
    principal.require_write("catalog:write")
    principal.require("reports:read")


def _invoice_items(invoice: Invoice) -> list[InvoiceItem]:
    return sorted(
        invoice.items, key=lambda item: ((item.receipt_details or {}).get("position", 999), item.id)
    )


def _sources(db: Session, invoice: Invoice, items: list[InvoiceItem]):
    counts = Counter(item.product_id for item in items)
    single = {item.product_id: item.id for item in items if counts[item.product_id] == 1}
    sources = defaultdict(list)
    for movement in db.scalars(
        select(StockMovement)
        .where(
            StockMovement.shop_id == invoice.shop_id,
            StockMovement.reference_type == "invoice",
            StockMovement.reference_id == invoice.id,
            StockMovement.movement_type == "sale",
            StockMovement.quantity < 0,
        )
        .order_by(StockMovement.created_at, StockMovement.id)
    ):
        item_id = movement.invoice_item_id or single.get(movement.product_id)
        if item_id:
            sources[item_id, movement.batch_id].append(movement)
    return sources


def _options(
    db: Session, invoice: Invoice, items: list[InvoiceItem], sources
) -> list[ReturnOption]:
    batches = defaultdict(list)
    for allocation in db.scalars(
        select(InvoiceBatchAllocation)
        .where(InvoiceBatchAllocation.invoice_item_id.in_([item.id for item in items]))
        .order_by(InvoiceBatchAllocation.expiry_date, InvoiceBatchAllocation.id)
    ):
        batches[allocation.invoice_item_id].append(allocation)
    used = {
        (item_id, batch_id): quantity
        for item_id, batch_id, quantity in db.execute(
            select(
                CustomerReturnLine.invoice_item_id,
                CustomerReturnLine.batch_id,
                func.sum(CustomerReturnLine.quantity),
            )
            .join(CustomerReturn, CustomerReturn.id == CustomerReturnLine.return_id)
            .where(CustomerReturn.invoice_id == invoice.id)
            .group_by(CustomerReturnLine.invoice_item_id, CustomerReturnLine.batch_id)
        )
    }
    rows = []
    today = shop_date(db, invoice.shop_id)
    for item in items:
        product = item.product
        details = item.receipt_details or {}
        original_unit = db.get(ProductUnit, item.product_unit_id) if item.product_unit_id else None
        options = batches[item.id]
        if not options:
            batch = db.get(MedicineBatch, item.batch_id) if item.batch_id else None
            movements = sources[item.id, item.batch_id]
            total = sum((-move.quantity for move in movements), ZERO) or Decimal(
                details.get("base_quantity")
                or (item.quantity * (original_unit.conversion_factor if original_unit else 1))
            ).quantize(QUANTITY)
            choices = [
                (
                    item.batch_id,
                    batch.batch_number if batch else details.get("batch"),
                    batch.expiry_date if batch else details.get("expiry"),
                    total,
                )
            ]
        else:
            choices = [(a.batch_id, a.batch_number, a.expiry_date, a.quantity) for a in options]
        for batch_id, number, expiry, quantity in choices:
            batch = db.get(MedicineBatch, batch_id) if batch_id else None
            traced = sum((-m.quantity for m in sources[item.id, batch_id]), ZERO) == quantity
            can_restore = (
                traced
                and product.is_active
                and (
                    not product.is_medicine
                    or bool(
                        batch
                        and batch.is_active
                        and not batch.quarantined
                        and batch.expiry_date > today
                    )
                )
            )
            rows.append(
                ReturnOption(
                    invoice_item_id=item.id,
                    description=item.description,
                    name_bn=details.get("name_bn"),
                    base_unit=product.unit,
                    batch_id=batch_id,
                    batch_number=number,
                    expiry_date=expiry,
                    quantity=quantity,
                    remaining=quantity - used.get((item.id, batch_id), ZERO),
                    medicine=product.is_medicine,
                    can_restore=can_restore,
                    stock_traced=traced,
                )
            )
    return rows


def _result(db: Session, row: CustomerReturn) -> ReturnOut:
    result = ReturnOut.model_validate(row)
    settlement = db.get(CustomerRefundSettlement, row.id)
    if row.refund_amount:
        completed = row.refund_method == "cash" or settlement is not None
        result.refund_status = "completed" if completed else "pending"
        if completed:
            result.refund_reference = settlement.reference if settlement else row.cash_reference
            result.refund_completed_at = settlement.created_at if settlement else row.created_at
            result.refund_actor_id = settlement.actor_id if settlement else row.actor_id
    for line in db.scalars(
        select(CustomerReturnLine)
        .where(CustomerReturnLine.return_id == row.id)
        .order_by(CustomerReturnLine.id)
    ):
        details = ReturnLineOut.model_validate(line)
        portions = db.scalars(
            select(ReturnStockPortion).where(ReturnStockPortion.line_id == line.id)
        ).all()
        details.stock_traced = bool(portions)
        details.held = (
            line.disposition in {"quarantine", "supplier_staging"}
            and bool(portions)
            and any(db.get(ReturnStockResolution, p.id) is None for p in portions)
        )
        result.lines.append(details)
    return result


def invoice_returns(db: Session, principal: Principal, invoice_id: UUID) -> InvoiceReturnsOut:
    principal.require("sales:read")
    principal.require("reports:read")
    invoice = _invoice(db, principal, invoice_id)
    items = _invoice_items(invoice)
    rows = _options(db, invoice, items, _sources(db, invoice, items))
    return InvoiceReturnsOut(
        invoice_id=invoice.id,
        outstanding_due=invoice.due_total,
        rows=rows,
        history=[
            _result(db, row)
            for row in db.scalars(
                select(CustomerReturn)
                .where(CustomerReturn.invoice_id == invoice.id)
                .order_by(CustomerReturn.created_at.desc(), CustomerReturn.id)
            )
        ],
    )


def _loyalty_change(
    db, principal, invoice, customer, prior_returns, eligible: Decimal, redemption: Decimal, result
) -> list[LoyaltyTransaction]:
    if invoice.loyalty_rule_snapshot is None or customer is None:
        return []
    total_eligible = eligible + sum((r.eligible_value for r in prior_returns), ZERO)
    total_redemption = redemption + sum((r.redemption_value for r in prior_returns), ZERO)
    award_base = (
        invoice.loyalty_award_base
        if invoice.loyalty_award_base is not None
        else (invoice.loyalty_earn_base or ZERO)
    )
    remaining_eligible = max((invoice.loyalty_earn_base or ZERO) - total_eligible, ZERO)
    reverse = points_share(
        invoice.loyalty_points_earned,
        max(award_base - remaining_eligible, ZERO),
        award_base,
    ) - sum(r.earned_reversed for r in prior_returns)
    restore = points_share(
        invoice.loyalty_points_redeemed, total_redemption, invoice.loyalty_discount
    ) - sum(r.redeemed_restored for r in prior_returns)
    if not (reverse or restore):
        return []
    account = lock_account(db, customer, include_inactive=True)
    if account is None or reverse < 0 or restore < 0:
        raise ConflictError("The original loyalty account does not reconcile")
    result.earned_reversed = reverse
    result.redeemed_restored = restore
    transactions = []
    for kind, points in (("reverse", -reverse), ("adjust", restore)):
        if not points:
            continue
        account.points_balance += points
        if kind == "reverse":
            account.lifetime_earned += points
        else:
            account.lifetime_redeemed -= points
        transactions.append(
            LoyaltyTransaction(
                account_id=account.id,
                invoice_id=invoice.id,
                return_id=result.id,
                transaction_type=kind,
                points=points,
                balance_after=account.points_balance,
                note="Earn reversal" if kind == "reverse" else "Original redemption restored",
                created_by=principal.user_id,
            )
        )
    account.version += 1
    audit(
        db,
        principal,
        "return.loyalty",
        "customer_return",
        result.id,
        earned_reversed=reverse,
        redeemed_restored=restore,
        balance=account.points_balance,
    )
    return transactions


def _add_stock(db, principal, invoice, line, product, sources, batches, lots, reason):
    if not sources:
        return
    if sum((-m.quantity for m in sources), ZERO) < line.quantity:
        raise ConflictError("Return exceeds recorded stock provenance")
    consumed = dict(
        db.execute(
            select(ReturnStockPortion.source_movement_id, func.sum(ReturnStockPortion.quantity))
            .where(ReturnStockPortion.source_movement_id.in_([m.id for m in sources]))
            .group_by(ReturnStockPortion.source_movement_id)
        ).all()
    )
    batch = batches.get(line.batch_id)
    left = line.quantity
    for move in sources:
        qty = min(left, -move.quantity - consumed.get(move.id, ZERO))
        if qty <= 0:
            continue
        lot = lots.get(move.stock_lot_id)
        if line.disposition == "supplier_staging" and (lot is None or lot.purchase_item_id is None):
            raise ValidationError("Supplier staging requires an original purchase lot")
        db.add(ReturnStockPortion(line_id=line.id, source_movement_id=move.id, quantity=qty))
        info = {
            "reference_id": line.id,
            "note": reason,
            "batch": batch,
            "lot": lot,
            "counter_id": invoice.counter_id,
            "invoice_item_id": line.invoice_item_id,
            "source_movement_id": move.id,
            "held": line.disposition != "sellable",
        }
        post_stock(
            db,
            principal,
            product,
            qty,
            movement_type="return",
            reference_type="customer_return",
            **info,
        )
        if line.disposition in {"damaged", "disposal"}:
            post_stock(
                db,
                principal,
                product,
                -qty,
                movement_type="damage",
                reference_type="customer_return_disposal",
                **info,
            )
        left -= qty
        if not left:
            return
    raise ConflictError("The original stock deductions have already been returned")


def _post_return(
    db: Session, principal: Principal, invoice_id: UUID, body: ReturnWrite
) -> ReturnOut:
    parent = _invoice(db, principal, invoice_id)
    customer = (
        get_customer(db, principal.shop_id, parent.customer_id, lock=True)
        if parent.customer_id
        else None
    )
    invoice = _invoice(db, principal, invoice_id, lock=True)
    db.refresh(invoice)
    items = _invoice_items(invoice)
    by_id = {item.id: item for item in items}
    if any(line.invoice_item_id not in by_id for line in body.lines):
        raise NotFoundError("Return item does not belong to this invoice")
    products = lock_products(
        db, principal.shop_id, {by_id[line.invoice_item_id].product_id for line in body.lines}
    )
    sources = _sources(db, invoice, items)
    options = _options(db, invoice, items, sources)
    indexed = {(row.invoice_item_id, row.batch_id): row for row in options}
    batch_ids = {
        r.batch_id
        for r in options
        if r.batch_id and by_id[r.invoice_item_id].product_id in products
    }
    batches = {
        b.id: b
        for b in db.scalars(
            select(MedicineBatch)
            .where(
                MedicineBatch.id.in_(batch_ids),
                MedicineBatch.shop_id == invoice.shop_id,
            )
            .order_by(MedicineBatch.product_id, MedicineBatch.id)
            .with_for_update(key_share=True)
        )
    }
    lots = {
        lot.id: lot
        for lot in db.scalars(
            select(StockLot)
            .where(
                StockLot.id.in_(
                    {
                        m.stock_lot_id
                        for moves in sources.values()
                        for m in moves
                        if m.stock_lot_id is not None and m.product_id in products
                    }
                )
            )
            .order_by(StockLot.id)
            .with_for_update(key_share=True)
        )
    }

    prior_returns = db.scalars(
        select(CustomerReturn).where(CustomerReturn.invoice_id == invoice.id)
    ).all()
    used, sold = defaultdict(Decimal), defaultdict(Decimal)
    for row in options:
        sold[row.invoice_item_id] += row.quantity
        used[row.invoice_item_id] += row.quantity - row.remaining
    pricing = original_values(invoice, items)
    entries = []
    seen = set()
    amount = eligible = redemption = ZERO
    result_id = uuid4()
    for line in body.lines:
        key = (line.invoice_item_id, line.batch_id)
        option = indexed.get(key)
        if option is None or key in seen:
            raise ValidationError("Select each original item and batch exactly once")
        seen.add(key)
        item = by_id[line.invoice_item_id]
        product = products[item.product_id]
        quantity = base_quantity(product, line.quantity, Decimal(1))
        if quantity > option.remaining:
            raise ConflictError("Return quantity exceeds the remaining sold quantity")
        disposition = line.disposition or ("quarantine" if product.is_medicine else "damaged")
        if disposition == "sellable" and not (option.can_restore and line.verified):
            raise ValidationError("Sellable stock requires verified, eligible and traceable stock")
        movements = sources[key]
        traced = sum((-m.quantity for m in movements), ZERO) == option.quantity
        if not traced and disposition == "supplier_staging":
            raise ValidationError("Supplier staging requires traceable stock")
        price, earn, redeem = [
            return_delta(value, sold[item.id], used[item.id], quantity)
            for value in pricing[item.id]
        ]
        used[item.id] += quantity
        amount += price
        eligible += earn
        redemption += redeem
        entries.append(
            (
                CustomerReturnLine(
                    id=uuid4(),
                    return_id=result_id,
                    invoice_item_id=item.id,
                    batch_id=option.batch_id,
                    quantity=quantity,
                    amount=price,
                    disposition=disposition,
                    verified=line.verified,
                ),
                product,
                movements if traced else [],
            )
        )
    if (
        customer
        and db.scalar(balance_query(customer.id, invoice_id=invoice.id)) != invoice.due_total
    ):
        raise ConflictError("Invoice and customer ledger balances disagree")
    due = min(amount, invoice.due_total)
    refund = amount - due
    collected = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.invoice_id == invoice.id, Payment.method != "due"
        )
    )
    if collected != invoice.paid_total:
        raise ConflictError("Invoice and tender payment records disagree")
    if refund + sum((row.refund_amount for row in prior_returns), ZERO) > collected:
        raise ConflictError("Return exceeds the amount collected")
    if refund and not body.refund_method:
        raise ValidationError("Select a tender for the collected portion of this return")
    if body.cash_reference and (not refund or body.refund_method != "cash"):
        raise ValidationError("Cash reference applies only to a cash refund")
    result = CustomerReturn(
        id=result_id,
        invoice_id=invoice.id,
        actor_id=principal.user_id,
        reason=body.reason,
        amount=amount,
        due_reduction=due,
        refund_amount=refund,
        refund_method=body.refund_method if refund else None,
        cash_reference=body.cash_reference,
        eligible_value=eligible,
        redemption_value=redemption,
        earned_reversed=0,
        redeemed_restored=0,
    )
    loyalty = _loyalty_change(
        db, principal, invoice, customer, prior_returns, eligible, redemption, result
    )
    db.add(result)
    db.flush()
    db.add_all(loyalty)
    if due:
        invoice.due_total -= due
        invoice.return_due_total += due
        db.add(
            CustomerLedgerEntry(
                customer_id=customer.id, invoice_id=invoice.id, return_id=result.id, amount=-due
            )
        )
        if (
            not invoice.due_total
            and invoice.loyalty_rule_snapshot
            and not invoice.loyalty_points_earned
        ):
            db.flush()
            award_qualified_points(
                db,
                lock_account(db, customer),
                invoice,
                principal.user_id,
                returned_eligible=eligible
                + sum((row.eligible_value for row in prior_returns), ZERO),
            )
    for line, product, movements in entries:
        db.add(line)
        db.flush()
        _add_stock(db, principal, invoice, line, product, movements, batches, lots, body.reason)
        audit(
            db,
            principal,
            "return.stock",
            "customer_return_line",
            line.id,
            disposition=line.disposition,
            quantity=str(line.quantity),
            traced=bool(movements),
        )
    audit(
        db,
        principal,
        "invoice.return",
        "customer_return",
        result.id,
        invoice_id=str(invoice.id),
        amount=str(amount),
        due_reduction=str(due),
        reason=body.reason,
    )
    if refund:
        audit(
            db,
            principal,
            "refund.cash" if body.refund_method == "cash" else "refund.pending",
            "customer_return",
            result.id,
            amount=str(refund),
            method=body.refund_method,
        )
    db.flush()
    return _result(db, result)


def create_return(
    db: Session, principal: Principal, invoice_id: UUID, body: ReturnWrite, key: str
) -> ReturnOut:
    _require_write(principal)
    _invoice(db, principal, invoice_id)
    return post_financial(
        db,
        principal,
        key,
        "invoice.return",
        invoice_id,
        body,
        ReturnOut,
        lambda: _post_return(db, principal, invoice_id, body),
    )


def complete_refund(db, principal, invoice_id, return_id, body: RefundComplete, key) -> ReturnOut:
    _require_write(principal)
    _invoice(db, principal, invoice_id)

    def complete():
        invoice = _invoice(db, principal, invoice_id, lock=True)
        row = db.get(CustomerReturn, return_id)
        if row is None or row.invoice_id != invoice.id:
            raise NotFoundError("Return not found")
        if row.refund_method not in {"bkash", "nagad"} or db.get(CustomerRefundSettlement, row.id):
            raise ConflictError("Only a pending external refund can be completed")
        db.add(
            CustomerRefundSettlement(
                return_id=row.id,
                actor_id=principal.user_id,
                method=row.refund_method,
                shop_id=principal.shop_id,
                reference=body.reference,
            )
        )
        audit(
            db,
            principal,
            "refund.complete",
            "customer_return",
            row.id,
            method=row.refund_method,
            reference=body.reference,
        )
        db.flush()
        return _result(db, row)

    return post_financial(
        db, principal, key, "refund.complete", return_id, body, ReturnOut, complete
    )


def resolve_stock(
    db, principal, invoice_id, line_id, body: ResolveReturnStock, key
) -> StockResolutionOut:
    _require_write(principal)
    _invoice(db, principal, invoice_id)

    def resolve():
        invoice = _invoice(db, principal, invoice_id, lock=True)
        line = db.get(CustomerReturnLine, line_id)
        row = db.get(CustomerReturn, line.return_id) if line else None
        if row is None or row.invoice_id != invoice.id:
            raise NotFoundError("Return line not found")
        if line.disposition not in {"quarantine", "supplier_staging"}:
            raise ConflictError("Only held stock can be resolved")
        item = db.get(InvoiceItem, line.invoice_item_id)
        product = lock_products(db, principal.shop_id, [item.product_id])[item.product_id]
        batch = (
            db.scalar(
                select(MedicineBatch)
                .where(MedicineBatch.id == line.batch_id)
                .with_for_update(key_share=True)
            )
            if line.batch_id
            else None
        )
        sources = db.execute(
            select(ReturnStockPortion, StockMovement)
            .join(StockMovement, StockMovement.id == ReturnStockPortion.source_movement_id)
            .where(ReturnStockPortion.line_id == line_id)
        ).all()
        if not sources or any(db.get(ReturnStockResolution, portion.id) for portion, _ in sources):
            raise ConflictError("No unresolved traceable stock was found")
        lots = {
            lot.id: lot
            for lot in db.scalars(
                select(StockLot)
                .where(
                    StockLot.id.in_(
                        {m.stock_lot_id for _, m in sources if m.stock_lot_id is not None}
                    )
                )
                .order_by(StockLot.id)
                .with_for_update(key_share=True)
            )
        }
        if body.action == "supplier_return" and any(
            m.stock_lot_id not in lots or not lots[m.stock_lot_id].purchase_item_id
            for _, m in sources
        ):
            raise ValidationError("Supplier returns require original purchase lots")
        ref = uuid4()
        for portion, move in sources:
            post_stock(
                db,
                principal,
                product,
                -portion.quantity,
                held=True,
                batch=batch,
                lot=lots.get(move.stock_lot_id),
                source_movement_id=move.id,
                invoice_item_id=item.id,
                counter_id=invoice.counter_id,
                movement_type="return" if body.action == "supplier_return" else "damage",
                reference_type=body.action,
                reference_id=ref,
                note=body.reason,
            )
            db.add(
                ReturnStockResolution(
                    portion_id=portion.id,
                    actor_id=principal.user_id,
                    action=body.action,
                    reason=body.reason,
                    reference_id=ref,
                )
            )
        audit(
            db,
            principal,
            "return." + body.action,
            "customer_return_line",
            line.id,
            reference_id=str(ref),
            reason=body.reason,
        )
        return StockResolutionOut(line_id=line.id, reference_id=ref, action=body.action)

    return post_financial(
        db, principal, key, "return.stock.resolve", line_id, body, StockResolutionOut, resolve
    )

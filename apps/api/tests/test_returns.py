from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Category,
    Customer,
    CustomerLedgerEntry,
    CustomerReturn,
    Invoice,
    LoyaltyAccount,
    MedicineBatch,
    Payment,
    Product,
    StockLot,
    StockMovement,
)
from app.schemas.customers import DuePaymentCreate
from app.schemas.purchasing import SupplierPaymentWrite
from app.schemas.returns import (
    CreditApply,
    CreditWrite,
    RefundComplete,
    ResolveReturnStock,
    ReturnWrite,
    SupplierRefundWrite,
    SupplierReturnWrite,
)
from app.schemas.sales import InvoiceCreate
from app.services import customer_returns
from app.services.billing import finalize_invoice
from app.services.customer_returns import (
    complete_refund,
    create_return,
    invoice_returns,
    resolve_stock,
)
from app.services.purchasing import pay_purchase
from app.services.receivables import collect_due_payment
from app.services.reconciliation import discrepancies, finance_report
from app.services.stock import available_stock, shop_date
from app.services.supplier_credits import (
    apply_credit,
    create_credit,
    purchase_credits,
    record_supplier_refund,
    send_to_supplier,
)
from test_purchasing import intake, order, race
from test_purchasing import setup as purchasing_setup

setup = purchasing_setup


def prepare(db, setup, product, quantity="5", batch="LOT-A", days=30):
    purchase = order(
        db,
        setup,
        product,
        quantity,
        batch=batch if product.is_medicine else None,
        expiry=setup[5] + timedelta(days=days) if product.is_medicine else None,
    )
    return intake(db, setup, purchase, quantity)


def account_customer(db, actor, opening=0):
    customer = Customer(
        shop_id=actor.shop_id, name="Return Account", phone="+8801" + str(uuid4().int)[-9:]
    )
    db.add(customer)
    db.flush()
    if opening:
        db.add(
            LoyaltyAccount(
                customer_id=customer.id,
                shop_id=actor.shop_id,
                points_balance=opening,
                lifetime_earned=opening,
                opening_points=opening,
            )
        )
    db.commit()
    return customer


def checkout(db, setup, lines, *, customer=None, paid=None, redemption=0, discount="0"):
    actor = replace(setup[0], permissions=setup[0].permissions | {"loyalty:write"})
    return finalize_invoice(
        db,
        actor,
        InvoiceCreate.model_validate(
            {
                "counter_id": setup[1][0],
                "items": lines,
                "customer_id": customer.id if customer else None,
                "discount_total": discount,
                "redeem_points": redemption,
                "payments": [{"method": "cash", "amount": paid}] if paid != "0" else [],
                "allow_due": paid is not None,
            }
        ),
        str(uuid4()),
    )


def line(product, qty):
    return {"product_id": product.id, "quantity": qty}


def return_body(rows, *, method="cash", reason="Customer returned goods"):
    return ReturnWrite.model_validate({"lines": rows, "refund_method": method, "reason": reason})


def selected(sale, qty, batch=None, disposition=None, verified=False, index=0):
    return {
        "invoice_item_id": sale.items[index].id,
        "quantity": qty,
        "batch_id": batch,
        "disposition": disposition,
        "verified": verified,
    }


def actor_for_reads(setup):
    actor = setup[0]
    return replace(actor, permissions=actor.permissions | {"sales:read", "customers:read"})


def check_entity(db, actor, area, entity_id):
    assert discrepancies(db, actor.shop_id, area, entity_id, 20, 0).total == 0


def test_full_return_exact_lot_replay_and_immutable_invoice(setup):
    actor, _, goods, *_ = setup
    with SessionLocal() as db:
        purchase = prepare(db, setup, goods, "2")
        sale = checkout(db, setup, [line(goods, "1.500")])
        key = str(uuid4())
        body = return_body([selected(sale, "1.500", disposition="sellable", verified=True)])
        row = create_return(db, actor, sale.id, body, key)
        assert (row.amount, row.refund_amount, row.refund_status) == (
            Decimal("255.00"),
            Decimal("255.00"),
            "completed",
        )
        assert create_return(db, actor, sale.id, body, key).idempotent_replay
        with pytest.raises(ConflictError):
            create_return(db, actor, sale.id, body, str(uuid4()))
        invoice = db.get(Invoice, sale.id)
        assert (invoice.total, invoice.paid_total, invoice.due_total, invoice.status) == (
            Decimal("255.00"),
            Decimal("255.00"),
            0,
            "finalized",
        )
        lot = db.scalar(select(StockLot).where(StockLot.purchase_item_id == purchase.items[0].id))
        assert lot.quantity_remaining == Decimal("2")
        movement = db.scalar(
            select(StockMovement).where(StockMovement.reference_id == row.lines[0].id)
        )
        source = db.get(StockMovement, movement.source_movement_id)
        assert movement.stock_lot_id == source.stock_lot_id == lot.id
        assert source.invoice_item_id == row.lines[0].invoice_item_id == sale.items[0].id
        for area, entity in (
            ("invoice", sale.id),
            ("refund", row.id),
            ("lot", lot.id),
            ("valuation", goods.id),
        ):
            check_entity(db, actor, area, entity)
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(
                text("UPDATE customer_returns SET reason = 'changed' WHERE id = :id"),
                {"id": row.id},
            )


def test_partial_paid_due_reduction_then_external_completion(setup):
    actor = actor_for_reads(setup)
    goods = setup[2]
    with SessionLocal() as db:
        prepare(db, setup, goods)
        customer = account_customer(db, actor)
        sale = checkout(db, setup, [line(goods, "2")], customer=customer, paid="100")
        row = create_return(db, actor, sale.id, return_body([selected(sale, "1.5")]), str(uuid4()))
        assert (row.amount, row.due_reduction, row.refund_amount) == (
            Decimal("255"),
            Decimal("240"),
            Decimal("15"),
        )
        assert db.get(Invoice, sale.id).due_total == 0
        assert db.scalar(
            select(CustomerLedgerEntry.amount).where(CustomerLedgerEntry.return_id == row.id)
        ) == Decimal("-240")
        body = return_body([selected(sale, ".5")], method="bkash")
        external = create_return(db, actor, sale.id, body, str(uuid4()))
        assert external.refund_amount == Decimal("85")
        assert external.refund_status == "pending" and external.refund_completed_at is None
        key = str(uuid4())
        completion = RefundComplete(reference=str(uuid4()))
        settled = complete_refund(db, actor, sale.id, external.id, completion, key)
        assert (
            settled.refund_status == "completed"
            and settled.refund_reference == completion.reference
        )
        assert complete_refund(db, actor, sale.id, external.id, completion, key).idempotent_replay
        with pytest.raises(ConflictError):
            complete_refund(db, actor, sale.id, external.id, completion, str(uuid4()))
        for area, entity in (
            ("invoice", sale.id),
            ("customer_due", sale.id),
            ("refund", external.id),
        ):
            check_entity(db, actor, area, entity)
        today = shop_date(db, actor.shop_id)
        report = finance_report(db, actor.shop_id, today, today)
        assert report.collections >= 100 and report.refunds >= 100


def test_due_only_reduction_then_collection_awards_retained_value(setup):
    actor = actor_for_reads(setup)
    goods = setup[2]
    with SessionLocal() as db:
        prepare(db, setup, goods)
        eligible(db, goods)
        customer = account_customer(db, actor)
        sale = checkout(db, setup, [line(goods, "3")], customer=customer, paid="0")
        row = create_return(
            db, actor, sale.id, return_body([selected(sale, "1")], method=None), str(uuid4())
        )
        assert (row.due_reduction, row.refund_amount, row.refund_status, row.earned_reversed) == (
            170,
            0,
            "none",
            0,
        )
        payment = collect_due_payment(
            db,
            actor,
            customer.id,
            sale.id,
            DuePaymentCreate(method="cash", amount=Decimal(340)),
            str(uuid4()),
        )
        assert payment.loyalty_points_earned == 3
        row = create_return(db, actor, sale.id, return_body([selected(sale, "1")]), str(uuid4()))
        assert row.earned_reversed == 1
        assert db.get(Invoice, sale.id).loyalty_points_earned == 3
        check_entity(db, actor, "customer_due", sale.id)


def eligible(db, goods):
    product = db.get(Product, goods.id)
    product.loyalty_eligible = True
    # Use an isolated category so eligibility tests leave the seeded categories alone.
    cat = Category(
        shop_id=goods.shop_id,
        slug=uuid4().hex,
        name_en="Returns",
        name_bn="ফেরত",
        loyalty_eligible=True,
    )
    db.add(cat)
    db.flush()
    product.category_id = cat.id
    db.commit()


def test_redemption_discount_per_item_and_negative_earned_balance(setup):
    actor, _, goods, medicine, _, _ = setup
    with SessionLocal() as db:
        prepare(db, setup, goods, "10")
        prepare(db, setup, medicine, "4")
        eligible(db, goods)
        customer = account_customer(db, actor, 295)
        first = checkout(db, setup, [line(goods, "3")], customer=customer)
        assert first.loyalty_points_earned == 5
        second = checkout(
            db,
            setup,
            [line(goods, "2"), line(medicine, "1")],
            customer=customer,
            redemption=300,
            discount="10",
        )
        assert second.total == Decimal("140")
        initial = create_return(
            db, actor, first.id, return_body([selected(first, "1")]), str(uuid4())
        )
        last = create_return(db, actor, first.id, return_body([selected(first, "2")]), str(uuid4()))
        assert (initial.earned_reversed, last.earned_reversed) == (1, 4)
        acct = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer.id))
        assert acct.points_balance == -5
        returned = create_return(
            db, actor, second.id, return_body([selected(second, "1")]), str(uuid4())
        )
        assert (returned.refund_amount, returned.redeemed_restored) == (15, 150)
        another = create_return(
            db, actor, second.id, return_body([selected(second, "1")]), str(uuid4())
        )
        assert (another.refund_amount, another.redeemed_restored) == (15, 150)
        batch = db.scalar(select(MedicineBatch).where(MedicineBatch.product_id == medicine.id))
        excluded = create_return(
            db,
            actor,
            second.id,
            return_body([selected(second, "1", batch.id, index=1)]),
            str(uuid4()),
        )
        assert (excluded.refund_amount, excluded.redeemed_restored) == (110, 0)
        db.refresh(acct)
        assert acct.points_balance == 295
        check_entity(db, actor, "loyalty", acct.id)


def test_medicine_default_quarantine_and_exact_verified_restore(setup):
    actor, _, _, medicine, _, _ = setup
    with SessionLocal() as db:
        prepare(db, setup, medicine, "2", "EARLY", 10)
        prepare(db, setup, medicine, "3", "LATE", 40)
        early, late = db.scalars(
            select(MedicineBatch)
            .where(MedicineBatch.product_id == medicine.id)
            .order_by(MedicineBatch.expiry_date)
        ).all()
        sale = checkout(db, setup, [line(medicine, "3")])
        quarantined = create_return(
            db, actor, sale.id, return_body([selected(sale, "1", early.id)]), str(uuid4())
        )
        assert (quarantined.lines[0].held, quarantined.lines[0].batch_id) == (True, early.id)
        assert (
            db.scalar(
                select(available_stock(shop_date(db, actor.shop_id))).where(
                    Product.id == medicine.id
                )
            )
            == 2
        )
        restored = create_return(
            db,
            actor,
            sale.id,
            return_body([selected(sale, "1", late.id, disposition="sellable", verified=True)]),
            str(uuid4()),
        )
        assert restored.lines[0].batch_id == late.id
        assert (
            db.scalar(
                select(available_stock(shop_date(db, actor.shop_id))).where(
                    Product.id == medicine.id
                )
            )
            == 3
        )
        check_entity(db, actor, "batch", early.id)
        check_entity(db, actor, "batch", late.id)
        resolved = resolve_stock(
            db,
            actor,
            sale.id,
            quarantined.lines[0].id,
            ResolveReturnStock(action="dispose", reason="Safe destruction"),
            str(uuid4()),
        )
        assert resolved.action == "dispose"
        db.refresh(early)
        assert early.held_quantity == 0 and early.quantity_on_hand == 0
        check_entity(db, actor, "batch", early.id)


def test_expired_and_unverified_medicine_cannot_be_restored(setup):
    actor, _, _, medicine, _, today = setup
    with SessionLocal() as db:
        prepare(db, setup, medicine, "3")
        batch = db.scalar(select(MedicineBatch).where(MedicineBatch.product_id == medicine.id))
        sale = checkout(db, setup, [line(medicine, "1")])
        with pytest.raises(ValidationError, match="verified"):
            create_return(
                db,
                actor,
                sale.id,
                return_body([selected(sale, "1", batch.id, "sellable")]),
                str(uuid4()),
            )
        batch.expiry_date = today
        db.commit()
        with pytest.raises(ValidationError, match="eligible"):
            create_return(
                db,
                actor,
                sale.id,
                return_body([selected(sale, "1", batch.id, "sellable", True)]),
                str(uuid4()),
            )
        row = create_return(
            db, actor, sale.id, return_body([selected(sale, "1", batch.id)]), str(uuid4())
        )
        assert row.lines[0].held
        assert db.scalar(select(available_stock(today)).where(Product.id == medicine.id)) == 0


def test_supplier_credit_and_duplicate_supplier_refund(setup):
    actor, _, goods, _, supplier, _ = setup
    with SessionLocal() as db:
        purchase = prepare(db, setup, goods, "4")
        stock = purchase_credits(db, actor, purchase.id)
        assert stock.payable == 50
        shipment = send_to_supplier(
            db,
            actor,
            purchase.id,
            SupplierReturnWrite.model_validate(
                {
                    "lines": [{"lot_id": stock.lots[0].lot_id, "quantity": "2"}],
                    "reason": "Damaged on arrival",
                }
            ),
            str(uuid4()),
        )
        assert shipment.cost == 25
        body = CreditWrite(
            shipment_id=shipment.id,
            reference="CN-RET-1",
            reason="Confirmed supplier credit",
            amount=Decimal(25),
        )
        note = create_credit(db, actor, purchase.id, body, str(uuid4()))
        assert note.available == 25
        with pytest.raises(ConflictError):
            create_credit(db, actor, purchase.id, body, str(uuid4()))
        note = apply_credit(
            db,
            actor,
            supplier.id,
            note.id,
            CreditApply(purchase_id=purchase.id, amount=Decimal(10)),
            str(uuid4()),
        )
        assert note.applied == 10 and note.available == 15
        pay = SupplierPaymentWrite(amount=Decimal(40), method="cash")
        assert pay_purchase(db, actor, purchase.id, pay, str(uuid4())).outstanding == 0
        money = SupplierRefundWrite(method="bank", reference="REF-1", amount=Decimal(5))
        key = str(uuid4())
        refund = record_supplier_refund(db, actor, supplier.id, note.id, money, key)
        assert refund.refunded == 5 and refund.available == 10
        assert record_supplier_refund(db, actor, supplier.id, note.id, money, key).idempotent_replay
        with pytest.raises(ConflictError):
            record_supplier_refund(db, actor, supplier.id, note.id, money, str(uuid4()))
        check_entity(db, actor, "supplier", purchase.id)
        check_entity(db, actor, "supplier", note.id)


def test_concurrent_returns_allow_exactly_one(setup):
    with SessionLocal() as db:
        prepare(db, setup, setup[2])
        sale = checkout(db, setup, [line(setup[2], "1")])
    body = return_body([selected(sale, "1")])
    responses = race(lambda db, _: create_return(db, setup[0], sale.id, body, str(uuid4())))
    assert sum(isinstance(r, ConflictError) for r in responses) == 1
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(CustomerReturn)
                .where(CustomerReturn.invoice_id == sale.id)
            )
            == 1
        )


def test_return_rollback_and_unauthorized_actions(setup, monkeypatch):
    actor = actor_for_reads(setup)
    with SessionLocal() as db:
        prepare(db, setup, setup[2])
        sale = checkout(db, setup, [line(setup[2], "1")])
        other = checkout(db, setup, [line(setup[2], "1")])
        body = return_body([selected(sale, "1", disposition="sellable", verified=True)])
        key = str(uuid4())
        with pytest.raises(HTTPException, match="403"):
            create_return(
                db, replace(actor, permissions=frozenset({"sales:write"})), sale.id, body, key
            )
        with pytest.raises(HTTPException, match="403"):
            invoice_returns(db, replace(actor, assigned_counter_ids={setup[1][1]}), sale.id)
        with pytest.raises(NotFoundError):
            create_return(db, actor, other.id, body, key)
        actual = customer_returns.post_stock

        def injected(*args, **kwargs):
            actual(*args, **kwargs)
            db.flush()
            raise RuntimeError("Simulated failure after stock and return writes")

        with monkeypatch.context() as patch:
            patch.setattr(customer_returns, "post_stock", injected)
            with pytest.raises(RuntimeError):
                create_return(db, actor, sale.id, body, key)
        assert not invoice_returns(db, actor, sale.id).history
        assert db.get(Product, setup[2].id).stock_on_hand == 3
        row = create_return(db, actor, sale.id, body, key)
        assert db.get(Product, setup[2].id).stock_on_hand == 4
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == row.id)))
        assert {"invoice.return", "refund.cash"} <= actions


def test_reconciliation_reports_without_repairing_projection(setup):
    actor, _, goods, *_ = setup
    with SessionLocal() as db:
        prepare(db, setup, goods)
        product = db.get(Product, goods.id)
        product.stock_on_hand += 1
        db.flush()
        result = discrepancies(db, actor.shop_id, "product", goods.id, 20, 0)
        assert result.total == 1 and result.items[0].check == "physical_stock"
        assert db.get(Product, goods.id).stock_on_hand == 6
        db.rollback()


def test_refund_uses_recorded_tender_and_rejects_drift(setup):
    actor, _, goods, *_ = setup
    with SessionLocal() as db:
        prepare(db, setup, goods)
        sale = checkout(db, setup, [line(goods, "1")])
        checkout_tender = db.scalar(select(Payment).where(Payment.invoice_id == sale.id))
        checkout_tender.amount -= 1
        db.commit()
        with pytest.raises(ConflictError, match="tender payment"):
            create_return(db, actor, sale.id, return_body([selected(sale, "1")]), str(uuid4()))
        found = discrepancies(db, actor.shop_id, "invoice", sale.id, 20, 0)
        assert found.total == 1 and found.items[0].check == "collections"
        checkout_tender.amount += 1
        db.commit()

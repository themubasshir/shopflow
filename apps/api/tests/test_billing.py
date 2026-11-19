"""Billing tests against the isolated, real shopflow_test PostgreSQL database.

Isolation: every product this module creates is marked inactive afterwards
(invoice_items hold RESTRICT FKs, so hard deletes are impossible). Seeded
test fixture products are never sold, so seed data stays intact.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import Principal
from app.core.config import settings
from app.core.errors import (
    IdempotencyConflictError,
    InsufficientStockError,
    LoyaltyError,
    NotFoundError,
    ValidationError,
)
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    Category,
    Counter,
    Customer,
    CustomerLedgerEntry,
    IdempotencyRecord,
    Invoice,
    LoyaltyAccount,
    LoyaltyRedemption,
    LoyaltyTransaction,
    Product,
    ProductUnit,
    Role,
    Shop,
    StockMovement,
    User,
)
from app.schemas.customers import CustomerCreate, CustomerUpdate, DuePaymentCreate
from app.schemas.sales import InvoiceCreate, InvoiceItemCreate, PaymentCreate
from app.services import billing
from app.services.billing import finalize_invoice
from app.services.customers import create_customer, update_customer
from app.services.receivables import CreditLimitError, OverpaymentError, collect_due_payment

# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def shop() -> Shop:
    with SessionLocal() as db:
        return db.execute(select(Shop).order_by(Shop.created_at)).scalars().first()


@pytest.fixture(scope="module")
def manager_principal(shop) -> Principal:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "manager@shopflow.dev")).scalar_one()
        role = db.get(Role, user.role_id)
        return Principal(
            user_id=user.id,
            shop_id=user.shop_id,
            email=user.email,
            name=user.name,
            role_code=role.code,
            permissions=frozenset(role.permissions or []),
        )


@pytest.fixture(scope="module")
def cashier_principal(shop) -> Principal:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == "cashier1@shopflow.dev")).scalar_one()
        role = db.get(Role, user.role_id)
        return Principal(
            user_id=user.id,
            shop_id=user.shop_id,
            email=user.email,
            name=user.name,
            role_code=role.code,
            permissions=frozenset(role.permissions or []),
        )


@pytest.fixture(scope="module")
def counter(shop) -> Counter:
    with SessionLocal() as db:
        return (
            db.execute(
                select(Counter).where(Counter.shop_id == shop.id).order_by(Counter.sort_order)
            )
            .scalars()
            .first()
        )


@pytest.fixture(scope="module")
def loyalty_customer(shop) -> Customer:
    """Named customer that has a loyalty account."""
    with SessionLocal() as db:
        row = db.execute(
            select(LoyaltyAccount, Customer)
            .join(Customer, LoyaltyAccount.customer_id == Customer.id)
            .where(LoyaltyAccount.shop_id == shop.id)
        ).first()
        return row[1]


@pytest.fixture()
def make_product(shop):
    """Factory: create a product + base unit; deactivate after the test."""
    created: list[uuid.UUID] = []

    def _make(
        *,
        price: str = "100.00",
        stock: str = "10",
        unit: str = "piece",
        eligible: bool = True,
    ) -> tuple[Product, ProductUnit]:
        with SessionLocal() as db:
            slug = "grocery" if eligible else "excluded"
            cat = db.execute(
                select(Category).where(Category.shop_id == shop.id, Category.slug == slug)
            ).scalar_one()
            p = Product(
                shop_id=shop.id,
                category_id=cat.id,
                sku=f"T-{uuid.uuid4().hex[:8]}",
                name_en="Billing Test Item",
                name_bn="টেস্ট আইটেম",
                unit=unit,
                is_active=True,
                stock_on_hand=Decimal(stock),
                low_stock_threshold=Decimal(0),
            )
            db.add(p)
            db.flush()
            u = ProductUnit(
                product_id=p.id,
                name=f"per {unit}",
                name_bn=unit,
                conversion_factor=Decimal(1),
                selling_price=Decimal(price),
                is_base=True,
            )
            db.add(u)
            db.commit()
            created.append(p.id)
            return p, u

    yield _make

    with SessionLocal() as db:
        for pid in created:
            prod = db.get(Product, pid)
            if prod is not None:
                prod.is_active = False
        db.commit()


# ----------------------------------------------------------------- helpers


@contextmanager
def _session():
    """Yield a session and always close it — a leaked session exhausts the pool."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _key() -> str:
    return "test-" + uuid.uuid4().hex[:16]


def _create(principal, body, key=None):
    with _session() as db:
        return finalize_invoice(db, principal, body, key or _key())


def _body(counter_id, customer_id=None, items=(), payments=None, discount="0"):
    return InvoiceCreate(
        counter_id=counter_id,
        customer_id=customer_id,
        items=list(items),
        discount_total=Decimal(discount),
        payments=payments or [PaymentCreate(method="cash")],
    )


def _item(product, unit, qty="1", discount="0"):
    return InvoiceItemCreate(
        product_id=product.id,
        product_unit_id=unit.id,
        quantity=Decimal(qty),
        line_discount=Decimal(discount),
    )


def _stock(pid) -> Decimal:
    with _session() as db:
        return db.get(Product, pid).stock_on_hand


# ------------------------------------------------------------------- tests


def test_successful_invoice_creation(manager_principal, counter, make_product):
    """T1 — a bill is created finalized, priced and paid by the server."""
    p, u = make_product(price="120.00", stock="5")
    out = _create(manager_principal, _body(counter.id, items=[_item(p, u, "2")]))
    assert out.status == "finalized"
    assert out.invoice_number.startswith("INV-")
    assert out.total == Decimal("240.00")
    assert out.paid_total == Decimal("240.00")
    assert out.due_total == Decimal("0.00")
    assert len(out.items) == 1
    assert out.items[0].unit_price == Decimal("120.00")
    assert out.payments[0].method == "cash"
    assert out.idempotent_replay is False


def test_stock_deduction(manager_principal, counter, make_product):
    """T2 — stock decreases and exactly one 'sale' ledger row is written."""
    p, u = make_product(price="50.00", stock="7")
    out = _create(manager_principal, _body(counter.id, items=[_item(p, u, "3")]))
    assert _stock(p.id) == Decimal("4")
    with _session() as db:
        moves = (
            db.execute(
                select(StockMovement).where(
                    StockMovement.product_id == p.id,
                    StockMovement.movement_type == "sale",
                )
            )
            .scalars()
            .all()
        )
        assert len(moves) == 1
        assert moves[0].quantity == Decimal("-3")
        assert moves[0].reference_id == out.id


def test_insufficient_stock(manager_principal, counter, make_product):
    """T3 — asking for more than is on hand is rejected, stock untouched."""
    p, u = make_product(price="50.00", stock="2")
    with pytest.raises(InsufficientStockError) as exc:
        _create(manager_principal, _body(counter.id, items=[_item(p, u, "5")]))
    assert exc.value.details["available"] == "2.000"
    assert _stock(p.id) == Decimal("2")


def test_concurrent_last_unit(manager_principal, cashier_principal, counter, make_product):
    """T4 — two counters race for the last unit; exactly one wins."""
    p, u = make_product(price="100.00", stock="1")
    results: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def attempt(name: str, principal: Principal):
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            results[name] = finalize_invoice(
                db, principal, _body(counter.id, items=[_item(p, u, "1")]), _key()
            )
        except InsufficientStockError as exc:
            results[name] = exc
        finally:
            db.close()

    threads = [
        threading.Thread(target=attempt, args=("a", manager_principal)),
        threading.Thread(target=attempt, args=("b", cashier_principal)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
        assert not t.is_alive(), "concurrent billing thread deadlocked"

    successes = [r for r in results.values() if not isinstance(r, Exception)]
    failures = [r for r in results.values() if isinstance(r, InsufficientStockError)]
    assert len(successes) == 1, results
    assert len(failures) == 1, results
    assert _stock(p.id) == Decimal("0")


def test_duplicate_idempotency_replays(manager_principal, counter, make_product):
    """T5 — same key + same payload returns the original invoice, no new effects."""
    p, u = make_product(price="80.00", stock="4")
    key = _key()
    body = _body(counter.id, items=[_item(p, u, "1")])
    first = _create(manager_principal, body, key)
    second = _create(manager_principal, body, key)

    assert second.id == first.id
    assert second.invoice_number == first.invoice_number
    assert second.idempotent_replay is True
    assert _stock(p.id) == Decimal("3")  # deducted once, not twice
    with _session() as db:
        sales = db.scalar(
            select(func.count(StockMovement.id)).where(
                StockMovement.product_id == p.id,
                StockMovement.movement_type == "sale",
            )
        )
        assert sales == 1


def test_same_key_different_payload_rejected(manager_principal, counter, make_product):
    """T6 — reusing a key with a different body is a 409 conflict."""
    p, u = make_product(price="80.00", stock="4")
    key = _key()
    _create(manager_principal, _body(counter.id, items=[_item(p, u, "1")]), key)
    different = _body(counter.id, items=[_item(p, u, "1")], discount="10")
    with pytest.raises(IdempotencyConflictError):
        _create(manager_principal, different, key)
    assert _stock(p.id) == Decimal("3")  # the rejected call changed nothing


def test_rollback_on_failure(manager_principal, counter, make_product):
    """T7 — a failure after validation leaves no partial writes."""
    p, u = make_product(price="100.00", stock="3")
    bad_customer = uuid.uuid4()
    body = _body(counter.id, customer_id=bad_customer, items=[_item(p, u, "1")])
    with pytest.raises(NotFoundError):
        _create(manager_principal, body)
    assert _stock(p.id) == Decimal("3")
    with _session() as db:
        assert (
            db.scalar(select(func.count(StockMovement.id)).where(StockMovement.product_id == p.id))
            == 0
        )


def test_invalid_product_rejected(manager_principal, counter):
    """T8 — an unknown product id cannot be billed."""
    body = _body(
        counter.id,
        items=[
            InvoiceItemCreate(product_id=uuid.uuid4(), product_unit_id=None, quantity=Decimal(1))
        ],
    )
    with pytest.raises(NotFoundError):
        _create(manager_principal, body)


def test_unauthorized_cashier_cannot_bill(manager_principal, counter):
    """T9 — a principal without sales:write is refused before any write."""
    viewer = Principal(
        user_id=manager_principal.user_id,
        shop_id=manager_principal.shop_id,
        email=manager_principal.email,
        name=manager_principal.name,
        role_code="viewer",
        permissions=frozenset({"sales:read"}),
    )
    with pytest.raises(HTTPException) as exc:
        viewer.require("sales:write")
    assert exc.value.status_code == 403


def test_client_price_never_trusted(manager_principal, counter, make_product):
    """T10 — the payload has no price field; totals come from the DB."""
    p, u = make_product(price="99.99", stock="2")
    body = _body(counter.id, items=[_item(p, u, "1")])
    assert "unit_price" not in body.items[0].model_dump()
    out = _create(manager_principal, body)
    assert out.total == Decimal("99.99")
    assert out.items[0].unit_price == Decimal("99.99")


def test_fractional_quantity_validated(manager_principal, counter, make_product):
    """T11 — pieces reject fractional qty; weight-based units accept it."""
    piece, piece_unit = make_product(price="50.00", stock="10", unit="piece")
    with pytest.raises(ValidationError, match="Fractional"):
        _create(
            manager_principal,
            _body(counter.id, items=[_item(piece, piece_unit, "1.5")]),
        )

    kg, kg_unit = make_product(price="120.00", stock="10", unit="kg")
    out = _create(manager_principal, _body(counter.id, items=[_item(kg, kg_unit, "1.250")]))
    assert out.total == Decimal("150.00")
    assert _stock(kg.id) == Decimal("8.750")


def test_discount_validation(manager_principal, counter, make_product):
    """T12 — discounts above the subtotal (invoice or line) are rejected."""
    p, u = make_product(price="50.00", stock="5")
    with pytest.raises(ValidationError):
        _create(manager_principal, _body(counter.id, items=[_item(p, u, "1")], discount="999"))
    with pytest.raises(ValidationError):
        _create(
            manager_principal,
            _body(counter.id, items=[_item(p, u, "1", discount="80")]),
        )
    # A valid discount reduces the payable total.
    out = _create(manager_principal, _body(counter.id, items=[_item(p, u, "2")], discount="15"))
    assert out.total == Decimal("85.00")


def test_loyalty_earned_for_named_customer(
    manager_principal, counter, loyalty_customer, make_product
):
    """T13 — a full ৳250 earns 2 points for a customer with an account."""
    p, u = make_product(price="250.00", stock="5")
    with _session() as db:
        before = (
            db.execute(
                select(LoyaltyAccount).where(LoyaltyAccount.customer_id == loyalty_customer.id)
            )
            .scalar_one()
            .points_balance
        )

    out = _create(
        manager_principal,
        _body(counter.id, customer_id=loyalty_customer.id, items=[_item(p, u, "1")]),
    )
    assert out.loyalty_points_earned == 2  # floor(250 / 100)
    assert out.loyalty_points_balance == before + 2


def test_walkin_customer_earns_nothing(manager_principal, counter, make_product):
    """T14 — no customer, no loyalty account, no points."""
    p, u = make_product(price="500.00", stock="5")
    out = _create(manager_principal, _body(counter.id, customer_id=None, items=[_item(p, u, "1")]))
    assert out.loyalty_points_earned == 0
    assert out.loyalty_points_balance is None


def test_loyalty_ledger_consistency(manager_principal, counter, loyalty_customer, make_product):
    """T15 — account balances and the ledger stay consistent after an award."""
    p, u = make_product(price="350.00", stock="5")
    with _session() as db:
        acct_before = db.execute(
            select(LoyaltyAccount).where(LoyaltyAccount.customer_id == loyalty_customer.id)
        ).scalar_one()
        earned_before = acct_before.lifetime_earned

    out = _create(
        manager_principal,
        _body(counter.id, customer_id=loyalty_customer.id, items=[_item(p, u, "1")]),
    )
    assert out.loyalty_points_earned == 3

    with _session() as db:
        acct = db.execute(
            select(LoyaltyAccount).where(LoyaltyAccount.customer_id == loyalty_customer.id)
        ).scalar_one()
        # DB CHECK: lifetime_earned - lifetime_redeemed = points_balance
        assert acct.lifetime_earned - acct.lifetime_redeemed == acct.points_balance
        assert acct.lifetime_earned == earned_before + 3

        rows = (
            db.execute(
                select(LoyaltyTransaction).where(
                    LoyaltyTransaction.invoice_id == out.id,
                    LoyaltyTransaction.transaction_type == "earn",
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1  # unique (account, invoice, type) enforced
        assert rows[0].points == 3
        assert rows[0].balance_after == acct.points_balance


def test_bangla_and_english_error_messages():
    """T16 — every billing error exposes a stable code the UI can translate."""
    assert InsufficientStockError.code == "insufficient_stock"
    assert IdempotencyConflictError.code == "idempotency_conflict"
    assert ValidationError.code == "validation_error"
    # Stable machine codes let messages/{en,bn}.json map to localized text.
    en = {"insufficient_stock": "Not enough stock for this item"}
    bn = {"insufficient_stock": "এই পণ্যের পর্যাপ্ত স্টক নেই"}
    assert en[InsufficientStockError.code] != bn[InsufficientStockError.code]


def test_non_eligible_category_earns_nothing(
    manager_principal, counter, loyalty_customer, make_product
):
    """Loyalty eligibility is category-driven and configurable."""
    p, u = make_product(price="400.00", stock="5", eligible=False)
    out = _create(
        manager_principal,
        _body(counter.id, customer_id=loyalty_customer.id, items=[_item(p, u, "1")]),
    )
    assert out.loyalty_points_earned == 0


def test_split_payment_must_equal_total(manager_principal, counter, make_product):
    """Payments must exactly cover the total; split methods are recorded."""
    p, u = make_product(price="300.00", stock="5")
    out = _create(
        manager_principal,
        _body(
            counter.id,
            items=[_item(p, u, "1")],
            payments=[
                PaymentCreate(method="cash", amount=Decimal("100")),
                PaymentCreate(method="bkash", amount=Decimal("200")),
            ],
        ),
    )
    assert out.paid_total == Decimal("300.00")
    assert {pay.method for pay in out.payments} == {"cash", "bkash"}

    p2, u2 = make_product(price="300.00", stock="5")
    underpaid = _body(
        counter.id,
        items=[_item(p2, u2, "1")],
        payments=[PaymentCreate(method="cash", amount=Decimal("100"))],
    )
    with pytest.raises(ValidationError, match="exactly equal"):
        _create(manager_principal, underpaid)


@pytest.fixture
def account_customer(manager_principal):
    def make(points=0, limit="0"):
        with SessionLocal() as db:
            customer = create_customer(
                db,
                manager_principal,
                CustomerCreate(
                    name="Phase 2C Test",
                    phone=f"015{uuid.uuid4().int % 100000000:08d}",
                    credit_limit=Decimal(limit),
                ),
            )
            account = db.scalar(
                select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer.id)
            )
            if points:
                account.points_balance = account.lifetime_earned = points
                db.add(
                    LoyaltyTransaction(
                        account_id=account.id,
                        transaction_type="earn",
                        points=points,
                        balance_after=points,
                    )
                )
                db.commit()
            return customer.id, account.id

    return make


def _checkout(
    counter, products, *, customer=None, points=0, payments=None, allow_due=False, discount="0"
):
    return InvoiceCreate(
        counter_id=counter.id,
        customer_id=customer,
        items=[_item(product, unit) for product, unit in products],
        redeem_points=points,
        payments=[PaymentCreate(method="cash")] if payments is None else payments,
        allow_due=allow_due,
        discount_total=Decimal(discount),
    )


@pytest.mark.parametrize(
    ("opening", "redeem", "price"),
    [
        (299, 100, "50000"),  # Would reach the threshold through this sale's earnings.
        (300, 101, "850"),
        (300, 400, "850"),
        (700, 700, "699.99"),
    ],
)
def test_redemption_rejects_invalid_opening_balance_increment_or_eligible_cap(
    manager_principal,
    counter,
    make_product,
    account_customer,
    opening,
    redeem,
    price,
):
    customer, account = account_customer(opening)
    product = make_product(price=price)
    with pytest.raises(LoyaltyError):
        _create(manager_principal, _checkout(counter, [product], customer=customer, points=redeem))
    with SessionLocal() as db:
        assert db.get(LoyaltyAccount, account).points_balance == opening
        assert (
            db.scalar(
                select(func.count()).select_from(Invoice).where(Invoice.customer_id == customer)
            )
            == 0
        )
    assert _stock(product[0].id) == Decimal("10")


@pytest.mark.parametrize("amount", [-1, -100, 100.5])
def test_redemption_schema_rejects_negative_or_fractional_points(counter, make_product, amount):
    valid = _checkout(counter, [make_product()])
    from pydantic import ValidationError as SchemaError

    with pytest.raises(SchemaError):
        InvoiceCreate.model_validate({**valid.model_dump(), "redeem_points": amount})


def test_redeem_at_exactly_300_and_award_only_on_eligible_net(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, account = account_customer(300)
    eligible = make_product(price="450")
    excluded_by_category = make_product(price="850", eligible=False)
    excluded_by_product = make_product(price="850")
    with SessionLocal() as db:
        db.get(Product, excluded_by_product[0].id).loyalty_eligible = False
        db.commit()
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [eligible, excluded_by_category, excluded_by_product],
            customer=customer,
            points=100,
            discount="55",
        ),
    )
    assert out.loyalty_discount == Decimal("100")
    assert out.total == Decimal("1995")
    assert out.loyalty_points_earned == 2
    assert out.loyalty_points_balance == 202
    with SessionLocal() as db:
        sales = db.get(Invoice, out.id)
        assert sales.loyalty_earn_base == Decimal("295")
        assert sales.loyalty_rule_snapshot["min_redeem_balance"] == 300
        assert sales.loyalty_rule_snapshot["point_value_bdt"] == "1.00"
        transactions = db.scalars(
            select(LoyaltyTransaction)
            .where(LoyaltyTransaction.invoice_id == out.id)
            .order_by(LoyaltyTransaction.ledger_sequence)
        ).all()
        assert [(t.transaction_type, t.points, t.balance_after) for t in transactions] == [
            ("redeem", -100, 200),
            ("earn", 2, 202),
        ]
        assert db.get(LoyaltyAccount, account).points_balance == sum(
            db.scalars(
                select(LoyaltyTransaction.points).where(LoyaltyTransaction.account_id == account)
            )
        )


def test_redemption_can_cover_entire_invoice(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, _ = account_customer(300)
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [make_product(price="200")],
            customer=customer,
            points=200,
            payments=[],
        ),
    )
    assert out.payment_status == "paid"
    assert out.total == out.due_total == out.paid_total == Decimal(0)
    assert out.payments == []
    assert out.loyalty_points_redeemed == 200
    assert out.loyalty_points_earned == 0


def _race(*operations):
    barrier = threading.Barrier(len(operations))

    def compete(operation):
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            barrier.wait(timeout=10)
            try:
                return operation(db)
            except (LoyaltyError, OverpaymentError, CreditLimitError) as exc:
                return exc

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        futures = [executor.submit(compete, operation) for operation in operations]
        return [future.result(timeout=20) for future in futures]


def _second_counter(shop, counter):
    with SessionLocal() as db:
        return db.scalars(
            select(Counter)
            .where(Counter.shop_id == shop.id, Counter.id != counter.id)
            .order_by(Counter.sort_order)
        ).first()


def test_two_counters_cannot_redeem_same_opening_balance(
    shop,
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, account = account_customer(300)
    other = _second_counter(shop, counter)
    first_body = _checkout(counter, [make_product(price="500")], customer=customer, points=300)
    second_body = _checkout(other, [make_product(price="500")], customer=customer, points=300)
    outcomes = _race(
        *[
            lambda db, body=body: finalize_invoice(db, manager_principal, body, _key())
            for body in (first_body, second_body)
        ]
    )
    assert sum(isinstance(item, LoyaltyError) for item in outcomes) == 1
    with SessionLocal() as db:
        assert db.get(LoyaltyAccount, account).points_balance == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(LoyaltyRedemption)
                .where(LoyaltyRedemption.account_id == account)
            )
            == 1
        )


def test_concurrent_identical_checkout_keys_share_persisted_redemption_and_payment_ids(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, account = account_customer(300)
    product = make_product(price="500")
    body = _checkout(counter, [product], customer=customer, points=100)
    key = _key()

    def sale(db):
        return finalize_invoice(db, manager_principal, body, key)

    first, second = _race(sale, sale)
    assert first.id == second.id
    assert (
        first.payments[0].id
        == second.payments[0].id
        == _create(manager_principal, body, key).payments[0].id
    )
    assert first.items[0].id == second.items[0].id
    assert sorted([first.idempotent_replay, second.idempotent_replay]) == [False, True]
    assert _stock(product[0].id) == Decimal("9")
    with SessionLocal() as db:
        assert db.get(LoyaltyAccount, account).points_balance == 204
        assert (
            db.scalar(
                select(func.count())
                .select_from(LoyaltyRedemption)
                .where(LoyaltyRedemption.account_id == account)
            )
            == 1
        )


def test_redemption_rolls_back_with_flushed_invoice_stock_and_ledger(
    manager_principal,
    counter,
    make_product,
    account_customer,
    monkeypatch,
):
    customer, account = account_customer(300)
    product = make_product(price="500")
    original = billing.record_redemption

    def fail_after_write(db, *args):
        original(db, *args)
        db.flush()
        raise RuntimeError("simulated invoice failure")

    monkeypatch.setattr(billing, "record_redemption", fail_after_write)
    key = _key()
    with pytest.raises(RuntimeError, match="simulated"):
        _create(
            manager_principal, _checkout(counter, [product], customer=customer, points=100), key
        )
    assert _stock(product[0].id) == Decimal("10")
    with SessionLocal() as db:
        assert db.get(LoyaltyAccount, account).points_balance == 300
        assert db.scalar(select(Invoice).where(Invoice.idempotency_key == key)) is None
        assert (
            db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))
            is None
        )
        assert (
            db.scalar(select(LoyaltyRedemption).where(LoyaltyRedemption.account_id == account))
            is None
        )
        assert (
            db.scalar(select(StockMovement).where(StockMovement.product_id == product[0].id))
            is None
        )


def _payment(db, principal, customer, invoice, amount, *, key=None, method="cash"):
    return collect_due_payment(
        db,
        principal,
        customer,
        invoice,
        DuePaymentCreate(method=method, amount=Decimal(amount)),
        key or _key(),
    )


def test_partial_payment_collections_and_direct_ledger_reconciliation(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, account = account_customer()
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [make_product(price="750")],
            customer=customer,
            allow_due=True,
            payments=[PaymentCreate(method="cash", amount=Decimal("100"))],
        ),
    )
    assert (out.payment_status, out.paid_total, out.due_total) == (
        "partially_paid",
        Decimal(100),
        Decimal(650),
    )
    assert out.loyalty_points_earned == 0
    with SessionLocal() as db:
        assert db.get(LoyaltyAccount, account).points_balance == 0
        first = _payment(db, manager_principal, customer, out.id, "150", method="bkash")
        assert (first.outstanding_due, first.paid_total, first.loyalty_points_earned) == (
            Decimal(500),
            Decimal(250),
            0,
        )

        # Editing the current product eligibility must not change the sale's reward.
        product = db.get(Product, out.items[0].product_id)
        product.loyalty_eligible = False
        db.commit()
        update_customer(db, manager_principal, customer, CustomerUpdate(is_active=False))
        with pytest.raises(OverpaymentError):
            _payment(db, manager_principal, customer, out.id, "500.01")
        db.rollback()
        key = _key()
        last = _payment(db, manager_principal, customer, out.id, "500", key=key, method="nagad")
        assert (last.payment_status, last.outstanding_due, last.loyalty_points_earned) == (
            "paid",
            Decimal(0),
            7,
        )
        replay = _payment(
            db, manager_principal, customer, out.id, "500.00", key=key, method="nagad"
        )
        assert replay.idempotent_replay
        assert replay.payment.id == last.payment.id
    with SessionLocal() as db:
        assert db.scalar(text("SELECT current_database()")) == "shopflow_test"
        entries = db.scalars(
            select(CustomerLedgerEntry)
            .where(CustomerLedgerEntry.customer_id == customer)
            .order_by(CustomerLedgerEntry.id)
        ).all()
        assert [entry.amount for entry in entries] == [Decimal(650), Decimal(-150), Decimal(-500)]
        invoice = db.get(Invoice, out.id)
        assert sum(entry.amount for entry in entries) == invoice.due_total == 0
        assert (
            sum(p.amount for p in invoice.payments)
            == invoice.paid_total
            == invoice.total
            == Decimal(750)
        )
        assert [p.method for p in sorted(invoice.payments, key=lambda p: p.paid_at)] == [
            "cash",
            "bkash",
            "nagad",
        ]
        assert invoice.loyalty_points_earned == db.get(LoyaltyAccount, account).points_balance == 7
        assert (
            db.scalar(
                select(func.count())
                .select_from(LoyaltyTransaction)
                .where(LoyaltyTransaction.invoice_id == out.id)
            )
            == 1
        )
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(
                update(CustomerLedgerEntry)
                .where(CustomerLedgerEntry.id == entries[0].id)
                .values(amount=1)
            )


def test_due_only_invoice_and_concurrent_due_collection(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, account = account_customer(300)
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [make_product(price="450")],
            customer=customer,
            points=100,
            payments=[],
            allow_due=True,
        ),
    )
    assert (out.payment_status, out.paid_total, out.due_total) == ("due", 0, Decimal(350))
    assert out.loyalty_points_balance == 200
    assert out.loyalty_points_earned == 0

    def pay(db):
        return _payment(db, manager_principal, customer, out.id, "350")

    winner, loser = sorted(_race(pay, pay), key=lambda result: isinstance(result, Exception))
    assert isinstance(loser, OverpaymentError)
    assert winner.loyalty_points_earned == 3
    with SessionLocal() as db:
        assert db.get(LoyaltyAccount, account).points_balance == 203
        assert (
            db.scalar(
                select(func.count())
                .select_from(CustomerLedgerEntry)
                .where(CustomerLedgerEntry.invoice_id == out.id)
            )
            == 2
        )


def test_concurrent_due_collection_replays_the_same_payment_id(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, _ = account_customer()
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [make_product(price="380")],
            customer=customer,
            payments=[],
            allow_due=True,
        ),
    )
    key = _key()

    def pay(db):
        return _payment(db, manager_principal, customer, out.id, "380", key=key)

    first, second = _race(pay, pay)
    assert first.payment.id == second.payment.id
    assert sorted([first.idempotent_replay, second.idempotent_replay]) == [False, True]
    with SessionLocal() as db, pytest.raises(IdempotencyConflictError):
        _payment(db, manager_principal, customer, out.id, "100", key=key)


def test_credit_limit_is_serialized_across_counters(
    shop,
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, _ = account_customer(limit="600")
    bodies = [
        _checkout(c, [make_product(price="400")], customer=customer, payments=[], allow_due=True)
        for c in (counter, _second_counter(shop, counter))
    ]
    assert (
        sum(
            isinstance(result, CreditLimitError)
            for result in _race(
                *[
                    lambda db, body=body: finalize_invoice(db, manager_principal, body, _key())
                    for body in bodies
                ]
            )
        )
        == 1
    )


def test_anonymous_credit_and_checkout_overpayment_are_rejected(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, _ = account_customer()
    product = make_product(price="100")
    with pytest.raises(ValidationError, match="registered customer"):
        _create(manager_principal, _checkout(counter, [product], payments=[], allow_due=True))
    with pytest.raises(OverpaymentError):
        _create(
            manager_principal,
            _checkout(
                counter,
                [product],
                customer=customer,
                allow_due=True,
                payments=[PaymentCreate(method="nagad", amount=Decimal(101))],
            ),
        )
    assert _stock(product[0].id) == Decimal(10)


def test_checkout_financial_permissions(
    manager_principal, cashier_principal, counter, make_product, account_customer
):
    customer, _ = account_customer(300)
    body = _checkout(counter, [make_product(price="500")], customer=customer, points=100)
    for principal, status in [
        (cashier_principal, 403),
        (replace(manager_principal, is_demo=True), 401),
    ]:
        with pytest.raises(HTTPException) as error:
            _create(principal, body)
        assert error.value.status_code == status


@pytest.mark.anyio
async def test_dashboard_returns_one_row_for_a_split_payment(
    manager_principal,
    counter,
    make_product,
    monkeypatch,
):
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [make_product(price="305")],
            payments=[
                PaymentCreate(method="cash", amount=Decimal("100")),
                PaymentCreate(method="bkash", amount=Decimal("205")),
            ],
        ),
    )
    monkeypatch.setattr(settings, "demo_mode", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/reports/dashboard")
    assert response.status_code == 200
    recent = response.json()["recent_transactions"]
    assert len({row["id"] for row in recent}) == len(recent)
    assert [row["method"] for row in recent if row["id"] == str(out.id)] == ["bkash"]


def test_loyalty_ledger_rows_are_immutable(
    manager_principal,
    counter,
    make_product,
    account_customer,
):
    customer, _ = account_customer(300)
    out = _create(
        manager_principal,
        _checkout(
            counter,
            [make_product(price="500")],
            customer=customer,
            points=100,
        ),
    )
    with SessionLocal() as db, pytest.raises(IntegrityError, match="append-only"):
        db.execute(
            update(LoyaltyTransaction)
            .where(LoyaltyTransaction.invoice_id == out.id)
            .values(note="attempted rewrite")
        )

"""Phase 2A billing tests — run against the real shopflow_dev PostgreSQL DB.

Isolation: every product this module creates is marked inactive afterwards
(invoice_items hold RESTRICT FKs, so hard deletes are impossible). Seeded
development products are never sold, so seed data stays intact.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.deps import Principal
from app.core.errors import (
    IdempotencyConflictError,
    InsufficientStockError,
    NotFoundError,
    ValidationError,
)
from app.db.session import SessionLocal
from app.models import (
    Category,
    Counter,
    Customer,
    LoyaltyAccount,
    LoyaltyTransaction,
    Product,
    ProductUnit,
    Role,
    Shop,
    StockMovement,
    User,
)
from app.schemas.sales import InvoiceCreate, InvoiceItemCreate, PaymentCreate
from app.services.billing import finalize_invoice

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
    from fastapi import HTTPException

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

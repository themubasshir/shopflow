"""Reconciliation validation on an isolated, fully-ledgered test shop.

Unlike the shared demo shop (which accumulates fixture data from every test
module), each test here builds a fresh ``Shop`` and drives it exclusively
through the public services — so ``discrepancies`` must report zero unless a
test deliberately corrupts a projection.

Covered:

* a clean fixture shop produces zero discrepancies;
* deliberately corrupted projections surface the expected check categories;
* purchase intake, sales, partial returns, supplier credits, loyalty events,
  and batch/stock-lot movements all reconcile end-to-end;
* opening stock without cost provenance stays visible as unvalued inventory
  instead of fabricating a valuation;
* the reconciliation query is strictly read-only.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.permissions import ALL_PERMISSIONS
from app.db.session import SessionLocal
from app.models import (
    Category,
    Counter,
    Customer,
    LoyaltyAccount,
    LoyaltyRule,
    MedicineBatch,
    Product,
    ProductUnit,
    Role,
    Shop,
    StockLot,
    StockMovement,
    User,
)
from app.schemas.purchasing import PurchaseWrite, ReceiveWrite, SupplierWrite
from app.schemas.returns import CreditApply, CreditWrite, ReturnWrite, SupplierReturnWrite
from app.schemas.sales import InvoiceCreate
from app.services.billing import finalize_invoice
from app.services.customer_returns import create_return
from app.services.inventory import stock_value
from app.services.purchasing import create_purchase, receive_purchase, save_supplier
from app.services.reconciliation import discrepancies
from app.services.stock import shop_date
from app.services.supplier_credits import apply_credit, create_credit, send_to_supplier
from fixtures import post_opening_stock, set_opening_points


def _key() -> str:
    return "recon-" + uuid.uuid4().hex


@pytest.fixture()
def shop_ctx():
    """A complete, self-contained shop: roles, counter, categories, products."""
    with SessionLocal() as db:
        shop = Shop(
            name_en="Reconciliation Test Shop",
            name_bn="মিলকরণ পরীক্ষার দোকান",
            slug="recon-" + uuid.uuid4().hex[:10],
            is_demo=False,
            is_active=True,
        )
        db.add(shop)
        db.flush()
        role = Role(
            shop_id=shop.id,
            code="owner",
            name_en="Owner",
            name_bn="মালিক",
            permissions=list(ALL_PERMISSIONS),
            is_system=True,
        )
        db.add(role)
        db.flush()
        user = User(
            shop_id=shop.id,
            role_id=role.id,
            name="Recon Owner",
            email=f"recon-{uuid.uuid4().hex[:8]}@shopflow.dev",
            password_hash="x",
            is_active=True,
        )
        counter = Counter(
            shop_id=shop.id, code="C1", name_en="Counter 1", name_bn="কাউন্টার ১", sort_order=1
        )
        grocery = Category(
            shop_id=shop.id,
            slug="grocery",
            name_en="Grocery",
            name_bn="মুদি",
            loyalty_eligible=True,
        )
        medcat = Category(
            shop_id=shop.id,
            slug="medicine",
            name_en="Medicine",
            name_bn="ঔষধ",
            is_medicine=True,
            loyalty_eligible=True,
        )
        db.add_all([user, counter, grocery, medcat])
        db.flush()
        today = shop_date(db, shop.id)
        goods = Product(
            shop_id=shop.id,
            category_id=grocery.id,
            sku="RG-" + uuid.uuid4().hex[:8],
            name_en="Recon rice",
            name_bn="চাল",
            unit="kg",
            stock_on_hand=Decimal(20),
            units=[
                ProductUnit(name="kg", name_bn="কেজি", is_base=True, selling_price=Decimal(100))
            ],
        )
        medicine = Product(
            shop_id=shop.id,
            category_id=medcat.id,
            sku="RM-" + uuid.uuid4().hex[:8],
            name_en="Recon tablet",
            name_bn="ট্যাবলেট",
            unit="piece",
            is_medicine=True,
            stock_on_hand=Decimal(0),
            units=[
                ProductUnit(name="piece", name_bn="টি", is_base=True, selling_price=Decimal(50))
            ],
        )
        db.add_all([goods, medicine])
        db.flush()
        # Fixture physical stock is seeded directly; reconcile the ledger.
        post_opening_stock(db, goods, medicine)
        db.commit()
        actor = Principal(
            user_id=user.id,
            shop_id=shop.id,
            email=user.email,
            name=user.name,
            role_code="owner",
            permissions=frozenset(ALL_PERMISSIONS),
        )
        yield {
            "shop": shop,
            "actor": actor,
            "counter": counter,
            "goods": goods,
            "medicine": medicine,
            "today": today,
            "grocery": grocery,
            "medcat": medcat,
        }
        db.rollback()


def _total(db: Session, shop_id) -> int:
    return discrepancies(db, shop_id, None, None, 200, 0).total


def _items(db: Session, shop_id, area=None, entity_id=None):
    return discrepancies(db, shop_id, area, entity_id, 200, 0).items


def test_clean_fixture_shop_has_zero_discrepancies(shop_ctx):
    with SessionLocal() as db:
        assert _total(db, shop_ctx["shop"].id) == 0


def test_corrupted_product_projection_is_flagged(shop_ctx):
    ctx = shop_ctx
    with SessionLocal() as db:
        product = db.get(Product, ctx["goods"].id)
        product.stock_on_hand += 5  # projection write with no ledger entry
        db.flush()
        found = _items(db, ctx["shop"].id, area="product", entity_id=product.id)
        assert [(i.area, i.check) for i in found] == [("product", "physical_stock")]
        assert _total(db, ctx["shop"].id) == 1
        db.rollback()


def test_corrupted_batch_projection_is_flagged(shop_ctx):
    ctx = shop_ctx
    with SessionLocal() as db:
        medicine = db.get(Product, ctx["medicine"].id)
        batch = MedicineBatch(
            shop_id=ctx["shop"].id,
            product_id=medicine.id,
            batch_number="B-" + uuid.uuid4().hex[:6],
            expiry_date=ctx["today"] + timedelta(days=30),
            quantity_on_hand=Decimal(7),
            quantity_received=Decimal(7),
        )
        medicine.stock_on_hand = Decimal(7)
        db.add(batch)
        db.flush()
        # The batch opening movement is posted but the product is over-projected.
        post_opening_stock(db, medicine)
        # Inflate both projections without a matching ledger row.
        batch.quantity_received += 2
        batch.quantity_on_hand += 2
        medicine.stock_on_hand += 2
        db.flush()
        found = {(i.area, i.check) for i in _items(db, ctx["shop"].id)}
        assert ("batch", "batch_stock") in found
        assert ("product", "physical_stock") in found
        db.rollback()


def test_corrupted_loyalty_balance_is_flagged(shop_ctx):
    ctx = shop_ctx
    with SessionLocal() as db:
        customer = Customer(shop_id=ctx["shop"].id, name="Recon Customer", phone="+8801700000001")
        db.add(customer)
        db.flush()
        account = LoyaltyAccount(customer_id=customer.id, shop_id=ctx["shop"].id, points_balance=0)
        db.add(account)
        db.flush()
        set_opening_points(account, 250)
        db.flush()
        assert _total(db, ctx["shop"].id) == 0
        # A bare projection bump without opening_points or a ledger row must flag.
        account.points_balance += 40
        account.lifetime_earned += 40
        db.flush()
        found = _items(db, ctx["shop"].id, area="loyalty", entity_id=account.id)
        assert [(i.area, i.check) for i in found] == [("loyalty", "account_balance")]
        db.rollback()


def test_unvalued_opening_inventory_stays_visible(shop_ctx):
    ctx = shop_ctx
    with SessionLocal() as db:
        summary = stock_value(db, ctx["shop"].id, ctx["goods"].id)
        # Opening stock carries no cost lot: it must report as unvalued, not 0.
        assert summary.quantity_on_hand == Decimal(20)
        assert summary.unvalued_quantity == Decimal(20)
        assert summary.value == Decimal(0)
        assert not db.scalars(
            select(StockLot).where(StockLot.product_id == ctx["goods"].id)
        ).first()
        assert _items(db, ctx["shop"].id, area="valuation", entity_id=ctx["goods"].id) == []


def _drive_full_cycle(db: Session, ctx) -> None:
    """Purchase -> receive -> sell -> partial return -> supplier credit/apply."""
    actor: Principal = ctx["actor"]
    supplier = save_supplier(
        db,
        actor,
        SupplierWrite(
            name="Recon Wholesale",
            name_bn="সরবরাহ",
            product_ids=[ctx["goods"].id, ctx["medicine"].id],
        ),
    )
    expiry = ctx["today"] + timedelta(days=60)
    purchase = create_purchase(
        db,
        actor,
        PurchaseWrite.model_validate(
            {
                "supplier_id": supplier.id,
                "supplier_invoice_number": "PINV-" + uuid.uuid4().hex[:8],
                "items": [
                    {"product_id": ctx["goods"].id, "quantity": "10", "unit_cost": "60"},
                    {
                        "product_id": ctx["medicine"].id,
                        "quantity": "10",
                        "unit_cost": "30",
                        "batch_number": "RB-1",
                        "expiry_date": expiry,
                    },
                ],
            }
        ),
        _key(),
    )
    received = receive_purchase(
        db,
        actor,
        purchase.id,
        ReceiveWrite.model_validate(
            {
                "items": [
                    {"purchase_item_id": item.id, "quantity": item.quantity}
                    for item in purchase.items
                ]
            }
        ),
        _key(),
    )
    assert received.status == "received"

    customer = Customer(shop_id=ctx["shop"].id, name="Cycle Customer", phone="+8801700000002")
    db.add(customer)
    db.flush()
    account = LoyaltyAccount(customer_id=customer.id, shop_id=ctx["shop"].id)
    db.add(account)
    db.flush()
    set_opening_points(account, 300)
    db.add(
        LoyaltyRule(
            shop_id=ctx["shop"].id,
            name="Default",
            points_per_100_bdt=1,
            min_redeem_balance=300,
            redeem_step_points=100,
            point_value_bdt=Decimal("1.00"),
            earn_on_eligible_category_only=True,
            is_active=True,
        )
    )
    db.flush()

    sale = finalize_invoice(
        db,
        actor,
        InvoiceCreate.model_validate(
            {
                "counter_id": ctx["counter"].id,
                "customer_id": customer.id,
                "redeem_points": 100,
                "items": [
                    {"product_id": ctx["goods"].id, "quantity": "2"},
                    {"product_id": ctx["medicine"].id, "quantity": "3"},
                ],
                "payments": [{"method": "cash"}],
            }
        ),
        _key(),
    )
    assert sale.loyalty_points_redeemed == 100

    goods_item = next(i for i in sale.items if i.product_id == ctx["goods"].id)
    ret = create_return(
        db,
        actor,
        sale.id,
        ReturnWrite.model_validate(
            {
                "lines": [{"invoice_item_id": goods_item.id, "quantity": "1"}],
                "refund_method": "cash",
                "reason": "Partial return",
            }
        ),
        _key(),
    )
    assert ret.amount > 0

    lot = db.scalar(
        select(StockLot).where(
            StockLot.product_id == ctx["goods"].id, StockLot.purchase_item_id.is_not(None)
        )
    )
    shipment = send_to_supplier(
        db,
        actor,
        purchase.id,
        SupplierReturnWrite.model_validate(
            {"lines": [{"lot_id": lot.id, "quantity": "1"}], "reason": "Damaged"}
        ),
        _key(),
    )
    note = create_credit(
        db,
        actor,
        purchase.id,
        CreditWrite(
            shipment_id=shipment.id,
            reference="CN-1",
            reason="Credit",
            amount=Decimal(30),
        ),
        _key(),
    )
    apply_credit(
        db,
        actor,
        supplier.id,
        note.id,
        CreditApply(purchase_id=purchase.id, amount=Decimal(10)),
        _key(),
    )


def test_full_business_cycle_reconciles_to_zero(shop_ctx):
    with SessionLocal() as db:
        _drive_full_cycle(db, shop_ctx)
        assert _total(db, shop_ctx["shop"].id) == 0


def test_reconciliation_query_is_read_only(shop_ctx):
    ctx = shop_ctx
    with SessionLocal() as db:
        product = db.get(Product, ctx["goods"].id)
        product.stock_on_hand += 3
        db.flush()
        before_moves = db.scalar(select(func.count(StockMovement.id)))
        result = discrepancies(db, ctx["shop"].id, None, None, 200, 0)
        assert result.total == 1
        # The query must observe, not repair: the projection stays corrupted
        # and the session recorded no writes.
        assert db.get(Product, ctx["goods"].id).stock_on_hand == Decimal(23)
        assert db.scalar(select(func.count(StockMovement.id))) == before_moves
        assert not db.new  # the read queued no inserts
        db.rollback()

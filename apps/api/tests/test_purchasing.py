from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import Principal
from app.core.errors import ConflictError, InsufficientStockError, ValidationError
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AuditLog,
    Category,
    Counter,
    InvoiceBatchAllocation,
    MedicineBatch,
    Product,
    ProductUnit,
    Shop,
    StockLot,
    StockMovement,
    SupplierLedger,
    User,
)
from app.schemas.purchasing import (
    BatchState,
    PurchaseWrite,
    ReceiveWrite,
    StockChange,
    SupplierPaymentWrite,
    SupplierWrite,
)
from app.schemas.sales import InvoiceCreate
from app.services import purchasing
from app.services.billing import finalize_invoice
from app.services.inventory import adjust_stock, set_batch_state, stock_value
from app.services.purchasing import (
    cancel_purchase,
    create_purchase,
    pay_purchase,
    receive_purchase,
    reverse_purchase,
    save_supplier,
)
from app.services.stock import shop_date


@pytest.fixture
def setup():
    with SessionLocal() as db:
        shop = db.scalar(select(Shop).where(Shop.is_demo.is_(True)).order_by(Shop.created_at))
        owner = db.scalar(
            select(User).where(User.shop_id == shop.id, User.email == "owner@shopflow.dev")
        )
        actor = Principal(
            user_id=owner.id,
            shop_id=shop.id,
            name=owner.name,
            email=owner.email,
            role_code="owner",
            permissions=frozenset({"reports:read", "catalog:write", "sales:write"}),
        )
        categories = {
            c.slug: c.id for c in db.scalars(select(Category).where(Category.shop_id == shop.id))
        }
        counters = list(
            db.scalars(select(Counter.id).where(Counter.shop_id == shop.id).order_by(Counter.code))
        )
        goods = Product(
            shop_id=shop.id,
            category_id=categories["grocery"],
            sku="E-" + uuid4().hex[:12],
            name_en="Rice by weight",
            name_bn="ওজনের চাল",
            unit="kg",
            stock_on_hand=0,
            units=[
                ProductUnit(
                    name="kg", name_bn="কেজি", conversion_factor=1, selling_price=170, is_base=True
                ),
                ProductUnit(
                    name="bag 5 kg", name_bn="৫ কেজির বস্তা", conversion_factor=5, selling_price=850
                ),
            ],
        )
        medicine = Product(
            shop_id=shop.id,
            category_id=categories["excluded"],
            sku="E-" + uuid4().hex[:12],
            name_en="Batch tracked medicine",
            name_bn="ব্যাচভিত্তিক ওষুধ",
            unit="piece",
            stock_on_hand=0,
            is_medicine=True,
            units=[ProductUnit(name="piece", name_bn="টি", selling_price=110, is_base=True)],
        )
        db.add_all([goods, medicine])
        db.commit()
        supplier = save_supplier(
            db,
            actor,
            SupplierWrite(
                name="Distribution " + uuid4().hex[:8],
                name_bn="ওষুধ সরবরাহ",
                phone="01700000000",
                address="Dhaka",
                product_ids=[goods.id, medicine.id],
            ),
        )
        yield actor, counters, goods, medicine, supplier, shop_date(db, shop.id)
        db.expire_all()
        db.get(Product, goods.id).is_active = False
        db.get(Product, medicine.id).is_active = False
        db.commit()


def order(
    db, setup, product, quantity, *, batch=None, expiry=None, discount="0", unit=None, ref=None
):
    actor, _, _, _, supplier, today = setup
    return create_purchase(
        db,
        actor,
        PurchaseWrite.model_validate(
            {
                "supplier_id": supplier.id,
                "supplier_invoice_number": ref or uuid4().hex,
                "discount_total": discount,
                "items": [
                    {
                        "product_id": product.id,
                        "product_unit_id": unit,
                        "quantity": quantity,
                        "unit_cost": "12.50",
                        "batch_number": batch,
                        "manufacture_date": today - timedelta(days=10) if batch else None,
                        "expiry_date": expiry,
                    }
                ],
            }
        ),
        str(uuid4()),
    )


def intake(db, setup, purchase, quantity, *, key=None):
    return receive_purchase(
        db,
        setup[0],
        purchase.id,
        ReceiveWrite.model_validate(
            {
                "items": [{"purchase_item_id": purchase.items[0].id, "quantity": quantity}],
            }
        ),
        key or str(uuid4()),
    )


def sell(db, setup, product, quantity, counter=0):
    actor, counters, *_ = setup
    return finalize_invoice(
        db,
        actor,
        InvoiceCreate.model_validate(
            {
                "counter_id": counters[counter],
                "items": [{"product_id": product.id, "quantity": quantity}],
                "payments": [{"method": "cash"}],
            }
        ),
        str(uuid4()),
    )


def race(operation):
    barrier = Barrier(2)

    def run(index):
        barrier.wait(timeout=10)
        try:
            with SessionLocal() as db:
                return operation(db, index)
        except (ValidationError, ConflictError, InsufficientStockError) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run, range(2)))


def test_supplier_update_deactivation_and_duplicate_reference(setup):
    actor, _, goods, _, supplier, _ = setup
    with SessionLocal() as db:
        updated = save_supplier(
            db,
            actor,
            SupplierWrite(
                name="Updated supplier",
                name_bn="নতুন সরবরাহকারী",
                address="Mirpur",
                phone="01800000000",
                product_ids=[goods.id],
            ),
            supplier.id,
        )
        assert updated.address == "Mirpur" and updated.product_ids == [goods.id]
        purchase = order(db, setup, goods, "1", ref=" INV-ABC ")
        with pytest.raises(ConflictError):
            order(db, setup, goods, "1", ref="inv-abc")
        cancelled = cancel_purchase(db, actor, purchase.id, "Entered twice", str(uuid4()))
        assert cancelled.status == "voided"
        active = order(db, setup, goods, "1", ref="INV-ABC")
        assert active.status == "draft"
        saved = save_supplier(
            db,
            actor,
            SupplierWrite(
                name=updated.name,
                address=updated.address,
                phone=updated.phone,
                is_active=False,
            ),
            supplier.id,
        )
        assert not saved.is_active
        with pytest.raises(ValidationError, match="inactive"):
            order(db, setup, goods, "1")


def test_partial_fractional_receipts_replay_payment_and_valuation(setup):
    actor, _, goods, _, supplier, _ = setup
    with SessionLocal() as db:
        purchase = order(
            db,
            setup,
            goods,
            "1.250",
            discount="1.63",
            unit=next(u.id for u in goods.units if not u.is_base),
        )
        assert db.get(Product, goods.id).stock_on_hand == 0
        key = str(uuid4())
        first = intake(db, setup, purchase, "0.500", key=key)
        assert first.status == "partially_received"
        assert first.items[0].received_base == Decimal("2.500")
        assert intake(db, setup, purchase, "0.500", key=key) == first
        last = intake(db, setup, purchase, "0.750")
        assert last.status == "received"
        assert last.received_total == last.total == Decimal("13.99")
        paid = pay_purchase(
            db,
            actor,
            purchase.id,
            SupplierPaymentWrite(amount=Decimal("3.99"), method="bkash", reference="demo-transfer"),
            str(uuid4()),
        )
        assert paid.outstanding == Decimal("10.00")
        summary = stock_value(db, actor.shop_id, goods.id)
        assert summary.quantity_on_hand == summary.ledger_quantity == Decimal("6.250")
        assert summary.unvalued_quantity == 0 and summary.value == Decimal("13.99")
        assert db.scalar(
            select(func.sum(SupplierLedger.amount)).where(SupplierLedger.supplier_id == supplier.id)
        ) == Decimal("10")
        with pytest.raises(ConflictError, match="unpaid"):
            reverse_purchase(db, actor, purchase.id, "Do not reverse", str(uuid4()))
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(
                update(SupplierLedger)
                .where(SupplierLedger.purchase_id == purchase.id)
                .values(amount=0)
            )


def test_receive_rollback_and_unpaid_reverse(setup, monkeypatch):
    actor, _, goods, _, _, _ = setup
    with SessionLocal() as db:
        purchase = order(db, setup, goods, "2")
        original = purchasing.post_stock

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("simulated write failure")

        with monkeypatch.context() as patch:
            patch.setattr(purchasing, "post_stock", fail)
            with pytest.raises(RuntimeError):
                intake(db, setup, purchase, "1")
        assert db.get(Product, goods.id).stock_on_hand == 0
        assert (
            db.scalar(select(func.count(StockLot.id)).where(StockLot.product_id == goods.id)) == 0
        )
        assert intake(db, setup, purchase, "2").received_total == Decimal("25")
        reversed_purchase = reverse_purchase(
            db, actor, purchase.id, "Wrong stock delivered", str(uuid4())
        )
        assert reversed_purchase.status == "reversed" and reversed_purchase.outstanding == 0
        assert db.get(Product, goods.id).stock_on_hand == 0
        assert (
            db.scalar(
                select(func.sum(SupplierLedger.amount)).where(
                    SupplierLedger.purchase_id == purchase.id
                )
            )
            == 0
        )
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == purchase.id)))
        assert actions == {"purchase.create", "purchase.receive", "purchase.reverse"}


@pytest.mark.parametrize("replay", [True, False])
def test_concurrent_receiving_does_not_duplicate_stock(setup, replay):
    actor, _, goods, *_ = setup
    with SessionLocal() as db:
        purchase = order(db, setup, goods, "2")
    key = str(uuid4())
    results = race(lambda db, _: intake(db, setup, purchase, "2", key=key if replay else None))
    assert sum(isinstance(x, ConflictError) for x in results) == (0 if replay else 1)
    if replay:
        assert results[0] == results[1]
    with SessionLocal() as db:
        assert stock_value(db, actor.shop_id, goods.id).ledger_quantity == 2
        assert (
            db.scalar(select(func.count(StockLot.id)).where(StockLot.product_id == goods.id)) == 1
        )


def test_fefo_skips_expired_and_quarantined_and_reconciles(setup):
    actor, _, _, medicine, _, today = setup
    with SessionLocal() as db:
        for name, days, qty in [
            ("LATE", 30, "4"),
            ("FIRST", 10, "2"),
            ("QUARANTINE", 5, "5"),
            ("EXPIRED", 3, "6"),
        ]:
            purchase = order(
                db, setup, medicine, qty, batch=name, expiry=today + timedelta(days=days)
            )
            intake(db, setup, purchase, qty)
        batches = {
            b.batch_number: b
            for b in db.scalars(
                select(MedicineBatch).where(MedicineBatch.product_id == medicine.id)
            )
        }
        set_batch_state(
            db,
            actor,
            batches["QUARANTINE"].id,
            BatchState(quarantined=True, reason="Damaged seal"),
            str(uuid4()),
        )
        batches["EXPIRED"].expiry_date = today
        db.commit()
        with pytest.raises(InsufficientStockError):
            sell(db, setup, medicine, "7")
        sale = sell(db, setup, medicine, "5")
        allocations = list(
            db.scalars(
                select(InvoiceBatchAllocation)
                .where(InvoiceBatchAllocation.invoice_item_id == sale.items[0].id)
                .order_by(InvoiceBatchAllocation.expiry_date)
            )
        )
        assert [(a.batch_number, a.quantity) for a in allocations] == [
            ("FIRST", Decimal(2)),
            ("LATE", Decimal(3)),
        ]
        assert (
            batches["QUARANTINE"].quantity_on_hand == 5 and batches["EXPIRED"].quantity_on_hand == 6
        )
        summary = stock_value(db, actor.shop_id, medicine.id)
        assert summary.available == 1
        assert (
            summary.ledger_quantity
            == summary.quantity_on_hand
            == sum(b.quantity_on_hand for b in batches.values())
        )
        for batch in batches.values():
            assert (
                db.scalar(
                    select(func.sum(StockMovement.quantity)).where(
                        StockMovement.batch_id == batch.id
                    )
                )
                == batch.quantity_on_hand
            )
        disposed = adjust_stock(
            db,
            actor,
            StockChange(
                product_id=medicine.id,
                batch_id=batches["EXPIRED"].id,
                action="dispose",
                quantity=Decimal(6),
                reason="Expired at cutoff",
            ),
            str(uuid4()),
        )
        assert disposed.available == 1 and disposed.quantity_on_hand == 6


def test_expired_batch_cutoff_is_shop_local_and_never_saleable(setup):
    actor, _, _, medicine, _, today = setup
    with SessionLocal() as db:
        assert shop_date(db, actor.shop_id, datetime(2026, 11, 19, 17, 59, tzinfo=UTC)).day == 19
        assert shop_date(db, actor.shop_id, datetime(2026, 11, 19, 18, 0, tzinfo=UTC)).day == 20
        with pytest.raises(ValidationError, match="expiry"):
            order(db, setup, medicine, "1", batch="TODAY", expiry=today)
        purchase = order(db, setup, medicine, "1", batch="LAST", expiry=today + timedelta(days=1))
        intake(db, setup, purchase, "1")
        batch = db.scalar(select(MedicineBatch).where(MedicineBatch.product_id == medicine.id))
        batch.expiry_date = today
        db.commit()
        with pytest.raises(InsufficientStockError, match="batch stock"):
            sell(db, setup, medicine, "1")


def test_quarantined_final_batch_blocks_sale_then_allows_only_one_counter(setup):
    actor, _, _, medicine, _, today = setup
    with SessionLocal() as db:
        purchase = order(
            db, setup, medicine, "1", batch="SINGLE", expiry=today + timedelta(days=20)
        )
        intake(db, setup, purchase, "1")
        batch = db.scalar(select(MedicineBatch).where(MedicineBatch.product_id == medicine.id))
        set_batch_state(
            db,
            actor,
            batch.id,
            BatchState(quarantined=True, reason="Inspect packaging"),
            str(uuid4()),
        )
        with pytest.raises(InsufficientStockError):
            sell(db, setup, medicine, "1")
        set_batch_state(
            db, actor, batch.id, BatchState(quarantined=False, reason="Seal verified"), str(uuid4())
        )
    results = race(lambda db, i: sell(db, setup, medicine, "1", counter=i))
    assert sum(isinstance(x, InsufficientStockError) for x in results) == 1
    with SessionLocal() as db:
        stock = stock_value(db, actor.shop_id, medicine.id)
        assert stock.available == stock.ledger_quantity == stock.quantity_on_hand == 0


@pytest.mark.anyio
async def test_cashier_cannot_browse_costs_or_adjust_stock(setup):
    actor, _, goods, _, supplier, _ = setup
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.23", 1)), base_url="http://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "cashier1@shopflow.dev", "password": "ShopFlow#Dev123"},
        )
        assert login.status_code == 200
        headers = {
            "Authorization": "Bearer " + login.json()["access_token"],
            "Idempotency-Key": str(uuid4()),
        }
        for path in [
            "/suppliers",
            f"/suppliers/{supplier.id}/ledger",
            "/purchases",
            "/inventory/batches",
            "/inventory/movements",
            f"/inventory/products/{goods.id}/valuation",
        ]:
            assert (await client.get("/api/v1" + path, headers=headers)).status_code == 403
        response = await client.post(
            "/api/v1/inventory/adjustments",
            headers=headers,
            json={
                "product_id": str(goods.id),
                "action": "add",
                "quantity": "1",
                "reason": "No access",
            },
        )
        assert response.status_code == 403
    with SessionLocal() as db:
        before = stock_value(db, actor.shop_id, goods.id).ledger_quantity
        updated = adjust_stock(
            db,
            actor,
            StockChange(
                product_id=goods.id,
                action="add",
                quantity=Decimal("1.25"),
                unit_cost=Decimal(20),
                reason="Count corrected",
            ),
            str(uuid4()),
        )
        assert updated.ledger_quantity == before + Decimal("1.25")
        assert updated.value == Decimal("25")
        assert "stock.add" in set(
            db.scalars(select(AuditLog.action).where(AuditLog.entity_id == goods.id))
        )


def test_repeated_batch_receipt_keeps_one_identity_and_rejects_conflict(setup):
    _, _, _, medicine, _, today = setup
    expiry = today + timedelta(days=45)
    with SessionLocal() as db:
        intake(db, setup, order(db, setup, medicine, "2", batch="LOT-1", expiry=expiry), "2")
        intake(db, setup, order(db, setup, medicine, "3", batch="lot-1", expiry=expiry), "3")
        conflict = order(db, setup, medicine, "2", batch="Lot-1", expiry=expiry + timedelta(days=2))
        with pytest.raises(ConflictError, match="conflicting details"):
            intake(db, setup, conflict, "2")
        batch = db.scalar(select(MedicineBatch).where(MedicineBatch.product_id == medicine.id))
        assert batch.quantity_on_hand == batch.quantity_received == 5
        assert db.scalar(select(func.count(StockLot.id)).where(StockLot.batch_id == batch.id)) == 2

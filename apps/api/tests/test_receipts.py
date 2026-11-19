from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.main import app
from app.models import (
    Category,
    Counter,
    Invoice,
    LoyaltyAccount,
    LoyaltyTransaction,
    MedicineBatch,
    Payment,
    Product,
    ProductUnit,
    Shop,
    StockMovement,
)
from app.services.receipts import mask_customer_phone


@pytest.mark.parametrize(
    ("phone", "masked"),
    [("+8801712345678", "•••• 5678"), ("০১৭১২৩৪৫৬৭৮", "•••• ৫৬৭৮"), (None, None), ("019", None)],
)
def test_mask_customer_phone(phone, masked):
    assert mask_customer_phone(phone) == masked


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.21", 1234)), base_url="http://test"
    ) as client:
        yield client


async def login(client, role):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": f"{role}@shopflow.dev", "password": "ShopFlow#Dev123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def catalog():
    with SessionLocal() as db:
        shop = db.scalar(select(Shop).where(Shop.is_demo.is_(True)).order_by(Shop.created_at))
        counters = db.scalars(
            select(Counter).where(Counter.shop_id == shop.id).order_by(Counter.sort_order)
        ).all()
        categories = {
            row.slug: row.id
            for row in db.scalars(select(Category).where(Category.shop_id == shop.id))
        }
        goods = Product(
            shop_id=shop.id,
            category_id=categories["grocery"],
            sku=f"R-{uuid4().hex[:12]}",
            name_en="Hand-sorted aromatic grocery rice from the northern harvest family pack",
            name_bn="উত্তরাঞ্চলের নতুন মৌসুমের হাতে বাছাই করা সুগন্ধি চালের পারিবারিক প্যাক",
            unit="kg",
            stock_on_hand=30,
            units=[ProductUnit(name="kg", name_bn="কেজি", is_base=True, selling_price="124.01")],
        )
        medicine = Product(
            shop_id=shop.id,
            category_id=categories["excluded"],
            sku=f"R-{uuid4().hex[:12]}",
            name_en="Extended-release medicine with a long descriptive name for repeat dispensing",
            name_bn="দীর্ঘ সময় ধরে কার্যকর ওষুধের বর্ধিত মুক্তির বিশেষ ফর্মুলার ট্যাবলেট",
            unit="pack",
            stock_on_hand=30,
            is_medicine=True,
            batches=[
                MedicineBatch(
                    shop_id=shop.id,
                    batch_number="BATCH-42",
                    expiry_date=date.today() + timedelta(days=365),
                    quantity_on_hand=30,
                    quantity_received=30,
                )
            ],
            units=[ProductUnit(name="pack", name_bn="প্যাক", is_base=True, selling_price="300.00")],
        )
        db.add_all([goods, medicine])
        db.commit()
        products = (goods.id, medicine.id)
        yield shop.id, [counter.id for counter in counters], products
        for product_id in products:
            db.get(Product, product_id).is_active = False
        db.commit()


async def sale(client, token, counter, items, **kwargs):
    response = await client.post(
        "/api/v1/invoices",
        headers={**token, "Idempotency-Key": str(uuid4())},
        json={
            "counter_id": str(counter),
            "items": items,
            "payments": [{"method": "cash"}],
            **kwargs,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _effects(invoice_id, product_ids):
    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        return (
            invoice.total,
            invoice.paid_total,
            invoice.due_total,
            invoice.loyalty_points_earned,
            *(db.get(Product, product_id).stock_on_hand for product_id in product_ids),
            db.scalar(
                select(func.count()).select_from(Payment).where(Payment.invoice_id == invoice_id)
            ),
            db.scalar(
                select(func.count())
                .select_from(LoyaltyTransaction)
                .where(LoyaltyTransaction.invoice_id == invoice_id)
            ),
            db.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(StockMovement.reference_id == invoice_id)
            ),
        )


@pytest.mark.anyio
async def test_saved_receipt_stability_privacy_rounding_and_tender(client, catalog):
    shop_id, counters, (goods, medicine) = catalog
    owner = await login(client, "owner")
    local = f"016{uuid4().int % 100000000:08d}"
    phone = "+880" + local[1:]
    result = await client.post(
        "/api/v1/customers",
        headers=owner,
        json={
            "name": "Receipt Customer",
            "name_bn": "রসিদের গ্রাহক",
            "phone": local,
            "email": "private@example.com",
        },
    )
    assert result.status_code == 201, result.text
    customer_id = UUID(result.json()["id"])
    with SessionLocal() as db:
        account = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id))
        account.points_balance = account.lifetime_earned = 400
        db.commit()
    original = await sale(
        client,
        owner,
        counters[0],
        [
            {"product_id": str(goods), "quantity": "1.250", "line_discount": "0.01"},
            {"product_id": str(medicine), "quantity": "2"},
        ],
        customer_id=str(customer_id),
        discount_total="15.00",
        redeem_points=100,
        allow_due=True,
        payments=[
            {"method": "cash", "amount": "50", "reference": "internal-ref"},
            {"method": "bkash", "amount": "70"},
        ],
    )
    endpoint = f"/api/v1/invoices/{original['id']}/receipt"
    before = _effects(UUID(original["id"]), [goods, medicine])
    saved = await client.get(endpoint, headers=owner)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert receipt["identity"]["source"] == "sale"
    assert receipt["identity"]["customer_name_bn"] == "রসিদের গ্রাহক"
    assert receipt["identity"]["customer_phone_masked"] == "•••• " + phone[-4:]
    assert phone not in saved.text and "private@example.com" not in saved.text
    assert "internal-ref" not in saved.text
    assert receipt["items"][0]["quantity"] == "1.250"
    assert receipt["items"][0]["unit_bn"] == "কেজি"
    assert receipt["items"][0]["line_total"] == "155.00"
    assert receipt["items"][1]["name_bn"].startswith("দীর্ঘ সময়")
    assert receipt["subtotal"] == "755.01"
    assert receipt["discount_total"] == "15.01"
    assert receipt["loyalty_discount"] == "100.00"
    assert receipt["paid_total"] == "120.00" and receipt["due_total"] == "520.00"
    assert receipt["total"] == "640.00"
    assert receipt["payments"] == [
        {"method": "bkash", "amount": "70.00"},
        {"method": "cash", "amount": "50.00"},
    ]
    assert receipt["loyalty_points_earned"] == 0
    assert receipt["loyalty_points_redeemed"] == 100
    assert receipt["loyalty_points_balance"] == 300

    settings_path = "/api/v1/settings/receipts"
    settings = (await client.get(settings_path, headers=owner)).json()
    with SessionLocal() as db:
        previous = db.get(Shop, shop_id).receipt_settings
        db.get(Product, goods).name_bn = "পরিবর্তিত পণ্যের নাম"
        db.get(Product, goods).units[0].name = "changed unit"
        db.get(Product, goods).units[0].selling_price = 999
        db.commit()
    try:
        result = await client.put(
            settings_path,
            headers=owner,
            json={
                **settings,
                "shop_name_en": "Renamed shop",
                "preferred_language": "bn",
                "printable_width_mm": 64,
                "footer_bn": "ধন্যবাদ",
            },
        )
        assert result.status_code == 200, result.text
        changed = await client.patch(
            f"/api/v1/customers/{customer_id}",
            headers=owner,
            json={
                "name": "Renamed Customer",
                "phone": f"014{uuid4().int % 100000000:08d}",
            },
        )
        assert changed.status_code == 200, changed.text
        for _ in range(2):
            assert (await client.get(endpoint, headers=owner)).json() == receipt
        assert _effects(UUID(original["id"]), [goods, medicine]) == before

        collected = await client.post(
            f"/api/v1/customers/{customer_id}/invoices/{original['id']}/payments",
            headers={**owner, "Idempotency-Key": str(uuid4())},
            json={"method": "nagad", "amount": "520.00"},
        )
        assert collected.status_code == 201, collected.text
        settled = (await client.get(endpoint, headers=owner)).json()
        assert settled["identity"] == receipt["identity"]
        assert settled["items"] == receipt["items"]
        assert settled["paid_total"] == "640.00" and settled["due_total"] == "0.00"
        assert settled["payments"][-1] == {"method": "nagad", "amount": "520.00"}
    finally:
        with SessionLocal() as db:
            db.get(Shop, shop_id).receipt_settings = previous
            db.commit()


@pytest.mark.anyio
async def test_receipt_permissions_history_search_and_missing_invoice(client, catalog):
    _shop, counters, (goods, _) = catalog
    owner = await login(client, "owner")
    cashier = await login(client, "cashier1")
    manager = await login(client, "manager")
    items = [{"product_id": str(goods), "quantity": "1"}]
    own = await sale(client, owner, counters[0], items)
    forbidden = await sale(client, owner, counters[1], items)
    own_path = f"/api/v1/invoices/{own['id']}/receipt"
    assert (await client.get(own_path, headers=cashier)).status_code == 200
    assert (await client.get(own_path)).status_code == 401
    assert (
        await client.get(f"/api/v1/invoices/{forbidden['id']}/receipt", headers=cashier)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/invoices/{uuid4()}/receipt", headers=cashier)
    ).status_code == 404
    assert (
        await client.get("/api/v1/invoices/invalid/receipt", headers=cashier)
    ).status_code == 422
    history = await client.get(
        "/api/v1/invoices", headers=cashier, params={"q": own["invoice_number"], "printable": True}
    )
    assert [item["id"] for item in history.json()["items"]] == [own["id"]]
    settings = "/api/v1/settings/receipts"
    assert (await client.get(settings, headers=manager)).status_code == 403
    fields = (await client.get(settings, headers=owner)).json()
    assert (await client.put(settings, headers=cashier, json=fields)).status_code == 403
    assert (
        await client.put(settings, headers=owner, json={**fields, "printable_width_mm": 90})
    ).status_code == 422


@pytest.mark.anyio
async def test_receipt_prefers_recorded_batch_and_void_status(client, catalog):
    _, counters, (_, medicine) = catalog
    owner = await login(client, "owner")
    out = await sale(client, owner, counters[0], [{"product_id": str(medicine), "quantity": "1"}])
    with SessionLocal() as db:
        invoice = db.get(Invoice, UUID(out["id"]))
        invoice.status = "voided"
        invoice.voided_at = invoice.finalized_at
        item = invoice.items[0]
        batch = db.get(MedicineBatch, item.batch_id)
        expiry = batch.expiry_date.isoformat()
        batch.batch_number = "CHANGED"
        db.commit()
    receipt = (await client.get(f"/api/v1/invoices/{out['id']}/receipt", headers=owner)).json()
    assert receipt["status"] == "voided" and receipt["voided_at"]
    assert receipt["items"][0]["batch"] == "BATCH-42"
    assert receipt["items"][0]["expiry"] == expiry
    assert receipt["items"][0]["batch_allocations"][0]["batch_number"] == "BATCH-42"

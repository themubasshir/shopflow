"""Phase 2E-2 catalog management tests — isolated shopflow_test database.

Covers product/category CRUD, bilingual names, duplicate SKU/barcode handling,
price updates, historical invoice price preservation, deactivation, unit
conversions, zero-stock creation, authorization, and CSV/XLSX import.
"""

from __future__ import annotations

import io
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import Principal
from app.core.errors import ConflictError, ValidationError
from app.db.session import SessionLocal
from app.main import app
from app.models import Category, Counter, InvoiceItem, Product, Shop, User
from app.schemas.catalog import (
    CategoryWrite,
    MedicineWrite,
    ProductUnitWrite,
    ProductUpdate,
    ProductWrite,
)
from app.schemas.purchasing import StockChange
from app.schemas.sales import InvoiceCreate
from app.services import catalog as catalog_service
from app.services.billing import finalize_invoice
from app.services.catalog import ImportParseError
from app.services.inventory import adjust_stock, stock_value

# ---------------------------------------------------------------------------


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
            permissions=frozenset({"reports:read", "catalog:write", "catalog:read", "sales:write"}),
        )
        categories = {
            c.slug: c.id for c in db.scalars(select(Category).where(Category.shop_id == shop.id))
        }
        counters = list(
            db.scalars(
                select(Counter.id)
                .where(Counter.shop_id == shop.id)
                .order_by(Counter.code)
            )
        )
        yield actor, categories, counters, shop


def _grocery_body(categories, **over):
    base = {
        "category_id": categories["grocery"],
        "sku": "GR-" + uuid4().hex[:10],
        "barcode": "88" + uuid4().hex[:10],
        "name_en": "Test Rice 5kg",
        "name_bn": "টেস্ট চাল",
        "unit": "piece",
        "is_medicine": False,
        "units": [
            ProductUnitWrite(
                name="piece", name_bn="টি", conversion_factor=Decimal("1"),
                selling_price=Decimal("450"), is_base=True,
            )
        ],
    }
    base.update(over)
    return ProductWrite.model_validate(base)


def _medicine_body(categories, **over):
    base = {
        "category_id": categories["medicine"],
        "sku": "MD-" + uuid4().hex[:10],
        "barcode": "89" + uuid4().hex[:10],
        "name_en": "Test Paracetamol 500",
        "name_bn": "টেস্ট প্যারাসিটামল",
        "unit": "tablet",
        "is_medicine": True,
        "units": [
            ProductUnitWrite(
                name="tablet", name_bn="ট্যাবলেট", conversion_factor=Decimal("1"),
                selling_price=Decimal("2"), is_base=True,
            ),
            ProductUnitWrite(
                name="strip", name_bn="স্ট্রিপ", conversion_factor=Decimal("10"),
                selling_price=Decimal("20"), is_base=False,
            ),
        ],
        "medicine": MedicineWrite(
            brand_name="Testmol",
            generic_name="Paracetamol",
            manufacturer="ACME",
            strength="500mg",
            dosage_form="Tablet",
            pack_size="10x10",
            mrp=Decimal("30"),
            prescription_required=False,
        ),
    }
    base.update(over)
    return ProductWrite.model_validate(base)


# --- creation & zero stock ----------------------------------------------------


def test_create_grocery_product_zero_stock(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _grocery_body(categories))
        assert detail.stock_on_hand == 0
        assert detail.units[0].is_base is True
        assert db.get(Product, detail.id).stock_on_hand == 0
        val = stock_value(db, actor.shop_id, detail.id)
        assert val.quantity_on_hand == 0
        db.rollback()


def test_create_medicine_product_with_detail(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _medicine_body(categories))
        assert detail.is_medicine is True
        assert detail.medicine.generic_name == "Paracetamol"
        assert detail.medicine.prescription_required is False
        # strip = 10 tablets conversion
        strip = next(u for u in detail.units if u.name == "strip")
        assert strip.conversion_factor == Decimal("10")
        db.rollback()


# --- duplicates ---------------------------------------------------------------


def test_duplicate_sku_and_barcode_rejected(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        first = _grocery_body(categories)
        catalog_service.create_product(db, actor, first)
        db.flush()
        with pytest.raises(ConflictError):
            catalog_service.create_product(db, actor, first.model_copy(update={"barcode": "DIFF"}))
        db.rollback()
    with SessionLocal() as db:
        first = _grocery_body(categories)
        catalog_service.create_product(db, actor, first)
        db.flush()
        dupe_bc = _grocery_body(categories, sku="GR-NEW-" + uuid4().hex[:6], barcode=first.barcode)
        with pytest.raises(ConflictError):
            catalog_service.create_product(db, actor, dupe_bc)
        db.rollback()


# --- updates + history --------------------------------------------------------


def test_price_update_preserves_history(setup):
    actor, categories, counters, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _grocery_body(categories))
        # give it stock via the audited ledger path, then bill once
        adjust_stock(
            db, actor,
            StockChange(product_id=detail.id, action="add", quantity=Decimal("5"),
                        unit_cost=Decimal("100"), reason="opening"),
            str(uuid4()),
        )
        invoice = finalize_invoice(
            db, actor,
            InvoiceCreate.model_validate({
                "counter_id": counters[0],
                "items": [{"product_id": detail.id, "quantity": "2"}],
                "payments": [{"method": "cash"}],
            }),
            str(uuid4()),
        )
        item = db.scalar(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        )
        historical_price = item.unit_price
        historical_desc = item.description

        # change price + name — snapshot on the invoice must not move
        catalog_service.update_product(
            db, actor, detail.id,
            ProductUpdate(name_en="Renamed Rice", units=[
                ProductUnitWrite(name="piece", name_bn="টি", conversion_factor=Decimal("1"),
                                 selling_price=Decimal("999"), is_base=True)
            ]),
        )
        db.flush()
        item2 = db.get(InvoiceItem, item.id)
        assert item2.unit_price == historical_price
        assert item2.description == historical_desc
        db.rollback()


def test_update_product_fields(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _grocery_body(categories))
        updated = catalog_service.update_product(
            db, actor, detail.id,
            ProductUpdate(name_en="New Name EN", name_bn="নতুন নাম",
                          low_stock_threshold=Decimal("25"), tax_rate=Decimal("5")),
        )
        assert updated.name_en == "New Name EN"
        assert updated.name_bn == "নতুন নাম"
        assert updated.low_stock_threshold == Decimal("25")
        db.rollback()


# --- state ---------------------------------------------------------------------


def test_deactivation_preserves_row(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _grocery_body(categories))
        out = catalog_service.set_product_active(db, actor, detail.id, False)
        assert out.is_active is False
        # row still present, not deleted
        assert db.get(Product, detail.id) is not None
        reactivated = catalog_service.set_product_active(db, actor, detail.id, True)
        assert reactivated.is_active is True
        db.rollback()


def test_hard_delete_blocked_with_history(setup):
    actor, categories, counters, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _grocery_body(categories))
        adjust_stock(
            db, actor,
            StockChange(product_id=detail.id, action="add", quantity=Decimal("3"),
                        unit_cost=Decimal("10"), reason="opening"),
            str(uuid4()),
        )
        finalize_invoice(
            db, actor,
            InvoiceCreate.model_validate({
                "counter_id": counters[0],
                "items": [{"product_id": detail.id, "quantity": "1"}],
                "payments": [{"method": "cash"}],
            }),
            str(uuid4()),
        )
        with pytest.raises(ValidationError):
            catalog_service.delete_product(db, actor, detail.id)
        db.rollback()


# --- unit validation ----------------------------------------------------------


def test_two_base_units_rejected(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        body = _grocery_body(categories, units=[
            ProductUnitWrite(name="piece", name_bn="টি", conversion_factor=Decimal("1"),
                             selling_price=Decimal("5"), is_base=True),
            ProductUnitWrite(name="box", name_bn="বক্স", conversion_factor=Decimal("1"),
                             selling_price=Decimal("50"), is_base=True),
        ])
        with pytest.raises(ValidationError):
            catalog_service.create_product(db, actor, body)
        db.rollback()


def test_no_base_unit_rejected(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        body = _grocery_body(categories, units=[
            ProductUnitWrite(name="piece", name_bn="টি", conversion_factor=Decimal("1"),
                             selling_price=Decimal("5"), is_base=False),
        ])
        with pytest.raises(ValidationError):
            catalog_service.create_product(db, actor, body)
        db.rollback()


def test_fractional_conversion_on_discrete_unit_rejected(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        body = _medicine_body(categories, units=[
            ProductUnitWrite(name="tablet", name_bn="ট্যাবলেট", conversion_factor=Decimal("1"),
                             selling_price=Decimal("2"), is_base=True),
            # 0.5 tablet strip — never valid for a discrete base unit
            ProductUnitWrite(name="half", name_bn="হাফ", conversion_factor=Decimal("0.5"),
                             selling_price=Decimal("1"), is_base=False),
        ])
        with pytest.raises(ValidationError):
            catalog_service.create_product(db, actor, body)
        db.rollback()


# --- category management --------------------------------------------------------


def test_category_create_and_cycle_prevention(setup):
    actor, _, _, _ = setup
    suf = uuid4().hex[:8]
    with SessionLocal() as db:
        cat = catalog_service.save_category(
            db, actor,
            CategoryWrite(name_en="Baby Food", name_bn="বেবি ফুড", slug=f"baby-food-{suf}"),
        )
        child = catalog_service.save_category(
            db, actor,
            CategoryWrite(name_en="Formula", name_bn="ফর্মুলা", slug=f"formula-{suf}",
                          parent_id=cat.id),
        )
        # try to make parent a child of its own child -> cycle
        with pytest.raises(ValidationError):
            catalog_service.save_category(
                db, actor,
                CategoryWrite(name_en="Baby Food", name_bn="বেবি ফুড", slug=f"baby-food-{suf}",
                              parent_id=child.id),
                cat.id,
            )


# --- authorization -------------------------------------------------------------


@pytest.mark.anyio
async def test_cashier_cannot_write_catalog(setup):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "cashier1@shopflow.dev", "password": "ShopFlow#Dev123"},
        )
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        body = {
            "category_id": str(uuid4()),
            "sku": "X-" + uuid4().hex[:6],
            "name_en": "Nope",
            "name_bn": "না",
            "units": [{"name": "piece", "name_bn": "টি", "conversion_factor": "1",
                       "selling_price": "1", "is_base": True}],
        }
        r = await client.post("/api/v1/catalog/products", headers=headers, json=body)
        assert r.status_code == 403


@pytest.mark.anyio
async def test_owner_can_create_via_api(setup):
    _, categories, _, _ = setup
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@shopflow.dev", "password": "ShopFlow#Dev123"},
        )
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        body = {
            "category_id": str(categories["grocery"]),
            "sku": "API-" + uuid4().hex[:8],
            "name_en": "API Rice",
            "name_bn": "এপিআই চাল",
            "unit": "piece",
            "units": [{"name": "piece", "name_bn": "টি", "conversion_factor": "1",
                       "selling_price": "200", "is_base": True}],
        }
        r = await client.post("/api/v1/catalog/products", headers=headers, json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        assert Decimal(str(data["stock_on_hand"])) == 0
        # found via the billing search
        find = await client.get(
            f"/api/v1/catalog/products?q={body['sku']}", headers=headers
        )
        assert find.status_code == 200
        assert any(i["sku"] == body["sku"] for i in find.json()["items"])


# --- CSV import ---------------------------------------------------------------


def _csv_bytes(rows: list[list[str]], header: list[str]) -> bytes:
    out = io.StringIO()
    out.write(",".join(header) + "\n")
    for r in rows:
        out.write(",".join(r) + "\n")
    return out.getvalue().encode("utf-8")


def test_parse_csv_import(setup):
    header = ["sku", "name_en", "name_bn", "unit", "selling_price", "is_medicine"]
    rows = [["SKU-1", "Rice", "চাল", "kg", "60", "0"]]
    raw = _csv_bytes(rows, header)
    parsed = catalog_service.parse_import_file("import.csv", raw)
    assert len(parsed) == 1
    model = catalog_service._row_from_mapping(parsed[0][0], parsed[0][1])
    assert model.sku == "SKU-1"
    assert model.selling_price == Decimal("60")


def test_parse_xlsx_import(setup):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["sku", "name_en", "name_bn", "unit", "selling_price"])
    ws.append(["XLSX-1", "Oil", "তেল", "litre", "140"])
    buf = io.BytesIO()
    wb.save(buf)
    parsed = catalog_service.parse_import_file("import.xlsx", buf.getvalue())
    assert len(parsed) == 1
    model = catalog_service._row_from_mapping(parsed[0][0], parsed[0][1])
    assert model.sku == "XLSX-1"


def test_invalid_file_type_rejected(setup):
    with pytest.raises(ImportParseError):
        catalog_service.parse_import_file("import.exe", b"MZ\x90")


def test_import_commit_skips_duplicates(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        existing = catalog_service.create_product(db, actor, _grocery_body(categories))
        body = catalog_service.ImportCommit.model_validate({
            "rows": [
                {"sku": existing.sku, "name_en": "Dup", "name_bn": "নকল", "unit": "piece"},
                {"sku": "NEW-" + uuid4().hex[:6], "name_en": "Fresh", "name_bn": "নতুন",
                 "unit": "piece", "selling_price": "10"},
            ]
        })
        report = catalog_service.commit_import(db, actor, body)
        assert report.created == 1
        assert report.skipped == 1
        db.rollback()


# --- regression: reconciliation intact ----------------------------------------


def test_product_crud_does_not_move_stock(setup):
    actor, categories, _, _ = setup
    with SessionLocal() as db:
        detail = catalog_service.create_product(db, actor, _grocery_body(categories))
        adjust_stock(
            db, actor,
            StockChange(product_id=detail.id, action="add", quantity=Decimal("7"),
                        unit_cost=Decimal("10"), reason="opening"),
            str(uuid4()),
        )
        # an edit must not change stock
        catalog_service.update_product(
            db, actor, detail.id, ProductUpdate(name_en="Edited")
        )
        val = stock_value(db, actor.shop_id, detail.id)
        assert val.quantity_on_hand == Decimal("7")
        db.rollback()

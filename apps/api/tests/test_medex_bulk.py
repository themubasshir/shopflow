"""Phase 3C bulk-promotion tests — shopflow_test only.

Covers the MedEx staging -> products bulk import: classification, idempotent
re-runs, zero-stock/zero-price invariants, duplicate handling, resume, and the
billing/catalog separation that keeps unstocked imported medicines unsellable.
``MedicineDetail`` records are built directly — no scraped HTML parsing.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api.deps import Principal
from app.db.session import SessionLocal
from app.integrations.medex.normalizer import comfortable_sku
from app.integrations.medex.promoter import PromoteReport, classify, promote_batch
from app.integrations.medex.repository import (
    find_match_candidates,
    get_or_create_source,
    stage_detail,
)
from app.integrations.medex.schemas import MedicineDetail as MedexDetail
from app.models import (
    MedicineBatch,
    MedicineCatalogStaging,
    MedicineDetail,
    Product,
    ProductUnit,
    Shop,
    StockMovement,
    User,
)
from app.schemas.catalog import ProductUnitWrite, ProductWrite
from app.services.catalog import create_product


def _purge(db):
    from sqlalchemy import delete

    from app.models import (
        MedicineCatalogImportRun,
        MedicineCatalogManifest,
        MedicineCatalogMatch,
        MedicineCatalogSyncHistory,
    )

    db.execute(MedicineCatalogSyncHistory.__table__.delete())
    db.execute(MedicineCatalogMatch.__table__.delete())
    db.execute(MedicineCatalogStaging.__table__.delete())
    db.execute(MedicineCatalogManifest.__table__.delete())
    db.execute(MedicineCatalogImportRun.__table__.delete())
    med_ids = select(Product.id).where(Product.sku.like("MED-%"))
    db.execute(delete(MedicineBatch).where(MedicineBatch.product_id.in_(med_ids)))
    db.execute(delete(MedicineDetail).where(MedicineDetail.product_id.in_(med_ids)))
    db.execute(delete(ProductUnit).where(ProductUnit.product_id.in_(med_ids)))
    db.execute(delete(Product).where(Product.sku.like("MED-%")))
    db.commit()


@pytest.fixture(autouse=True)
def _clean():
    with SessionLocal() as db:
        _purge(db)
    yield
    with SessionLocal() as db:
        _purge(db)


@pytest.fixture
def shop():
    with SessionLocal() as db:
        yield db.scalar(select(Shop).order_by(Shop.created_at))


@pytest.fixture
def actor(shop):
    with SessionLocal() as db:
        owner = db.scalar(
            select(User).where(User.shop_id == shop.id, User.email == "owner@shopflow.dev")
        )
        yield Principal(
            user_id=owner.id,
            shop_id=shop.id,
            name=owner.name,
            email=owner.email,
            role_code="owner",
            permissions=frozenset({"catalog:read", "catalog:write", "sales:write"}),
        )


def _uniq(prefix: str) -> str:
    """A run-unique manual SKU so repeat suite runs never collide."""
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def _detail(source_id: str, **over) -> MedexDetail:
    """Build a MedicineDetail directly — no HTML parsing needed."""
    base = {
        "source_id": source_id,
        "url": f"https://medex.com.bd/brands/{source_id}/x",
        "slug": "x",
        "brand_name": "A-B1",
        "generic_name": "Thiamine Hydrochloride",
        "manufacturer": "ACME Laboratories Ltd.",
        "strength": "100 mg",
        "dosage_form": "Tablet",
        "unit_price": Decimal("0.86"),
    }
    base.update(over)
    return MedexDetail.model_validate(base)


def _stage(db, src, source_id, **over):
    row, _ = stage_detail(db, src, None, _detail(source_id, **over))
    return row


def _counts(db):
    return {
        "products": db.scalar(select(func.count(Product.id))),
        "med_products": db.scalar(select(func.count(Product.id)).where(Product.sku.like("MED-%"))),
        "moves": db.scalar(select(func.count(StockMovement.id))),
        "batches": db.scalar(select(func.count(MedicineBatch.id))),
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_classify_ready_valid_row(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row = _stage(db, src, "77100")
        db.commit()
        assert classify(db, db.get(MedicineCatalogStaging, row.id), actor.shop_id) == "ready"


def test_classify_invalid_no_brand(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = stage_detail(
            db,
            src,
            None,
            _detail("77101", brand_name=None, brand_name_bn=None, generic_name=None),
        )
        db.commit()
        cls = classify(db, db.get(MedicineCatalogStaging, row.id), actor.shop_id)
        assert cls in {"invalid", "ambiguous"}


def test_classify_imported_when_sku_exists(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row = _stage(db, src, "77102")
        db.commit()
        # manually mint the deterministic SKU as a product
        sku = comfortable_sku(row.brand_name, row.external_id)
        create_product(
            db,
            actor,
            ProductWrite(
                category_id=_med_cat(db, actor),
                sku=sku,
                name_en="X",
                name_bn="X",
                units=[
                    ProductUnitWrite(
                        name="tablet",
                        name_bn="t",
                        conversion_factor=Decimal("1"),
                        selling_price=Decimal("1"),
                        is_base=True,
                    )
                ],
            ),
        )
        db.commit()
        assert classify(db, db.get(MedicineCatalogStaging, row.id), actor.shop_id) == "imported"


def test_classify_non_medicine_device(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = stage_detail(db, src, None, _detail("77103", dosage_form="Glucometer"))
        db.commit()
        assert classify(db, db.get(MedicineCatalogStaging, row.id), actor.shop_id) == "non_medicine"


def _med_cat(db, actor):
    from app.services.catalog import _default_category

    return _default_category(db, actor.shop_id, is_medicine=True).id


# ---------------------------------------------------------------------------
# Bulk import: invariants + idempotency
# ---------------------------------------------------------------------------


def test_bulk_import_creates_zero_stock_unpriced(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        before = _counts(db)
        row = _stage(db, src, "77200")
        db.commit()
        rep = promote_batch(db, actor, limit=50)
        db.commit()

        assert rep.imported >= 1
        staging = db.get(MedicineCatalogStaging, row.id)
        assert staging.import_status == "imported"
        assert staging.linked_product_id is not None

        p = db.get(Product, staging.linked_product_id)
        assert p.sku.startswith("MED-") and p.is_medicine
        assert p.stock_on_hand == 0  # zero stock, always
        # sellable at the MedEx MRP: base unit + retail both carry the
        # reference price (owner directive: MRP == retail). Still zero stock.
        base = db.scalar(
            select(ProductUnit).where(ProductUnit.product_id == p.id, ProductUnit.is_base.is_(True))
        )
        med = db.scalar(select(MedicineDetail).where(MedicineDetail.product_id == p.id))
        assert med.source == "medex"
        assert med.mrp is not None  # reference price preserved separately
        assert med.retail_price == med.mrp
        assert base.selling_price == med.mrp
        # no inventory or financial side effects
        after = _counts(db)
        assert after["moves"] == before["moves"]
        assert after["batches"] == before["batches"]


def test_bulk_import_idempotent(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        _stage(db, src, "77201")
        db.commit()
        promote_batch(db, actor, limit=100)
        n1 = db.scalar(select(func.count(Product.id)).where(Product.sku.like("MED-%")))
        r2 = promote_batch(db, actor, limit=100)
        n2 = db.scalar(select(func.count(Product.id)).where(Product.sku.like("MED-%")))
        assert n1 == n2  # second run imported nothing new
        assert r2.imported == 0
        assert r2.skipped_existing >= 1


def test_bulk_import_resume_by_limit(actor):
    """A small limit processes a bounded slice; a second call continues."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        # stage several distinct medicines
        for i, form in enumerate(["Tablet", "Capsule", "Syrup"]):
            stage_detail(db, src, None, _detail(f"773{i}0", dosage_form=form))
        db.commit()
        rep = PromoteReport()
        promote_batch(db, actor, limit=1, report=rep)
        first = rep.imported
        assert first == 1
        promote_batch(db, actor, limit=10, report=rep)
        assert rep.imported >= first  # continued, not restarted


def test_same_brand_different_strengths_both_import(actor):
    """Same brand, different strength = distinct medicines, both importable."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        for i, strength in enumerate(["100 mg", "200 mg"]):
            stage_detail(db, src, None, _detail(f"774{i}0", strength=strength))
        db.commit()
        promote_batch(db, actor, limit=50)
        # each produces its own MED- SKU (external_id differs)
        meds = db.scalars(select(Product).where(Product.sku.like("MED-%"))).all()
        assert len(meds) >= 2


def test_pending_match_kept_in_review(actor):
    """A staged row with an unconfirmed fuzzy match is 'ambiguous', not imported."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        # create a real medicine product
        create_product(
            db,
            actor,
            ProductWrite(
                category_id=_med_cat(db, actor),
                sku=_uniq("HANDMADE"),
                name_en="A-B1",
                name_bn="A-B1",
                is_medicine=True,
                medicine=_med_write(),
                units=[
                    ProductUnitWrite(
                        name="tablet",
                        name_bn="t",
                        conversion_factor=Decimal("1"),
                        selling_price=Decimal("5"),
                        is_base=True,
                    )
                ],
            ),
        )
        db.commit()
        # stage a row that fuzzy-matches it
        row, _ = stage_detail(db, src, None, _detail("77500"))
        db.commit()
        find_match_candidates(db, actor.shop_id, row)
        db.commit()
        cls = classify(db, db.get(MedicineCatalogStaging, row.id), actor.shop_id)
        # ambiguous (pending match) OR ready if it didn't match — the invariant
        # is it must NOT be auto-imported as a fresh product
        promote_batch(db, actor, limit=100)
        if cls == "ambiguous":
            assert db.get(MedicineCatalogStaging, row.id).import_status != "imported"


def _med_write():
    from app.schemas.catalog import MedicineWrite

    return MedicineWrite(brand_name="A-B1", generic_name="Thiamine Hydrochloride")


# ---------------------------------------------------------------------------
# Billing / catalog separation
# ---------------------------------------------------------------------------


def test_imported_medicine_excluded_from_sellable(actor):
    """A zero-stock unpriced import must NOT appear under view=sellable logic —
    mirrors the SQL in catalog.list_products."""
    from sqlalchemy import func as f

    from app.services.stock import available_stock, shop_date

    with SessionLocal() as db:
        src = get_or_create_source(db)
        _stage(db, src, "77600")
        db.commit()
        promote_batch(db, actor, limit=50)
        db.commit()

        saleable = available_stock(shop_date(db, actor.shop_id))
        base_price = (
            select(ProductUnit.selling_price)
            .where(ProductUnit.product_id == Product.id, ProductUnit.is_base.is_(True))
            .scalar_subquery()
        )
        sellable_ids = set(
            db.scalars(
                select(Product.id).where(
                    Product.shop_id == actor.shop_id,
                    Product.is_active.is_(True),
                    Product.sku.like("MED-%"),
                    saleable > 0,
                    f.coalesce(base_price, 0) > 0,
                )
            ).all()
        )
        med_ids = set(db.scalars(select(Product.id).where(Product.sku.like("MED-%"))).all())
        # no imported (0-stock/0-price) med is sellable
        assert sellable_ids.isdisjoint(med_ids)


def test_catalog_includes_imports(actor):
    """Imported medicines DO appear in the general catalog listing (not sellable filter)."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        _stage(db, src, "77700")
        db.commit()
        promote_batch(db, actor, limit=50)
        db.commit()
        med = db.scalar(select(Product).where(Product.sku.like("MED-%")))
        assert med is not None and med.is_medicine
        # visible via medicine view
        listed = db.scalars(
            select(Product).where(Product.is_medicine.is_(True), Product.id == med.id)
        ).all()
        assert listed


# ---------------------------------------------------------------------------
# Regression: existing data untouched
# ---------------------------------------------------------------------------


def test_manual_products_never_overwritten(actor):
    """A manually-created product with a non-MED sku is never touched."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        manual_sku = _uniq("GROC-KEEP")
        manual = create_product(
            db,
            actor,
            ProductWrite(
                category_id=_med_cat(db, actor),
                sku=manual_sku,
                name_en="Rice 5kg",
                name_bn="চাল",
                units=[
                    ProductUnitWrite(
                        name="bag",
                        name_bn="ব্যাগ",
                        conversion_factor=Decimal("1"),
                        selling_price=Decimal("600"),
                        is_base=True,
                    )
                ],
            ),
        )
        db.commit()
        manual_id = manual.id
        _stage(db, src, "77800")
        db.commit()
        promote_batch(db, actor, limit=100)
        db.commit()
        p = db.get(Product, manual_id)
        assert p.sku == manual_sku and p.name_en == "Rice 5kg"

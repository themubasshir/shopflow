"""MedEx staging / approval tests — shopflow_test only.

The live scraper was removed; the catalog is populated offline via the
dataset importer. These tests exercise the surviving pipeline — the real
``medicine_catalog_*`` tables, staging upserts, deduplication, matching, and
the zero-stock product-creation path — proving it never touches stock or
ledgers. ``MedicineDetail`` records are built directly rather than parsed
from scraped HTML.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.deps import Principal
from app.core.errors import ConflictError
from app.db.session import SessionLocal
from app.integrations.medex.approver import approve_staging, reject_staging, set_match_status
from app.integrations.medex.repository import (
    find_match_candidates,
    get_or_create_source,
    list_staging,
    stage_detail,
    staging_stats,
)
from app.integrations.medex.schemas import MedicineDetail
from app.models import (
    MedicineCatalogStaging,
    Product,
    Shop,
    StockMovement,
    User,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def shop():
    with SessionLocal() as db:
        s = db.scalar(select(Shop).order_by(Shop.created_at))
        yield s


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


def _detail(source_id: str, **over) -> MedicineDetail:
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
    return MedicineDetail.model_validate(base)


def _stage(db, source, source_id, **over):
    return stage_detail(db, source, None, _detail(source_id, **over))


def _purge_medex_artifacts(db):
    """Delete MedEx staging rows AND any MED-* products a prior run created,
    so the suite is repeatable against the shared (non-wiped) test DB.

    Products imported from MedEx always start at zero stock and are never sold
    or batched in tests, so they have no stock/ledger references — deleting the
    child detail/unit rows then the product row is safe and complete.
    """
    from sqlalchemy import delete

    from app.models import (
        MedicineBatch,
        MedicineCatalogImportRun,
        MedicineCatalogManifest,
        MedicineCatalogMatch,
        MedicineCatalogStaging,
        MedicineCatalogSyncHistory,
        MedicineDetail,
        Product,
        ProductUnit,
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


@pytest.fixture(scope="session", autouse=True)
def _clean_medex_staging():
    """Clear MedEx artifacts before AND after the run for repeatability."""
    with SessionLocal() as db:
        _purge_medex_artifacts(db)
    yield
    with SessionLocal() as db:
        _purge_medex_artifacts(db)


# --- Staging / dedup ----------------------------------------------------------


def test_staging_insert_and_idempotent_update(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, action = _stage(db, src, "13582")
        assert action in {"inserted", "updated", "unchanged"}
        assert row.external_id == "13582"
        assert row.validation_status == "valid"
        db.commit()

        # Re-stage same medicine -> same row, still exactly one record for it.
        row2, _action2 = _stage(db, src, "13582")
        assert row2.id == row.id
        db.commit()

        n = db.scalar(
            select(func.count())
            .select_from(MedicineCatalogStaging)
            .where(MedicineCatalogStaging.external_id == "13582")
        )
        assert n == 1


def test_staging_uniqueness_external_id(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        _stage(db, src, "6171")
        _stage(db, src, "6171")
        db.commit()
        n = db.scalar(
            select(func.count())
            .select_from(MedicineCatalogStaging)
            .where(MedicineCatalogStaging.external_id == "6171")
        )
        assert n == 1


def test_staging_search_and_filters(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        _stage(db, src, "13582")
        _stage(db, src, "6171", generic_name="Omeprazole")
        _stage(db, src, "38307", unit_price=None, generic_name="Test Generic")
        db.commit()
        rows, total = list_staging(db, src.id, q="cefixime")
        assert total == 0  # cefixime is not among these three
        rows, total = list_staging(db, src.id, generic="Thiamine Hydrochloride")
        assert total >= 1 and all(r.generic_name == "Thiamine Hydrochloride" for r in rows)
        rows, total = list_staging(db, src.id, q="a-b1")
        assert total >= 1 and any(r.brand_name == "A-B1" for r in rows)
        stats = staging_stats(db, src.id)
        assert stats["total"] >= 3
        assert stats["missing_price"] >= 1


# --- Matching / approval ------------------------------------------------------


def test_zero_stock_product_on_approve(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, "88002")
        db.commit()
        before_moves = db.scalar(select(func.count(StockMovement.id)))
        approved = approve_staging(db, actor, row.id, selling_price=Decimal("1.00"))
        db.commit()
        assert approved.import_status == "imported"
        product = db.get(Product, approved.linked_product_id)
        assert product is not None
        assert product.stock_on_hand == 0  # zero initial stock, always
        assert product.is_medicine is True
        assert product.medicine.generic_name == "Thiamine Hydrochloride"
        # reference price kept as MRP, sellable price is the explicit one
        assert product.medicine.mrp == Decimal("0.86")
        # no stock movement was created by the import
        after_moves = db.scalar(select(func.count(StockMovement.id)))
        assert after_moves == before_moves


def test_approve_twice_blocked(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, "88003", dosage_form="Capsule", generic_name="Cloxacillin")
        db.commit()
        approve_staging(db, actor, row.id)
        db.commit()
        with pytest.raises(ConflictError):
            approve_staging(db, actor, row.id)


def test_match_and_confirm(actor):
    """Create a real product first, then stage a duplicate -> match + confirm."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        # stage + approve -> creates a real product
        row, _ = _stage(db, src, "88001")
        db.commit()
        approved = approve_staging(db, actor, row.id)
        product_id = approved.linked_product_id
        db.commit()

        # Stage a DIFFERENT staging row for the same medicine identity by
        # pointing at a new external_id with same brand/form/mfr.
        duprow, _ = _stage(db, src, "99999")
        db.commit()
        cands = find_match_candidates(db, actor.shop_id, duprow)
        db.commit()
        assert cands, "expected at least one match candidate"
        target = next(c for c in cands if c.product_id == product_id)
        # confirm the match to the product we created
        m = set_match_status(db, actor, target.id, confirm=True)
        db.commit()
        assert m.status == "confirmed"
        assert db.get(MedicineCatalogStaging, duprow.id).linked_product_id == product_id


def test_reject_staging(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, "4006", dosage_form="Syrup")
        db.commit()
        r = reject_staging(db, actor, row.id)
        assert r.import_status == "rejected"


def test_unauthorized_import_blocked(shop):
    """A cashier-like principal (no catalog:write) cannot approve."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, "13582")
        db.commit()
        cashier = Principal(
            user_id=uuid4(),
            shop_id=shop.id,
            name="c",
            email="c@x",
            role_code="cashier",
            permissions=frozenset({"catalog:read"}),
        )
        with pytest.raises(HTTPException):
            approve_staging(db, cashier, row.id)


def test_content_hash_update_records_sync_history(actor):
    """Re-staging with a changed detail updates the row + writes a
    MedicineCatalogSyncHistory entry for the changed tracked field."""
    from app.models import MedicineCatalogSyncHistory

    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, "88004")
        db.commit()
        # mutate a tracked field and re-stage
        d2 = _detail("88004", brand_name="A-B1 Renamed", content_hash="deadbeef" * 8)
        row2, action = stage_detail(db, src, None, d2)
        db.commit()
        assert row2.id == row.id and action == "updated"
        hist = db.scalars(
            select(MedicineCatalogSyncHistory).where(
                MedicineCatalogSyncHistory.staging_id == row.id
            )
        ).all()
        assert any(h.field == "brand_name" for h in hist)


def test_staging_malformed_detail_flags_warning(actor):
    """A detail missing required fields stages as warning/invalid, flagged —
    rather than crashing the importer."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, "88099", brand_name=None, generic_name=None)
        db.commit()
        assert row.external_id == "88099"
        assert row.validation_status in {"warning", "invalid"}
        assert row.parse_warnings  # something was flagged


def test_existing_catalog_untouched_by_staging(actor):
    """Staging a batch of medicines changes no products, prices, stock, or
    batches — the staging area is inert until owner approval."""
    from app.models import MedicineBatch, ProductUnit

    with SessionLocal() as db:
        src = get_or_create_source(db)
        before_products = db.scalar(select(func.count(Product.id)))
        before_units = db.scalar(select(func.count(ProductUnit.id)))
        before_batches = db.scalar(select(func.count(MedicineBatch.id)))
        before_moves = db.scalar(select(func.count(StockMovement.id)))
        _stage(db, src, "88011")
        _stage(db, src, "88012")
        _stage(db, src, "88013")
        _stage(db, src, "88014")
        db.commit()
        assert db.scalar(select(func.count(Product.id))) == before_products
        assert db.scalar(select(func.count(ProductUnit.id))) == before_units
        assert db.scalar(select(func.count(MedicineBatch.id))) == before_batches
        assert db.scalar(select(func.count(StockMovement.id))) == before_moves

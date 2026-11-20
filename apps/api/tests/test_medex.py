"""Phase 3A MedEx ingestion tests — shopflow_test only.

Parser tests run entirely against recorded HTML fixtures (no live site).
Staging/matching tests exercise the real ``medicine_catalog_*`` tables and the
zero-stock product-creation path, proving the pipeline never touches stock or
ledgers. ``FixtureFetcher`` replays saved pages through the same importer the
live run uses.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.deps import Principal
from app.core.errors import ConflictError
from app.db.session import SessionLocal
from app.integrations.medex.approver import approve_staging, reject_staging, set_match_status
from app.integrations.medex.detail_parser import parse_detail
from app.integrations.medex.importer import run_import
from app.integrations.medex.index_parser import detail_id_from_url, parse_index
from app.integrations.medex.repository import (
    create_run,
    find_match_candidates,
    get_or_create_source,
    list_staging,
    stage_detail,
    staging_stats,
)
from app.models import (
    MedicineCatalogStaging,
    Product,
    Shop,
    StockMovement,
    User,
)

FIX = Path(__file__).parent / "fixtures" / "medex"

# Map canonical detail URLs -> fixture filenames so the fixture fetcher can
# replay a multi-medicine collection without any network.
_DETAIL_FIXTURES = {
    "13582": "detail_tablet.html",
    "6171": "detail_capsule.html",
    "4006": "detail_syrup.html",
    "38307": "detail_noprice.html",
    "17301": "detail_injection.html",
    "14399": "detail_combo.html",
    "10934": "detail_supp.html",
}


def _fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class FixtureFetcher:
    """Replays recorded pages. Index pages come from the saved index fixtures;
    detail URLs resolve to their recorded file by source id."""

    def __init__(self, index_pages: list[str]):
        self.index_pages = index_pages
        self.detail_calls: list[str] = []

    def fetch_index(self, page: int) -> tuple[str, str]:
        name = self.index_pages[min(page - 1, len(self.index_pages) - 1)]
        url = (
            "https://medex.com.bd/brands"
            if page <= 1
            else f"https://medex.com.bd/brands?page={page}"
        )
        return _fixture(name), url

    def fetch_detail(self, url: str) -> tuple[str, bytes]:
        self.detail_calls.append(url)
        sid = detail_id_from_url(url)
        name = _DETAIL_FIXTURES.get(sid, "detail_tablet.html")
        html = _fixture(name)
        return html, html.encode("utf-8")


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


def _parse(name: str, url: str):
    return parse_detail(_fixture(name), url)


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


# --- Index parsing ------------------------------------------------------------


def test_index_parses_cards_and_pagination():
    page = parse_index(_fixture("index_p1.html"), "https://medex.com.bd/brands")
    assert len(page.cards) == 30
    assert page.page_number == 1
    assert page.last_page == 859  # discovered, not assumed
    assert page.next_page_url and "page=2" in page.next_page_url
    c = page.cards[0]
    assert c.source_id == "13717"
    assert c.brand_name == "3 Bion"
    assert c.generic_name == "Vitamin B1, B6 & B12"
    assert c.manufacturer == "Jenphar Bangladesh Ltd."
    assert c.dosage_form == "Tablet"


def test_index_stable_ids_unique():
    page = parse_index(_fixture("index_p1.html"), "https://medex.com.bd/brands")
    ids = [c.source_id for c in page.cards]
    assert len(ids) == len(set(ids))
    for c in page.cards:
        assert detail_id_from_url(c.url) == c.source_id


def test_index_no_cards_on_empty():
    page = parse_index("<html><body></body></html>")
    assert page.cards == []


# --- Detail parsing -----------------------------------------------------------


def test_detail_tablet_full_fields():
    d = _parse("detail_tablet.html", "https://medex.com.bd/brands/13582/a-b1-100-mg-tablet")
    assert d.source_id == "13582"
    assert d.brand_name == "A-B1"
    assert d.generic_name == "Thiamine Hydrochloride"
    assert d.manufacturer == "ACME Laboratories Ltd."
    assert d.strength == "100 mg"
    assert d.dosage_form == "Tablet"
    assert d.unit_price == Decimal("0.86")
    assert d.strip_price == Decimal("8.6") or d.strip_price == Decimal("8.60")
    assert d.pack and d.pack.pack_quantity == 10 and d.pack.units_per_pack == 10
    assert d.pack.pack_price == Decimal("86") or d.pack.pack_price == Decimal("86.00")
    assert d.therapeutic_class == "Vitamin-B preparations"
    assert d.parse_warnings == []


def test_detail_bangla_variant():
    d = _parse("detail_tablet_bn.html", "https://medex.com.bd/brands/13582/a-b1-100-mg-tablet/bn")
    assert d.brand_name_bn == "এ-বি১"
    assert d.generic_name_bn and "থা" in d.generic_name_bn and "হাইড্রোক্লোরাইড" in d.generic_name_bn
    assert d.dosage_form_bn == "ট্যাবলেট"
    assert d.source_id == "13582"


def test_detail_missing_price_kept_null():
    d = _parse("detail_noprice.html", "https://medex.com.bd/brands/38307/x")
    # No "Unit Price" literal -> unit_price stays None, pack label preserved.
    assert d.unit_price is None
    assert d.pack is not None and d.pack.price == Decimal("1375")
    assert d.pack.label == "90 ml bottle"


def test_detail_complex_strength_combo():
    d = _parse("detail_combo.html", "https://medex.com.bd/brands/14399/x")
    assert d.strength == "500 mg+200 IU"
    assert d.unit_price == Decimal("7")


def test_detail_pack_size_variants():
    d = _parse("detail_syrup.html", "https://medex.com.bd/brands/4006/x")
    assert d.dosage_form == "Syrup"
    assert d.strength == "(10 mg+30 mg+1.25 mg)/5 ml"
    assert d.pack and d.pack.label == "100 ml bottle"
    d2 = _parse("detail_supp.html", "https://medex.com.bd/brands/10934/x")
    assert d2.dosage_form == "Suppository"
    assert d2.pack and d2.pack.pack_quantity == 2


# --- Staging / dedup ------------------------------------------------------------


def _stage(db, source, run, name, url):
    return stage_detail(db, source, run, _parse(name, url))


def test_staging_insert_and_idempotent_update(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        run = create_run(db, src, scope="pilot", index_limit=1, detail_limit=5)
        url = "https://medex.com.bd/brands/13582/a-b1-100-mg-tablet"
        row, action = _stage(db, src, run, "detail_tablet.html", url)
        assert action in {"inserted", "updated", "unchanged"}
        assert row.external_id == "13582"
        assert row.validation_status == "valid"
        db.commit()

        # Re-stage same medicine -> same row, still exactly one record for it.
        row2, _action2 = _stage(db, src, run, "detail_tablet.html", url)
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
        _stage(db, src, None, "detail_capsule.html", "https://medex.com.bd/brands/6171/x")
        _stage(db, src, None, "detail_capsule.html", "https://medex.com.bd/brands/6171/x")
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
        _stage(db, src, None, "detail_tablet.html", "https://medex.com.bd/brands/13582/a")
        _stage(db, src, None, "detail_capsule.html", "https://medex.com.bd/brands/6171/b")
        _stage(db, src, None, "detail_noprice.html", "https://medex.com.bd/brands/38307/c")
        db.commit()
        rows, total = list_staging(db, src.id, q="cefixime")
        assert total == 0  # cefixime is not among these three
        # generic filter narrows to a known fixture; verify it filters
        rows, total = list_staging(db, src.id, generic="Thiamine Hydrochloride")
        assert total >= 1 and all(r.generic_name == "Thiamine Hydrochloride" for r in rows)
        rows, total = list_staging(db, src.id, q="a-b1")
        assert total >= 1 and any(r.brand_name == "A-B1" for r in rows)
        stats = staging_stats(db, src.id)
        assert stats["total"] >= 3
        assert stats["missing_price"] >= 1


# --- Importer (checkpointed, fixture-driven) ------------------------------------


def test_import_pilot_stages_medicines(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        run = create_run(db, src, scope="pilot", index_start=1, index_limit=1, detail_limit=3)
        db.commit()
        fetcher = FixtureFetcher(["index_p1.html"])
        run_import(db, fetcher, run, fetch_bn=False)
        db.commit()
        assert run.status == "completed"
        assert run.staged >= 3
        _rows, total = list_staging(db, src.id)
        assert total >= 3
        # detail urls actually fetched
        assert len(fetcher.detail_calls) >= 3


def test_import_resume_after_interruption(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        run = create_run(db, src, scope="pilot", index_start=1, index_limit=1, detail_limit=6)
        db.commit()
        fetcher = FixtureFetcher(["index_p1.html"])
        calls = {"n": 0}

        def stop_after_two():
            calls["n"] += 1
            return calls["n"] > 2

        run_import(db, fetcher, run, fetch_bn=False, stop_check=stop_after_two)
        db.commit()
        assert run.status == "interrupted"
        staged_first = run.staged

        # Resume — should continue from pending_urls, not re-fetch staged ones.
        calls["n"] = 0
        run2 = run_import(db, fetcher, run, fetch_bn=False)
        db.commit()
        assert run2.status == "completed"
        assert run2.staged >= staged_first


# --- Matching / approval --------------------------------------------------------


def test_zero_stock_product_on_approve(actor):
    with SessionLocal() as db:
        src = get_or_create_source(db)
        d = _parse("detail_tablet.html", "https://medex.com.bd/brands/88002/a-b1-100-mg-tablet")
        d.source_id = "88002"
        row, _ = stage_detail(db, src, None, d)
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
        d = _parse("detail_capsule.html", "https://medex.com.bd/brands/88003/a-clox-500-mg-capsule")
        d.source_id = "88003"
        row, _ = stage_detail(db, src, None, d)
        db.commit()
        approve_staging(db, actor, row.id)
        db.commit()
        with pytest.raises(ConflictError):
            approve_staging(db, actor, row.id)


def test_match_and_confirm(actor):
    """Create a real product first, then stage a duplicate -> match + confirm."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        # stage + approve -> creates a real product. Use a unique external id so
        # other tests that already imported 13582 don't clash.
        base = _parse("detail_tablet.html", "https://medex.com.bd/brands/88001/a-b1-100-mg-tablet")
        base.source_id = "88001"
        row, _ = stage_detail(db, src, None, base)
        db.commit()
        approved = approve_staging(db, actor, row.id)
        product_id = approved.linked_product_id
        db.commit()

        # Now stage a DIFFERENT staging row for the same medicine identity by
        # manually pointing at a new external_id with same brand/form/mfr.
        dup = _parse("detail_tablet.html", "https://medex.com.bd/brands/99999/a-b1-100-mg-tablet")
        dup.source_id = "99999"
        duprow, _ = stage_detail(db, src, None, dup)
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
        row, _ = _stage(db, src, None, "detail_syrup.html", "https://medex.com.bd/brands/4006/c")
        db.commit()
        r = reject_staging(db, actor, row.id)
        assert r.import_status == "rejected"


def test_unauthorized_import_blocked(shop):
    """A cashier-like principal (no catalog:write) cannot approve."""
    with SessionLocal() as db:
        src = get_or_create_source(db)
        row, _ = _stage(db, src, None, "detail_tablet.html", "https://medex.com.bd/brands/13582/z")
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

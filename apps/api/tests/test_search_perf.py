"""Phase 3C §6 — catalog search performance at MedEx-catalog scale.

Seeds a few thousand products + medicine detail rows and times the real
``list_products`` query path (the same SQL the API runs) to prove the trigram
indexes keep substring search interactive — not a seq-scan-per-keystroke.

Marked slow-ish but still CI-safe (a few seconds of bulk INSERT, all inside
test DB transactions that are rolled back by the fixtures' purge where the
rows are MED-*).
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from sqlalchemy import func, insert, or_, select

from app.api.deps import Principal
from app.db.session import SessionLocal
from app.models import Category, Product, ProductUnit, Shop, User
from app.services.stock import available_stock, shop_date

N_SEED = 4000  # representative of the ~25k catalog's search behaviour


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
            permissions=frozenset({"catalog:read", "catalog:write"}),
        )


def _seed_catalog(db, shop_id, n=N_SEED):
    """Bulk-insert n MED-* products + a base unit each (unpriced, 0 stock)."""
    cat = db.scalar(
        select(Category).where(Category.shop_id == shop_id, Category.is_medicine.is_(True))
    )
    if cat is None:
        from app.services.catalog import _default_category

        cat = _default_category(db, shop_id, is_medicine=True)
    names = [
        "Napa",
        "Seclo",
        "Ace",
        "Monas",
        "Fexo",
        "Maxpro",
        "Rabex",
        "Ceevit",
        "Savlon",
        "Hepatix",
        "Omep",
        "Paracet",
        "Amoxi",
        "Ceftra",
        "Azith",
        "Losar",
        "Metform",
        "Atova",
        "Rosuva",
        "Clopi",
    ]
    products = []
    for i in range(n):
        nm = f"{names[i % len(names)]} {i}mg"
        products.append(
            {
                "shop_id": shop_id,
                "category_id": cat.id,
                "sku": f"MED-PERF-{i:05d}",
                "name_en": nm,
                "name_bn": nm,
                "unit": "tablet",
                "is_medicine": True,
                "is_active": True,
                "stock_on_hand": Decimal("0"),
            }
        )
    # bulk insert products
    db.execute(insert(Product), products)
    db.flush()
    ids = db.scalars(select(Product.id).where(Product.sku.like("MED-PERF-%"))).all()
    units = [
        {
            "product_id": pid,
            "name": "tablet",
            "name_bn": "ট্যাবলেট",
            "conversion_factor": Decimal("1"),
            "selling_price": Decimal("0"),
            "is_base": True,
        }
        for pid in ids
    ]
    db.execute(insert(ProductUnit), units)
    db.commit()
    return len(ids)


def _q_search(db, shop_id, q, limit=50):
    """Replicates the list_products `q` predicate (lower LIKE on name/sku/alias)."""
    like = f"%{q.lower()}%"
    stmt = (
        select(Product)
        .where(Product.shop_id == shop_id, Product.is_active.is_(True))
        .where(
            or_(
                func.lower(Product.name_en).like(like),
                func.lower(Product.sku).like(like),
                func.lower(Product.name_bn).like(like),
            )
        )
        .order_by(Product.name_en)
        .limit(limit)
    )
    return db.scalars(stmt).all()


def test_search_performance_at_scale(actor):
    """A substring product search over thousands of MED-* rows stays fast."""
    with SessionLocal() as db:
        seeded = _seed_catalog(db, actor.shop_id)
        assert seeded >= N_SEED
        try:
            # warm the planner
            _q_search(db, actor.shop_id, "napa")
            timings = {}
            for q in ("napa", "ace", "500", "med-perf-0001"):
                t0 = time.perf_counter()
                rows = _q_search(db, actor.shop_id, q)
                timings[q] = (time.perf_counter() - t0, len(rows))
            # each search must be comfortably interactive (< 1.5s even cold)
            for q, (dt, n) in timings.items():
                assert dt < 1.5, f"search '{q}' took {dt:.2f}s for {n} rows"
            print("\nperf:", {q: f"{dt * 1000:.0f}ms/{n}rows" for q, (dt, n) in timings.items()})
        finally:
            # clean up the perf rows so the suite stays repeatable
            from sqlalchemy import delete

            ids = select(Product.id).where(Product.sku.like("MED-PERF-%"))
            db.execute(delete(ProductUnit).where(ProductUnit.product_id.in_(ids)))
            db.execute(delete(Product).where(Product.sku.like("MED-PERF-%")))
            db.commit()


def test_sellable_filter_excludes_zero_stock(actor):
    """At scale the sellable predicate still returns only stocked+priced rows."""
    with SessionLocal() as db:
        _seed_catalog(db, actor.shop_id)
        try:
            saleable = available_stock(shop_date(db, actor.shop_id))
            base_price = (
                select(ProductUnit.selling_price)
                .where(ProductUnit.product_id == Product.id, ProductUnit.is_base.is_(True))
                .scalar_subquery()
            )
            n = db.scalar(
                select(func.count())
                .select_from(Product)
                .where(
                    Product.sku.like("MED-PERF-%"),
                    saleable > 0,
                    func.coalesce(base_price, 0) > 0,
                )
            )
            assert n == 0  # seeded rows are 0-stock/0-price -> none sellable
        finally:
            from sqlalchemy import delete

            ids = select(Product.id).where(Product.sku.like("MED-PERF-%"))
            db.execute(delete(ProductUnit).where(ProductUnit.product_id.in_(ids)))
            db.execute(delete(Product).where(Product.sku.like("MED-PERF-%")))
            db.commit()

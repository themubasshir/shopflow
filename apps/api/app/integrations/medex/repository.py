"""Persistence for the MedEx staging pipeline.

Owns the ``medicine_catalog_*`` tables: registering the source, recording
import runs, upserting staged medicines (keyed on ``(source, external_id)``),
recording field-level sync changes, and writing match candidates. It never
touches ``products``, stock or ledgers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.medex.schemas import MedicineDetail
from app.models import (
    MedicineCatalogImportRun,
    MedicineCatalogMatch,
    MedicineCatalogSource,
    MedicineCatalogStaging,
    MedicineCatalogSyncHistory,
    Product,
)

MEDEX_CODE = "medex"
MEDEX_BASE = "https://medex.com.bd"

# Fields compared when a re-scrape's content hash differs. Price fields are
# flagged so a price change is reviewable rather than silently applied.
_TRACKED = (
    "brand_name",
    "generic_name",
    "manufacturer",
    "strength",
    "dosage_form",
    "unit_price",
    "strip_price",
    "pack_price",
)
_PRICE_FIELDS = {"unit_price", "strip_price", "pack_price"}


def get_or_create_source(db: Session) -> MedicineCatalogSource:
    src = db.scalar(select(MedicineCatalogSource).where(MedicineCatalogSource.code == MEDEX_CODE))
    if src is None:
        src = MedicineCatalogSource(
            code=MEDEX_CODE,
            name="MedEx Bangladesh",
            base_url=MEDEX_BASE,
            consent_note=(
                "User-asserted written consent from MedEx for scraping the public "
                "brand catalogue for internal product-catalog reference. "
                "Conservative rate (single concurrency, ~1 req/2s). Not enabled "
                "for recurring collection. Document held by shop owner; not "
                "committed to the repository."
            ),
            consent_recorded_at=datetime.now(UTC),
        )
        db.add(src)
        db.flush()
    return src


def create_run(
    db: Session,
    source: MedicineCatalogSource,
    *,
    scope: str,
    index_start: int = 1,
    index_limit: int | None,
    detail_limit: int | None,
) -> MedicineCatalogImportRun:
    run = MedicineCatalogImportRun(
        source_id=source.id,
        scope=scope,
        index_start=index_start,
        index_limit=index_limit,
        detail_limit=detail_limit,
        status="pending",
    )
    db.add(run)
    db.flush()
    return run


def staging_by_external_id(
    db: Session, source_id: UUID, external_id: str
) -> MedicineCatalogStaging | None:
    return db.scalar(
        select(MedicineCatalogStaging).where(
            MedicineCatalogStaging.source_id == source_id,
            MedicineCatalogStaging.external_id == external_id,
        )
    )


def _validate(d: MedicineDetail) -> tuple[str, list[str]]:
    """Assign a validation status from parse warnings + required fields."""
    warnings = list(d.parse_warnings)
    if "missing_source_id" in warnings:
        return "invalid", warnings
    if not (d.brand_name or d.brand_name_bn):
        return "invalid", [*warnings, "missing_brand_name"]
    if not (d.generic_name or d.generic_name_bn):
        # generic is needed for a useful match but not fatal
        return "warning", [*warnings, "missing_generic_name"]
    if warnings:
        return "warning", warnings
    return "valid", warnings


def stage_detail(
    db: Session,
    source: MedicineCatalogSource,
    run: MedicineCatalogImportRun | None,
    d: MedicineDetail,
) -> tuple[MedicineCatalogStaging, str]:
    """Upsert one parsed medicine. Returns (row, action).

    action: "inserted" | "updated" | "unchanged".
    Re-scraping the same external_id updates the row in place (no duplicate)
    and records a ``MedicineCatalogSyncHistory`` entry per changed field.
    """
    validation, warnings = _validate(d)
    existing = staging_by_external_id(db, source.id, d.source_id)

    raw = d.model_dump(mode="json", exclude={"content_hash"})
    fields = {
        "slug": d.slug,
        "content_hash": d.content_hash,
        "brand_name": d.brand_name,
        "brand_name_bn": d.brand_name_bn,
        "generic_name": d.generic_name,
        "generic_name_bn": d.generic_name_bn,
        "manufacturer": d.manufacturer,
        "manufacturer_bn": d.manufacturer_bn,
        "strength": d.strength,
        "strength_bn": d.strength_bn,
        "dosage_form": d.dosage_form,
        "dosage_form_bn": d.dosage_form_bn,
        "unit_price": d.unit_price,
        "strip_price": d.strip_price,
        "pack_price": d.pack.pack_price if d.pack else None,
        "pack_quantity": d.pack.pack_quantity if d.pack else None,
        "units_per_pack": d.pack.units_per_pack if d.pack else None,
        "pack_label": d.pack.label if d.pack else None,
        "therapeutic_class": d.therapeutic_class,
        "prescription_note": d.prescription_note,
        "raw_payload": raw,
        "validation_status": validation,
        "parse_warnings": warnings,
        "source_fetched_at": d.fetched_at,
    }

    if existing is None:
        row = MedicineCatalogStaging(
            source_id=source.id,
            run_id=run.id if run else None,
            external_id=d.source_id,
            source_url=d.url,
            import_status="pending_review",
            **fields,
        )
        db.add(row)
        db.flush()
        return row, "inserted"

    # update-in-place; log field-level changes
    changed = False
    for key in _TRACKED:
        old = getattr(existing, key)
        new = fields.get(key)
        if str(old) != str(new):
            db.add(
                MedicineCatalogSyncHistory(
                    staging_id=existing.id,
                    field=key,
                    old_value=None if old is None else str(old),
                    new_value=None if new is None else str(new),
                    price_change=key in _PRICE_FIELDS,
                )
            )
            setattr(existing, key, new)
            changed = True
    # always refresh non-tracked metadata + hash + validation
    for key, value in fields.items():
        if key not in _TRACKED:
            setattr(existing, key, value)
    if existing.content_hash != d.content_hash:
        existing.content_hash = d.content_hash
        changed = True
    existing.run_id = run.id if run else existing.run_id
    db.flush()
    return existing, ("updated" if changed else "unchanged")


def find_match_candidates(
    db: Session, shop_id: UUID, staging: MedicineCatalogStaging, limit: int = 5
) -> list[MedicineCatalogMatch]:
    """Record candidate product links for a staging row.

    Order of confidence: an existing product whose sku/barcode encodes the
    MedEx id, then a normalized name+strength+form+manufacturer match. Only
    candidates are written — nothing auto-links.
    """
    from app.integrations.medex.normalizer import comfortable_sku, medicine_key

    candidates: list[MedicineCatalogMatch] = []
    sku = comfortable_sku(staging.brand_name, staging.external_id)

    # 1) exact SKU we would mint — strongest (means we already imported it)
    exact = db.scalar(select(Product).where(Product.shop_id == shop_id, Product.sku == sku))
    if exact is not None:
        candidates.append(_match(db, staging, exact, basis="sku", score=100))
        return candidates

    # 2) normalized identity match on medicine details + product name
    key = medicine_key(
        staging.brand_name, staging.strength, staging.dosage_form, staging.manufacturer
    )
    if all(key[:2]) or (key[0] and key[3]):  # need brand + (strength or mfr)
        rows = db.scalars(
            select(Product)
            .where(Product.shop_id == shop_id, Product.is_medicine.is_(True))
            .limit(5000)
        ).all()
        for p in rows:
            med = p.medicine
            if med is None:
                continue
            pkey = medicine_key(med.brand_name, med.strength, med.dosage_form, med.manufacturer)
            if pkey == key:
                candidates.append(_match(db, staging, p, basis="fuzzy", score=80))
            elif (
                pkey[0] == key[0] and pkey[2] == key[2] and pkey[3] == key[3] and pkey[1] != key[1]
            ):
                # same brand+form+manufacturer, different strength -> candidate, never auto
                candidates.append(_match(db, staging, p, basis="name", score=40))
            if len(candidates) >= limit:
                break
    return candidates


def _match(
    db: Session, staging: MedicineCatalogStaging, product: Product, *, basis: str, score: int
) -> MedicineCatalogMatch:
    m = db.scalar(
        select(MedicineCatalogMatch).where(
            MedicineCatalogMatch.staging_id == staging.id,
            MedicineCatalogMatch.product_id == product.id,
        )
    )
    if m is None:
        m = MedicineCatalogMatch(
            staging_id=staging.id, product_id=product.id, basis=basis, score=score
        )
        db.add(m)
    else:
        m.basis, m.score = basis, score
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Review / approve helpers (used by the API layer)
# ---------------------------------------------------------------------------


def list_staging(
    db: Session,
    source_id: UUID,
    *,
    q: str | None = None,
    manufacturer: str | None = None,
    generic: str | None = None,
    import_status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[MedicineCatalogStaging], int]:
    stmt = select(MedicineCatalogStaging).where(MedicineCatalogStaging.source_id == source_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(MedicineCatalogStaging.brand_name).like(like)
            | func.lower(MedicineCatalogStaging.generic_name).like(like)
            | func.lower(MedicineCatalogStaging.manufacturer).like(like)
        )
    if manufacturer:
        stmt = stmt.where(func.lower(MedicineCatalogStaging.manufacturer) == manufacturer.lower())
    if generic:
        stmt = stmt.where(func.lower(MedicineCatalogStaging.generic_name) == generic.lower())
    if import_status:
        stmt = stmt.where(MedicineCatalogStaging.import_status == import_status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(MedicineCatalogStaging.brand_name).offset(offset).limit(limit)
    ).all()
    return list(rows), total


def staging_stats(db: Session, source_id: UUID) -> dict:
    rows = db.execute(
        select(MedicineCatalogStaging.import_status, func.count())
        .where(MedicineCatalogStaging.source_id == source_id)
        .group_by(MedicineCatalogStaging.import_status)
    ).all()
    by_status = {r[0]: r[1] for r in rows}
    missing_price = (
        db.scalar(
            select(func.count()).where(
                MedicineCatalogStaging.source_id == source_id,
                MedicineCatalogStaging.unit_price.is_(None),
                MedicineCatalogStaging.pack_price.is_(None),
            )
        )
        or 0
    )
    matches = (
        db.scalar(
            select(func.count(MedicineCatalogMatch.id))
            .join(
                MedicineCatalogStaging,
                MedicineCatalogMatch.staging_id == MedicineCatalogStaging.id,
            )
            .where(MedicineCatalogStaging.source_id == source_id)
        )
        or 0
    )
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "missing_price": missing_price,
        "match_candidates": matches,
    }

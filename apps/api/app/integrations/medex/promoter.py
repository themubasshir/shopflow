"""Bulk promotion of staged MedEx medicines into ShopFlow products.

Phase 3C replaces the manual per-row approval with an idempotent bulk import:
every *valid, unambiguous* staging row becomes a real ``products`` row that is
always created **zero-stock and unpriced** — no batches, no stock movements,
no sellable unit price, no purchase cost. The MedEx reference price is stored
on ``medicine_details.mrp`` only, never on a sellable unit.

Classification (``classify``) decides each row's fate before any insert:

* ``ready``      — has a brand name and is not already imported/matched and not
                   a confirmed duplicate -> safe to auto-import.
* ``imported``   — ``import_status == 'imported'`` already, or its deterministic
                   ``MED-…`` SKU already exists -> skip (idempotent).
* ``duplicate``  — ``import_status == 'matched'`` or a *confirmed* match exists
                   -> keep in review, never auto-import.
* ``invalid``    — ``validation_status == 'invalid'`` or no usable brand name
                   -> skip, needs manual attention.
* ``ambiguous``  — an *unconfirmed* fuzzy/name match candidate exists -> hold
                   for owner review rather than guess a link.
* ``non_medicine``— reserved for items MedEx lists that aren't medicines
                   (glucometers, test strips). Detection is by explicit dosage
                   form / therapeutic class, never by guessing from the name.

Promotion is resumable: ``promote_batch`` processes a bounded slice ordered by
``external_id`` and records each row's outcome on the staging row itself, so a
re-run skips rows already imported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.integrations.medex.approver import _base_unit, _base_unit_bn
from app.integrations.medex.normalizer import comfortable_sku
from app.integrations.medex.repository import get_or_create_source
from app.models import (
    MedicineCatalogMatch,
    MedicineCatalogStaging,
    Product,
)
from app.schemas.catalog import MedicineWrite, ProductUnitWrite, ProductWrite
from app.services.catalog import _default_category, _insert_product, _validate_units
from app.services.purchasing import audit

# Dosage forms / classes that are devices or consumables, not saleable medicine.
_NON_MEDICINE_FORMS = {
    "glucometer",
    "test strip",
    "test strips",
    "lancet",
    "lancets",
    "device",
    "meter",
    "strip",
    "thermometer",
    "nebulizer",
    "surgical",
    "syringe",
    "needle",
    "catheter",
    "gauze",
    "bandage",
    "cotton",
    "sanitary",
    "diaper",
    "mask",
    "gloves",
    "condom",
}


def classify(db: Session, row: MedicineCatalogStaging, shop_id: UUID) -> str:
    """Return the bulk-import classification for one staging row.

    Pure read — never mutates. Order matters: explicit terminal statuses win,
    then data-quality gates, then ambiguity.
    """
    if row.import_status in {"imported", "rejected"}:
        return "imported"
    if row.import_status == "matched":
        return "duplicate"
    # deterministic SKU already exists -> this medicine was imported before
    sku = comfortable_sku(row.brand_name, row.external_id)
    if (
        db.scalar(select(Product.id).where(Product.shop_id == shop_id, Product.sku == sku))
        is not None
    ):
        return "imported"
    if not (row.brand_name or row.brand_name_bn):
        return "invalid"
    if row.validation_status == "invalid":
        return "invalid"
    # non-medicine items stay staged for a classification decision
    form = (row.dosage_form or "").strip().lower()
    if form and form in _NON_MEDICINE_FORMS:
        return "non_medicine"
    # a *pending* (unconfirmed) match candidate means a plausible existing
    # product — hold it for the owner rather than mint a near-duplicate.
    pending = db.scalar(
        select(func.count())
        .select_from(MedicineCatalogMatch)
        .where(
            MedicineCatalogMatch.staging_id == row.id,
            MedicineCatalogMatch.status == "pending",
        )
    )
    if pending:
        return "ambiguous"
    return "ready"


@dataclass
class PromoteReport:
    """Aggregated outcome of one bulk-promotion sweep."""

    ready: int = 0
    imported: int = 0
    skipped_existing: int = 0
    duplicates: int = 0
    invalid: int = 0
    ambiguous: int = 0
    non_medicine: int = 0
    failed: int = 0
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ready": self.ready,
            "imported": self.imported,
            "skipped_existing": self.skipped_existing,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "ambiguous": self.ambiguous,
            "non_medicine": self.non_medicine,
            "failed": self.failed,
            "errors": self.errors[-200:],
        }


def _build_product_write(
    db: Session, principal: Principal, row: MedicineCatalogStaging
) -> ProductWrite:
    """Map a staging row to a ProductWrite — zero stock, unpriced, MRP-only.

    Mirrors ``approver._product_for_staging`` but *never* sets a sellable unit
    price (bulk import leaves selling price unset until the owner configures
    it). ``retail_price`` stays ``None``; only ``medicine_details.mrp`` carries
    the reference price.
    """
    cat = _default_category(db, principal.shop_id, is_medicine=True)
    name_en = row.brand_name or row.brand_name_bn or f"MedEx {row.external_id}"
    name_bn = row.brand_name_bn or name_en
    sku = comfortable_sku(row.brand_name, row.external_id)

    med = MedicineWrite(
        brand_name=row.brand_name or name_en,
        generic_name=row.generic_name or name_en,
        manufacturer=row.manufacturer,
        strength=row.strength,
        dosage_form=row.dosage_form,
        pack_size=row.pack_label,
        mrp=row.unit_price or row.strip_price or row.pack_price,
        retail_price=None,  # never auto-price
        prescription_required=bool(row.prescription_note),
    )
    unit = _base_unit(row.dosage_form)
    return ProductWrite(
        category_id=cat.id,
        sku=sku,
        name_en=name_en,
        name_bn=name_bn,
        search_aliases=[a for a in {row.generic_name} if a][:10],
        unit=unit,
        pack_size=row.pack_label,
        is_medicine=True,
        units=[
            ProductUnitWrite(
                name=unit,
                name_bn=_base_unit_bn(row.dosage_form),
                conversion_factor=Decimal("1"),
                selling_price=Decimal("0"),  # 0 = "price not configured"
                is_base=True,
            )
        ],
        medicine=med,
    )


def _promote_one(
    db: Session, principal: Principal, row: MedicineCatalogStaging, report: PromoteReport
) -> None:
    """Create the product for one 'ready' row inside the caller's transaction."""
    body = _build_product_write(db, principal, row)
    _validate_units(body.units, body.unit)
    product = _insert_product(db, principal, body)
    # provenance: record where this catalog row came from
    if product.medicine is not None:
        product.medicine.source = "medex"
        product.medicine.verified_at = None
    row.linked_product_id = product.id
    row.import_status = "imported"
    report.imported += 1


def promote_batch(
    db: Session,
    principal: Principal,
    *,
    limit: int = 500,
    report: PromoteReport | None = None,
) -> PromoteReport:
    """Import up to ``limit`` 'ready' staging rows, committing as one batch.

    Idempotent + resumable: rows already ``imported``/``matched``/SKU-existing
    are skipped, so a re-run continues where the last batch stopped. All
    classification counts accumulate into ``report`` across calls.
    """
    principal.require_write("catalog:write")
    report = report or PromoteReport()
    src = get_or_create_source(db)

    rows = db.scalars(
        select(MedicineCatalogStaging)
        .where(MedicineCatalogStaging.source_id == src.id)
        .order_by(MedicineCatalogStaging.external_id)
    ).all()

    imported_this_batch = 0
    for row in rows:
        if imported_this_batch >= limit:
            break
        cls = classify(db, row, principal.shop_id)
        if cls == "imported":
            report.skipped_existing += 1
            continue
        if cls == "duplicate":
            report.duplicates += 1
            continue
        if cls == "invalid":
            report.invalid += 1
            continue
        if cls == "non_medicine":
            report.non_medicine += 1
            continue
        if cls == "ambiguous":
            report.ambiguous += 1
            continue
        report.ready += 1
        try:
            _promote_one(db, principal, row, report)
            imported_this_batch += 1
        except Exception as exc:  # one bad row must not kill the batch
            db.rollback()
            report.failed += 1
            row_err = {
                "external_id": row.external_id,
                "brand": row.brand_name,
                "error": f"{type(exc).__name__}: {exc}"[:400],
            }
            report.errors.append(row_err)
            # mark the row failed so a re-run doesn't loop on it
            try:
                row.error = row_err
                row.import_status = "failed"
                db.flush()
            except Exception:
                db.rollback()
    db.commit()
    audit(
        db,
        principal,
        "medex.bulk_import",
        "medicine_catalog_staging",
        src.id,
        **report.as_dict(),
    )
    db.commit()
    return report


def promotion_progress(db: Session, source_id: UUID, shop_id: UUID) -> dict:
    """Count staging rows by bulk-import classification (cheap, for the UI)."""
    src_rows = db.scalars(
        select(MedicineCatalogStaging).where(MedicineCatalogStaging.source_id == source_id)
    ).all()
    counts = {
        "total": 0,
        "ready": 0,
        "imported": 0,
        "duplicates": 0,
        "invalid": 0,
        "ambiguous": 0,
        "non_medicine": 0,
    }
    for row in src_rows:
        counts["total"] += 1
        counts[classify(db, row, shop_id)] = counts.get(classify(db, row, shop_id), 0) + 1
    return counts

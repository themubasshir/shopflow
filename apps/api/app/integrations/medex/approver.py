"""Approve / reject staged medicines and match them to existing products.

The only path from staging to a live ``products`` row. It reuses the catalog
service's own ``_insert_product`` / ``_validate_units`` so a promoted medicine
satisfies every existing invariant — most importantly **zero initial stock**
(no ``stock_on_hand`` write, no batches, no expiry). Reference prices are
kept on the staging row + ``medicine_details.mrp`` and are NEVER written to a
sellable unit price unless the caller explicitly supplies one — that decision
belongs to the shop owner, per the spec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import ConflictError, NotFoundError
from app.integrations.medex.normalizer import comfortable_sku, medicine_key
from app.models import (
    MedicineCatalogMatch,
    MedicineCatalogStaging,
    Product,
)
from app.schemas.catalog import MedicineWrite, ProductUnitWrite, ProductWrite
from app.services.catalog import _default_category, _insert_product, _validate_units
from app.services.purchasing import audit


def _staging(db: Session, staging_id: UUID) -> MedicineCatalogStaging:
    row = db.get(MedicineCatalogStaging, staging_id)
    if row is None:
        raise NotFoundError("Staged medicine not found")
    return row


def _product_for_staging(
    db: Session, principal: Principal, row: MedicineCatalogStaging, *, unit_price: Decimal | None
) -> Product:
    """Build a zero-stock medicine product from a staging row."""
    cat = _default_category(db, principal.shop_id, is_medicine=True)
    name_en = row.brand_name or row.brand_name_bn or f"MedEx {row.external_id}"
    name_bn = row.brand_name_bn or name_en
    sku = comfortable_sku(row.brand_name, row.external_id)

    # Reference price -> MRP only. The base sellable unit price is whatever the
    # owner passed explicitly (``unit_price``), else 0 — never the MedEx price.
    med = MedicineWrite(
        brand_name=row.brand_name or name_en,
        generic_name=row.generic_name or name_en,
        manufacturer=row.manufacturer,
        strength=row.strength,
        dosage_form=row.dosage_form,
        pack_size=row.pack_label,
        mrp=row.unit_price or row.strip_price or row.pack_price,
        retail_price=unit_price,
        prescription_required=bool(row.prescription_note),
    )
    body = ProductWrite(
        category_id=cat.id,
        sku=sku,
        name_en=name_en,
        name_bn=name_bn,
        search_aliases=[a for a in {row.generic_name, row.generic_name_bn} if a][:10],
        unit=_base_unit(row.dosage_form),
        pack_size=row.pack_label,
        is_medicine=True,
        units=[
            ProductUnitWrite(
                name=_base_unit(row.dosage_form),
                name_bn=_base_unit_bn(row.dosage_form),
                conversion_factor=Decimal("1"),
                selling_price=unit_price or Decimal("0"),
                is_base=True,
            )
        ],
        medicine=med,
    )
    _validate_units(body.units, body.unit)
    return _insert_product(db, principal, body)


_BASE_UNITS = {
    "tablet": "tablet",
    "capsule": "capsule",
    "syrup": "bottle",
    "suspension": "bottle",
    "injection": "piece",
    "suppository": "piece",
    "cream": "piece",
    "drops": "bottle",
}
_BASE_UNITS_BN = {
    "tablet": "ট্যাবলেট",
    "capsule": "ক্যাপসুল",
    "syrup": "বোতল",
    "suspension": "বোতল",
    "injection": "পিস",
    "suppository": "পিস",
    "cream": "পিস",
    "drops": "বোতল",
}


def _base_unit(form: str | None) -> str:
    return _BASE_UNITS.get((form or "").lower(), "piece")


def _base_unit_bn(form: str | None) -> str:
    return _BASE_UNITS_BN.get((form or "").lower(), "পিস")


def approve_staging(
    db: Session,
    principal: Principal,
    staging_id: UUID,
    *,
    selling_price: Decimal | None = None,
    link_product_id: UUID | None = None,
) -> MedicineCatalogStaging:
    """Promote one staged medicine to a real, zero-stock product — or link it
    to an existing product. ``selling_price`` is the *only* way a price reaches
    the sellable unit; the MedEx reference price never becomes it implicitly.
    """
    principal.require_write("catalog:write")
    row = _staging(db, staging_id)
    if row.import_status == "imported":
        raise ConflictError("Already imported")

    try:
        if link_product_id is not None:
            product = db.scalar(
                select(Product).where(
                    Product.id == link_product_id, Product.shop_id == principal.shop_id
                )
            )
            if product is None:
                raise NotFoundError("Product to link not found")
            row.linked_product_id = product.id
            row.import_status = "matched"
        else:
            product = _product_for_staging(db, principal, row, unit_price=selling_price)
            row.linked_product_id = product.id
            row.import_status = "imported"
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by = principal.user_id
        audit(
            db,
            principal,
            "medex.approve",
            "medicine_catalog_staging",
            row.id,
            external_id=row.external_id,
            product_id=str(row.linked_product_id),
        )
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def reject_staging(db: Session, principal: Principal, staging_id: UUID) -> MedicineCatalogStaging:
    principal.require_write("catalog:write")
    row = _staging(db, staging_id)
    try:
        row.import_status = "rejected"
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by = principal.user_id
        audit(db, principal, "medex.reject", "medicine_catalog_staging", row.id)
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def set_match_status(
    db: Session, principal: Principal, match_id: UUID, *, confirm: bool
) -> MedicineCatalogMatch:
    """Confirm or reject a candidate match. Confirming links the staging row to
    that product (and marks the staging row matched) — the duplicate-handling
    path the spec requires when several candidates are plausible."""
    principal.require_write("catalog:write")
    m = db.get(MedicineCatalogMatch, match_id)
    if m is None:
        raise NotFoundError("Match not found")
    row = _staging(db, m.staging_id)
    try:
        m.status = "confirmed" if confirm else "rejected"
        if confirm:
            row.linked_product_id = m.product_id
            row.import_status = "matched"
            row.reviewed_at = datetime.now(UTC)
            row.reviewed_by = principal.user_id
        audit(
            db,
            principal,
            "medex.match",
            "medicine_catalog_match",
            m.id,
            status=m.status,
            product_id=str(m.product_id),
        )
        db.commit()
        return m
    except Exception:
        db.rollback()
        raise


def identity_key(row: MedicineCatalogStaging) -> tuple[str, str, str, str]:
    return medicine_key(row.brand_name, row.strength, row.dosage_form, row.manufacturer)

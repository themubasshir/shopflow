"""Offline dataset importer for MedEx-derived medicine rows (Phase 3E).

Reads a CSV snapshot of the MedEx catalog (the
``Mahadih534/all-Bangladeshi-medicines`` HuggingFace dataset, CC-BY-2.0) and
feeds each row through the *same* stage → validate → classify → promote
pipeline the live scraper uses. Because ``stage_detail`` upserts on
``(source, external_id)``, re-running this over the 643 previously
CAPTCHA-junked rows self-heals them into valid rows, and ``promote_batch``
only mints products for rows not already imported — fully idempotent.

No network access, no scraping, no CAPTCHA involved: the data comes from a
file already on disk. Prices come from the CSV's ``package container`` /
``Package Size`` columns and land on ``medicine_details.mrp`` only — products
stay zero-stock and unpriced exactly like live-imported rows.

CSV columns (as published):
    brand id, brand name, type, slug, dosage form, generic, strength,
    manufacturer, package container, Package Size

``package container`` carries literal price strings such as:
    "Unit Price: ৳ 5.98,(100's pack: ৳ 598.00),"   -> unit + pack price
    "100 ml bottle: ৳ 40.12"                        -> single-container price
    "250 mg vial: ৳ 55.00,500 mg vial: ৳ 95.00"    -> several container prices
    "Price Unavailable"                             -> no price
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.integrations.medex.repository import get_or_create_source, stage_detail
from app.integrations.medex.schemas import MedicineDetail, PackInfo

_MEDEX_BASE = "https://medex.com.bd"

# A single "label: ৳ amount" price segment inside a comma-separated cell.
# Some labels use a fullwidth colon (\uFF1A), so both colons are accepted.
_COLON = "[:\uff1a]"
_AMT = r"(?P<amt>[\d,]+(?:\.\d+)?)"
_PRICE_SEG = re.compile(r"(?P<label>[^:\uFF1A,()]+?)\s*" + _COLON + r"\s*৳\s*" + _AMT)
# A parenthesised pack price like "(100's pack: ৳ 598.00)".
_PACK_SEG = re.compile(r"\(\s*(?P<label>[^()]*?)\s*" + _COLON + r"\s*৳\s*" + _AMT + r"\s*\)")


def _money(text: str | None) -> Decimal | None:
    """Parse '৳ 1,234.56' -> Decimal('1234.56'); None when absent/invalid."""
    if not text:
        return None
    cleaned = text.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _parse_prices(container: str | None, pack_size: str | None) -> PackInfo | None:
    """Turn the dataset's free-text price cells into a PackInfo.

    We take the *first* unit/container price as ``price`` (the per-sellable-unit
    MRP) and the *first* ``(N's pack: ৳ X)`` parenthesised value as
    ``pack_price``. Labels are preserved verbatim in ``label``/``raw``. Nothing
    is invented: if a cell is ``Price Unavailable`` or empty, fields stay None.
    """
    container = (container or "").strip()
    pack_size = (pack_size or "").strip()
    if not container and not pack_size:
        return None
    # still keep a pack label if pack_size carries one
    if "price unavailable" in container.lower() and not pack_size:
        return None

    pack = PackInfo(raw=container or pack_size or None)

    # unit/container price — first "label: ৳ amount" in the container cell.
    m = _PRICE_SEG.search(container)
    if m:
        pack.label = m.group("label").strip() or None
        pack.price = _money(m.group("amt"))
    elif pack_size:
        # pack_size alone like "(30's pack: ৳ 300.00)" still gives a pack price.
        pm = _PACK_SEG.search(pack_size)
        if pm:
            pack.label = pm.group("label").strip() or None

    # pack price — parenthesised "(N's pack: ৳ X)" in either cell.
    pm = _PACK_SEG.search(container) or _PACK_SEG.search(pack_size)
    if pm:
        pack.pack_price = _money(pm.group("amt"))
        if not pack.label:
            pack.label = pm.group("label").strip() or None

    # If we found nothing priceable, return a bare PackInfo carrying a short
    # label so pack_size still reaches medicine_details.pack_size. pack_label
    # is varchar(80) — never stuff the whole raw cell in (it's in raw_payload).
    if pack.price is None and pack.pack_price is None and not pack.label:
        pack.label = (container or pack_size or "").split(",")[0].strip()[:80] or None
    if pack.label and len(pack.label) > 80:
        pack.label = pack.label[:80]
    return pack


def row_to_detail(row: dict[str, str]) -> MedicineDetail | None:
    """Map one CSV row to a MedicineDetail; None if it lacks a usable id."""
    source_id = (row.get("brand id") or "").strip()
    if not source_id:
        return None
    slug = (row.get("slug") or "").strip() or None
    url = (
        f"{_MEDEX_BASE}/brands/{source_id}/{slug}"
        if slug
        else (f"{_MEDEX_BASE}/brands/{source_id}")
    )
    pack = _parse_prices(row.get("package container"), row.get("Package Size"))

    def _cut(v: str | None, n: int) -> str | None:
        v = (v or "").strip() or None
        return v[:n] if v else None

    d = MedicineDetail(
        source_id=source_id,
        url=url,
        slug=slug[:255] if slug else None,
        brand_name=_cut(row.get("brand name"), 200),
        generic_name=_cut(row.get("generic"), 200),
        manufacturer=_cut(row.get("manufacturer"), 160),
        strength=_cut(row.get("strength"), 120),
        dosage_form=_cut(row.get("dosage form"), 80),
        unit_price=pack.price if pack else None,
        pack=pack,
        raw_price_text=row.get("package container") or None,
    )
    # provenance marker so staging raw_payload shows this came from a file.
    d.parse_warnings.append("dataset_snapshot")
    return d


@dataclass
class DatasetReport:
    rows: int = 0
    staged: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    promoted: int = 0
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            k: getattr(self, k)
            for k in ("rows", "staged", "updated", "unchanged", "skipped", "promoted")
        } | {"errors": self.errors[-100:]}


def import_dataset(
    db: Session,
    principal: Principal,
    csv_path: str | Path,
    *,
    promote: bool = True,
    batch: int = 500,
) -> DatasetReport:
    """Stage every CSV row, then optionally promote ready rows to products.

    Idempotent: ``stage_detail`` upserts on external_id and ``promote_batch``
    skips already-imported rows, so a re-run only processes the delta.
    """
    report = DatasetReport()
    src = get_or_create_source(db)
    path = Path(csv_path)

    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            report.rows += 1
            d = row_to_detail(row)
            if d is None:
                report.skipped += 1
                continue
            try:
                _, action = stage_detail(db, src, None, d)
                if action == "inserted":
                    report.staged += 1
                elif action == "updated":
                    report.updated += 1
                else:
                    report.unchanged += 1
            except Exception as exc:  # one bad row must not stop the sweep
                report.errors.append(
                    {"row": report.rows, "error": f"{type(exc).__name__}: {exc}"[:300]}
                )
            if report.rows % 2000 == 0:
                db.commit()
                print(f"  ...staged {report.rows} rows (new={report.staged} "
                      f"upd={report.updated} same={report.unchanged})", flush=True)
    db.commit()

    if promote:
        from app.integrations.medex.promoter import promote_batch

        while True:
            rep = promote_batch(db, principal, limit=batch)
            report.promoted += rep.imported
            print(f"  ...promote batch: +{rep.imported} (total {report.promoted})", flush=True)
            # stop when a batch imports nothing new (all classified/skipped)
            if rep.imported == 0:
                report.errors.extend(rep.errors)
                break
    db.commit()
    return report

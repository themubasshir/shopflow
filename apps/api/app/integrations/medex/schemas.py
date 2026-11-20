"""Pydantic shapes for MedEx-derived data.

``MedicineDetail`` is the canonical record for one medicine, whether it came
from the live scraper (removed) or the offline dataset importer.
``PackInfo`` carries the packaging/price breakdown parsed from the source.

Prices are ``Decimal``; a missing price is ``None`` — never guessed or
inferred. ``raw`` keeps the literal source strings so re-parsing later can be
audited against what the source actually said.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class PackInfo(BaseModel):
    """A packaging price line like ``(10 x 10: ৳ 86.00)``."""

    label: str | None = None  # "Unit Price", "90 ml bottle", "Box"…
    price: Decimal | None = None  # the labelled price (unit / bottle / box)
    pack_quantity: int | None = None  # units per box/strip (the "10" in "10 x 10")
    units_per_pack: int | None = None  # inner count (the "10" inside a strip)
    pack_price: Decimal | None = None  # the parenthesised total price
    raw: str | None = None  # literal source text


class MedicineDetail(BaseModel):
    """A medicine record — a parsed detail page or a dataset row."""

    source_id: str
    url: str
    slug: str | None = None
    brand_name: str | None = None
    brand_name_bn: str | None = None
    generic_name: str | None = None
    generic_name_bn: str | None = None
    manufacturer: str | None = None
    manufacturer_bn: str | None = None
    strength: str | None = None
    strength_bn: str | None = None
    dosage_form: str | None = None
    dosage_form_bn: str | None = None
    unit_price: Decimal | None = None
    strip_price: Decimal | None = None
    pack: PackInfo | None = None
    therapeutic_class: str | None = None
    prescription_note: str | None = None  # only an explicit on-page designation
    fetched_at: datetime = Field(default_factory=utcnow)
    content_hash: str | None = None
    # Audit trail: literal strings the parser read, before normalization.
    raw_price_text: str | None = None
    parse_warnings: list[str] = Field(default_factory=list)


class StageResult(BaseModel):
    """Outcome of writing a parsed detail into staging."""

    staging_id: str | None = None
    status: str  # staged | updated | unchanged | error | duplicate_in_batch
    detail: str | None = None

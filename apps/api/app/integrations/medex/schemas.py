"""Pydantic shapes for MedEx-extracted data.

Two layers:

* ``IndexCard``    — one ``.brand-card`` on a ``/brands`` index page. Carries
  the stable numeric source id parsed from the ``/brands/{id}/{slug}`` URL.
* ``MedicineDetail`` — a fully parsed ``/brands/{id}/...`` detail page.

Prices are ``Decimal``; a missing price is ``None`` — never guessed or
inferred. ``raw`` keeps the literal source strings so re-parsing later can be
audited against what the page actually said.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class IndexCard(BaseModel):
    """One brand card discovered on a /brands index page."""

    source_id: str  # numeric id from /brands/{id}/{slug}
    url: str  # canonical absolute detail URL (no /bn, no query)
    slug: str  # trailing url slug
    brand_name: str
    strength: str | None = None
    generic_name: str | None = None
    manufacturer: str | None = None
    dosage_form: str | None = None  # from the card's dosage icon title


class IndexPage(BaseModel):
    """Result of parsing one index page."""

    cards: list[IndexCard] = Field(default_factory=list)
    page_number: int | None = None  # current page, if determinable
    last_page: int | None = None  # highest page number seen in pagination
    next_page_url: str | None = None


class PackInfo(BaseModel):
    """A packaging price line like ``(10 x 10: ৳ 86.00)``."""

    label: str | None = None  # "Unit Price", "90 ml bottle", "Box"…
    price: Decimal | None = None  # the labelled price (unit / bottle / box)
    pack_quantity: int | None = None  # units per box/strip (the "10" in "10 x 10")
    units_per_pack: int | None = None  # inner count (the "10" inside a strip)
    pack_price: Decimal | None = None  # the parenthesised total price
    raw: str | None = None  # literal source text


class MedicineDetail(BaseModel):
    """A parsed MedEx brand detail page."""

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

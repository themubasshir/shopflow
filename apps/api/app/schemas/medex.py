"""Pydantic response models for the MedEx catalog-import workspace API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceOut(ORM):
    id: UUID
    code: str
    name: str
    base_url: str
    is_active: bool
    consent_note: str | None = None
    consent_recorded_at: datetime | None = None


class RunOut(ORM):
    id: UUID
    scope: str
    status: str
    index_start: int
    index_limit: int | None
    detail_limit: int | None
    last_index_page: int
    last_page_seen: int | None
    discovered: int
    fetched: int
    staged: int
    failed: int
    pending_count: int = 0
    started_at: datetime | None
    finished_at: datetime | None


class StagingOut(ORM):
    id: UUID
    external_id: str
    source_url: str
    slug: str | None
    brand_name: str | None
    brand_name_bn: str | None
    generic_name: str | None
    generic_name_bn: str | None
    manufacturer: str | None
    manufacturer_bn: str | None
    strength: str | None
    strength_bn: str | None
    dosage_form: str | None
    dosage_form_bn: str | None
    unit_price: Decimal | None
    strip_price: Decimal | None
    pack_price: Decimal | None
    pack_quantity: int | None
    units_per_pack: int | None
    pack_label: str | None
    therapeutic_class: str | None
    prescription_note: str | None
    validation_status: str
    import_status: str
    parse_warnings: list
    source_fetched_at: datetime | None
    reviewed_at: datetime | None
    linked_product_id: UUID | None
    content_hash: str | None


class StagingListOut(BaseModel):
    rows: list[StagingOut]
    total: int
    offset: int
    limit: int


class MatchOut(ORM):
    id: UUID
    staging_id: UUID
    product_id: UUID
    basis: str
    score: int
    status: str
    product_name_en: str | None = None
    product_sku: str | None = None


class StatsOut(BaseModel):
    total: int
    by_status: dict
    missing_price: int
    match_candidates: int


class ApproveBody(BaseModel):
    staging_id: UUID
    selling_price: Decimal | None = None
    link_product_id: UUID | None = None


class RejectBody(BaseModel):
    staging_id: UUID


class MatchBody(BaseModel):
    match_id: UUID
    confirm: bool


# --- Phase 3C: bulk promotion -------------------------------------------------


class BulkImportBody(BaseModel):
    """One bulk-promotion sweep. ``limit`` bounds the batch so a very large

    catalog is imported in manageable, resumable transactions."""

    limit: int = 500


class BulkImportOut(BaseModel):
    ready: int = 0
    imported: int = 0
    skipped_existing: int = 0
    duplicates: int = 0
    invalid: int = 0
    ambiguous: int = 0
    non_medicine: int = 0
    failed: int = 0
    errors: list[dict] = []


class PromotionProgressOut(BaseModel):
    total: int = 0
    ready: int = 0
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    ambiguous: int = 0
    non_medicine: int = 0

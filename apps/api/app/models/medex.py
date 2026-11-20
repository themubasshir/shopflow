"""Staging + provenance tables for the MedEx catalog import (Phase 3A).

Five tables model one pipeline:

* ``medicine_catalog_sources``    — one row per upstream source ("medex").
* ``medicine_catalog_import_runs`` — a collector run (pilot or full): bounds,
  counters, status. Lets an interrupted run be resumed and audited.
* ``medicine_catalog_staging``     — one row per scraped medicine, keyed by
  ``(source_id, external_id)`` so re-collection updates in place instead of
  duplicating. Carries every parsed field + validation/import status.
* ``medicine_catalog_matches``     — candidate links between a staging row and
  an existing ``products`` row, awaiting owner review.
* ``medicine_catalog_sync_history`` — per-field change log when a re-scrape's
  content hash differs (price changes flagged for review).

Nothing here writes ``products``, ``stock_movements`` or any ledger — the
staging area is inert until an explicit owner approval promotes a row, which
still goes through the normal zero-stock product-creation service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MONEY = Numeric(14, 2)


class MedicineCatalogSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered upstream data source."""

    __tablename__ = "medicine_catalog_sources"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Recorded consent metadata — never the private document itself.
    consent_note: Mapped[str | None] = mapped_column(Text)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    staging_rows: Mapped[list[MedicineCatalogStaging]] = relationship(back_populates="source")


class MedicineCatalogImportRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single collection run — pilot or full — with resumable counters."""

    __tablename__ = "medicine_catalog_import_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("medicine_catalog_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )  # pending|running|paused|completed|failed|interrupted
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pilot")
    # discovery bounds
    index_start: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    index_limit: Mapped[int | None] = mapped_column(Integer)
    detail_limit: Mapped[int | None] = mapped_column(Integer)
    # progress / checkpoint
    last_index_page: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    discovered: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    staged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # persisted work-queue + errors (no secrets)
    pending_urls: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    last_page_seen: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_medicine_runs_source_status", "source_id", "status"),)


class MedicineCatalogStaging(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One scraped medicine, keyed by (source, external_id)."""

    __tablename__ = "medicine_catalog_staging"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("medicine_catalog_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medicine_catalog_import_runs.id", ondelete="SET NULL")
    )
    external_id: Mapped[str] = mapped_column(String(40), nullable=False)  # MedEx numeric id
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64))

    # parsed fields
    brand_name: Mapped[str | None] = mapped_column(String(200))
    brand_name_bn: Mapped[str | None] = mapped_column(String(200))
    generic_name: Mapped[str | None] = mapped_column(String(200))
    generic_name_bn: Mapped[str | None] = mapped_column(String(200))
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    manufacturer_bn: Mapped[str | None] = mapped_column(String(160))
    strength: Mapped[str | None] = mapped_column(String(120))
    strength_bn: Mapped[str | None] = mapped_column(String(120))
    dosage_form: Mapped[str | None] = mapped_column(String(80))
    dosage_form_bn: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    strip_price: Mapped[Decimal | None] = mapped_column(MONEY)
    pack_price: Mapped[Decimal | None] = mapped_column(MONEY)
    pack_quantity: Mapped[int | None] = mapped_column(Integer)
    units_per_pack: Mapped[int | None] = mapped_column(Integer)
    pack_label: Mapped[str | None] = mapped_column(String(80))
    therapeutic_class: Mapped[str | None] = mapped_column(String(200))
    prescription_note: Mapped[str | None] = mapped_column(String(200))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)  # literal parsed dump

    # workflow status
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )  # pending|valid|warning|invalid
    import_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="staged"
    )  # staged|pending_review|approved|rejected|imported|matched|failed
    error: Mapped[dict | None] = mapped_column(JSONB)
    parse_warnings: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    source_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    linked_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL")
    )

    source: Mapped[MedicineCatalogSource] = relationship(back_populates="staging_rows")

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_medicine_staging_source_external"),
        Index("ix_medicine_staging_import_status", "import_status"),
        Index("ix_medicine_staging_validation", "validation_status"),
        Index("ix_medicine_staging_generic", "generic_name"),
        Index("ix_medicine_staging_manufacturer", "manufacturer"),
    )


class MedicineCatalogMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A candidate link between a staging row and an existing product."""

    __tablename__ = "medicine_catalog_matches"

    staging_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("medicine_catalog_staging.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    basis: Mapped[str] = mapped_column(String(30), nullable=False)  # source_id|barcode|fuzzy|name
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )  # pending|confirmed|rejected

    __table_args__ = (
        UniqueConstraint("staging_id", "product_id", name="uq_medicine_match_staging_product"),
        Index("ix_medicine_matches_product", "product_id"),
    )


class MedicineCatalogSyncHistory(UUIDPrimaryKeyMixin, Base):
    """A per-field change recorded when a re-scrape's hash differed."""

    __tablename__ = "medicine_catalog_sync_history"

    staging_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("medicine_catalog_staging.id", ondelete="CASCADE"),
        nullable=False,
    )
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    price_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_medicine_sync_staging", "staging_id"),)

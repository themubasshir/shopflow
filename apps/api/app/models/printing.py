"""Print-queue domain (Phase 2D-2): shared thermal printers and their jobs.

The queue is a first-class, append-only audit trail. A ``Printer`` is hardware
registered by the owner; a ``PrintJob`` is one physical print of one saved
invoice. Jobs are claimed under a lease so two concurrent agents can never pick
the same row, and a job that may have physically printed is moved to
``uncertain`` rather than silently reprinted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Printer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered thermal printer shared by one or more counters.

    ``token_hash`` is the argon2 hash of the agent credential used to claim its
    jobs — never the raw token. ``config`` holds transport-specific connection
    detail (host/port for ``network``) that only the bound agent may read.
    ``capabilities`` records what the firmware can do; the agent only implements
    ESC/POS raster, so a character-only device is refused rather than guessed at.
    """

    __tablename__ = "printers"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transport: Mapped[str] = mapped_column(String(24), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Free-text hardware identity for the acceptance checklist, e.g. "Epson TM-T82X".
    device_model: Mapped[str | None] = mapped_column(String(120))
    paper_width_mm: Mapped[int] = mapped_column(Integer, nullable=False, server_default="80")
    dots_width: Mapped[int] = mapped_column(Integer, nullable=False, server_default="576")
    dpi: Mapped[int] = mapped_column(Integer, nullable=False, server_default="203")
    # 1..8, vendor scale; 4 is the neutral level that reproduces the default
    # threshold, so an untouched printer rasterizes exactly as before.
    density: Mapped[int] = mapped_column(Integer, nullable=False, server_default="4")
    # ESC d n feed after the raster, in 1/8 mm dots.
    feed_dots: Mapped[int] = mapped_column(Integer, nullable=False, server_default="90")
    has_cutter: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    default_language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="bilingual"
    )
    # Per-transport connection config (e.g. {"host": "192.168.0.50", "port": 9100}).
    config: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    # e.g. {"raster": true, "character": false}.
    capabilities: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (
        CheckConstraint("transport IN ('network','bluetooth')", name="transport_valid"),
        CheckConstraint("paper_width_mm > 0", name="paper_width_positive"),
        CheckConstraint("dots_width > 0", name="dots_width_positive"),
        CheckConstraint("dpi > 0", name="dpi_positive"),
        CheckConstraint("density BETWEEN 1 AND 8", name="density_range"),
        CheckConstraint("feed_dots BETWEEN 0 AND 255", name="feed_dots_range"),
        CheckConstraint(
            "default_language IN ('en','bn','bilingual')", name="default_language_valid"
        ),
        Index("ix_printers_shop_id_is_enabled", "shop_id", "is_enabled"),
        Index("ix_printers_shop_id_agent_id", "shop_id", "agent_id"),
    )


class CounterPrinter(Base):
    """Maps each counter to its preferred printer.

    A counter has at most one preferred printer (PK on ``counter_id``), but a
    printer may serve many counters — the shared setup the owner configures.
    """

    __tablename__ = "counter_printers"

    counter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("counters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    printer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_counter_printers_printer_id", "printer_id"),
        Index("ix_counter_printers_shop_id", "shop_id"),
    )


class PrintJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One physical print, queued for a specific printer.

    ``kind`` is ``invoice`` (the normal case: an immutable saved receipt) or
    ``test_page`` (an owner-initiated printer/alignment page that is not tied to
    any invoice, so ``invoice_id`` is null). The row stores everything an
    authorized agent needs to render the document without an extra DB lookup or
    a second template: the invoice id, the receipt language, and the printer's
    raster calibration. ``claim_token`` is the lease identifier the agent echoes
    back when reporting — only the holder of the current token may transition
    the job.
    """

    __tablename__ = "print_jobs"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="invoice")
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE")
    )
    printer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    counter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("counters.id", ondelete="SET NULL")
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="bilingual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(Text)
    # Lease: the agent that claimed this job holds a random claim_token and the
    # lease_until deadline. Completing/failing requires the current token.
    claim_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by_agent: Mapped[str | None] = mapped_column(String(80))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # One-time document fetch secret issued at claim time (argon2 hash only). It
    # is burned on first use so the saved-invoice PDF is never replay-fetchable.
    document_token_hash: Mapped[str | None] = mapped_column(String(255))
    document_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Self-reference: a reprint points at the original job for the audit trail.
    reprint_of_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("print_jobs.id", ondelete="SET NULL")
    )
    # Raster calibration snapshot copied from the printer at enqueue time, so a
    # later printer-config change cannot silently alter an in-flight job.
    dots_width: Mapped[int] = mapped_column(Integer, nullable=False, server_default="576")
    dpi: Mapped[int] = mapped_column(Integer, nullable=False, server_default="203")
    density: Mapped[int] = mapped_column(Integer, nullable=False, server_default="4")
    feed_dots: Mapped[int] = mapped_column(Integer, nullable=False, server_default="90")
    meta: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (
        CheckConstraint("kind IN ('invoice','test_page')", name="kind_valid"),
        # An invoice job must name its invoice; a test page must not.
        CheckConstraint(
            "(kind = 'invoice' AND invoice_id IS NOT NULL)"
            " OR (kind = 'test_page' AND invoice_id IS NULL)",
            name="invoice_required_for_invoice_job",
        ),
        CheckConstraint("language IN ('en','bn','bilingual')", name="language_valid"),
        CheckConstraint(
            "status IN ('pending','claimed','printing','completed','failed',"
            "'uncertain','cancelled')",
            name="status_valid",
        ),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("density BETWEEN 1 AND 8", name="density_range"),
        CheckConstraint("feed_dots BETWEEN 0 AND 255", name="feed_dots_range"),
        Index("ix_print_jobs_printer_id_status", "printer_id", "status"),
        Index("ix_print_jobs_shop_id_created_at", "shop_id", "created_at"),
        Index("ix_print_jobs_invoice_id", "invoice_id"),
        # FIFO claim: an agent pulls the oldest pending job for its printer.
        Index(
            "ix_print_jobs_pending_fifo",
            "printer_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_print_jobs_leased",
            "lease_until",
            postgresql_where=text("status IN ('claimed','printing')"),
        ),
    )

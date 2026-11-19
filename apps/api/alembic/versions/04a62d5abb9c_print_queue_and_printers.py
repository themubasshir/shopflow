"""Shared thermal printing: printers, counter assignments and the print queue.

Adds three tables for Phase 2D-2. ``printers`` registers shared thermal
hardware per shop (agent-scoped, argon2 credential). ``counter_printers`` maps
each counter to a preferred printer so many counters can share one device.
``print_jobs`` is the persistent FIFO queue an agent leases from; it carries a
frozen raster calibration snapshot so a later printer change cannot alter an
in-flight job, a lease (claim_token + lease_until) for deterministic
claim-by-claim, and a one-time document secret so the saved-invoice PDF is
never replay-fetchable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "04a62d5abb9c"
down_revision: str = "f8bcc76b2f43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "printers",
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("transport", sa.String(length=24), nullable=False),
        sa.Column("agent_id", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("paper_width_mm", sa.Integer(), server_default="80", nullable=False),
        sa.Column("dots_width", sa.Integer(), server_default="576", nullable=False),
        sa.Column("dpi", sa.Integer(), server_default="203", nullable=False),
        sa.Column("has_cutter", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "default_language",
            sa.String(length=10),
            server_default="bilingual",
            nullable=False,
        ),
        sa.Column("config", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_printers_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_printers")),
        sa.CheckConstraint(
            "transport IN ('network','bluetooth')",
            name=op.f("ck_printers_transport_valid"),
        ),
        sa.CheckConstraint("paper_width_mm > 0", name=op.f("ck_printers_paper_width_positive")),
        sa.CheckConstraint("dots_width > 0", name=op.f("ck_printers_dots_width_positive")),
        sa.CheckConstraint("dpi > 0", name=op.f("ck_printers_dpi_positive")),
        sa.CheckConstraint(
            "default_language IN ('en','bn','bilingual')",
            name=op.f("ck_printers_default_language_valid"),
        ),
    )
    op.create_index("ix_printers_shop_id_is_enabled", "printers", ["shop_id", "is_enabled"])
    op.create_index("ix_printers_shop_id_agent_id", "printers", ["shop_id", "agent_id"])
    op.create_index(op.f("ix_printers_created_at"), "printers", ["created_at"])

    op.create_table(
        "counter_printers",
        sa.Column("counter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("printer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["counter_id"],
            ["counters.id"],
            name=op.f("fk_counter_printers_counter_id_counters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["printer_id"],
            ["printers.id"],
            name=op.f("fk_counter_printers_printer_id_printers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_counter_printers_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("counter_id", name=op.f("pk_counter_printers")),
    )
    op.create_index("ix_counter_printers_printer_id", "counter_printers", ["printer_id"])
    op.create_index("ix_counter_printers_shop_id", "counter_printers", ["shop_id"])

    op.create_table(
        "print_jobs",
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="invoice", nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("printer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("counter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("language", sa.String(length=10), server_default="bilingual", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_agent", sa.String(length=80), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_token_hash", sa.String(length=255), nullable=True),
        sa.Column("document_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reprint_of_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dots_width", sa.Integer(), server_default="576", nullable=False),
        sa.Column("dpi", sa.Integer(), server_default="203", nullable=False),
        sa.Column("meta", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_print_jobs_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_print_jobs_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["printer_id"],
            ["printers.id"],
            name=op.f("fk_print_jobs_printer_id_printers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_print_jobs_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["counter_id"],
            ["counters.id"],
            name=op.f("fk_print_jobs_counter_id_counters"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reprint_of_job_id"],
            ["print_jobs.id"],
            name=op.f("fk_print_jobs_reprint_of_job_id_print_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_print_jobs")),
        sa.CheckConstraint(
            "kind IN ('invoice','test_page')", name=op.f("ck_print_jobs_kind_valid")
        ),
        sa.CheckConstraint(
            "(kind = 'invoice' AND invoice_id IS NOT NULL)"
            " OR (kind = 'test_page' AND invoice_id IS NULL)",
            name=op.f("ck_print_jobs_invoice_required_for_invoice_job"),
        ),
        sa.CheckConstraint(
            "language IN ('en','bn','bilingual')",
            name=op.f("ck_print_jobs_language_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','claimed','printing','completed',"
            "'failed','uncertain','cancelled')",
            name=op.f("ck_print_jobs_status_valid"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_print_jobs_attempts_non_negative")),
    )
    op.create_index("ix_print_jobs_printer_id_status", "print_jobs", ["printer_id", "status"])
    op.create_index("ix_print_jobs_shop_id_created_at", "print_jobs", ["shop_id", "created_at"])
    op.create_index("ix_print_jobs_invoice_id", "print_jobs", ["invoice_id"])
    op.create_index(op.f("ix_print_jobs_created_at"), "print_jobs", ["created_at"])
    op.create_index(
        "ix_print_jobs_pending_fifo",
        "print_jobs",
        ["printer_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_print_jobs_leased",
        "print_jobs",
        ["lease_until"],
        postgresql_where=sa.text("status IN ('claimed','printing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_print_jobs_leased", table_name="print_jobs")
    op.drop_index("ix_print_jobs_pending_fifo", table_name="print_jobs")
    op.drop_index(op.f("ix_print_jobs_created_at"), table_name="print_jobs")
    op.drop_index("ix_print_jobs_invoice_id", table_name="print_jobs")
    op.drop_index("ix_print_jobs_shop_id_created_at", table_name="print_jobs")
    op.drop_index("ix_print_jobs_printer_id_status", table_name="print_jobs")
    op.drop_table("print_jobs")
    op.drop_index("ix_counter_printers_shop_id", table_name="counter_printers")
    op.drop_index("ix_counter_printers_printer_id", table_name="counter_printers")
    op.drop_table("counter_printers")
    op.drop_index(op.f("ix_printers_created_at"), table_name="printers")
    op.drop_index("ix_printers_shop_id_agent_id", table_name="printers")
    op.drop_index("ix_printers_shop_id_is_enabled", table_name="printers")
    op.drop_table("printers")

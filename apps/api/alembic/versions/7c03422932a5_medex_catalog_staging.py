"""medex_catalog_staging

Revision ID: 7c03422932a5
Revises: b7d41f0c92ae
Create Date: 2026-11-20 11:44:57.044874

Phase 3A: MedEx medicine-catalog ingestion staging area.

Creates five tables that model the scrape -> stage -> match -> approve
pipeline. The staging area is deliberately inert: no trigger, FK or service
here ever writes ``products``, ``stock_movements`` or any financial ledger.
A staged row only becomes a real product after an explicit owner approval,
which goes through the normal zero-stock product-creation service.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c03422932a5"
down_revision: str | None = "b7d41f0c92ae"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "medicine_catalog_sources",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("consent_note", sa.Text(), nullable=True),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medicine_catalog_sources")),
        sa.UniqueConstraint("code", name=op.f("uq_medicine_catalog_sources_code")),
    )
    op.create_table(
        "medicine_catalog_import_runs",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("scope", sa.String(length=20), server_default="pilot", nullable=False),
        sa.Column("index_start", sa.Integer(), server_default="1", nullable=False),
        sa.Column("index_limit", sa.Integer(), nullable=True),
        sa.Column("detail_limit", sa.Integer(), nullable=True),
        sa.Column("last_index_page", sa.Integer(), server_default="0", nullable=False),
        sa.Column("discovered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("staged", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "pending_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_page_seen", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["medicine_catalog_sources.id"],
            name=op.f("fk_medicine_catalog_import_runs_source_id_medicine_catalog_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medicine_catalog_import_runs")),
    )
    op.create_index(
        "ix_medicine_runs_source_status",
        "medicine_catalog_import_runs",
        ["source_id", "status"],
        unique=False,
    )
    op.create_table(
        "medicine_catalog_staging",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("external_id", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("brand_name", sa.String(length=200), nullable=True),
        sa.Column("brand_name_bn", sa.String(length=200), nullable=True),
        sa.Column("generic_name", sa.String(length=200), nullable=True),
        sa.Column("generic_name_bn", sa.String(length=200), nullable=True),
        sa.Column("manufacturer", sa.String(length=160), nullable=True),
        sa.Column("manufacturer_bn", sa.String(length=160), nullable=True),
        sa.Column("strength", sa.String(length=120), nullable=True),
        sa.Column("strength_bn", sa.String(length=120), nullable=True),
        sa.Column("dosage_form", sa.String(length=80), nullable=True),
        sa.Column("dosage_form_bn", sa.String(length=80), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("strip_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("pack_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("pack_quantity", sa.Integer(), nullable=True),
        sa.Column("units_per_pack", sa.Integer(), nullable=True),
        sa.Column("pack_label", sa.String(length=80), nullable=True),
        sa.Column("therapeutic_class", sa.String(length=200), nullable=True),
        sa.Column("prescription_note", sa.String(length=200), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "validation_status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("import_status", sa.String(length=20), server_default="staged", nullable=False),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "parse_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("linked_product_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["linked_product_id"],
            ["products.id"],
            name=op.f("fk_medicine_catalog_staging_linked_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_medicine_catalog_staging_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["medicine_catalog_import_runs.id"],
            name=op.f("fk_medicine_catalog_staging_run_id_medicine_catalog_import_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["medicine_catalog_sources.id"],
            name=op.f("fk_medicine_catalog_staging_source_id_medicine_catalog_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medicine_catalog_staging")),
        sa.UniqueConstraint("source_id", "external_id", name="uq_medicine_staging_source_external"),
    )
    op.create_index(
        "ix_medicine_staging_generic", "medicine_catalog_staging", ["generic_name"], unique=False
    )
    op.create_index(
        "ix_medicine_staging_import_status",
        "medicine_catalog_staging",
        ["import_status"],
        unique=False,
    )
    op.create_index(
        "ix_medicine_staging_manufacturer",
        "medicine_catalog_staging",
        ["manufacturer"],
        unique=False,
    )
    op.create_index(
        "ix_medicine_staging_validation",
        "medicine_catalog_staging",
        ["validation_status"],
        unique=False,
    )
    op.create_table(
        "medicine_catalog_matches",
        sa.Column("staging_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("basis", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_medicine_catalog_matches_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staging_id"],
            ["medicine_catalog_staging.id"],
            name=op.f("fk_medicine_catalog_matches_staging_id_medicine_catalog_staging"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medicine_catalog_matches")),
        sa.UniqueConstraint("staging_id", "product_id", name="uq_medicine_match_staging_product"),
    )
    op.create_index(
        "ix_medicine_matches_product", "medicine_catalog_matches", ["product_id"], unique=False
    )
    op.create_table(
        "medicine_catalog_sync_history",
        sa.Column("staging_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=60), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("price_change", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["staging_id"],
            ["medicine_catalog_staging.id"],
            name=op.f("fk_medicine_catalog_sync_history_staging_id_medicine_catalog_staging"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medicine_catalog_sync_history")),
    )
    op.create_index(
        "ix_medicine_sync_staging",
        "medicine_catalog_sync_history",
        ["staging_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_medicine_sync_staging", table_name="medicine_catalog_sync_history")
    op.drop_table("medicine_catalog_sync_history")
    op.drop_index("ix_medicine_matches_product", table_name="medicine_catalog_matches")
    op.drop_table("medicine_catalog_matches")
    op.drop_index("ix_medicine_staging_validation", table_name="medicine_catalog_staging")
    op.drop_index("ix_medicine_staging_manufacturer", table_name="medicine_catalog_staging")
    op.drop_index("ix_medicine_staging_import_status", table_name="medicine_catalog_staging")
    op.drop_index("ix_medicine_staging_generic", table_name="medicine_catalog_staging")
    op.drop_table("medicine_catalog_staging")
    op.drop_index("ix_medicine_runs_source_status", table_name="medicine_catalog_import_runs")
    op.drop_table("medicine_catalog_import_runs")
    op.drop_table("medicine_catalog_sources")

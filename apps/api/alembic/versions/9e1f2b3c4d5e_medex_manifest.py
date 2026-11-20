"""medex_catalog_manifest

Revision ID: 9e1f2b3c4d5e
Revises: 7c03422932a5
Create Date: 2026-11-20 13:00:00.000000

Phase 3B: deduplicated detail-URL manifest for the MedEx collection.

Adds ``medicine_catalog_manifest`` — one row per discovered ``/brands/{id}``
detail URL, keyed on ``(source_id, external_id)``. It records index-page
provenance and a per-URL ``attempts`` counter so the collector can bound
retries: a persistently-failing page is marked ``failed`` after
``max_detail_attempts`` instead of re-queuing forever and stalling the run.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9e1f2b3c4d5e"
down_revision: str | None = "7c03422932a5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "medicine_catalog_manifest",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("medicine_catalog_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("medicine_catalog_import_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_id", sa.String(length=40), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("brand_label", sa.String(length=200), nullable=True),
        sa.Column("index_page", sa.Integer(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medicine_catalog_manifest")),
        sa.UniqueConstraint(
            "source_id", "external_id", name="uq_medicine_manifest_source_external"
        ),
    )
    op.create_index("ix_medicine_manifest_state", "medicine_catalog_manifest", ["state"])
    op.create_index("ix_medicine_manifest_run", "medicine_catalog_manifest", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_medicine_manifest_run", table_name="medicine_catalog_manifest")
    op.drop_index("ix_medicine_manifest_state", table_name="medicine_catalog_manifest")
    op.drop_table("medicine_catalog_manifest")

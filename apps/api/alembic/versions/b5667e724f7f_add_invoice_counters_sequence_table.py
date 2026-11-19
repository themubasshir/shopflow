"""add invoice_counters sequence table

Revision ID: b5667e724f7f
Revises: 6a5680c635ea
Create Date: 2026-11-19 00:16:56.720466

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b5667e724f7f"
down_revision: str | None = "6a5680c635ea"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_counters",
        sa.Column("shop_id", UUID(as_uuid=True), nullable=False),
        sa.Column("counter_date", sa.String(length=8), nullable=False),
        sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_invoice_counters_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("shop_id", "counter_date", name=op.f("pk_invoice_counters")),
    )


def downgrade() -> None:
    op.drop_table("invoice_counters")

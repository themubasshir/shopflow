"""medicine_supplier_price

Revision ID: e5a7b8c9d0e1
Revises: a1b2c3d4e5f6
Create Date: 2026-11-20 16:30:00.000000

Add a ``supplier_price`` column to ``medicine_details``.

This is the *reference* supplier/cost price for the catalog row, kept separate
from ``purchase_cost`` (which is the per-batch actual cost fed by purchases)
and from ``retail_price``/``mrp`` (sellable/reference prices). It enables a
future profit/loss view (``retail_price - supplier_price``) without touching
billing, ledgers, or batch accounting. Nullable; non-negative when set.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e5a7b8c9d0e1"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "medicine_details",
        sa.Column("supplier_price", sa.Numeric(precision=14, scale=2), nullable=True),
    )
    op.create_check_constraint(
        "supplier_price_non_negative",
        "medicine_details",
        "supplier_price IS NULL OR supplier_price >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("supplier_price_non_negative", "medicine_details", type_="check")
    op.drop_column("medicine_details", "supplier_price")

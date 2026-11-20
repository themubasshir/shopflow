"""medex_search_trgm

Revision ID: a1b2c3d4e5f6
Revises: 9e1f2b3c4d5e
Create Date: 2026-11-20 15:00:00.000000

Phase 3C: trigram (pg_trgm) indexes for catalog search at scale.

A full MedEx import lands ~25k products; the billing/catalog `q` filter does
``lower(name_en|sku|alias) LIKE '%q%'``, which cannot use a btree index and
would seq-scan every keystroke. GIN trigram indexes accelerate substring/ILIKE
matching on the searched text columns. Additive only — no existing index,
column or constraint is altered.

Indexes created:
* products.name_en / products.name_bn / products.sku
* medicine_catalog_staging.brand_name / generic_name / manufacturer
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "9e1f2b3c4d5e"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_name_en_trgm "
        "ON products USING gin (name_en gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_name_bn_trgm "
        "ON products USING gin (name_bn gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_sku_trgm "
        "ON products USING gin (sku gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mstaging_brand_trgm "
        "ON medicine_catalog_staging USING gin (brand_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mstaging_generic_trgm "
        "ON medicine_catalog_staging USING gin (generic_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mstaging_manufacturer_trgm "
        "ON medicine_catalog_staging USING gin (manufacturer gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mstaging_manufacturer_trgm")
    op.execute("DROP INDEX IF EXISTS ix_mstaging_generic_trgm")
    op.execute("DROP INDEX IF EXISTS ix_mstaging_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_sku_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_name_bn_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_name_en_trgm")

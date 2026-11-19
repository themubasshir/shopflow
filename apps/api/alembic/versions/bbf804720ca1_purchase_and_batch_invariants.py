"""Enforce purchase projections and store the complete purchase status.

Revision ID: bbf804720ca1
Revises: 7f58b276a2e0
"""

from alembic import op

revision = "bbf804720ca1"
down_revision = "7f58b276a2e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE purchases ALTER COLUMN status TYPE varchar(24);
        ALTER TABLE purchases ADD CONSTRAINT ck_purchases_received_total
            CHECK (received_total >= 0 AND received_total <= total AND paid_total <= received_total)
            NOT VALID;
        ALTER TABLE purchase_items ADD CONSTRAINT ck_purchase_items_receiving_projection
            CHECK (ordered_base IS NULL OR (
                ordered_base > 0 AND received_base <= ordered_base
                AND net_total BETWEEN 0 AND line_total
            )) NOT VALID;
        ALTER TABLE medicine_batches ADD CONSTRAINT ck_medicine_batches_received_projection
            CHECK (quantity_received >= quantity_on_hand) NOT VALID;
        """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE medicine_batches DROP CONSTRAINT ck_medicine_batches_received_projection;
        ALTER TABLE purchase_items DROP CONSTRAINT ck_purchase_items_receiving_projection;
        ALTER TABLE purchases DROP CONSTRAINT ck_purchases_received_total;
        ALTER TABLE purchases ALTER COLUMN status TYPE varchar(16);
        """)

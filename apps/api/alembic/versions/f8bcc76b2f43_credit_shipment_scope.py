"""Scope supplier return shipments to each original purchase."""

from alembic import op

revision = "f8bcc76b2f43"
down_revision = "de452fa8b713"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE supplier_credit_notes DROP CONSTRAINT supplier_credit_notes_shipment_id_key;
        ALTER TABLE supplier_credit_notes ADD CONSTRAINT uq_supplier_credit_notes_purchase_shipment
            UNIQUE (purchase_id, shipment_id);
        CREATE INDEX ix_stock_movements_stock_lot ON stock_movements(stock_lot_id)
            WHERE stock_lot_id IS NOT NULL;
        CREATE INDEX ix_stock_movements_batch ON stock_movements(batch_id)
            WHERE batch_id IS NOT NULL;
    """)


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup to roll back supplier credit scope")

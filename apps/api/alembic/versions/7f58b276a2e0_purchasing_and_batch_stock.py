"""Purchasing, stock lots, and pharmacy batch allocation.

Revision ID: 7f58b276a2e0
Revises: 2f374de4f27c
"""

from alembic import op

revision = "7f58b276a2e0"
down_revision = "2f374de4f27c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE suppliers ADD COLUMN name_bn varchar(160);
        ALTER TABLE purchases ADD COLUMN received_total numeric(14,2) NOT NULL DEFAULT 0;
        ALTER TABLE purchases DROP CONSTRAINT ck_purchases_status_valid;
        ALTER TABLE purchases ADD CONSTRAINT ck_purchases_status_valid
            CHECK (status IN ('draft','partially_received','received','voided','reversed'));
        UPDATE purchases SET received_total = total WHERE status = 'received';
        CREATE UNIQUE INDEX uq_purchases_supplier_reference
            ON purchases (supplier_id, lower(btrim(supplier_invoice_number)))
            WHERE supplier_invoice_number IS NOT NULL AND status NOT IN ('voided','reversed');
        ALTER TABLE purchase_items
            ADD COLUMN product_unit_id uuid REFERENCES product_units(id) ON DELETE RESTRICT,
            ADD COLUMN conversion_factor numeric(12,3) NOT NULL DEFAULT 1
                CHECK (conversion_factor > 0),
            ADD COLUMN ordered_base numeric(12,3),
            ADD COLUMN received_base numeric(12,3) NOT NULL DEFAULT 0 CHECK (received_base >= 0),
            ADD COLUMN net_total numeric(14,2),
            ADD COLUMN manufacture_date date;
        ALTER TABLE medicine_batches
            ADD COLUMN quantity_received numeric(12,3) NOT NULL DEFAULT 0,
            ADD COLUMN manufacture_date date,
            ADD COLUMN quarantined boolean NOT NULL DEFAULT false;
        UPDATE medicine_batches SET quantity_received = quantity_on_hand;
        ALTER TABLE medicine_batches ADD CONSTRAINT ck_batch_received_nonnegative
            CHECK (quantity_received >= 0);
        CREATE INDEX ix_batches_sellable ON medicine_batches (product_id, expiry_date, id)
            WHERE is_active AND NOT quarantined AND quantity_on_hand > 0;
        CREATE TABLE supplier_products (
            supplier_id uuid NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
            product_id uuid NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
            PRIMARY KEY (supplier_id, product_id)
        );
        INSERT INTO supplier_products (supplier_id, product_id)
        SELECT DISTINCT p.supplier_id, i.product_id
        FROM purchases p JOIN purchase_items i ON i.purchase_id = p.id
        UNION
        SELECT supplier_id, product_id FROM medicine_batches WHERE supplier_id IS NOT NULL;
        CREATE TABLE stock_lots (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id uuid NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
            batch_id uuid REFERENCES medicine_batches(id) ON DELETE RESTRICT,
            purchase_item_id uuid REFERENCES purchase_items(id) ON DELETE RESTRICT,
            quantity_received numeric(12,3) NOT NULL CHECK (quantity_received > 0),
            quantity_remaining numeric(12,3) NOT NULL,
            cost_amount numeric(14,2) CHECK (cost_amount >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_stock_lots_quantity CHECK (
                quantity_remaining >= 0 AND quantity_remaining <= quantity_received
            )
        );
        CREATE INDEX ix_stock_lots_product_id ON stock_lots(product_id);
        CREATE INDEX ix_stock_lots_purchase_item_id ON stock_lots(purchase_item_id);
        CREATE TABLE supplier_ledger (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            supplier_id uuid NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
            purchase_id uuid NOT NULL REFERENCES purchases(id) ON DELETE RESTRICT,
            kind varchar(24) NOT NULL,
            amount numeric(14,2) NOT NULL,
            method varchar(16),
            reference varchar(120),
            created_by uuid REFERENCES users(id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (
                (kind = 'receipt' AND amount > 0 AND method IS NULL)
                OR (kind = 'payment' AND amount < 0 AND method IN ('cash','bkash','nagad','bank'))
                OR (kind = 'reversal' AND amount < 0 AND method IS NULL)
                OR (kind = 'opening' AND amount > 0 AND method IS NULL)
            )
        );
        CREATE INDEX ix_supplier_ledger_supplier_id ON supplier_ledger(supplier_id);
        CREATE INDEX ix_supplier_ledger_purchase_id ON supplier_ledger(purchase_id);
        INSERT INTO supplier_ledger (supplier_id, purchase_id, kind, amount, created_at)
        SELECT supplier_id, id, 'opening', total - paid_total, coalesce(purchased_at, created_at)
        FROM purchases WHERE status = 'received' AND total > paid_total;
        CREATE TABLE invoice_batch_allocations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            invoice_item_id uuid NOT NULL REFERENCES invoice_items(id) ON DELETE RESTRICT,
            batch_id uuid NOT NULL REFERENCES medicine_batches(id) ON DELETE RESTRICT,
            quantity numeric(12,3) NOT NULL CHECK (quantity > 0),
            batch_number varchar(64) NOT NULL,
            expiry_date date NOT NULL,
            UNIQUE (invoice_item_id, batch_id)
        );
        ALTER TABLE stock_movements ADD COLUMN stock_lot_id uuid
            REFERENCES stock_lots(id) ON DELETE RESTRICT;
        -- Reconcile the two physical projections against recorded batch counts.
        INSERT INTO audit_logs (shop_id, action, entity_type, entity_id, "before", "after")
        SELECT p.shop_id, 'stock.migrate_projection', 'product', p.id,
               jsonb_build_object('quantity', p.stock_on_hand),
               jsonb_build_object('quantity', batches.quantity)
        FROM products p CROSS JOIN LATERAL (
            SELECT coalesce(sum(b.quantity_on_hand), 0) AS quantity
            FROM medicine_batches b WHERE b.product_id = p.id AND b.shop_id = p.shop_id
        ) AS batches
        WHERE p.is_medicine AND p.stock_on_hand <> batches.quantity;
        UPDATE products p SET stock_on_hand = coalesce((
            SELECT sum(b.quantity_on_hand) FROM medicine_batches b
            WHERE b.product_id = p.id AND b.shop_id = p.shop_id
        ), 0) WHERE p.is_medicine AND p.stock_on_hand <> coalesce((
            SELECT sum(b.quantity_on_hand) FROM medicine_batches b
            WHERE b.product_id = p.id AND b.shop_id = p.shop_id
        ), 0);
        INSERT INTO stock_movements (shop_id, product_id, batch_id, movement_type, quantity, note)
        SELECT b.shop_id, b.product_id, b.id, 'opening',
               b.quantity_on_hand - coalesce(sum(m.quantity),0),
               'Phase 2E batch opening reconciliation'
        FROM medicine_batches b LEFT JOIN stock_movements m ON m.batch_id = b.id
        GROUP BY b.id HAVING b.quantity_on_hand <> coalesce(sum(m.quantity),0);
        INSERT INTO stock_movements (shop_id, product_id, movement_type, quantity, note)
        SELECT p.shop_id, p.id, 'opening', p.stock_on_hand - coalesce(sum(m.quantity),0),
               'Phase 2E product opening reconciliation'
        FROM products p LEFT JOIN stock_movements m ON m.product_id = p.id
        GROUP BY p.id HAVING p.stock_on_hand <> coalesce(sum(m.quantity),0);
        CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON supplier_ledger
            FOR EACH STATEMENT EXECUTE FUNCTION shopflow_reject_ledger_mutation();
        CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON stock_movements
            FOR EACH STATEMENT EXECUTE FUNCTION shopflow_reject_ledger_mutation();
        CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON invoice_batch_allocations
            FOR EACH STATEMENT EXECUTE FUNCTION shopflow_reject_ledger_mutation();
        """)


def downgrade() -> None:
    raise RuntimeError(
        "Phase 2E ledger and stock reconciliation require a database backup to roll back"
    )

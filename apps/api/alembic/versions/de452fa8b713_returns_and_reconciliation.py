"""Return postings, supplier credits, and ledger reconciliation.

Revision ID: de452fa8b713
Revises: bbf804720ca1
"""

from alembic import op

revision = "de452fa8b713"
down_revision = "bbf804720ca1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE customer_returns (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            invoice_id uuid NOT NULL REFERENCES invoices(id),
            actor_id uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            reason varchar(400) NOT NULL,
            amount numeric(14,2) NOT NULL,
            due_reduction numeric(14,2) NOT NULL,
            refund_amount numeric(14,2) NOT NULL,
            refund_method varchar(16),
            cash_reference varchar(120),
            eligible_value numeric(14,2) NOT NULL CHECK (eligible_value >= 0),
            earned_reversed integer NOT NULL CHECK (earned_reversed >= 0),
            redemption_value numeric(14,2) NOT NULL CHECK (redemption_value >= 0),
            redeemed_restored integer NOT NULL CHECK (redeemed_restored >= 0),
            CHECK (due_reduction >= 0 AND refund_amount >= 0
                AND amount = due_reduction + refund_amount),
            CHECK ((refund_amount = 0 AND refund_method IS NULL)
                OR (refund_amount > 0 AND refund_method IS NOT NULL
                    AND refund_method IN ('cash','bkash','nagad'))),
            CHECK (cash_reference IS NULL OR refund_method = 'cash')
        );
        CREATE INDEX ix_customer_returns_invoice ON customer_returns(invoice_id, created_at);
        CREATE INDEX ix_customer_returns_created ON customer_returns(created_at);
        CREATE TABLE customer_return_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            return_id uuid NOT NULL REFERENCES customer_returns(id),
            invoice_item_id uuid NOT NULL REFERENCES invoice_items(id),
            batch_id uuid REFERENCES medicine_batches(id),
            quantity numeric(12,3) NOT NULL CHECK (quantity > 0),
            amount numeric(14,2) NOT NULL CHECK (amount >= 0),
            disposition varchar(24) NOT NULL CHECK (
                disposition IN ('sellable','quarantine','damaged','disposal','supplier_staging')
            ),
            verified boolean NOT NULL
        );
        CREATE INDEX ix_customer_return_lines_item ON customer_return_lines(invoice_item_id);
        CREATE INDEX ix_customer_return_lines_return ON customer_return_lines(return_id);
        CREATE TABLE customer_refund_settlements (
            return_id uuid PRIMARY KEY REFERENCES customer_returns(id),
            actor_id uuid NOT NULL REFERENCES users(id),
            shop_id uuid NOT NULL REFERENCES shops(id),
            method varchar(16) NOT NULL CHECK (method IN ('bkash','nagad')),
            reference varchar(120) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX uq_customer_refund_reference ON customer_refund_settlements
            (shop_id, method, lower(btrim(reference)));
        ALTER TABLE invoices ADD COLUMN loyalty_award_base numeric(14,2);
        ALTER TABLE invoices ADD COLUMN return_due_total numeric(14,2) NOT NULL DEFAULT 0
            CHECK (return_due_total >= 0);
        ALTER TABLE invoices DROP CONSTRAINT ck_invoices_finalized_payment_totals;
        ALTER TABLE invoices ADD CONSTRAINT ck_invoices_finalized_payment_totals
            CHECK (status <> 'finalized' OR paid_total + due_total + return_due_total = total);
        ALTER TABLE customer_ledger_entries ADD COLUMN return_id uuid UNIQUE
            REFERENCES customer_returns(id);
        ALTER TABLE customer_ledger_entries
            DROP CONSTRAINT ck_customer_ledger_entries_amount_matches_type;
        ALTER TABLE customer_ledger_entries
            ADD CONSTRAINT ck_customer_ledger_entries_amount_matches_type CHECK (
                (payment_id IS NULL AND return_id IS NULL AND amount > 0) OR
                (num_nonnulls(payment_id, return_id) = 1 AND amount < 0)
            );
        DROP INDEX uq_customer_ledger_entries_invoice_charge;
        CREATE UNIQUE INDEX uq_customer_ledger_entries_invoice_charge
            ON customer_ledger_entries(invoice_id) WHERE payment_id IS NULL AND return_id IS NULL;

        ALTER TABLE loyalty_accounts DROP CONSTRAINT ck_loyalty_accounts_points_non_negative;
        ALTER TABLE loyalty_accounts ADD CONSTRAINT ck_loyalty_accounts_points_non_negative
            CHECK (lifetime_earned >= 0 AND lifetime_redeemed >= 0);
        ALTER TABLE loyalty_transactions DROP CONSTRAINT
            ck_loyalty_transactions_balance_after_non_negative;
        ALTER TABLE loyalty_transactions ADD COLUMN return_id uuid REFERENCES customer_returns(id);
        ALTER TABLE loyalty_transactions
            DROP CONSTRAINT uq_loyalty_transactions_account_invoice_type;
        CREATE UNIQUE INDEX uq_loyalty_transactions_original_invoice_type ON loyalty_transactions
            (account_id, invoice_id, transaction_type) WHERE return_id IS NULL;
        CREATE UNIQUE INDEX uq_loyalty_transactions_return_type ON loyalty_transactions
            (return_id, transaction_type) WHERE return_id IS NOT NULL;
        ALTER TABLE loyalty_accounts ADD COLUMN opening_points bigint NOT NULL DEFAULT 0;
        UPDATE loyalty_accounts a SET opening_points = points_balance - coalesce((
            SELECT sum(t.points) FROM loyalty_transactions t WHERE t.account_id = a.id
        ), 0);

        ALTER TABLE products ADD COLUMN held_quantity numeric(12,3) NOT NULL DEFAULT 0
            CHECK (held_quantity >= 0 AND held_quantity <= stock_on_hand);
        ALTER TABLE medicine_batches ADD COLUMN held_quantity numeric(12,3) NOT NULL DEFAULT 0
            CHECK (held_quantity >= 0 AND held_quantity <= quantity_on_hand);
        ALTER TABLE stock_lots ADD COLUMN held_quantity numeric(12,3) NOT NULL DEFAULT 0
            CHECK (held_quantity >= 0 AND held_quantity <= quantity_remaining);
        ALTER TABLE stock_movements ADD COLUMN held boolean NOT NULL DEFAULT false,
            ADD COLUMN invoice_item_id uuid REFERENCES invoice_items(id),
            ADD COLUMN source_movement_id uuid REFERENCES stock_movements(id);
        CREATE INDEX ix_stock_movements_invoice_item ON stock_movements(invoice_item_id)
            WHERE invoice_item_id IS NOT NULL;
        CREATE INDEX ix_stock_movements_return_source ON stock_movements(source_movement_id)
            WHERE source_movement_id IS NOT NULL;
        CREATE TABLE return_stock_portions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            line_id uuid NOT NULL REFERENCES customer_return_lines(id),
            source_movement_id uuid NOT NULL REFERENCES stock_movements(id),
            quantity numeric(12,3) NOT NULL CHECK (quantity > 0)
        );
        CREATE INDEX ix_return_stock_portions_source ON return_stock_portions(source_movement_id);
        CREATE INDEX ix_return_stock_portions_line ON return_stock_portions(line_id);
        CREATE TABLE return_stock_resolutions (
            portion_id uuid PRIMARY KEY REFERENCES return_stock_portions(id),
            actor_id uuid NOT NULL REFERENCES users(id),
            action varchar(24) NOT NULL CHECK (action IN ('dispose','supplier_return')),
            reason varchar(400) NOT NULL,
            reference_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE supplier_credit_notes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            purchase_id uuid NOT NULL REFERENCES purchases(id),
            supplier_id uuid NOT NULL REFERENCES suppliers(id),
            shipment_id uuid NOT NULL UNIQUE,
            reference varchar(120) NOT NULL,
            reason varchar(400) NOT NULL,
            amount numeric(14,2) NOT NULL CHECK (amount > 0),
            actor_id uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX uq_supplier_credit_notes_reference ON supplier_credit_notes
            (supplier_id, lower(btrim(reference)));
        CREATE INDEX ix_supplier_credit_notes_purchase ON supplier_credit_notes(purchase_id);
        ALTER TABLE supplier_ledger ADD COLUMN credit_note_id uuid
            REFERENCES supplier_credit_notes(id);
        ALTER TABLE supplier_ledger DROP CONSTRAINT supplier_ledger_check;
        ALTER TABLE supplier_ledger ADD CONSTRAINT supplier_ledger_check CHECK (
            (credit_note_id IS NULL AND
                ((kind IN ('receipt','opening') AND amount > 0 AND method IS NULL)
                OR (kind = 'reversal' AND amount < 0 AND method IS NULL)
                OR (kind = 'payment' AND amount < 0 AND method IS NOT NULL
                    AND method IN ('cash','bkash','nagad','bank'))))
            OR (credit_note_id IS NOT NULL AND
                ((kind IN ('credit','credit_application') AND amount < 0 AND method IS NULL)
                OR (kind = 'credit_offset' AND amount > 0 AND method IS NULL)
                OR (kind = 'refund' AND amount > 0 AND method IS NOT NULL
                    AND method IN ('cash','bkash','nagad','bank') AND reference IS NOT NULL)))
        );
        CREATE INDEX ix_supplier_ledger_credit_note ON supplier_ledger(credit_note_id);
        CREATE UNIQUE INDEX uq_supplier_ledger_refund_reference ON supplier_ledger
            (supplier_id, method, lower(btrim(reference))) WHERE kind = 'refund';
        CREATE UNIQUE INDEX uq_supplier_ledger_credit_post ON supplier_ledger(credit_note_id)
            WHERE kind = 'credit';
        """)
    for table in (
        "customer_returns",
        "customer_return_lines",
        "customer_refund_settlements",
        "return_stock_portions",
        "return_stock_resolutions",
        "supplier_credit_notes",
    ):
        op.execute(
            f"CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION shopflow_reject_ledger_mutation()"
        )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup to roll back posted returns and supplier credits")

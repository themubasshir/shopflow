"""Capture medicine batch metadata when a batch is recorded on a sale line.

Revision ID: 2f374de4f27c
Revises: 6fd2b56f1403
"""

from alembic import op

revision = "2f374de4f27c"
down_revision = "6fd2b56f1403"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION shopflow_snapshot_receipt_batch() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE batch_details jsonb;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.batch_id IS NOT DISTINCT FROM OLD.batch_id THEN
                RETURN NEW;
            END IF;
            SELECT jsonb_build_object('batch', b.batch_number, 'expiry', b.expiry_date)
            INTO batch_details
            FROM medicine_batches b
            JOIN products p ON p.id = b.product_id AND p.is_medicine
            WHERE b.id = NEW.batch_id AND p.id = NEW.product_id;

            -- Preserve recorded labels when a related row is later deleted.
            IF batch_details IS NOT NULL THEN
                NEW.receipt_details = coalesce(NEW.receipt_details, '{}'::jsonb) || batch_details;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER snapshot_receipt_batch
        BEFORE INSERT OR UPDATE OF batch_id ON invoice_items
        FOR EACH ROW EXECUTE FUNCTION shopflow_snapshot_receipt_batch();
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER snapshot_receipt_batch ON invoice_items")
    op.execute("DROP FUNCTION shopflow_snapshot_receipt_batch()")

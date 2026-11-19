"""Persist identity and line snapshots for thermal receipts.

Revision ID: 6fd2b56f1403
Revises: c493c5806cb7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "6fd2b56f1403"
down_revision = "c493c5806cb7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("receipt_settings", JSONB()))
    op.add_column("invoices", sa.Column("receipt_identity", JSONB()))
    op.add_column("invoices", sa.Column("receipt_points_balance", sa.Integer()))
    op.add_column("invoice_items", sa.Column("receipt_details", JSONB()))
    op.create_index(
        "ix_loyalty_transactions_invoice_id_ledger_sequence",
        "loyalty_transactions",
        ["invoice_id", "ledger_sequence"],
    )

    # Shop branding and a linked batch are frozen as migration-time context.
    # Unrecorded historical names, units, mobile numbers and points stay unknown.
    op.execute("""
        UPDATE invoices AS bill
        SET receipt_identity = jsonb_build_object(
            'branding', jsonb_build_object(
                'shop_name_en', shop.name_en,
                'shop_name_bn', shop.name_bn,
                'address', left(shop.address, 400),
                'phone', shop.phone,
                'tax_registration', shop.vat_number
            ),
            'source', 'legacy_migration',
            'currency', shop.currency,
            'timezone', shop.timezone,
            'counter_code', coalesce(saved.response_body->>'counter_code', data.counter_code),
            'customer_name', saved.response_body->>'customer_name'
        ),
        receipt_points_balance = CASE
            WHEN jsonb_typeof(saved.response_body->'loyalty_points_balance') = 'number'
            THEN (saved.response_body->>'loyalty_points_balance')::integer
        END
        FROM (
            SELECT i.id, i.shop_id, i.idempotency_key, counter.code AS counter_code
            FROM invoices i JOIN counters counter ON counter.id = i.counter_id
            WHERE i.status IN ('finalized','voided','refunded')
        ) AS data
        JOIN shops shop ON shop.id = data.shop_id
        LEFT JOIN idempotency_records saved
            ON saved.shop_id = data.shop_id AND saved.idempotency_key = data.idempotency_key
        WHERE bill.id = data.id
        """)
    op.execute("""
        UPDATE invoice_items AS item
        SET receipt_details = jsonb_build_object(
            'batch', batch.batch_number,
            'expiry', batch.expiry_date
        )
        FROM medicine_batches batch
        JOIN products product ON product.id = batch.product_id AND product.is_medicine
        WHERE item.batch_id = batch.id AND item.product_id = product.id
        """)


def downgrade() -> None:
    op.drop_index("ix_loyalty_transactions_invoice_id_ledger_sequence", "loyalty_transactions")
    op.drop_column("invoice_items", "receipt_details")
    op.drop_column("invoices", "receipt_points_balance")
    op.drop_column("invoices", "receipt_identity")
    op.drop_column("shops", "receipt_settings")

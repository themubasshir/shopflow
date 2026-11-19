"""Customer loyalty redemption and receivables.

Revision ID: c493c5806cb7
Revises: 92eeb64fd2a9
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c493c5806cb7"
down_revision = "92eeb64fd2a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("loyalty_eligible", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("customers", sa.Column("name_bn", sa.String(160)))
    # Normalize recognized legacy formats. A collision aborts the migration so
    # an operator can reconcile the two records without merging their histories.
    op.execute(r"""
        WITH cleaned AS (
            SELECT id, regexp_replace(
                translate(phone, '০১২৩৪৫৬৭৮৯', '0123456789'), '[[:space:]().-]', '', 'g'
            ) AS mobile
            FROM customers WHERE phone IS NOT NULL
        )
        UPDATE customers AS c SET phone = '+880' || right(cleaned.mobile, 10)
        FROM cleaned
        WHERE c.id = cleaned.id AND cleaned.mobile ~ '^(0|[+]?880|00880)1[3-9][0-9]{8}$'
          AND c.phone <> '+880' || right(cleaned.mobile, 10)
        """)
    op.add_column("invoices", sa.Column("loyalty_rule_snapshot", postgresql.JSONB()))
    op.add_column("invoices", sa.Column("loyalty_earn_base", sa.Numeric(14, 2)))
    op.drop_constraint(op.f("ck_invoices_loyalty_discount_within_total"), "invoices", type_="check")
    op.create_check_constraint(
        op.f("ck_invoices_loyalty_discount_within_total"),
        "invoices",
        "loyalty_discount <= subtotal - discount_total + tax_total",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        op.f("ck_invoices_finalized_payment_totals"),
        "invoices",
        "status <> 'finalized' OR paid_total + due_total = total",
        postgresql_not_valid=True,
    )

    op.drop_constraint(
        op.f("ck_loyalty_transactions_signed_points_match_type"),
        "loyalty_transactions",
        type_="check",
    )
    op.execute("UPDATE loyalty_transactions SET points = -points WHERE transaction_type = 'redeem'")
    op.create_check_constraint(
        op.f("ck_loyalty_transactions_signed_points_match_type"),
        "loyalty_transactions",
        "(transaction_type = 'earn' AND points > 0) OR "
        "(transaction_type IN ('redeem','reverse','expire') AND points < 0) OR "
        "transaction_type = 'adjust'",
    )

    op.add_column(
        "loyalty_transactions", sa.Column("ledger_sequence", sa.BigInteger(), sa.Identity())
    )
    op.create_table(
        "customer_ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), unique=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(payment_id IS NULL AND amount > 0) OR (payment_id IS NOT NULL AND amount < 0)",
            name=op.f("ck_customer_ledger_entries_amount_matches_type"),
        ),
    )
    op.create_index(
        "ix_customer_ledger_entries_customer_id_id",
        "customer_ledger_entries",
        ["customer_id", "id"],
    )
    op.create_index(
        "uq_customer_ledger_entries_invoice_charge",
        "customer_ledger_entries",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NULL"),
    )
    # Previous invoices are kept as-is. Only an existing unpaid amount is
    # carried forward into the receivables ledger.
    op.execute("""
        INSERT INTO customer_ledger_entries (customer_id, invoice_id, amount, created_at)
        SELECT i.customer_id, i.id, i.due_total, coalesce(i.finalized_at, i.created_at)
        FROM invoices i JOIN customers c ON c.id = i.customer_id AND c.shop_id = i.shop_id
        WHERE i.status = 'finalized' AND i.due_total > 0
        ORDER BY coalesce(i.finalized_at, i.created_at), i.id
        """)
    op.execute("""
        CREATE FUNCTION shopflow_reject_ledger_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ShopFlow ledger rows are append-only' USING ERRCODE = '23514';
        END;
        $$
        """)
    for table in ("customer_ledger_entries", "loyalty_transactions"):
        op.execute(f"""
            CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION shopflow_reject_ledger_mutation()
            """)


def downgrade() -> None:
    # Previous software cannot represent Phase 2C sales. Refuse a lossy downgrade.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM invoices WHERE loyalty_rule_snapshot IS NOT NULL)
                OR EXISTS (SELECT 1 FROM customer_ledger_entries WHERE payment_id IS NOT NULL)
            THEN
                RAISE EXCEPTION 'Cannot downgrade with Phase 2C financial history';
            END IF;
        END;
        $$
        """)
    op.execute("DROP TRIGGER append_only ON loyalty_transactions")
    op.drop_column("loyalty_transactions", "ledger_sequence")
    op.drop_table("customer_ledger_entries")
    op.execute("DROP FUNCTION shopflow_reject_ledger_mutation()")
    op.drop_constraint(
        op.f("ck_loyalty_transactions_signed_points_match_type"),
        "loyalty_transactions",
        type_="check",
    )
    op.execute("UPDATE loyalty_transactions SET points = -points WHERE transaction_type = 'redeem'")
    op.create_check_constraint(
        op.f("ck_loyalty_transactions_signed_points_match_type"),
        "loyalty_transactions",
        "(transaction_type IN ('earn','redeem') AND points > 0) OR "
        "(transaction_type IN ('reverse','expire') AND points < 0) OR transaction_type = 'adjust'",
    )
    op.drop_constraint(op.f("ck_invoices_finalized_payment_totals"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_loyalty_discount_within_total"), "invoices", type_="check")
    op.create_check_constraint(
        op.f("ck_invoices_loyalty_discount_within_total"), "invoices", "loyalty_discount <= total"
    )
    op.drop_column("invoices", "loyalty_earn_base")
    op.drop_column("invoices", "loyalty_rule_snapshot")
    op.drop_column("customers", "name_bn")
    op.drop_column("products", "loyalty_eligible")

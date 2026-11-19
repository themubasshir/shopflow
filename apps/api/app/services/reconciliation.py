from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.reconciliation import FinanceReport, ReconciliationOut


def discrepancies(
    db: Session, shop_id: UUID, area: str | None, entity_id: UUID | None, limit: int, offset: int
) -> ReconciliationOut:
    # Compare independent sources in a single PostgreSQL statement and snapshot.
    sql = text("""
    WITH
        sales AS (
            SELECT * FROM invoices WHERE shop_id = :shop AND status = 'finalized'
        ),
        returns AS (
            SELECT r.* FROM customer_returns r JOIN sales i ON i.id = r.invoice_id
        ),
        products_scoped AS (SELECT * FROM products WHERE shop_id = :shop),
        batches AS (SELECT * FROM medicine_batches WHERE shop_id = :shop),
        moves AS NOT MATERIALIZED (SELECT * FROM stock_movements WHERE shop_id = :shop),
        lots AS NOT MATERIALIZED (
            SELECT l.* FROM stock_lots l JOIN products_scoped p ON p.id = l.product_id
        ),
        purchases_scoped AS (SELECT * FROM purchases WHERE shop_id = :shop),
        checks(area, entity_id, check_code, expected, actual) AS (
            SELECT 'invoice', i.id, 'collections', i.paid_total, coalesce((
                SELECT sum(p.amount) FROM payments p WHERE p.invoice_id = i.id AND p.method <> 'due'
            ), 0) FROM sales i
            UNION ALL
            SELECT 'invoice', i.id, 'sale_total', i.total,
                i.paid_total + i.due_total + i.return_due_total FROM sales i
            UNION ALL
            SELECT 'customer_due', i.id, 'invoice_due', i.due_total, coalesce((
                SELECT sum(e.amount) FROM customer_ledger_entries e
                WHERE e.invoice_id = i.id AND e.customer_id = i.customer_id
            ), 0) FROM sales i
            UNION ALL
            SELECT 'customer_due', i.id, 'return_credits', i.return_due_total, coalesce((
                SELECT sum(r.due_reduction) FROM returns r WHERE r.invoice_id = i.id
            ), 0) FROM sales i
            UNION ALL
            SELECT 'customer_due', r.id, 'return_statement', r.due_reduction, coalesce((
                SELECT -sum(e.amount) FROM customer_ledger_entries e
                JOIN sales i ON i.customer_id = e.customer_id AND i.id = e.invoice_id
                WHERE e.return_id = r.id AND i.id = r.invoice_id
            ), 0) FROM returns r
            UNION ALL
            SELECT 'refund', r.id, 'return_lines', r.amount, coalesce((
                SELECT sum(l.amount) FROM customer_return_lines l WHERE l.return_id = r.id
            ), 0) FROM returns r
            UNION ALL
            SELECT 'refund', i.id, 'above_collections', 0, greatest(coalesce((
                SELECT sum(r.refund_amount) FROM returns r WHERE r.invoice_id = i.id
            ), 0) - i.paid_total, 0) FROM sales i
            UNION ALL
            SELECT 'refund', s.return_id, 'settlement_identity', 1,
                   CASE WHEN s.method = r.refund_method AND s.shop_id = :shop
                        AND r.refund_amount > 0
                   THEN 1 ELSE 0 END
            FROM customer_refund_settlements s JOIN returns r ON r.id = s.return_id
            UNION ALL
            SELECT 'loyalty', a.id, 'account_balance', a.points_balance,
                a.opening_points + coalesce((
                SELECT sum(t.points) FROM loyalty_transactions t WHERE t.account_id = a.id
            ), 0) FROM loyalty_accounts a WHERE a.shop_id = :shop
            UNION ALL
            SELECT 'loyalty', r.id, 'earned_reversed', r.earned_reversed, coalesce((
                SELECT -sum(t.points) FROM loyalty_transactions t WHERE t.return_id = r.id
                AND t.invoice_id = r.invoice_id AND t.transaction_type = 'reverse'
            ), 0) FROM returns r
            UNION ALL
            SELECT 'loyalty', r.id, 'redeemed_restored', r.redeemed_restored, coalesce((
                SELECT sum(t.points) FROM loyalty_transactions t WHERE t.return_id = r.id
                AND t.invoice_id = r.invoice_id AND t.transaction_type = 'adjust'
            ), 0) FROM returns r
            UNION ALL
            SELECT 'supplier', p.id, 'purchase_balance',
                CASE WHEN p.status IN ('received','partially_received')
                THEN p.received_total - p.paid_total ELSE 0 END,
                coalesce((SELECT sum(l.amount) FROM supplier_ledger l WHERE
                    l.purchase_id = p.id AND l.supplier_id = p.supplier_id
                    AND l.kind IN ('receipt','opening','payment','reversal')), 0)
                FROM purchases_scoped p
            UNION ALL
            SELECT 'supplier', p.id, 'negative_payable', 0, least(coalesce((
                SELECT sum(l.amount) FROM supplier_ledger l WHERE l.purchase_id = p.id
                AND l.kind IN ('receipt','opening','payment','reversal','credit_application')
            ), 0), 0) FROM purchases_scoped p
            UNION ALL
            SELECT 'supplier', n.id, 'credit_note_amount', n.amount, coalesce((
                SELECT -sum(l.amount) FROM supplier_ledger l WHERE l.credit_note_id = n.id
                    AND l.kind = 'credit' AND l.supplier_id = n.supplier_id
            ), 0) FROM supplier_credit_notes n JOIN purchases_scoped p ON p.id = n.purchase_id
            UNION ALL
            SELECT 'supplier', n.id, 'credit_application_pair', 0, coalesce((
                SELECT sum(l.amount) FROM supplier_ledger l WHERE l.credit_note_id = n.id
                AND l.kind IN ('credit_offset','credit_application')
            ), 0) FROM supplier_credit_notes n JOIN purchases_scoped p ON p.id = n.purchase_id
            UNION ALL
            SELECT 'supplier', n.id, 'negative_receivable', 0, greatest(coalesce((
                SELECT sum(l.amount) FROM supplier_ledger l WHERE l.credit_note_id = n.id
                AND l.kind <> 'credit_application'
            ), 0), 0) FROM supplier_credit_notes n JOIN purchases_scoped p ON p.id = n.purchase_id
            UNION ALL
            SELECT 'product', p.id, 'physical_stock', p.stock_on_hand, coalesce((
                SELECT sum(m.quantity) FROM moves m WHERE m.product_id = p.id
            ), 0) FROM products_scoped p
            UNION ALL
            SELECT 'product', p.id, 'held_stock', p.held_quantity, coalesce((
                SELECT sum(m.quantity) FROM moves m WHERE m.product_id = p.id AND m.held
            ), 0) FROM products_scoped p
            UNION ALL
            SELECT 'batch', b.id, 'batch_stock', b.quantity_on_hand, coalesce((
                SELECT sum(m.quantity) FROM moves m WHERE m.batch_id = b.id
            ), 0) FROM batches b
            UNION ALL
            SELECT 'batch', b.id, 'batch_held', b.held_quantity, coalesce((
                SELECT sum(m.quantity) FROM moves m WHERE m.batch_id = b.id AND m.held
            ), 0) FROM batches b
            UNION ALL
            SELECT 'batch', p.id, 'medicine_product_sum', p.stock_on_hand, coalesce((
                SELECT sum(b.quantity_on_hand) FROM batches b WHERE b.product_id = p.id
            ), 0) FROM products_scoped p WHERE p.is_medicine
            UNION ALL
            SELECT 'allocation', a.id, 'sale_batch_allocation', a.quantity, coalesce((
                SELECT -sum(m.quantity) FROM moves m WHERE m.batch_id = a.batch_id
                AND m.movement_type = 'sale' AND m.reference_type = 'invoice'
                AND m.reference_id = i.invoice_id AND (
                    m.invoice_item_id = i.id OR (m.invoice_item_id IS NULL AND NOT EXISTS (
                        SELECT 1 FROM invoice_items sibling WHERE sibling.invoice_id = i.invoice_id
                        AND sibling.product_id = i.product_id AND sibling.id <> i.id
                    ))
                )
            ), 0)
            FROM invoice_batch_allocations a JOIN invoice_items i ON i.id = a.invoice_item_id
            JOIN sales s ON s.id = i.invoice_id
            WHERE i.receipt_details ? 'base_quantity' OR EXISTS (
                SELECT 1 FROM moves m WHERE m.reference_id = i.invoice_id
                AND m.reference_type = 'invoice' AND m.batch_id = a.batch_id
                AND (m.invoice_item_id IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM invoice_items sibling WHERE sibling.invoice_id = i.invoice_id
                    AND sibling.product_id = i.product_id AND sibling.id <> i.id
                ))
            )
            UNION ALL
            SELECT 'allocation', m.id, 'returned_above_sold', 0, greatest(coalesce((
                SELECT sum(p.quantity) FROM return_stock_portions p
                WHERE p.source_movement_id = m.id
            ), 0) + m.quantity, 0) FROM moves m
              WHERE m.movement_type = 'sale' AND m.quantity < 0
            UNION ALL
            SELECT 'allocation', l.id, 'return_stock_links', l.quantity,
                coalesce(sum(p.quantity), 0)
            FROM customer_return_lines l JOIN returns r ON r.id = l.return_id
              JOIN return_stock_portions p ON p.line_id = l.id GROUP BY l.id
            UNION ALL
            SELECT 'lot', l.id, 'lot_units', l.quantity_remaining, coalesce((
                SELECT sum(m.quantity) FROM moves m WHERE m.stock_lot_id = l.id
            ), 0) FROM lots l
            UNION ALL
            SELECT 'lot', l.id, 'lot_held', l.held_quantity, coalesce((
                SELECT sum(m.quantity) FROM moves m WHERE m.stock_lot_id = l.id AND m.held
            ), 0) FROM lots l
            UNION ALL
            SELECT 'valuation', p.id, 'lot_units_above_physical', 0, greatest(coalesce((
                SELECT sum(l.quantity_remaining) FROM lots l WHERE l.product_id = p.id
            ), 0) - p.stock_on_hand, 0) FROM products_scoped p
            UNION ALL
            SELECT 'valuation', p.id, 'cost_value',
              round(coalesce((SELECT sum(l.cost_amount * l.quantity_remaining / l.quantity_received)
                               FROM lots l WHERE l.product_id = p.id), 0), 2),
              round(coalesce((SELECT sum(l.cost_amount * m.quantity / l.quantity_received)
                               FROM moves m JOIN lots l ON l.id = m.stock_lot_id
                               WHERE l.product_id = p.id), 0), 2)
              FROM products_scoped p
        ),
        differences AS (
            SELECT * FROM checks WHERE actual <> expected
             AND (CAST(:area AS text) IS NULL OR area = :area)
             AND (CAST(:id AS uuid) IS NULL OR entity_id = :id)
        )
        SELECT (SELECT count(*) FROM differences) AS total,
               coalesce((
                   SELECT jsonb_agg(to_jsonb(page) ORDER BY page.area, page.entity_id, page."check")
                   FROM (
                       SELECT area, entity_id, check_code AS "check", expected::text, actual::text
                       FROM differences ORDER BY area, entity_id, check_code
                       LIMIT :limit OFFSET :offset
                   ) page
               ), '[]') AS items
    """)
    row = db.execute(
        sql, {"shop": shop_id, "area": area, "id": entity_id, "limit": limit, "offset": offset}
    ).one()
    return ReconciliationOut(total=row.total, items=row.items, limit=limit, offset=offset)


def finance_report(db: Session, shop_id: UUID, start: date, end: date) -> FinanceReport:
    sql = text("""
        WITH local_period AS (
            SELECT timezone(timezone, CAST(CAST(:start AS date) AS timestamp)) AS starts,
                   timezone(timezone, CAST(CAST(:end AS date) + 1 AS timestamp)) AS stops
            FROM shops WHERE id = :shop
        ),
        invoices_scoped AS (SELECT * FROM invoices WHERE shop_id = :shop AND status = 'finalized'),
        sales AS (
            SELECT coalesce(sum(subtotal),0) AS gross_sales,
                   coalesce(sum(discount_total + loyalty_discount),0) AS discounts,
                   coalesce(sum(total),0) AS sales
            FROM invoices_scoped, local_period WHERE finalized_at >= starts AND finalized_at < stops
        ),
        return_events AS (
            SELECT r.amount, r.created_at, r.refund_amount,
                   CASE WHEN r.refund_method = 'cash' THEN r.created_at ELSE s.created_at END
                       AS refund_date
            FROM customer_returns r JOIN invoices_scoped i ON i.id = r.invoice_id
            LEFT JOIN customer_refund_settlements s ON s.return_id = r.id
        ),
        returns AS (
            SELECT coalesce(sum(amount) FILTER (
                       WHERE created_at >= starts AND created_at < stops
                   ),0) AS customer_returns,
                   coalesce(sum(refund_amount) FILTER (
                       WHERE refund_date >= starts AND refund_date < stops
                   ),0) AS refunds,
                   coalesce(sum(refund_amount) FILTER (WHERE refund_date IS NULL),0)
                       AS pending_refunds
            FROM return_events CROSS JOIN local_period
        ),
        collections AS (
            SELECT coalesce(sum(p.amount),0) AS collections FROM payments p
              JOIN invoices_scoped i ON i.id = p.invoice_id CROSS JOIN local_period
              WHERE p.method <> 'due' AND p.paid_at >= starts AND p.paid_at < stops
        ),
        due AS (SELECT coalesce(sum(due_total),0) AS outstanding_dues FROM invoices_scoped),
        supplier AS (
            SELECT coalesce(sum(l.amount) FILTER (
                       WHERE l.kind IN ('receipt','opening','payment','reversal',
                                        'credit_application')
                   ),0) AS supplier_payables,
                   coalesce(-sum(l.amount) FILTER (
                       WHERE l.kind = 'credit' AND l.created_at >= starts AND l.created_at < stops
                   ),0) AS supplier_credits,
                   coalesce(-sum(l.amount) FILTER (
                       WHERE l.kind IN ('credit','credit_offset','refund')
                   ),0) AS supplier_receivables,
                   coalesce(sum(l.amount) FILTER (
                       WHERE l.kind = 'refund' AND l.created_at >= starts AND l.created_at < stops
                   ),0) AS supplier_refunds
            FROM supplier_ledger l JOIN suppliers s ON s.id = l.supplier_id CROSS JOIN local_period
            WHERE s.shop_id = :shop
        ),
        loyalty AS (
            SELECT coalesce(sum(t.points) FILTER (WHERE t.transaction_type = 'earn'),0)
                      AS loyalty_issued,
                   coalesce(-sum(t.points) FILTER (WHERE t.transaction_type = 'redeem'),0)
                      AS loyalty_redeemed,
                   coalesce(-sum(t.points) FILTER (
                       WHERE t.transaction_type = 'reverse' AND t.return_id IS NOT NULL
                   ),0) AS loyalty_reversed,
                   coalesce(sum(t.points) FILTER (
                       WHERE t.transaction_type = 'adjust' AND t.return_id IS NOT NULL
                   ),0) AS loyalty_restored
            FROM loyalty_transactions t JOIN loyalty_accounts a ON a.id = t.account_id
             CROSS JOIN local_period
            WHERE a.shop_id = :shop AND t.created_at >= starts AND t.created_at < stops
        )
        SELECT gross_sales, discounts, customer_returns, sales - customer_returns AS net_sales,
               collections, refunds, pending_refunds, outstanding_dues,
               supplier_payables, supplier_credits, supplier_receivables, supplier_refunds,
               loyalty_issued, loyalty_redeemed, loyalty_reversed, loyalty_restored
        FROM sales, returns, collections, due, supplier, loyalty
    """)
    row = db.execute(sql, {"shop": shop_id, "start": start, "end": end}).mappings().one()
    return FinanceReport(start=start, end=end, **row)

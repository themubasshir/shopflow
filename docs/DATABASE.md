# ShopFlow database schema

`shopflow_dev` on local PostgreSQL 17 · owner/role `shopflow_app` · all IDs
`UUID` (`gen_random_uuid()`) · money `NUMERIC(14,2)` · quantity `NUMERIC(12,3)`
· loyalty points `INTEGER`.

## Entity map

```
shops ─┬─ counters (3 billing counters)
       ├─ roles ── users (manager, cashier)
       ├─ categories ── products ─┬─ product_units (sellable units + price)
       │                        ├─ medicine_details (generic, brand, Rx, MRP…)
       │                        └─ medicine_batches ─┐
       │                                             ├─ batch/expiry/FEFO
       ├─ suppliers ── purchases ── purchase_items ──┘
       ├─ customers ─── loyalty_accounts ─┬─ loyalty_transactions
       │                                 └─ loyalty_redemptions ── invoice
       ├─ loyalty_rules (1 active per shop)
       ├─ invoices ─── invoice_items ─┬─ payments (cash/bkash/nagad/card/due)
       │                              └─ stock_movements (signed qty ledger)
       ├─ stock_movements
       ├─ invoice_counters    (per-shop daily INV-YYMMDD-NNNN sequence)
       ├─ audit_logs          (who/what/when for sensitive ops)
       └─ idempotency_records (request hash per Idempotency-Key)
```

## Key constraints

* `products`: `stock_on_hand >= 0`, `low_stock_threshold >= 0`, unique
  `shop_id + sku` and `shop_id + barcode`, GIN index on `search_aliases`.
* `product_units`: partial unique `one base unit per product`,
  `conversion_factor > 0`.
* `medicine_batches`: unique `(product_id, batch_number, expiry_date)`,
  `quantity_on_hand >= 0`.
* `invoices`: status CHECK, totals >= 0, `loyalty_discount <= total`,
  unique `shop_id + invoice_number`, unique `shop_id + idempotency_key`.
* `invoice_counters`: unique `(shop_id, counter_date)`, `last_seq >= 0`;
  the row is locked `FOR UPDATE` to hand out each day's invoice numbers.
* `loyalty_accounts`: `points_balance >= 0`,
  `lifetime_earned - lifetime_redeemed = points_balance`.
* `loyalty_redemptions`: `points_redeemed % 100 = 0`, one redemption per
  invoice (`invoice_id` unique), status applied/reversed.
* `loyalty_rules`: partial unique index = **one active rule per shop**.
* `loyalty_transactions`: signed-points CHECK matching type, unique
  `(account_id, invoice_id, transaction_type)`.
* `payments`: `amount > 0`, method CHECK.
* `stock_movements`: `quantity <> 0`, type CHECK, `reference_type +
  reference_id` index.
* Every table has `created_at` + `updated_at` (timestamps) and consistent
  `ix_`, `uq_`, `ck_`, `fk_`, `pk_` naming via SQLAlchemy naming convention.

## Loyalty rule (implemented + unit tested)

```
earn  = floor(eligible_amount / 100) points          (category-gated)
unlock: points_balance >= 300
redeem: multiples of 100 pts, 100 pts = BDT 100 off,
        capped by min(balance, floor(total / 100) * 100)
        → never exceeds the invoice total
no same-invoice earn-and-spend, no expiry in v1,
returns write a negative `reverse` transaction.
```

Phase 2A implements only the **earn** half of this rule on a real bill; the
unlock/redeem legs stay in `services/loyalty.py` for the redemption phase.

## Invoice numbering

```sql
invoice_counters (shop_id, counter_date 'YYMMDD', last_seq)
  → INV-<counter_date>-<last_seq:04d>       e.g. INV-261118-0005
```

`finalize_invoice` selects the row for today `FOR UPDATE`, so concurrent bills
serialize on it instead of racing to pick the same number. A day with no row
starts at 1; the sequence is seeded from the highest existing number for that
date, so applying the migration to a populated DB never hands out a duplicate.

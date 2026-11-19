# Phase 2F-H reconciliation audit

## Summary

The shop-wide reconciliation report showed 520 discrepancies in the shared
`shopflow_test` database when the Phase 2F screenshots were captured. The audit
traced every discrepancy to two test-fixture defects and one legacy-data policy
already supported by the product. No business record, invoice, payment, return,
loyalty entry, stock movement, or cost was altered to make a report green.

The defects were repaired at their source — the fixture helpers that seeded the
data — and a validation suite now fails if they reappear.

## Measured counts

The report grew after the screenshots because the same fixtures run on every
suite invocation. Reconstructing the ledger state at the screenshot timestamp
reproduces exactly 520; the current total was 706.

| Area | Check | Count at audit |
|---|---|---|
| product | `physical_stock` | 669 |
| batch | `batch_stock` | 30 |
| loyalty | `account_balance` | 7 |
| **Total** | | **706** |

Every invoice, customer-due, refund, supplier, allocation, lot, and valuation
check reported zero discrepancies throughout. Collections, dues, refund
settlements, supplier payables, credit pairs, batch allocations, and cost lots
all reconciled unaided, which is why the audit could rule out a defect in the
posting services.

## Root cause

All three categories share one cause: a fixture wrote a **projection** column
directly and never appended the **ledger** row that justifies it. The
reconciliation query compares two independent sources, so a projection-only
write is indistinguishable from real drift.

| Fixture | Defect | Discrepancies |
|---|---|---|
| `test_billing.py` `make_product` | `stock_on_hand=stock` with no opening movement | 369 products (`T-`) |
| `test_receipts.py` `catalog` | `stock_on_hand=30` and `MedicineBatch(quantity_on_hand=30)` with no movements | 36 products, 27 batches (`R-`) |
| `test_receipts.py` loyalty line | `points_balance=400` with `opening_points=0` and no transaction | 5 loyalty accounts |
| `verify_receipts.py` `fixtures` | 82 products with `stock_on_hand` set directly; loyalty account at 400 with no opening | 246 products, 3 batches, 2 loyalty accounts |
| `test_purchasing.py` `setup` | Correct: `stock_on_hand=0`, stock arrives through real intake | 0 |

The `R-` batch rows in the 30-row `batch_stock` count come from the same
`catalog` fixture: the batch carried stock with no opening movement, and once a
sale consumed two units the projection and the ledger diverged. The
`batch allocations` rows are a symptom of the missing opening rather than a
second defect — the allocation itself was recorded correctly.

`test_purchasing.py` and `verify_purchasing.py` were already correct, and both
confirm the intended pattern: seed an empty projection and let the real service
paths create the stock.

## Repair

A new `apps/api/tests/fixtures.py` provides the two helpers that make fixture
intent match the ledger model.

`post_opening_stock` appends `opening` movements until each projection equals
its recorded ledger. It posts **batch movements first** and then measures the
remaining product shortfall, because batch movements also carry `product_id` —
posting both blindly would double-count the product. This is the same order used
by migration `7f58b276a2e0` and by `database/seeds/seed.py`.

`set_opening_points` sets `opening_points` alongside the balance, matching the
backfill in migration `de452fa8b713`. The reconciliation check is
`points_balance = opening_points + Σ transactions`; a bare projection write is
exactly the legacy shape the report is designed to surface.

Applied to `test_billing.py` `make_product`, `test_receipts.py` `catalog` and
loyalty grant, and `scripts/verify_receipts.py`. `scripts/verify_receipts.py`
reuses the pytest helpers through a single `sys.path` entry rather than
duplicating the logic, so the two entry points cannot drift apart again.

Three existing assertions had encoded the fixture's incomplete ledger and were
narrowed to their actual intent: two counted *all* movements for a product when
they meant "no **sale** movement was written", and one asserted
`points_balance == Σ transactions` without the opening balance term.

## Legacy-data policy

Opening stock is posted **without** a `StockLot`, so `cost_amount` stays `NULL`.
Fixture cost provenance is unknown, and inventing it would fabricate valuation
from nothing. The product already models this: `stock_value` reports it as
`unvalued_quantity` instead of silently valuing it at zero. A test pins that
behaviour so the transparency cannot regress.

No backfill was run against accumulated test data, no migration was added, and
`shopflow_dev` was not touched. The existing `de452fa8b713` and
`7f58b276a2e0` opening-reconciliation patterns were sufficient.

## Validation

`apps/api/tests/test_reconciliation.py` builds a fresh, isolated shop per test
and drives it only through the public services, so it cannot be masked by
fixture residue elsewhere in the shared database.

| Test | Guarantee |
|---|---|
| `test_clean_fixture_shop_has_zero_discrepancies` | A correctly seeded shop reports zero |
| `test_corrupted_product_projection_is_flagged` | A projection-only stock write surfaces `product/physical_stock` |
| `test_corrupted_batch_projection_is_flagged` | Batch drift surfaces `batch/batch_stock` |
| `test_corrupted_loyalty_balance_is_flagged` | A balance bump without opening or ledger surfaces `loyalty/account_balance` |
| `test_full_business_cycle_reconciles_to_zero` | Purchase → intake → sale with redemption → partial return → supplier shipment → credit → apply reconciles to zero |
| `test_unvalued_opening_inventory_stays_visible` | Opening stock reports as unvalued, not as zero value |
| `test_reconciliation_query_is_read_only` | A corrupted projection is observed but never repaired |

`test_reconciliation_reports_without_repairing_projection` in `test_returns.py`
already covered the read-only guarantee for the product area; the new test
extends it to ledger-row immutability during a shop-wide run.

## Fresh-database verification

The repairs were validated by rebuilding `shopflow_test` from zero rather than
by trusting the accumulated database. The database was created empty by the
operator (the application role cannot `CREATE DATABASE`), owned by
`shopflow_app`, UTF-8, and migrated with `alembic upgrade head` to
`f8bcc76b2f43`.

| Step | Result |
|---|---|
| Reconciliation after `alembic upgrade head` + `seed.py`, before any test | 0 |
| Full suite on that fresh database | 147 passed |
| Reconciliation after the full suite, all shops | 0 (9 shops: 1 demo + 8 isolated) |

The zero is not vacuous: the run left 41 `T-` products, 6 `R-` products, 73
`opening` movements, 163 `sale` movements, 12 `damage`, 28 `purchase`, 19
`return`, and 27 loyalty accounts holding 4,678 points. Direct SQL confirms
`products.stock_on_hand` vs Σ movements, `medicine_batches.quantity_on_hand` vs
Σ movements, and `points_balance` vs `opening_points + Σ transactions` are each
exactly zero rows of drift.

As a negative control, drift was injected inside a transaction that was then
rolled back: `+3` on a real fixture product surfaced `product/physical_stock`,
and `+5` on a real loyalty account surfaced `loyalty/account_balance`, with the
shop returning to 0 after rollback. The query is therefore still live and is
genuinely reading the repaired rows.

`shopflow_dev` was never migrated or written: it remains at `92eeb64fd2a9`.
Both isolation guards were exercised and refuse a non-test target — the pytest
`conftest.py` raises during collection, and `scripts/reset_test_db.py` prints
`REFUSING:` before connecting.

## Ruff findings

`ruff check .` reported 17 pre-existing findings confined to `alembic/env.py`
and three migrations (`6a5680c635ea`, `92eeb64fd2a9`, `b5667e724f7f`): 4 ×
`I001` and 13 × `E501`. These are historical formatting in generated scaffold
files, not defects; `alembic/env.py` also carries a deliberate `# noqa: F401` on
its model-registration import, which was preserved.

All 17 were fixed, and the fixes were proven inert rather than assumed:

- **Import sorting (4).** Reordering only; `env.py`'s `noqa` comment moved with
  its import and still suppresses the same line.
- **Long lines (13).** Split into implicitly concatenated string literals and
  multi-line `sa.Column` / `sa.ForeignKeyConstraint` calls. The resulting SQL
  text is the same string.

Two independent proofs were run against a pristine baseline captured before any
edit:

1. `alembic upgrade head --sql` produces **994 non-empty lines that are
   byte-identical** before and after the changes.
2. All migrations applied from scratch into a throwaway *schema* inside
   `shopflow_test` (never a database) produce a schema **identical to the live
   one: 797 objects, 0 differences** — columns, constraints, indexes and
   triggers, including the `op.execute` data bodies. The scratch schema was
   dropped afterwards.

`app/api/v1/employees.py` was reformatted (one collapsed expression) because it
sits inside the documented `ruff format --check` scope and was the only file
keeping that gate red. It is behavior-neutral and the suite was re-run after it.

Two files outside the documented gate, `scripts/verify_returns.py` and
`database/seeds/seed.py`, also want reformatting. Those reformats were applied,
verified green, then reverted: neither file is functionally part of this phase,
and absorbing unrelated churn would obscure the audit diff. They remain
pre-existing drift and are reported rather than silently bundled.

## Gates

| Check | Result |
|---|---|
| `ruff check .` (whole repo) | clean — 0 findings, was 17 |
| `ruff check app tests database/seeds` | clean |
| `ruff format --check app tests database/seeds` | clean (68 files) |
| `pytest` on fresh `shopflow_test` | 147 passed (140 before, +7 new) |
| `alembic upgrade head` offline DDL | byte-identical (994 lines) |
| Scratch-schema rebuild | identical (797/797 objects) |
| `npm run typecheck` | passed |
| `npm run lint` | passed (`--max-warnings=0`) |
| `npm run build` | passed |

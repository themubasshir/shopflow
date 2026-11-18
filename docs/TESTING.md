# ShopFlow QA summary

## Backend

| Check | Result |
|---|---|
| `ruff check app tests database\seeds` | ✅ clean |
| `ruff format --check` | ✅ 33 files formatted |
| `pytest` | ✅ **57 passed** |
| `alembic upgrade head` | ✅ applied `b5667e724f7f` |
| `alembic current` | `b5667e724f7f (head)` |

Test coverage: loyalty earn/redeem/unlock/reverse edge cases (parametrised),
JWT create/decode/tamper, argon2 hash+verify+timing-safe unknown-user,
login 401, health, dashboard shape, product pagination, OpenAPI served,
plus the Phase 2A billing suite.

### Billing suite (`tests/test_billing.py`, 18 cases)

| # | Case |
|---|---|
| 1 | `test_successful_invoice_creation` |
| 2 | `test_stock_deduction` |
| 3 | `test_insufficient_stock` |
| 4 | `test_concurrent_last_unit` — real-PG concurrency: one bill wins the last unit |
| 5 | `test_duplicate_idempotency_replays` |
| 6 | `test_same_key_different_payload_rejected` |
| 7 | `test_rollback_on_failure` |
| 8 | `test_invalid_product_rejected` |
| 9 | `test_unauthorized_cashier_cannot_bill` |
| 10 | `test_client_price_never_trusted` |
| 11 | `test_fractional_quantity_validated` |
| 12 | `test_discount_validation` |
| 13 | `test_loyalty_earned_for_named_customer` |
| 14 | `test_walkin_customer_earns_nothing` |
| 15 | `test_loyalty_ledger_consistency` |
| 16 | `test_bangla_and_english_error_messages` |
| 17 | `test_non_eligible_category_earns_nothing` |
| 18 | `test_split_payment_must_equal_total` |

The concurrency case (#4) uses a real PostgreSQL connection on a second
thread/session — it exercises the `SELECT ... FOR UPDATE` locks, not a mock.

## Frontend

| Check | Result |
|---|---|
| `tsc --noEmit` | ✅ clean |
| `eslint . --max-warnings=0` | ✅ 0 warnings |
| `next build` | ✅ compiled, 18 pages incl. `/api/auth` + `/api/billing/invoices` |

## Integration

* `GET /api/v1/health` → `{"status":"ok","database":"ok"}`
* `GET /api/v1/reports/dashboard` → seeded totals: today BDT 8,125, 8 invoices, 3 counters
* Playwright screenshots at 375/768/1024/1440 in `docs/screenshots/` — 16 captures, all `OK`
* Phase 2A browser evidence in `docs/screenshots/`:
  * `phase2a-billing-success.png` — completed sale, invoice number, ৳ total, +1 pt, new balance
  * `phase2a-billing-rejected.png` — server rejected an oversell; the cart shows
    "Not enough stock for this item"; page has no horizontal overflow (414 = 414)

### HTTP verification of `POST /invoices`

| Request | Status | `code` |
|---|---|---|
| create with Idempotency-Key | 201 | — |
| replay same key + payload | 200 | — (`idempotent_replay: true`) |
| same key, different payload | 409 | `idempotency_conflict` |
| quantity beyond stock | 409 | `insufficient_stock` |
| missing Idempotency-Key | 422 | `validation_error` |
| no `Authorization` header | 401 | `unauthenticated` |

## Known limitations

* Demo-only data (`is_demo` flag + badge).
* Loyalty is earn-only in Phase 2A; redemption lands in the next phase.
* Payments are recorded manually (cash/bKash/Nagad); no gateway integration.
* Port 8001 used because 8000 was occupied by another local process.
* `alembic` post-write hook (`ruff format`) emits a harmless entry-point warning on Windows.

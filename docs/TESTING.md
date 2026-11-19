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

## Phase 2B — auth, RBAC & counter management

| Check | Result |
|---|---|
| `ruff check app tests database\seeds` | clean |
| `pytest` | **75 passed** (57 prior + 18 new authz/auth cases) |
| `alembic upgrade head` | `92eeb64fd2a9` (user_counters + auth_sessions) |
| dedicated `shopflow_test` | all tests run against it, never `shopflow_dev` |

### Test DB isolation

* `tests/conftest.py` builds `TestingSessionLocal` bound to `shopflow_test`,
  swaps `app.db.session.SessionLocal`/`engine` **and** the FastAPI `get_db`
  dependency before the app imports, and hard-aborts if the URL is not a
  `*test*` database (it refuses `shopflow_dev`/`prod` anywhere in the URL).
* `scripts/reset_test_db.py` is the safeguarded dev-only reset utility — it
  drops/recreates only a `*test*` database and refuses any non-test target,
  replacing the ad-hoc Phase 2A cleanup script.

### Authorization matrix tests (`tests/test_rbac.py`, 18 cases)

login success / wrong-password / me reflects role / owner unrestricted /
logout invalidates / disable kills live session / disabled cannot login /
concurrent sessions independent / rate-limit 429 / cashier→employees 403 /
cashier→counters 403 / manager→employees 403 / manager→counters 403 /
owner→employees 200 / cashier unassigned-counter 403 / cashier history
scoped / manager full history / change-password revokes other sessions.

### Verified over real HTTP (:8001)

| Request | Result |
|---|---|
| `GET /auth/me` cashier1 | `assigned_counter_ids` = C1 only |
| cashier → `GET /employees` / `/manage/counters` | `403 forbidden` |
| manager → `GET /employees` / `PATCH counter` | `403 forbidden` |
| owner → `GET /employees` | `200`, no password hashes |
| cashier1 → `POST /invoices` @ C2 (unassigned) | `403 Not assigned to this counter` |
| cashier1 → `POST /invoices` @ C1 (assigned) | `201` invoice created |
| cashier1 → `GET /invoices` | only `C1` history |
| manager → `GET /invoices` | `C1`,`C2`,`C3` |
| `POST /auth/logout` then `/me` | `401 unauthenticated` |
| 6 bad logins | `429 rate_limited` |

### Verified in the browser (Playwright, :3000)

| Flow | Result |
|---|---|
| `/en/billing` unauthenticated | redirects to `/en/login` |
| bad credentials | localized `Wrong email or password`, stays on `/login` |
| owner login | → `/en` dashboard, Employees + Counters in nav |
| cashier1 login | → `/en`, nav hides Reports/Employees/Counters |
| cashier → `/en/employees` | redirected away (permission gate) |
| `/bn/login` | fully localized Bangla form |
| mobile 375px login | renders correctly |

Screenshots: `docs/screenshots/p2b-*.png` (login EN/BN, owner dashboard +
employees + counters, cashier-scoped dashboard, mobile login).

## Phase 2B limitations at release

* Demo-only data (`is_demo` flag + badge).
* Loyalty is earn-only in Phase 2A; redemption lands in the next phase.
* Payments are recorded manually (cash/bKash/Nagad); no gateway integration.
* Port 8001 used because 8000 was occupied by another local process.
* `alembic` post-write hook (`ruff format`) emits a harmless entry-point warning on Windows.

## Phase 2C — customer accounts, loyalty and dues

| Check | Result |
|---|---|
| Alembic on `shopflow_test` | `c493c5806cb7` is head |
| Full pytest suite against PostgreSQL `shopflow_test` | 112 passed |
| Ruff lint and changed Python file formatting | Passed |
| `npm run typecheck`, `npm run lint`, `npm run build` | Passed |
| Playwright Chromium against the production build | Four workflows passed |
| Direct PostgreSQL reconciliation | Four browser accounts and invoices reconciled |

The API suite includes customer normalization and duplicates, tenant and permission checks, the 299/300-point boundary, step validation, product and category eligibility, distinct-counter redemption races, identical retries, rollback after database writes, full and partial payments, due-only invoices, concurrent collections, overpayment, credit-limit races, immutable ledger rows and existing billing and access regressions.

Chromium verified English and Bangla at 375 px and 1440 px. In each scenario it created and edited a customer, searched by mobile number, earned 300 points on a fully paid bill, redeemed 100 points on a second bill, took a ৳50 partial payment, collected the remaining ৳300 via Nagad, viewed the transaction histories and deactivated the account. Cross-origin and missing-Origin API writes were rejected. The pages had no horizontal overflow, and Chromium reported no duplicate React keys or hydration errors.

Independent database queries confirmed signed loyalty entries of `+300, -100, +3` and a final balance of 203 points. They also confirmed receivable entries of `+৳300, -৳300`, a settled ৳350 invoice and zero outstanding dues for each browser customer.

- [English desktop customer profile](screenshots/p2c-en-desktop-customer.png)
- [English mobile checkout receipt](screenshots/p2c-en-mobile-billing.png)
- [Bangla desktop points history](screenshots/p2c-bn-desktop-loyalty.png)
- [Bangla mobile account statement](screenshots/p2c-bn-mobile-statement.png)

See [Phase 2C](PHASE-2C.md) for limitations and business rules.

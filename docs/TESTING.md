# ShopFlow QA summary — Phase 1

## Backend

| Check | Result |
|---|---|
| `ruff check app tests database\seeds` | ✅ clean |
| `ruff format --check` | ✅ 31 files formatted |
| `pytest` | ✅ **35 passed** |
| `alembic upgrade head` | ✅ applied `6a5680c635ea` |
| `alembic history` | `base -> 6a5680c635ea (head)` |

Test coverage: loyalty earn/redeem/unlock/reverse edge cases (parametrised),
JWT create/decode/tamper, argon2 hash+verify+timing-safe unknown-user,
login 401, health, dashboard shape, product pagination, OpenAPI served.

## Frontend

| Check | Result |
|---|---|
| `tsc --noEmit` | ✅ clean |
| `eslint . --max-warnings=0` | ✅ 0 warnings |
| `next build` | ✅ 16 static + dynamic routes |

## Integration

* `GET /api/v1/health` → `{"status":"ok","database":"ok"}`
* `GET /api/v1/reports/dashboard` → seeded totals: today BDT 8,125, 8 invoices, 3 counters
* Playwright screenshots at 375/768/1024/1440 in `docs/screenshots/` — 16 captures, all `OK`

## Known limitations

* Demo-only data (`is_demo` flag + badge); no write APIs yet.
* Port 8001 used because 8000 was occupied by another local process.
* `alembic` post-write hook (`ruff format`) emits a harmless entry-point warning on Windows.

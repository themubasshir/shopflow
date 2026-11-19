# ShopFlow

Bilingual (English/Bangla) grocery & pharmacy management for a shop in
Bangladesh with three billing counters. Phase 1: project foundation,
database, loyalty rule engine, and the working dashboard. Phase 2C adds customer accounts, loyalty redemption, and বাকি খাতা (customer dues).

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 · TypeScript · App Router · Tailwind CSS 4 · next-intl · Recharts · Lucide |
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic 2 |
| Database | PostgreSQL 17 (`shopflow_dev`, role `shopflow_app`) |
| Contracts | OpenAPI → `openapi-typescript` in `packages/contracts` |

## Repo layout

```
apps/
  api/        FastAPI backend + Alembic migrations + pytest
  web/        Next.js frontend (App Router, [locale] segment)
packages/
  contracts/  Generated OpenAPI TypeScript types + contract README
database/
  seeds/      Idempotent development seed (47 demo invoices, 3 counters, …)
design-system/
  shopflow/   Persisted UI/UX design system (MASTER.md, tokens, overrides)
docs/         Architecture, schema, design-system, testing notes + screenshots
scripts/      dev.ps1 launcher, setup-db.ps1 bootstrap
```

## Quick start (Windows)

```powershell
# 1. Backend
cd apps\api
uv venv && uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# 2. Seed (idempotent) — in another terminal
cd D:\Projects\shopflow
$env:PYTHONPATH='apps\api'
apps\api\.venv\Scripts\python.exe database\seeds\seed.py

# 3. Frontend
cd apps\web
npm install
npm run dev   # http://localhost:3000 → redirects to /en
```

`.\scripts\dev.ps1` wraps the same two commands.

## Environment

* `apps/api/.env` — `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS` (see `.env.example`)
* `apps/web/.env.local` — `NEXT_PUBLIC_API_URL` (default `http://localhost:8001/api/v1`)

Ports: web **3000**, API **8001** (8000 was occupied on this machine).

## Staff logins (dev seed, password `ShopFlow#Dev123`)

| Email | Role | Counters |
|---|---|---|
| `owner@shopflow.dev` | OWNER — everything incl. employee/counter mgmt | all |
| `manager@shopflow.dev` | MANAGER — operations, no admin grants | all |
| `cashier1@shopflow.dev` | CASHIER — billing + lookup | C1 |
| `cashier2@shopflow.dev` | CASHIER — billing + lookup | C2 |

## Test database

Automated tests run against a dedicated **`shopflow_test`** database — never
`shopflow_dev`. Create + provision it once:

```powershell
cd apps\api
$env:PYTHONPATH='.'
$env:SHOPFLOW_TEST_DATABASE_URL='postgresql+psycopg://shopflow_app:<pw>@localhost:5432/shopflow_test'
$env:DATABASE_URL=$env:SHOPFLOW_TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe database\seeds\seed.py
```

`tests/conftest.py` swaps `SessionLocal` and the `get_db` dependency to the
test DB and aborts if the URL targets anything else. `scripts/reset_test_db.py`
requires an explicit test URL and resets only a PostgreSQL database named `shopflow_test`.

## Quality gates that pass

- `npm run typecheck`, `npm run lint`, `npm run build`
- `ruff check` + `ruff format` on `app`, `tests`, `database/seeds`
- `pytest` — 112 tests against PostgreSQL `shopflow_test`
- Alembic `c493c5806cb7` applied and verified on `shopflow_test`
- Playwright verified Phase 2C in English and Bangla at 375 and 1440 px. See [test results](docs/TESTING.md#phase-2c--customer-accounts-loyalty-and-dues).

## Demo vs real data

Demo fallback is off by default. Development and test can opt in with
`DEMO_MODE=true` for read-only access to a seeded demo shop. Customer accounts and
financial operations require a live session. Production web writes require
`SHOPFLOW_WEB_ORIGIN`. See [Phase 2C](docs/PHASE-2C.md).

# ShopFlow

Bilingual (English/Bangla) grocery & pharmacy management for a shop in
Bangladesh with three billing counters. Phase 1: project foundation,
database, loyalty rule engine, and the working dashboard.

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

## Quality gates that pass

- `npm run typecheck`, `npm run lint`, `npm run build`
- `ruff check` + `ruff format` on `app`, `tests`, `database/seeds`
- `pytest` — 35 tests (loyalty rules, auth/JWT, API shape)
- Alembic `upgrade head` on `shopflow_dev`
- Playwright screenshots at 375/768/1024/1440 in `docs/screenshots/`

## Demo vs real data

Everything you see in Phase 1 is labelled demo data (`is_demo` flag +
"Demo data" badge). No production billing, stock, or loyalty writes are
implemented yet.

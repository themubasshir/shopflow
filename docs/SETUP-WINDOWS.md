# ShopFlow setup — Windows

Prereqs (verified on this machine): Node 22.16, npm 10.9, Python 3.12.4,
PostgreSQL 17.5 (port 5432), git 2.51, uv 0.12.

## 1. Database (one-time, needs the postgres admin password)

```powershell
$env:PGPASSWORD='<postgres admin password>'
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -h 127.0.0.1 -p 5432 -U postgres -w -c `
  "CREATE ROLE shopflow_app LOGIN PASSWORD '<generated>'; CREATE DATABASE shopflow_dev OWNER shopflow_app;"
```

Then put the generated password in `apps/api/.env` (see `.env.example`).

## 2. Backend

```powershell
cd apps\api
uv venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Seed demo data (idempotent — safe to re-run):

```powershell
cd D:\Projects\shopflow
$env:PYTHONPATH='apps\api'
apps\api\.venv\Scripts\python.exe database\seeds\seed.py
```

Start the API:

```powershell
cd apps\api
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

## 3. Frontend

```powershell
cd apps\web
npm install
npm run dev
```

Open http://localhost:3000 → redirects to `/en`. The language toggle in the
header switches `/en` ↔ `/bn` without losing page state.

## Notes

* Port 8000 is occupied by another local process on this machine, so the
  API defaults to **8001**. Change `NEXT_PUBLIC_API_URL` if you move it.
* `npm` was run with `npm_config_cache` pointed at the repo (`.\.npm-cache`)
  because the default cache hit a permissions issue — safe to remove once
  your own cache is writable.

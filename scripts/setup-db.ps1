# One-time database bootstrap for a fresh developer machine.
# Requires the postgres superuser password for the local PG 17 instance.
# Usage:  $env:PGPASSWORD='...'; .\scripts\setup-db.ps1

$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
if (-not (Test-Path $psql)) { Write-Error "PostgreSQL 17 not found at $psql"; exit 1 }

& $psql -h 127.0.0.1 -p 5432 -U postgres -w -v ON_ERROR_STOP=1 -c @"
DO `$$`$$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shopflow_app') THEN
    CREATE ROLE shopflow_app LOGIN PASSWORD 'CHANGE_ME_GENERATED';
  END IF;
END`$$`$$;
"@

& $psql -h 127.0.0.1 -p 5432 -U postgres -w -v ON_ERROR_STOP=1 -c `
  "CREATE DATABASE shopflow_dev OWNER shopflow_app" 2>$null

Write-Host "Done. Update apps/api/.env with the shopflow_app password, then run:"
Write-Host "  cd apps\api; `$env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m alembic upgrade head"
Write-Host "  cd ..; `$env:PYTHONPATH='apps\api'; apps\api\.venv\Scripts\python.exe database\seeds\seed.py"

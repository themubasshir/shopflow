# ShopFlow Phase 1 dev launcher - Windows PowerShell
# Usage:  .\scripts\dev.ps1 [backend|frontend|both]

param([string]$Target = "both")

$root = Split-Path -Parent $PSScriptRoot

function Start-Backend {
    Write-Host "ShopFlow API on http://127.0.0.1:8001  (docs: /docs)" -ForegroundColor Green
    Push-Location "$root\apps\api"
    $env:PYTHONPATH = "."
    & .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
    Pop-Location
}

function Start-Frontend {
    Write-Host "ShopFlow web on http://localhost:3000" -ForegroundColor Green
    Push-Location "$root\apps\web"
    $env:npm_config_cache = "$root\.npm-cache"
    npm run dev
    Pop-Location
}

switch ($Target) {
    "backend"  { Start-Backend }
    "frontend" { Start-Frontend }
    default {
        $be = Start-Job -ScriptBlock ${function:Start-Backend}
        Start-Sleep -Seconds 2
        Start-Frontend
        Stop-Job $be
    }
}

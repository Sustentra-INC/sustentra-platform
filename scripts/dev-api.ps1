<#
.SYNOPSIS
  Run the Sustentra API locally (FastAPI with auto-reload) against Docker Postgres + Mailpit.

.EXAMPLE
  .\scripts\dev-api.ps1              # start db/mailpit if needed, migrate, run API on :8000
  .\scripts\dev-api.ps1 -Install     # also (re)install Python dependencies first
  .\scripts\dev-api.ps1 -SkipMigrate # don't run alembic
#>
param(
    [switch]$Install,
    [switch]$SkipMigrate,
    [int]$Port = 8000,
    [int]$DbPort = 5433
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "No .venv found - creating it with uv ..." -ForegroundColor Yellow
    uv venv .venv --python 3.12
    $Install = $true
}

if ($Install) {
    Write-Host "Installing backend dependencies ..." -ForegroundColor Cyan
    uv pip install --python $Python -r backend\requirements-dev.txt
}

# 1. Postgres + Mailpit in Docker (no-op if already running)
Write-Host "Starting db + mailpit (Docker) ..." -ForegroundColor Cyan
$env:POSTGRES_HOST_PORT = "$DbPort"
docker compose up -d db mailpit | Out-Null

Write-Host "Waiting for Postgres ..." -NoNewline
for ($i = 0; $i -lt 30; $i++) {
    docker compose exec -T db pg_isready -U sustentra_admin -d sustentra *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Write-Host "." -NoNewline; Start-Sleep -Seconds 1
}
Write-Host " ready"

# 2. Local settings (same names as prod; values are local-only)
$AdminUrl = "postgresql://sustentra_admin:local-admin-password@localhost:$DbPort/sustentra"
$AppUrl   = "postgresql://app_user:local-app-password@localhost:$DbPort/sustentra"
$env:ENVIRONMENT      = "local"
$env:GIT_SHA          = "local"
$env:ALLOWED_ORIGINS  = "http://localhost:3000,http://127.0.0.1:3000"
$env:APP_DATABASE_URL = $AppUrl
$env:OTP_HMAC_SECRET  = "local-otp-hmac-secret-not-for-prod"
$env:SES_FROM_ADDRESS = "no-reply@localhost"
$env:SMTP_HOST        = "localhost"
$env:SMTP_PORT        = "1025"
$env:PYTHONPATH       = $Root

# 3. Migrations run as the owner; the app itself connects as app_user (RLS enforced)
if (-not $SkipMigrate) {
    Write-Host "Applying migrations ..." -ForegroundColor Cyan
    $env:DATABASE_URL = $AdminUrl
    Push-Location backend
    & $Python -m alembic upgrade head
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "alembic upgrade failed" }
}
$env:DATABASE_URL = $AppUrl

# 4. Run the API
Write-Host ""
Write-Host "API      http://localhost:$Port/health" -ForegroundColor Green
Write-Host "API docs http://localhost:$Port/api/v1/docs" -ForegroundColor Green
Write-Host "Mailpit  http://localhost:8025" -ForegroundColor Green
Write-Host "Frontend: in another terminal -> cd frontend; npm run dev  (http://localhost:3000)"
Write-Host ""
& $Python -m uvicorn backend.app.main:app --reload --reload-dir backend --port $Port
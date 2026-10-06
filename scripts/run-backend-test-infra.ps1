<#
.SYNOPSIS
  Run TEST-001 backend infrastructure checks against an isolated disposable Postgres compose project.

.DESCRIPTION
  Creates a unique compose project and free DB port, migrates to head, verifies runtime app_user identity,
  runs backend DB tests in required-db mode, runs lint/type checks, optionally runs full backend coverage,
  then tears down only resources created by this run.

.EXAMPLE
  .\scripts\run-backend-test-infra.ps1

.EXAMPLE
  .\scripts\run-backend-test-infra.ps1 -SkipFullSuite
#>
[CmdletBinding()]
param(
    [switch]$SkipFullSuite
)

$originalLocation = Get-Location
$originalErrorActionPreference = $ErrorActionPreference
$hadNativeErrorPreference = $null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
$originalNativeErrorPreference = if ($hadNativeErrorPreference) { $PSNativeCommandUseErrorActionPreference } else { $null }

$managedEnvVars = @(
    "COMPOSE_PROJECT_NAME",
    "POSTGRES_HOST_PORT",
    "DATABASE_URL",
    "APP_DATABASE_URL",
    "TEST_DATABASE_URL",
    "TEST_APP_DATABASE_URL",
    "TEST_DB_REQUIRED",
    "TEST_DB_DISPOSABLE",
    "OTP_HMAC_SECRET",
    "PUBLIC_BASE_URL"
)

$envSnapshot = @{}
foreach ($name in $managedEnvVars) {
    $item = Get-Item "Env:$name" -ErrorAction SilentlyContinue
    $envSnapshot[$name] = [pscustomobject]@{
        Present = ($null -ne $item)
        Value = if ($item) { $item.Value } else { $null }
    }
}

function Restore-ManagedEnvironment {
    foreach ($name in $managedEnvVars) {
        $state = $envSnapshot[$name]
        if ($state.Present) {
            Set-Item "Env:$name" -Value $state.Value
        }
        else {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return $listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

function Invoke-Checked {
    param(
        [string]$Step,
        [scriptblock]$Action
    )

    Write-Host "==> $Step" -ForegroundColor Cyan
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Action
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Step (exit code $LASTEXITCODE)"
    }
}

$ErrorActionPreference = "Stop"
if ($hadNativeErrorPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$primaryFailure = $null
$cleanupFailure = $null
$startupAttempted = $false
$composeProject = $null
$composeFile = $null
$composeBaseArgs = @()

try {
    $Root = Split-Path -Parent $PSScriptRoot
    Set-Location $Root

    $Python = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        throw "Expected Python interpreter at $Python. Create the venv first."
    }

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $suffix = Get-Random -Minimum 1000 -Maximum 9999
    $composeProject = "mvp27_test001_${stamp}_${suffix}"
    $composeFile = Join-Path $Root "docker-compose.yml"
    if (-not (Test-Path $composeFile)) {
        throw "Expected docker compose file at $composeFile."
    }
    $composeBaseArgs = @("--project-name", $composeProject, "--file", $composeFile)

    $dbPort = Get-FreeTcpPort

    $adminUrl = "postgresql://sustentra_admin:local-admin-password@localhost:$dbPort/sustentra"
    $appUrl = "postgresql://app_user:local-app-password@localhost:$dbPort/sustentra"

    $env:COMPOSE_PROJECT_NAME = $composeProject
    $env:POSTGRES_HOST_PORT = "$dbPort"
    $env:DATABASE_URL = $adminUrl
    $env:APP_DATABASE_URL = $appUrl
    $env:TEST_DATABASE_URL = $adminUrl
    $env:TEST_APP_DATABASE_URL = $appUrl
    $env:TEST_DB_REQUIRED = "1"
    $env:TEST_DB_DISPOSABLE = "1"
    $env:OTP_HMAC_SECRET = "local-otp-hmac-secret-for-tests"
    $env:PUBLIC_BASE_URL = "https://app.sustentra.test"

    Write-Host "Disposable compose project: $composeProject" -ForegroundColor Green
    Write-Host "Disposable DB port: $dbPort" -ForegroundColor Green

    # Mark before 'up' so a partially created project is still torn down.
    $startupAttempted = $true
    Invoke-Checked "Start isolated DB service" { & docker compose @composeBaseArgs up -d db 2>&1 | Out-Null }

    Write-Host "==> Wait for Postgres readiness" -ForegroundColor Cyan
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        & docker compose @composeBaseArgs exec -T db pg_isready -U sustentra_admin -d sustentra 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "Postgres did not become ready within 40 seconds."
    }

    Push-Location backend
    try {
        Invoke-Checked "Apply Alembic migrations to head" { & $Python -m alembic -c alembic.ini upgrade head }
    }
    finally {
        Pop-Location
    }

    $checkScript = Join-Path $env:TEMP "mvp27_test001_db_role_check_${suffix}.py"
    @'
import os

import psycopg2

admin_url = os.environ["TEST_DATABASE_URL"]
app_url = os.environ["TEST_APP_DATABASE_URL"]

with psycopg2.connect(app_url) as app_conn:
    with app_conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        runtime_database, runtime_user = cur.fetchone()

if runtime_user != "app_user":
    raise SystemExit(f"Runtime user must be app_user, got {runtime_user!r}")

with psycopg2.connect(admin_url) as admin_conn:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname = 'app_user'"
        )
        row = cur.fetchone()

if row is None:
    raise SystemExit("Role 'app_user' does not exist")

if any(bool(value) for value in row):
    raise SystemExit(f"Role 'app_user' has unsafe flags: {row}")

print(f"Runtime identity validated: app_user on {runtime_database}")
'@ | Set-Content -Encoding ASCII $checkScript

    try {
        Invoke-Checked "Verify runtime DB identity and role safety" { & $Python $checkScript }
    }
    finally {
        Remove-Item $checkScript -Force -ErrorAction SilentlyContinue
    }

    Invoke-Checked "ruff backend" { & $Python -m ruff check backend }
    Invoke-Checked "mypy backend.app" { & $Python -m mypy -p backend.app }
    Invoke-Checked "pytest backend/tests/db in required-db mode" { & $Python -m pytest --require-test-db -ra backend/tests/db }

    if (-not $SkipFullSuite) {
        Invoke-Checked "pytest backend/tests with coverage gate" {
            & $Python -m pytest --require-test-db backend/tests --cov=backend/app --cov-report=term-missing --cov-fail-under=80
        }
    }
}
catch {
    $primaryFailure = $_
}
finally {
    try {
        if ($startupAttempted) {
            Write-Host "==> Teardown isolated compose resources" -ForegroundColor Cyan
            $previousErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $cleanupOutput = & docker compose @composeBaseArgs down -v 2>&1
            }
            finally {
                $ErrorActionPreference = $previousErrorActionPreference
            }

            $cleanupExitCode = $LASTEXITCODE
            if ($cleanupOutput) {
                $cleanupOutput | ForEach-Object { Write-Host $_ }
            }
            if ($cleanupExitCode -ne 0) {
                throw "Cleanup failed: docker compose down -v exited with code $cleanupExitCode"
            }
        }
        else {
            Write-Host "==> Teardown skipped (startup not attempted)" -ForegroundColor DarkGray
        }
    }
    catch {
        $cleanupFailure = $_
    }
    finally {
        Restore-ManagedEnvironment
        if ($hadNativeErrorPreference) {
            $PSNativeCommandUseErrorActionPreference = $originalNativeErrorPreference
        }
        $ErrorActionPreference = $originalErrorActionPreference
        Set-Location $originalLocation
    }
}

if ($primaryFailure -ne $null) {
    if ($cleanupFailure -ne $null) {
        [Console]::Error.WriteLine("Cleanup also failed: $($cleanupFailure.Exception.Message)")
    }
    throw $primaryFailure
}

if ($cleanupFailure -ne $null) {
    throw $cleanupFailure
}

Write-Host "All TEST-001 backend infrastructure checks completed." -ForegroundColor Green

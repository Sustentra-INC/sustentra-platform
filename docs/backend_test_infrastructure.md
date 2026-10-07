# Backend Test Infrastructure (MVP-27 / TEST-001)

This document describes the required-database contract for backend integration tests and the recommended local execution flow.

## 1. Database Contract

Backend DB integration tests rely on two URLs:

- TEST_DATABASE_URL: migration/admin connection used only for migrations and fixture provisioning/cleanup.
- TEST_APP_DATABASE_URL: runtime application connection used for requests and RLS assertions.

The test harness validates all of the following before destructive seeding:

- both URLs are set together;
- both URLs target the same host:port/database;
- TEST_APP_DATABASE_URL resolves to runtime user app_user;
- app_user has rolsuper=false, rolbypassrls=false, rolcreatedb=false, rolcreaterole=false;
- alembic_version exists and required application tables exist.

A disposable-data acknowledgement is mandatory:

- TEST_DB_DISPOSABLE=1

Required-database mode can be enabled by either:

- pytest option: --require-test-db
- environment variable: TEST_DB_REQUIRED=1

In required mode, invalid setup fails fast instead of skipping DB tests.

## 2. PowerShell Local Commands (Manual)

From repository root:

```powershell
$env:TEST_DATABASE_URL = "postgresql://sustentra_admin:local-admin-password@localhost:55457/sustentra"
$env:TEST_APP_DATABASE_URL = "postgresql://app_user:local-app-password@localhost:55457/sustentra"
$env:TEST_DB_DISPOSABLE = "1"
$env:TEST_DB_REQUIRED = "1"
$env:OTP_HMAC_SECRET = "local-otp-hmac-secret-for-tests"
$env:PUBLIC_BASE_URL = "https://app.sustentra.test"

.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy -p backend.app
.\.venv\Scripts\python.exe -m pytest --require-test-db -ra backend/tests/db
.\.venv\Scripts\python.exe -m pytest --require-test-db backend/tests --cov=backend/app --cov-report=term-missing --cov-fail-under=80
```

Bash (macOS / Linux / Git Bash), from the repository root:

```bash
export TEST_DATABASE_URL=postgresql://sustentra_admin:local-admin-password@localhost:5433/sustentra_test
export TEST_APP_DATABASE_URL=postgresql://app_user:local-app-password@localhost:5433/sustentra_test
export TEST_DB_DISPOSABLE=1 TEST_DB_REQUIRED=1 OTP_HMAC_SECRET=local-otp-hmac-secret-for-tests
(cd backend && DATABASE_URL=$TEST_DATABASE_URL alembic upgrade head)
pytest --require-test-db --cov --cov-fail-under=80
```

Point these at a database you can lose: the tests TRUNCATE users, organizations, sessions
and audit logs. Never the `sustentra` database your local `docker compose` app uses.
Without `TEST_DB_DISPOSABLE=1` the DB tests are skipped and the run ends with a warning
saying how many.

## 3. One-Command Local Runner

The script below creates a unique compose project and DB port, waits for readiness, migrates, validates runtime role safety, runs tests, and tears down only resources it created.

```powershell
.\scripts\run-backend-test-infra.ps1
```

Optional (skip full backend coverage run):

```powershell
.\scripts\run-backend-test-infra.ps1 -SkipFullSuite
```

## 4. Shared fixtures (backend/tests/db/conftest.py)

| Fixture | What it gives a test |
|---|---|
| `seeded_identities` | Org A and Org B, an org_admin and org_member in each, a provider_admin; one known password |
| `db_test_client` | httpx client on the real app, connected as `app_user`; `login_with_otp(...)` returns the session cookie |
| `email_capture` | OTP codes, reset links and invite links the app tried to send (`latest_otp_code`, `latest_invite_link`) |
| `transport_guard` | Fails the test if anything reaches real SMTP / SES |
| `controlled_clock` | A fixed clock for login, reset, session and invite expiry (`advance(timedelta)`) |
| `as_app_user` | Run raw SQL as `app_user` in a tenant or provider scope (RLS assertions) |

Older DB test modules still seed their own data; new tests should use these fixtures.

## 5. CI Behavior

The backend CI job now sets:

- TEST_DB_REQUIRED=1
- TEST_DB_DISPOSABLE=1

CI keeps migration upgrade/downgrade/upgrade checks, enforces coverage threshold, publishes a readable coverage summary, and uploads coverage artifacts while preserving failing exit status when tests or coverage fail.

# Sustentra Project Handoff - 2026-08-17

This document captures the current engineering state, project structure, operating runbooks, and handoff risks for the Sustentra S1/S2 platform as of August 17, 2026.

It is written for a non-engineer operator plus the next engineer. It intentionally does not include secret values. Any account owner, billing plan, or cost field marked `TBD by owner` must be filled from the live dashboard before external handoff.

## Current Status

### S1 Frontend And Backend

S1 is the evidence intake and extraction-review subsystem.

Current S1 state:

- Evidence Workspace and Extraction Review exist in `frontend/features/s1/`.
- Revision and addendum work has been implemented locally, including state-role mapping, backend validation flags, halt-reason copy mapping, upload behavior, row actions, glossary, preview fallback, audit/session notices, withdraw/reinstate shape, and manual-entry surfaces.
- The revised S1 UI has been pushed and deployed to cloud according to owner confirmation.
- Cloud frontend: `https://sustentra-platform.vercel.app/`
- Cloud backend: `https://sustentra-s1-backend.onrender.com`
- Vercel deployment/project link provided by owner: `https://vercel.com/qinghuanyang2005-7748s-projects/sustentra-platform/AfAgWjtRxJwCY37n5aUZZGio46ue`
- S1 backend mode is supported through `frontend/features/s1/api/s1Backend.ts`.
- S1 fixture and backend E2E suites exist under `frontend/e2e/s1/`.
- The FastAPI backend is integrated for the core S1 durable flow:
  - document registration/upload/preview/download
  - pipeline processing
  - extraction result retrieval
  - review decision persistence
  - approved evidence projection
  - JSONL or Postgres repositories
  - local or S3-compatible object storage
- Mounted S1/backend routers are visible in `backend/app/main.py`: `engagements`, `documents`, `processing_runs`, `pipeline`, `extraction_results`, `evidence`, `reviews`, and `assistant`.

Known S1 caveat:

- S1 cloud deployment exists and owner reports cloud audit persistence has been tested. Before changing S1 persistence behavior, the next engineer should repeat the cloud smoke test and record the exact frontend/backend commit SHAs tested.

### S2 Frontend And Backend

S2 is the verification/reported-inventory review subsystem.

Current S2 frontend state:

- Branch: `s2-ui`.
- GitHub branch after this handoff push: `https://github.com/claireyqh/sustentra-platform/tree/s2-ui`
- S2 is currently mounted as the local app entry point in `frontend/app/page.tsx` for implementation review.
- S2 is fixture-first. The Meridian fixture contract is the acceptance baseline.
- Waves 1-4 are implemented:
  - Wave 1: core contracts, copy/state constants, component inventory, lifecycle utilities, persistence boundary.
  - Wave 2: Reported Inventory, Inventory Line, Examine normal/partial/no-evidence modes, keyboard behavior.
  - Wave 3: Request Builder, Open Requests, Findings.
  - Wave 4: Documents, Since you were last here, Analytical Procedures, Check Coverage.
- Current local validation baseline:
  - `npm test -- --run`: 45 tests passing.
  - `S2_FIXTURE_URL=http://localhost:3001 npx playwright test --project=s2-fixture`: 10 E2E tests passing.
  - `npm run build`: passing.

Current S2 backend state visible in source:

- S2 methodology backend foundation exists in source:
  - `backend/app/domain/methodology.py`
  - `backend/app/reference/methodology_loader.py`
  - `backend/app/services/methodology_integrity_service.py`
  - related tests in `backend/tests/reference/test_methodology_loader.py` and `backend/tests/services/test_methodology_integrity_service.py`
- The S1 backend produces the intended upstream object for S2: approved evidence.
- The repo also contains the S2 backend roadmap in `reference-data/methodology/s2_backend_pr_roadmap_and_collaboration_plan.md`.

Known S2 integration caveat:

- From the current visible source, S2-specific API routes for examination records, notes, requests, findings, documents, and coverage checks are not mounted in `backend/app/main.py`.
- The current S2 frontend therefore remains fixture-contract first. Before removing the fixture persistence banner, connect the S2 frontend to the actual S2 backend routes/repositories and run a live persistence test.
- S2 is not yet connected to S1 as a production navigation/data flow in the frontend.
- The current `Fixture mode: recording is not durable` banner is intentional. It should appear once at engagement level while S2 writes are session/in-memory only.

## README Coverage

The root `README.md` currently covers:

- Overall product skeleton.
- S1 backend pilot status.
- Basic backend setup.
- Local runtime safety.
- Key documentation links.

Before a non-engineering handoff, update `README.md` to link this handoff document and add a short tool list. This handoff contains the detailed system inventory, runbooks, failure playbook, and security posture.

## Project Structure

```text
sustentra-platform/
  README.md
  FRONTEND_CONSTRAINTS.md
  docker-compose.yml
  render.yaml
  .env.example

  backend/
    app/
      api/                  FastAPI routers
      services/             upload, parse, classify, extraction, review services
      repositories/         JSONL/Postgres repositories
      reference/            vocabulary, methodology, extraction config loaders
      workers/              document-processing entry points
    alembic/                database migrations
    tests/                  backend unit/API/service tests
    scripts/                smoke-test helpers

  frontend/
    app/                    Next.js app entry
    features/
      s1/                   S1 Evidence Workspace and Extraction Review
      s2/                   S2 verification frontend, fixtures, tests
    e2e/
      s1/                   S1 Playwright suites
      s2/                   S2 Playwright fixture-contract suite
    package.json
    playwright.config.ts

  contracts/                JSON Schema contracts
  reference-data/
    extraction-config/      S1 extraction target seed
    methodology/            S2 methodology spreadsheets/reference files
    config/libraries/       legacy/reference libraries
    vocab library/          vocabulary workbook/reference docs

  docs/                     architecture, setup, QA, handoff docs
  demo-fixtures/            preserved demo fixture data

  S2_Handoff(08_13)/        untracked handoff input, do not commit unless intended
  s2_e2e_golden_test_pack/  untracked test-pack input, do not commit unless intended
```

## Local Setup

### Frontend Only

From `frontend/`:

```bash
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

If port 3000 is already in use, Next will choose another port such as `http://localhost:3001`.

Useful commands:

```bash
npm test -- --run
npm run build
npx playwright test --project=s2-fixture
```

For S2 Playwright against an already-running local server:

```bash
S2_FIXTURE_URL=http://localhost:3001 npx playwright test --project=s2-fixture
```

### Full Local Durable S1 Stack

From repo root:

```bash
docker compose up
```

Services:

```text
Frontend:     http://localhost:3000
Backend:      http://localhost:8000
Backend docs: http://localhost:8000/docs
MinIO API:    http://localhost:9000
MinIO console:http://localhost:9001
Postgres:     localhost:5432
```

Local defaults from `docker-compose.yml`:

```text
Postgres db/user/password: sustentra / sustentra / sustentra
MinIO user/password:       sustentra / sustentra-password
MinIO bucket:              sustentra-documents
```

## Tool And Service Inventory

Fill in account owner, plan, exact cost, and transfer status before external handoff.

| Tool/service | What it does | Login/admin URL | Current owner account | Plan/cost | Upgrade trigger | Notes |
|---|---|---|---|---|---|---|
| GitHub | Source repository, branches, PRs | `https://github.com` | No ownership transfer requested; confirm repo/org admin access | TBD by owner | Private repo seats, CI minutes, storage | Current working branch is `s2-ui`. |
| Vercel | Next.js frontend hosting | `https://vercel.com` | No transfer required for handoff; a new company account/project can be created if needed | TBD by owner | Team seats, bandwidth/build limits, custom domains | Provided production URL: `https://sustentra-platform.vercel.app/`. |
| Render | FastAPI backend hosting | `https://dashboard.render.com` | No ownership transfer requested; confirm admin/redeploy access or recreate service from `render.yaml` | Repo config says `plan: free` for `sustentra-s1-backend`; confirm dashboard | Free services sleep after inactivity; request/runtime/resource limits; paid plan needed for always-on/stability | Provided backend URL: `https://sustentra-s1-backend.onrender.com`. |
| Supabase | Cloud Postgres and S3-compatible storage path described in staging docs | `https://supabase.com/dashboard` | Ownership transfer required; invite already sent | TBD by owner | Database size, storage size, bandwidth, pooled connection limits | This is the only currently identified ownership transfer item. |
| Local Docker Postgres | Local durable metadata/review state | local only | none | free local | disk space | Volume: `postgres-data`. |
| MinIO | Local/S3-compatible object storage for uploaded documents | local console `http://localhost:9001` | none | free local | disk space | Volume: `minio-data`; bucket `sustentra-documents`. |
| OpenAI API | Optional LLM extraction pass | `https://platform.openai.com` | Org-owned; no ownership transfer requested | Usage-based, confirm billing | API usage/quotas/rate limits | Env vars: `OPENAI_API_KEY`, `OPENAI_EXTRACTION_MODEL`. |
| AWS / Textract | Future/parser option only; disabled by default | `https://console.aws.amazon.com` | Org-owned; no ownership transfer requested | TBD by owner | OCR/document analysis usage | Env vars exist but `TEXTRACT_ENABLED=false` by default. |
| Domain/DNS provider | Custom domain and DNS | TBD by owner | TBD by owner | TBD by owner | custom domain/DNS records | Not identifiable from repo. |
| Monitoring | Uptime/alerting | TBD | TBD | TBD | production external users | No dedicated monitor found in repo. Render health check exists at `/health`. |

## Secrets And Rotation

Never commit real secrets. Repo examples are safe templates only:

- Root example: `.env.example`
- Frontend example: `frontend/.env.example`
- Live secrets should live in provider dashboards, not git:
  - Render service environment variables.
  - Vercel project environment variables.
  - Supabase database/storage settings.
  - OpenAI API console.
  - AWS IAM console if enabled.

### Important Environment Variables

| Variable | Where used | Purpose | Where live value should be stored |
|---|---|---|---|
| `NEXT_PUBLIC_BACKEND_API_URL` | Frontend | Backend API base URL | Vercel env, local `.env`/shell |
| `NEXT_PUBLIC_S1_DATA_MODE` | Frontend | `fixture` or `backend` mode for S1 | Vercel env, local `.env`/shell |
| `DATABASE_URL` | Backend | SQLAlchemy/Postgres connection | Render env, local `.env` |
| `SUSTENTRA_PERSISTENCE_BACKEND` | Backend | `jsonl` or `postgres` | Render/local env |
| `SUSTENTRA_STORAGE_BACKEND` | Backend | `local` or `minio` | Render/local env |
| `SUSTENTRA_LOCAL_UPLOAD_ROOT` | Backend | local file upload root | local env only |
| `SUSTENTRA_S3_ENDPOINT_URL` | Backend | S3-compatible endpoint | Render/local env |
| `SUSTENTRA_S3_ACCESS_KEY_ID` | Backend | S3-compatible access key | Render/local env |
| `SUSTENTRA_S3_SECRET_ACCESS_KEY` | Backend | S3-compatible secret | Render/local env |
| `SUSTENTRA_S3_BUCKET` | Backend | document bucket | Render/local env |
| `SUSTENTRA_S3_REGION` | Backend | S3 region | Render/local env |
| `SUSTENTRA_CORS_ORIGINS` | Backend | allowed frontend origins | Render/local env |
| `SUSTENTRA_LLM_EXTRACTION_ENABLED` | Backend | enables/disables LLM extraction | Render/local env |
| `OPENAI_API_KEY` | Backend | LLM extraction API key | Render/local env |
| `OPENAI_EXTRACTION_MODEL` | Backend | LLM extraction model | Render/local env |
| `TEXTRACT_ENABLED` | Backend | AWS Textract toggle | Render/local env |
| `TEXTRACT_REGION` | Backend | AWS Textract region | Render/local env |
| `TEXTRACT_OUTPUT_BUCKET` | Backend | Textract output bucket | Render/local env |

### Rotation Procedure If A Secret Leaks

1. Disable or delete the leaked key in the provider dashboard.
2. Create a replacement key with the smallest required scope.
3. Update the live provider environment variable:
   - Render: service -> Environment -> edit secret -> save -> redeploy/restart.
   - Vercel: project -> Settings -> Environment Variables -> edit -> redeploy frontend.
   - Supabase: Project Settings -> Database/Storage/S3 keys -> rotate -> update Render.
   - OpenAI: API keys -> delete leaked key -> create new key -> update Render.
   - AWS: IAM -> deactivate/delete access key -> create new key if still needed.
4. Restart/redeploy the affected service.
5. Confirm health:
   - Backend: `https://sustentra-s1-backend.onrender.com/health`
   - Frontend: `https://sustentra-platform.vercel.app/`
6. Search git history and deployment logs for accidental exposure.
7. Record the incident and rotation date in a private operations log.

### Ownership And Access Transfer Checklist

Only Supabase currently needs ownership transfer. The invite has already been sent.

1. Supabase ownership transfer:
   - Accept the pending Supabase invite from the company/target account.
   - Confirm the target account has owner/admin access to the project.
   - Confirm the target account can view database settings, storage buckets, S3-compatible keys, backups, and billing.
   - Rotate database and S3-compatible storage credentials after ownership is confirmed.
   - Update Render environment variables with the rotated Supabase values.
   - Restart/redeploy Render and confirm `/health` plus one upload/review smoke test.
2. GitHub:
   - No ownership transfer requested in this handoff.
   - Confirm the repo remains accessible to the intended maintainers.
3. AWS:
   - Already org-owned.
   - No ownership transfer requested.
4. OpenAI:
   - Already org-owned.
   - No ownership transfer requested.
5. Vercel:
   - No ownership transfer required for handoff.
   - If needed, create a new company Vercel project from the GitHub repo and copy the environment variables.
6. Render:
   - No ownership transfer required for handoff.
   - If needed, recreate the backend service from `render.yaml` and copy the environment variables.
7. Domain/DNS:
   - Confirm whether any custom domain is currently in use.
   - If not, no transfer action is needed.

## Task Runbooks

Each runbook has: what to do, how to verify, and how to undo.

### Add A New Evidence Document Type

Purpose: teach S1 to classify a new document and extract fields from it.

Files likely involved:

- Vocabulary/canonical type source: `reference-data/vocab library/Vocabulary_Library_v1.0.xlsx` and generated/loader outputs.
- Classification service: `backend/app/services/classification_service.py`.
- Extraction config seed: `reference-data/extraction-config/extraction_config_seed.json`.
- Extraction schema: `contracts/extraction_config.schema.json`.
- Tests:
  - `backend/tests/reference/test_extraction_config_loader.py`
  - `backend/tests/services/test_classification_service.py`
  - `backend/tests/services/test_extraction_target_service.py`
  - `backend/tests/services/test_extraction_candidate_service.py`

Steps:

1. Pick a stable canonical type ID, for example `CT-S1-NEW-DOC-TYPE`.
2. Add vocabulary/classification signals:
   - filename patterns
   - header terms
   - key phrases
   - layout features, if available
3. Add extraction config rows in `reference-data/extraction-config/extraction_config_seed.json`.
   - Use unique `extraction_config_id`.
   - Use stable `field_id`.
   - Set `canonical_type_id` to the new canonical type.
   - Fill value type, required status, hints, and extraction methods.
4. Add or update tests with a sample filename/text that should classify as the new type.
5. Run:

```bash
python -m pytest -q backend/tests/reference/test_extraction_config_loader.py
python -m pytest -q backend/tests/services/test_classification_service.py
python -m pytest -q backend/tests/services/test_extraction_target_service.py
```

6. Locally upload a known sample through S1 backend mode.
7. Confirm:
   - document classifies to the new canonical type
   - extraction targets are selected
   - Extraction Review shows human-readable fields
   - no raw backend prose leaks to the frontend

Undo:

1. Revert the vocabulary/classification entry.
2. Remove the extraction config rows.
3. Remove or disable tests that depend on that type.
4. Redeploy previous known-good backend/frontend if already deployed.

### Add A New Data Point Or Expression To Verification Rules

Purpose: extend S2 methodology/rule coverage.

Files likely involved:

- Methodology source spreadsheets:
  - `reference-data/methodology/S2_Scope1_Data_Schema_v.1.xlsx`
  - `reference-data/methodology/S2_Scope2_Data_Schema_v.1.xlsx`
  - `reference-data/methodology/S2_General_Methodology_Schema_v.1.xlsx`
  - `reference-data/methodology/S2_Verification_Rules_v.1.xlsx`
  - `reference-data/methodology/S2_Cross_Layer_Edge_Table_v1.xlsx`
- Loader/integrity code:
  - `backend/app/reference/methodology_loader.py`
  - `backend/app/services/methodology_integrity_service.py`
- S2 frontend fixture:
  - `frontend/features/s2/fixtures/meridian.ts`

Steps:

1. Add the new field/rule to the source methodology workbook.
2. Keep Field_ID stable and unique.
3. If the rule references other fields, update cross-layer edge data.
4. Run methodology integrity checks:

```bash
python -m pytest -q backend/tests/reference/test_methodology_loader.py
python -m pytest -q backend/tests/services/test_methodology_integrity_service.py
```

5. If the frontend fixture must demonstrate it, add a requirement row to `frontend/features/s2/fixtures/meridian.ts`.
6. Add or update S2 component/E2E tests if this creates a new visible state.
7. Run:

```bash
cd frontend
npm test -- --run
npx playwright test --project=s2-fixture
```

Verify:

- New rule appears in S2 where expected.
- Check Coverage counts still make sense.
- No duplicate platform findings are created by rerunning checks.
- Client-facing request wording does not expose Field_IDs.

Undo:

1. Revert workbook/source change.
2. Revert fixture/test change.
3. Redeploy previous known-good version if already deployed.

### Add User Login / Roles / Password Reset

Current code structure does not yet expose a production auth layer, but it is straightforward to add one without disturbing the S1/S2 feature folders.

Recommended shape:

1. Pick the identity provider.
   - If using Supabase Auth, keep auth with the existing Supabase project.
   - If using another provider, keep the provider account org-owned.
2. Backend:
   - Add an auth dependency/middleware in `backend/app/main.py` or a new `backend/app/auth/` package.
   - Validate bearer tokens on protected routes.
   - Add a user/role model if roles are stored locally.
   - Add tests proving unauthenticated requests are rejected and allowed roles can access S1/S2 routes.
3. Frontend:
   - Add an auth client under `frontend/features/auth/`.
   - Wrap `frontend/app/page.tsx` with an auth/session boundary.
   - Pass the access token into S1/S2 API adapters, starting with `frontend/features/s1/api/s1Backend.ts`.
   - Add visible user/account controls in shared app chrome rather than inside individual S1/S2 tables.
4. Invite/remove user:
   - Use the provider dashboard to invite or disable a user.
   - If local roles exist, update that user's role record.
   - Verify by logging in as that user and opening the relevant workspace.
5. Reset password:
   - Use the provider dashboard password-reset action or built-in reset email.
   - Verify the user can sign in and the old password no longer works.
6. Undo:
   - Disable the user in the provider dashboard.
   - Remove or downgrade the local role record if one exists.
   - Confirm the user can no longer access the frontend or backend API.

### Deploy A Change

Current expected deployment shape:

```text
GitHub branch -> Vercel frontend
GitHub branch -> Render backend
```

Before deploy:

```bash
cd frontend
npm test -- --run
npm run build
npx playwright test --project=s2-fixture
```

For backend changes:

```bash
python -m pytest -q backend/tests
```

Deploy steps:

1. Commit only intended files.
2. Push branch to GitHub.
3. Open PR or merge according to project practice.
4. Confirm Vercel deployment completes.
5. Confirm Render deployment completes if backend changed.
6. Smoke test:
   - Frontend opens.
   - Backend health returns `{"status":"ok"}`.
   - Upload and review one S1 document in backend mode if backend changed.
   - Run S2 fixture smoke if S2 changed.

Rollback:

1. Vercel: open Deployments -> select previous good deployment -> Promote/Redeploy.
2. Render: open service -> Events/Deploys -> redeploy previous commit if available, or push a revert commit.
3. Confirm health and smoke tests.

### Restart Backend When It Goes Down

Steps:

1. Open Render dashboard.
2. Open service `sustentra-s1-backend`.
3. Check Logs for the error.
4. Click Restart.
5. Wait for health check.
6. Open:

```text
https://sustentra-s1-backend.onrender.com/health
```

Verify:

- Expected JSON: `{"status":"ok"}`.
- Vercel frontend can reach backend without CORS errors.

Undo:

- If restart makes things worse, redeploy the last known-good Render deploy or push a revert commit.

### Back Up And Restore Database

Local Docker Postgres backup:

```bash
docker compose exec postgres pg_dump -U sustentra sustentra > backups/sustentra_YYYY-MM-DD.sql
```

Local Docker Postgres restore:

```bash
docker compose exec -T postgres psql -U sustentra sustentra < backups/sustentra_YYYY-MM-DD.sql
```

Cloud Supabase backup:

1. Open Supabase dashboard.
2. Go to Project -> Database -> Backups or connection settings.
3. Use built-in backup/export if available for the current plan.
4. For manual export, use the Supabase/Postgres connection string with `pg_dump`.

Verify restore:

1. Backend health works.
2. S1 document list still loads.
3. Previously reviewed fields still show accepted/corrected state.
4. Uploaded file download still works.

Undo:

- Restore from the previous backup or redeploy against the previous database if available.

## Failure Playbook

| Symptom | Likely cause | Fix | How to verify |
|---|---|---|---|
| Frontend shows a server/client manifest error in local dev | Stale Next `.next` cache after moving client components or switching branches | Stop dev server, delete `frontend/.next`, restart `npm run dev` | Page reloads, dev server logs `GET / 200`, tests can find expected rows |
| Vercel page loads but API calls fail | Backend URL env wrong, backend down, or CORS missing Vercel origin | Check `NEXT_PUBLIC_BACKEND_API_URL`; check Render health; update `SUSTENTRA_CORS_ORIGINS` | Browser network calls succeed |
| Uploads hang | Render cold start, backend down, object storage issue, or storage limit | Open `/health`; check Render logs; check Supabase/MinIO storage; restart backend | Upload row progresses beyond initial state |
| Uploaded document disappears after refresh | Running fixture/local JSON mode or persistence env wrong | Confirm backend uses `SUSTENTRA_PERSISTENCE_BACKEND=postgres`; check DB records | Refresh keeps document |
| Download original fails | Object missing, wrong bucket/key, S3 credentials invalid | Check MinIO/Supabase bucket and Render S3 env vars | Download returns correct file |
| Extraction never completes | parser/LLM failure, missing OpenAI key, disabled LLM fallback issue | Check backend pipeline logs; confirm `OPENAI_API_KEY` if LLM enabled; rerun pipeline | Pipeline reaches Extracted or mapped Blocked |
| Review decisions vanish after refresh | Review endpoint not persisted or frontend in fixture/session mode | Check backend review API and DB table `s1_review_decisions` | Refresh keeps accepted/corrected state |
| S2 actions show fixture-mode banner | Expected in current S2 build | Do not remove until durable S2 backend exists | Banner appears once at engagement level |
| S2 no-evidence row opens a page | Regression against S2 spec | Fix `RequirementRow` behavior to keep no-evidence inline | E2E no-evidence test passes |
| Render first load is slow | Free service slept after inactivity | Wait for cold start or upgrade Render plan | Subsequent requests respond faster |
| CORS error from deployed frontend | Vercel origin missing from Render CORS env | Add Vercel URL to `SUSTENTRA_CORS_ORIGINS`, redeploy/restart Render | Browser network tab shows successful API calls |

## Monitoring

No dedicated external monitoring/alerting setup was found in the repo.

Minimum monitoring to set up before customers:

1. Use a free uptime monitor such as UptimeRobot, Better Stack, or another company-approved tool.
2. Add checks:
   - `https://sustentra-platform.vercel.app/`
   - `https://sustentra-s1-backend.onrender.com/health`
3. Alert email:
   - company support/shared inbox, not a personal inbox.
4. Check interval:
   - 5 minutes is enough for staging.
5. Alert rule:
   - alert after 2 failed checks.
6. Weekly manual check:
   - upload one small document
   - open Extraction Review
   - accept/correct one field
   - refresh and confirm persistence

## Do-Not-Touch List

- Do not commit `.env`, `local-data/`, `local-samples/`, uploaded customer documents, parser outputs from private files, or local runtime artifacts.
- Do not commit `frontend/playwright-report/` or `frontend/test-results/`.
- Do not commit `S2_Handoff(08_13)/` or `s2_e2e_golden_test_pack/` unless the owner explicitly decides these inputs belong in the repo.
- Do not remove the S2 fixture-mode persistence banner until durable S2 backend writes exist.
- Do not hide dependency-explained S1/S2 controls. The specs require visible shapes with clear explanations when a route, durable write, or live integration has not been verified.
- Do not let raw backend extraction candidate fields leak into React components outside resolver/adapter boundaries.
- Do not use raw backend halt prose in the frontend; route halt/copy through approved constants.
- Do not turn S2 Check Coverage into pass/fail or pass-rate framing.
- Do not imply final assurance conclusions in S1 or S2.

## Known Debt And Next Engineering Priorities

Top 3:

1. S2 review actions are still demonstrated from fixture data.
   - What a non-technical user sees: S2 screens work locally, but the banner says fixture-mode recording is not durable.
   - Why it matters: a reviewer should not enter live engagement decisions into S2 until those decisions are stored in the backend and survive refresh/restart.
   - Next engineering step: connect S2 examination records, notes, requests, findings, documents, and coverage checks to real backend routes/repositories; then test refresh, second browser, and backend restart.
2. Authentication, authorization, and account administration.
   - What a non-technical user sees: there is no real sign-in, role management, invite/remove user flow, or password reset flow in the current app.
   - Why it matters: customer documents and review decisions need access control before live customer use.
   - Next engineering step: add an org-owned auth provider, protect backend routes, add frontend session handling, and add user/role runbooks.
3. Cloud persistence/lifecycle validation.
   - What a non-technical user sees: the cloud app may look healthy after a normal refresh, but there is no written recurring proof that data survives Render restarts, cold starts, redeploys, and Supabase credential rotation.
   - Why it matters: if the backend restarts or a service sleeps, users need confidence that uploaded documents and review records remain.
   - Next engineering step: schedule and record a cloud smoke test: upload -> extract -> review -> refresh -> second browser -> Render restart -> verify persistence.

Other debt:

- Billing/limits are not fully written down. Owner/account info for Supabase plan limits, Vercel limits, Render limits, and OpenAI usage should be copied from the live dashboards into the system inventory table.
- S1 cloud audit persistence is owner-reported as tested, but the result should be recorded with exact test date, frontend URL, backend URL, frontend commit SHA, backend commit SHA, and screenshots/log notes.
- S1 candidate-less whole-document manual entry needs one explicit cloud test. The question is simple: if a document has no extraction candidate, can a human-entered value be saved, refreshed, and seen from a second browser?
- Render free tier can sleep after inactivity. Users may see a slow first request; either document this in tester instructions or upgrade Render when demos need a smoother first load.
- Root `README.md` is still too backend-pilot-oriented. Add a short index linking S1 frontend, S2 frontend, deployment, and this handoff.

## Data And Security Posture

### Where Documents Live

Local modes:

- `SUSTENTRA_STORAGE_BACKEND=local`: files under `SUSTENTRA_LOCAL_UPLOAD_ROOT`, default `local-data/uploads`.
- Docker durable mode: MinIO bucket `sustentra-documents`, volume `minio-data`.

Cloud staging path described in docs:

- Supabase Storage through S3-compatible API, bucket `sustentra-documents`.
- Render backend holds object keys/metadata in Postgres.

Confirm actual production storage in Render env before customer use.

### What Data Persists

S1 durable backend mode persists:

- document metadata
- uploaded document objects
- pipeline runs
- extraction results
- review decisions
- approved evidence projection

S2 current fixture mode:

- session/in-memory review actions only
- no durable S2 persistence yet

### What Passes Through LLM APIs

When `SUSTENTRA_LLM_EXTRACTION_ENABLED=true`, the backend LLM extraction service may send parsed document text or extracted snippets to the configured OpenAI extraction model to produce structured extraction candidates.

Operator requirements before customer use:

1. Confirm the OpenAI project/account is company-owned.
2. Confirm data usage/retention settings in the OpenAI console.
3. Document which fields/snippets are sent.
4. Do not send documents containing data outside the approved testing scope.
5. Keep LLM disabled for environments that should use deterministic extraction only.

### Retention

Current repo does not define a formal retention policy.

Minimum policy to define before live customer use:

- how long uploaded documents are retained
- how long parser output/extraction candidates are retained
- how long review/audit records are retained
- who can delete/export data
- backup retention period
- incident response owner

## Final Pre-Push Checklist

```bash
cd frontend
npm test -- --run
npm run build
S2_E2E_WEB_SERVER=1 npx playwright test --project=s2-fixture
```

Then from repo root:

```bash
git status --short
```

Commit only intended implementation/docs files. Keep private inputs and generated artifacts out of the commit unless explicitly approved.

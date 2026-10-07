# Sustentra Evidence Extraction Product Skeleton

This repository is the production-oriented skeleton for the Sustentra evidence extraction product.

## Current S1 Backend Pilot Status

The active backend pilot supports a local, auditable S1 evidence workflow:

1. Upload a document into backend-controlled local storage.
2. Run local pipeline orchestration (parse -> classify -> target plan -> candidate generation).
3. Review machine-generated extraction candidates.
4. Submit reviewer decisions (accepted, edited, rejected, needs_more_evidence).
5. Project approved evidence for downstream use.

Approved evidence is the reviewed output that later validation/calculation work will consume.

## Read This First

- ESG / audit reviewers: `docs/esg_reviewer_testing_guide.md`
- Engineering testing and smoke flow: `docs/s1_backend_testing_guide.md`

## Quick Backend Setup

From repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python -m pytest -q backend/tests
uvicorn backend.app.main:app --reload
```

Dependencies are pinned (exact versions + hashes) in `backend/requirements.txt` and
`backend/requirements-dev.txt`, generated from the short lists in `requirements.in` /
`requirements-dev.in`. To add or upgrade a package, edit the `.in` file and regenerate
(`pip install uv` once):

```bash
cd backend
uv pip compile requirements.in --universal --python-version 3.12 --generate-hashes -o requirements.txt
uv pip compile requirements-dev.in --universal --python-version 3.12 --generate-hashes -o requirements-dev.txt
# upgrade one package: add  --upgrade-package fastapi  to both commands
```

CI fails when a `.txt` file is out of date with its `.in` file.

FastAPI docs:

```text
http://localhost:8000/docs
```

## Local Runtime Safety

Local runtime/testing data is intentionally git-ignored:

- `local-data/` (runtime JSONL state, uploaded files, run outputs)
- `local-samples/` (local synthetic/sample files and smoke outputs)

Never commit `local-data/`, `local-samples/`, private evidence documents, parser outputs from private files, `.env`, credentials, or generated local runtime artifacts.

## What The S1 Backend Does Today

- Local upload + storage path for evidence documents.
- Local pipeline orchestration and run summaries.
- Candidate generation for configured extraction targets.
- Review decision persistence with candidate snapshot traceability.
- Approved evidence projection from latest review decisions.

## What The S1 Backend Does Not Do Yet

- This is not yet a compliance judgment tool.
- This is not yet calculation, reconciliation, or gap analysis.
- This does not provide final regulatory conclusions.
- This does not include cloud storage deployment/auth hardening in this local pilot workflow.

## Core Terminology

- `Extraction candidate`: a machine suggestion (value, unit, confidence, source reference).
- `Review decision`: a human decision on that candidate (`accepted`, `edited`, `rejected`, `needs_more_evidence`).
- `Approved evidence`: the reviewed, projected output from accepted/edited latest field decisions.

## Key Documentation

- Pilot scope: `docs/pilot_scope.md`
- PR9 pipeline orchestration: `docs/backend_pipeline_orchestration.md`
- PR10 upload + local storage: `docs/upload_local_storage_backend.md`
- PR7 review decisions: `docs/review_decision_persistence.md`
- PR8 approved evidence: `docs/approved_evidence_projection.md`
- Parser smoke harness: `docs/local_parser_smoke_testing.md`
- Extraction smoke harness: `docs/local_extraction_smoke_testing.md`

## Repository Intent

- The Next.js frontend and FastAPI backend in this repository are the forward product architecture.
- The old Streamlit demo exists locally under `demo_package/` and is intentionally ignored.
- Preserved schemas, JSON libraries, and fixtures are copied into versioned folders for migration safety.

## Preserved Reference Assets

- Legacy schemas: `legacy-schemas/copied_from_streamlit_demo/`
- Reference JSON libraries and config: `reference-data/`
- Demo fixtures: `demo-fixtures/mock_outputs/`
- Legacy docs snapshot: `docs/legacy_streamlit_demo/`

## Organizations - provider admin (ORG-001 / MVP-17)

`/api/v1/provider/orgs` - provider admins only (401 without a session, 403 for any org user).

| Method | Path | Notes |
|---|---|---|
| GET | `/provider/orgs?search=&status=&page=&page_size=` | `{items, total, page, page_size}`, newest first; search matches name or slug |
| POST | `/provider/orgs` | `{name, slug, max_users?, initial_admin?: {email, first_name, last_name}}` -> 201; duplicate slug -> 409 |
| GET | `/provider/orgs/{id}` | 404 if unknown |
| PATCH | `/provider/orgs/{id}` | `{name?, max_users?}`; the slug is immutable |
| POST | `/provider/orgs/{id}/suspend` | deletes every session of the org's users at once; idempotent |
| POST | `/provider/orgs/{id}/activate` | idempotent; revoked sessions stay revoked |

- `max_users` defaults to 25 (1..10000). Lowering it below the current seat count is allowed and only blocks new seats.
- `initial_admin` creates an `org_admin` with status `invited` and a 24-hour invite token in the same transaction as the org, and emails `{PUBLIC_BASE_URL}/invite/accept?token=...` after the commit. Accepting the invite is ORG-003.
- Audit events: `org_created`, `user_invited`, `org_updated` (changed field names only), `org_suspended` (with `sessions_revoked`), `org_activated`.

## Users in an organization (ORG-002 / MVP-18)

`/api/v1/orgs/{org_id}/users` - an `org_admin` for their own org (another org's id -> 404), a `provider_admin` for any org; `org_member` -> 403.

| Method | Path | Notes |
|---|---|---|
| GET | `/orgs/{org_id}/users?status=&role=&page=&page_size=` | `{items, total, page, page_size, max_users, seats_used}`, newest first; deleted users are never listed |
| GET | `/orgs/{org_id}/users/{user_id}` | 404 if unknown, deleted or in another org |
| PATCH | `/orgs/{org_id}/users/{user_id}` | `{role: "org_admin" \| "org_member"}` |
| POST | `/orgs/{org_id}/users/{user_id}/suspend` | deletes the user's sessions and outstanding tokens at once; idempotent |
| POST | `/orgs/{org_id}/users/{user_id}/reactivate` | back to `active` (or `invited` if they never set a password); idempotent |

- An admin cannot demote or suspend themselves (409), and an org always keeps at least one active `org_admin` (409). The active admins are row-locked first, so two admins demoting each other at the same moment cannot leave the org with none.
- A session only authenticates while the user is `active` and their org is `active`.
- Audit events: `user_role_changed` (from/to), `user_suspended` (sessions revoked), `user_reactivated`.

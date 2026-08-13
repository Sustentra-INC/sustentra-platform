# intake — client onboarding

The front door to the platform: a client signs in, describes their company and
sites, and ends up with a profile that drives evidence requests and calculation
inputs. Spec: `intake/SPEC.md`. Data mapping: `intake/profile_schema_mapping.md`.
Repo rules: `CLAUDE.md`.

Everything here is new code. No existing file in the repo is modified.

## Status

| Phase | Scope | State |
|---|---|---|
| A | Schema seed: mapping → config, with validation | done |
| B | Stage 0 auth + org/site models + seed form API & UI | done |
| C1 | State machine, applicability, seed back-fill, escalation records | done |
| C2 | Interview engine, coverage meter, interview screen | done |
| D | LLM parse/rephrase + escalation queue + emails | not started |
| E | Evidence requests + profile page + audit log | not started |
| F | Instrumentation of the two success metrics | not started |

## Layout

```
intake/
  config/        the source of truth: schema seed, form definition, settings
  contracts/     JSON Schemas for the seed and for every stored record
  backend/       FastAPI app: domain, repositories, services, api
  scripts/       extractors, validator, smoke run
  tests/         pytest suite
```

## Setup

```sh
pip install -r intake/requirements.txt   # intake tooling
pip install -r backend/requirements.txt  # only needed to run the composed API
```

## Running things

```sh
# validate the Phase A schema seed (16 checks)
python intake/scripts/validate_profile_schema.py

# watch the whole Phase B flow run, with nothing written and no email sent
python intake/scripts/intake_smoke.py

# watch the Phase C1 state layer: instantiation, back-fill, a screening "no",
# applicability, and an escalation opened then resolved
python intake/scripts/interview_state_smoke.py

# play a whole guided interview for a two-site studio, start to finish
python intake/scripts/interview_smoke.py

# ...or exercise the real JSONL repositories and outbox
python intake/scripts/intake_smoke.py --data-dir local-data/intake-smoke

# tests
python -m pytest intake/tests
```

### The API

The intake routers are registered by a **new entrypoint** so that
`backend/app/main.py` is never edited:

```sh
uvicorn intake.backend.app:app --reload
```

That serves everything the S1 API served, plus `/v1/intake/*`. Running
`backend.app.main:app` still works and simply has no intake routes.

| Endpoint | Purpose |
|---|---|
| `POST /v1/intake/auth/magic-link` | Request a sign-in link. Same response whether or not the email exists. |
| `POST /v1/intake/auth/verify` | Exchange the link token for a session. Single use. |
| `GET  /v1/intake/auth/me` | Current user, org and role. |
| `POST /v1/intake/auth/sign-out` | Revoke the session. |
| `POST /v1/intake/orgs` | Create a company + first owner. **Internal**, admin-key guarded. |
| `GET  /v1/intake/orgs/{org_id}` | Company record. |
| `GET/POST /v1/intake/orgs/{org_id}/users` | List / add users. |
| `GET  /v1/intake/orgs/{org_id}/sites` | Sites for a company. |
| `GET  /v1/intake/sites/{site_id}` | One site, scoped to the caller's org. |
| `GET  /v1/intake/seed-form/schema` | Form definition with option lists resolved. |
| `POST /v1/intake/seed-form` | Submit the form. Creates/updates org and sites. |
| `GET  /v1/intake/seed-form/answers` | Existing answers, so the form prefills instead of duplicating sites. |
| `GET  /v1/intake/seed-form/submissions/latest` | Most recent submission. |
| `POST /v1/intake/interview/start` | Instantiate states, back-fill the seed form, return the first question. |
| `GET  /v1/intake/interview/next` | The next question, with options and explainer. |
| `POST /v1/intake/interview/answer` | Record an answer and advance. |
| `POST /v1/intake/interview/not-sure` | Explainer, escalate, keep going. |
| `GET  /v1/intake/interview/coverage` | Progress meter. |
| `GET  /v1/intake/interview/states` | Every recorded state (feeds Phase E). |

Sites are read-only over the API on purpose: every site write goes through the
seed-form endpoint so it passes the same validation, provisional-value recording
and boundary-deferral logic.

### The screens

```sh
cd frontend && npm install && npm run dev
```

- `/intake/login` — request a sign-in link
- `/intake/login/verify` — consume the link
- `/intake/seed` — the seed form (prefills from existing answers)
- `/intake/interview` — the guided interview, with the coverage meter

New pages only; no existing page, component or config is touched.

## Configuration

`intake/config/intake_settings.json` holds token lifetimes, storage paths,
industry options, roles and the SPEC §11 escalation contacts and SLAs. Every
value can be overridden by the environment variable named in its `env_overrides`
block, so nothing needs editing per environment.

Two settings are environment-only because they are secrets or per-deployment:

| Variable | Purpose |
|---|---|
| `INTAKE_ADMIN_API_KEY` | Required to create orgs. Unset means the endpoint refuses (fails closed). |
| `INTAKE_DATA_DIR` | Redirects all JSONL storage to one directory. |
| `INTAKE_CORS_ALLOWED_ORIGINS` | Comma-separated origins allowed to call the API from a browser. Defaults to `http://localhost:3000`. Never set this to `*`. |

The screens run on a different origin from the API, so the browser will refuse
every request unless that origin is listed. The policy is applied by
`intake/backend/app.py`; running `backend.app.main:app` directly is unaffected.

Storage defaults live under `local-data/`, which is gitignored — client data
never reaches the repository.

## What this deliberately does not decide

- **Boundary judgments.** Own/lease is captured as a raw fact.
  `ORG-050.operational_control_over_asset_flag` and `ORG-040.party_role` are left
  unset and recorded on each site as deferred to `BND-2.3`.
- **Vocabularies that do not exist yet.** `FAC-010.operational_status` and
  `PER-010.fiscal_year_basis` have no controlled vocabulary anywhere in
  `reference-data/` or `legacy-schemas/`, so they are free text flagged
  `provisional` and recorded against Todd for sign-off. Same for general-overlay
  site types, which the mapping defines for the film overlay only.
- **Datapoint states.** Phase C1 owns the state machine and back-fills
  `datapoint_states` from the seed submissions. Only
  `services/state_machine.py` may change a status, and every change is audited.
- **Whether a client has more than one legal entity.** No intake question
  establishes this today, so `BND-2.2` stays hidden behind a profile flag that
  defaults to false (the mapping's stated common case). Recorded as an
  `unresolved` condition in `config/applicability.json` rather than assumed.
- **Question wording.** Labels, questions and explainers are working copy;
  final plain-language copy follows the Vocabulary Library review (SPEC §10).
  The answer *shapes* are not placeholder - they define what is collected.
- **Nine answer lists with no source in the repo** (refrigerant gases,
  fire-suppression agents, industrial gases, vehicle types, instrument types,
  and others). These are free text flagged `provisional` for Todd rather than
  invented dropdowns. The screening questions themselves are yes/no, so the
  interview works regardless.

## Known limits

Pilot-grade, and worth stating plainly:

- Auth has no rate limiting, lockout or CSRF protection. The session token is
  held in `localStorage`; an httpOnly cookie is the right answer before real
  client exposure.
- JSONL storage is append-only and single-process. Concurrent writers need a
  real database — that swap only touches the repository layer.
- No real email provider is configured. The default `outbox` adapter writes
  messages to a local file and sends nothing.
- The intake screens render inside the existing internal sidebar shell; giving
  them their own full-page shell would mean restructuring the existing root
  layout.
- The screens use Tailwind v4, enabled by `frontend/postcss.config.mjs` and
  `@tailwindcss/postcss`. Tailwind's global reset (Preflight) is deliberately
  not imported, because the stylesheet loads inside that shared shell; a small
  reset scoped to `.intake` stands in for it. Existing pages import no CSS and
  are unaffected.

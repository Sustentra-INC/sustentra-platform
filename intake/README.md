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
| D1 | AI reading of typed answers, with playback and guardrails | done |
| D2 | Escalation queue screen, digest/reminder emails, SMTP adapter | done |
| E | Profile page + audit log + expected-document list | done |
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

# see what the escalation digests and reminders would say, sending nothing
python intake/scripts/send_escalation_notices.py --dry-run

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
| `POST /v1/intake/interview/parse` | Read a typed answer with the model. Proposal only; never written unconfirmed. |
| `GET  /v1/intake/review/queue` | Everything waiting on the team, oldest first. **Reviewers only.** |
| `GET  /v1/intake/review/escalations/{id}` | One question, with the client's attempts and the data point's history. |
| `POST /v1/intake/review/escalations/{id}/resolve` | Write the team's answer into the client's profile and email them. |
| `GET  /v1/intake/profile` | The living record: company, sites, every answer with who gave it. |
| `GET  /v1/intake/profile/history` | Every recorded change, oldest first. |
| `GET  /v1/intake/evidence-requests` | Documents expected from this client, with the Stage 5 safe-to-parse flag. |
| `GET  /v1/intake/evidence-requests/completeness-spec` | Expected counts per site, for S1's completeness gate. |

The three review routes require the `sustentra_reviewer` role and are the one
place org scoping is deliberately crossed: a reviewer sees every client's open
questions, which is the point of the queue. The check is explicit on each route.

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
- `/intake/review` — the team's queue of escalated questions (reviewers only)
- `/intake/review/{escalation_id}` — answer one, with the context to do it
- `/intake/profile` — the client's living record and its edit history

New pages only; no existing page, component or config is touched.

## Expected documents (Phase E)

The intake knows what documents a client should send; S1 knows what to do with
them when they arrive. Phase E builds the first half only — **there is no upload
endpoint and no file handling anywhere in `intake/`**, and S1 is untouched.

Each answer that establishes a source produces requests of *evidence type x
scope x period*, using the J2 evidence types already attached to every data point
in `config/profile_schema.json`. Saying "no, we have no generators" produces a
completeness record and no request at all.

Two rules the compiler will not break:

- **It never invents an expected count.** `config/evidence_cadence.json` sources
  exactly one cadence from the mapping — electricity, twelve months per meter
  (§6.1) — and ships every other type as `as_available`, flagged provisional for
  Todd. In the completeness spec those report `expected_documents: null`, never
  `0`, so a gate cannot mistake unknown for nothing-expected.
- **It says what S1 may safely start on.** Per SPEC Stage 5, a request is
  `safe_to_parse` only when nothing it rests on is still open — and a boundary
  decision covering its site must be human-confirmed first. A blocked request
  always carries the reason.

Requests are recompiled on every read. IDs are derived from identity rather than
generated, so recompiling updates the same record, keeps any status already set,
and writes nothing when nothing changed.

## Escalation emails

Three things happen when a client cannot answer a question (SPEC §3):

| When | Who gets it | How |
|---|---|---|
| A client is **stuck** — a contradiction, two failed attempts, or they asked for help | vivian@ and claire@ | Immediately, from the app |
| Any other escalation (mostly boundary answers a person must confirm) | vivian@ and claire@ | Batched into **one digest per client** |
| Still open past `reminder_hours` (12) | vivian@ and claire@ | One reminder, once |
| Answered by the team | the client's responsible party | Immediately, from the app |

The batching is a deliberate departure from "one email per escalation", approved
by the founder: every boundary answer is human-confirmed by design, so a two-site
client generates a dozen or more. An email apiece would bury the ones that matter.
Which triggers count as urgent is `escalation.urgent_triggers` in the settings —
a config change, not a code change.

Digests and reminders are sent by a command you run on a schedule:

```sh
python intake/scripts/send_escalation_notices.py --dry-run   # show, send nothing
python intake/scripts/send_escalation_notices.py             # digests and reminders
```

```
*/30 * * * * cd /path/to/sustentra-platform && python intake/scripts/send_escalation_notices.py
```

It is safe to run twice: each escalation is stamped when it is digested and again
when it is reminded about, and both jobs skip anything already stamped. Nothing
reaches a real person until an email adapter is configured — see below.

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
| `INTAKE_SMTP_USERNAME` / `INTAKE_SMTP_PASSWORD` | SMTP credentials. Environment only — never in a config file. |

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
- **How often a document should arrive.** Only electricity has a cadence in the
  mapping. The other eleven evidence types in use ship as `as_available` flagged
  for Todd, because how often a client's fuel is delivered is a fact about their
  operations, not a methodology rule.
- **The uncertainty roll-up.** The profile page reports the metered / invoiced /
  estimated basis per answer, which is the input ISO 14064-1 8.3 asks for. It does
  not roll those up into a category rating: that rule is PRV-8.2, HUMAN class.
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
- **No email leaves the machine by default.** The `outbox` adapter writes
  messages to a local file and sends nothing. An `smtp` adapter exists and is
  tested, but switching it on takes three deliberate steps: set
  `email.adapter` to `smtp`, set `INTAKE_SMTP_HOST`, and supply credentials in
  the environment. It refuses to start without a host rather than failing quietly.
- The intake screens render inside the existing internal sidebar shell; giving
  them their own full-page shell would mean restructuring the existing root
  layout.
- The screens use Tailwind v4, enabled by `frontend/postcss.config.mjs` and
  `@tailwindcss/postcss`. Tailwind's global reset (Preflight) is deliberately
  not imported, because the stylesheet loads inside that shared shell; a small
  reset scoped to `.intake` stands in for it. Existing pages import no CSS and
  are unaffected.

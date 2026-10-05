# MVP Priority Plan

**Audience:** engineering, product, ESG reviewers  
**Status:** tech-lead recommendation  
**Date:** 2026-09-17  
**Scope:** what to build next so `sustentra-platform` is actually usable as a Pilot 1 MVP

Related docs:

- Pilot definition: `docs/pilot_scope.md`
- Architecture: `docs/architecture_plan.md`
- Migration follow-up: `docs/migration_notes.md`
- S2 backend roadmap: `reference-data/methodology/s2_backend_pr_roadmap_and_collaboration_plan.md`

---

## 1. Executive verdict

The highest priority is **not** “set up the ORM.”

The highest priority is to make **one real reviewer complete the Pilot 1 loop in the UI**:

```text
create engagement
→ upload document
→ run extraction
→ review candidates with source snippets
→ save decisions
→ retrieve approved evidence
```

That loop is the MVP. Database work only matters insofar as it unblocks that loop.

The backend engines are ahead of the product. S1 parse / classify / extract / review / approve already exists. S2 methodology services also exist. What is missing is a durable product surface a non-engineer can use.

---

## 2. Current state

### 2.1 What is already real

- Local document upload into backend-controlled storage (`local-data/uploads/`).
- Pipeline orchestration: parse → classify → target plan → candidate generation.
- Review decision persistence and approved-evidence projection.
- S2 methodology services: completeness, derivation, verification, recompute, gap records.
- Versioned JSON Schema contracts under `contracts/`.
- Repository pattern with in-memory and JSONL implementations.

### 2.2 What is still a skeleton

- `POST /v1/engagements` always returns `eng_demo_001`.
- Processing-run and list/get-evidence endpoints return hardcoded demo payloads.
- There is **no candidate repository**. The pipeline returns candidates once; they then disappear except as snapshots inside review decisions.
- Next.js pages are static demo cards (`doc_demo_001`, `ev_demo_001`). Review controls are not wired.
- SQLAlchemy / Alembic / psycopg2 are in `backend/requirements.txt`, but `backend/app/adapters/persistence/database.py` is an unused shell.
- `docker-compose.yml` has no database service.
- No auth, no object storage, no job queue.

Runtime state today is append-only JSONL under git-ignored `local-data/`:

```text
local-data/documents/documents.jsonl
local-data/pipeline-runs/pipeline_runs.jsonl
local-data/review-decisions/review_decisions.jsonl
local-data/approved-evidence/...
```

The system can be smoked via curl and `/docs`. It cannot be used as an MVP by an ESG reviewer.

---

## 3. What not to do first

Do not start a greenfield “proper stack” pass. These are the usual ways this project stalls:

- Prisma on the frontend, or a second ORM
- Redis / Celery / workers
- S3 / cloud storage
- SSO / full auth
- RAG / assistant parity
- S2 UI, validation, calculation, or gap-page parity
- ORM-ing methodology workbooks, parser full text, or gap-ticket reports

Leave worker and S3 adapter shells as shells until a second concurrent engagement or a cloud deploy forces the issue.

---

## 4. Priority 0 — close Pilot 1 as a product

Pilot scope in `docs/pilot_scope.md` is already the right MVP definition. Treat the following as **one vertical slice**, not more isolated backend PRs.

### P0.1 Persist extraction candidates

This is the missing glue.

The review workspace must be able to reload candidates after the pipeline returns. Without a candidate store, the UI has nothing to review except whatever is still in the process-document HTTP response.

Add:

- candidate repository (in-memory + durable)
- list/get APIs by `document_id` / `evidence_id` / `field_name`
- enough parser/source-reference data to render snippets in the review UI

### P0.2 Make Engagement a real entity

Today it is a stub, so every other record is orphaned. Engagements must be created, listed, and fetched with real IDs and summary counts.

### P0.3 Replace fake lifecycle APIs

Make these return real data, not demo fixtures:

- evidence listing and get-by-id
- processing-run start and status (or equivalent pipeline-run polling)
- latest candidates for a document / evidence record
- approved evidence by engagement (already closer to real than the others)

### P0.4 Wire the Next.js pages

Connect existing routes to the real APIs:

| Route | Job |
|---|---|
| `/audit-setup` | create / select an engagement |
| `/evidence-intake` | real upload + trigger process |
| `/extraction-review` | candidates, snippets, accept / edit / reject / needs_more_evidence |
| approved-evidence view | list reviewed output by engagement |

`/validation`, `/calculation`, `/gap-analysis`, and `/assistant` stay placeholders.

### P0.5 One golden path

A utility bill. A handful of fields. A reviewer who is not an engineer. No curl.

Definition of done:

> An ESG teammate can create an engagement, upload a bill, review fields with source snippets, and see approved evidence — without opening FastAPI docs.

---

## 5. Persistence decision

JSONL got the engines built. It will not carry a review workspace.

Problems with the current store:

- five uncoordinated JSONL “databases”
- append-only updates (document status, latest decision)
- no transactions across candidates → decisions → approved evidence
- weak query support for a review UI (`candidates by document`, `latest decision by field`)

### Recommendation

Introduce **Postgres + SQLAlchemy 2 + Alembic now**, as part of P0, not as a separate “infra epic.”

Reasons:

- they are already the chosen stack in `requirements.txt`
- repository interfaces already exist (`InMemory*` / `Jsonl*`)
- engagements cannot exist without a real store
- a review UI needs relational queries and latest-row semantics

Add `SqlAlchemy*` repository implementations behind the current interfaces. Keep in-memory repos for tests. Do not add Prisma or any second ORM.

Add a Postgres service to `docker-compose.yml`.

### Minimal MVP schema

Persist only the S1 product loop:

| Table | Why it is MVP-critical |
|---|---|
| `engagements` | currently a stub |
| `documents` | already real, currently JSONL |
| `pipeline_runs` | status the UI can poll |
| `extraction_candidates` | **the gap** |
| `review_decisions` | already real, currently JSONL |
| `approved_evidence` | already real, currently JSONL |

### Keep out of Postgres for now

- uploaded file bytes — stay on disk at `local-data/uploads/`
- methodology xlsx / JSON libraries — stay versioned reference data
- full parser text dumps — files, not table blobs
- RAG chunks / vectors
- S3 metadata
- users / roles
- S3/S2 gap tickets and practitioner reports

### Mapping note

S1 field names (`activity_quantity`, `fuel_type`, `service_period_start`) are **not** yet aligned to methodology `Field_ID`s (`S1-STC-010`). Do not freeze a heavy schema around the current extraction field names. Keep candidate/review/approved values flexible enough (JSON columns where the field set still moves) so S2 mapping can land in P1 without a rewrite.

---

## 6. Priority 1 — after a reviewer can finish the loop

Do not start this until P0 is demonstrable.

1. Map S1 extraction fields onto official methodology `Field_ID`s. This mapping mismatch is the real S2 risk, not missing formulas.
2. Run S2 from **persisted** approved evidence, not a posted JSON blob to `/v1/methodology/s2/run`.
3. One Scope 1 happy-path completeness / gap view. Not the full rule catalog.
4. Simple reviewer identity. A `reviewer_id` plus a shared-pilot password is enough. Full SSO is later.

S2 already has a PR-sized backend plan (`S2-PR1` through `S2-PR14`). Most of those engines exist. The remaining product work is connecting them to durable approved evidence and a human-readable output, not rebuilding the engines.

---

## 7. Explicitly later (P2+)

- Authentication and authorization hardening
- Cloud object storage (S3 / Azure Blob / GCS)
- Queues, workers, and production orchestration
- Assistant / RAG as an explanation layer
- Validation, calculation, and gap-analysis UI parity
- Materiality, practitioner wording, and S3 gap-ticket aggregation

RAG is a read/explanation layer, not the core verification engine. It should not lead the MVP.

---

## 8. Suggested build order

Protect the vertical slice. No new methodology PRs until the UI loop is real.

```text
1. Candidate persistence + list/get APIs
2. Real Engagement entity + APIs
3. Postgres + Alembic behind existing repositories
     (engagements, documents, pipeline_runs,
      extraction_candidates, review_decisions, approved_evidence)
4. Replace remaining stub lifecycle APIs
5. Wire /evidence-intake (upload + process + status)
6. Wire /extraction-review (candidates, snippets, decisions)
7. Show approved evidence by engagement
8. ESG reviewer dry-run on one utility-bill golden path
```

If a choice appears between “more S2 correctness” and “reviewer can finish the loop,” choose the loop.

---

## 9. MVP-ready bar

The platform is MVP-ready when all of the following are true:

- [ ] An engagement can be created and reused; IDs are not hardcoded.
- [ ] A document can be uploaded from the UI and processed without a server-local file path.
- [ ] Extraction candidates persist and can be reloaded in `/extraction-review`.
- [ ] Every reviewed field shows a source snippet.
- [ ] Accept / edit / reject / needs_more_evidence persist and survive refresh.
- [ ] Approved evidence can be listed by engagement in the UI.
- [ ] An ESG reviewer can complete the golden path without FastAPI docs or curl.

It is **not** MVP-ready because parsers, S2 engines, or SQLAlchemy imports exist.

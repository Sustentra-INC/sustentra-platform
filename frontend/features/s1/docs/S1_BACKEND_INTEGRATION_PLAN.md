# S1 Backend Integration Plan

This is the next implementation stage after the fixture-driven S1 frontend
review candidate.

## Objective

Move the same S1 UI from fixture mode to backend mode so testers can run the
actual pipeline:

```
Create project
-> upload document
-> processing
-> extraction
-> review
-> correction / manual entry
-> refresh
-> see persisted state and original document
```

Fixtures remain available for visual review and regression testing. Backend mode
must not silently fall back to fixtures unless the environment is explicitly set
to fixture mode.

## Data Modes

The S1 page now chooses data mode at runtime:

```
NEXT_PUBLIC_S1_DATA_MODE=backend | fixture
NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8000
```

Rules:

- `backend`: default; load backend data through API modules and adapters.
- `fixture`: opt-in; load S1 fixtures only for visual review/regression checks.
- Backend mode renders degraded/dependency-blocked states for unsupported
  backend features.
- Components continue to consume S1 view models only.

## Required Persistent Storage

The current implementation uses backend JSONL repositories plus local upload
storage for a real local smoke-test pipeline:

- `local-data/documents/documents.jsonl`
- `local-data/pipeline-runs/pipeline_runs.jsonl`
- `local-data/extraction-results/extraction_results.jsonl`
- `local-data/review-decisions/review_decisions.jsonl`
- `local-data/uploads/...`

Shared pipeline testing still needs durable storage for concurrent users. Target
architecture:

```
Frontend
  -> Backend API
      -> PostgreSQL or equivalent persistent DB
      -> MinIO/S3-compatible object storage
      -> Extraction pipeline
```

Minimum persistent objects:

- Project / engagement
- Facility config
- Document metadata
- Uploaded document object
- Pipeline run
- Extraction result / extracted field
- Review decision
- Audit event
- User / actor

## Backend Work Items

### 1. Project / Engagement Persistence

Create or confirm endpoints for:

- create project / engagement
- list projects / engagements visible to actor
- get project / engagement config
- update engagement config if needed

Persist:

- client name
- engagement ID
- reporting period
- regulation
- assurance level
- boundary approach
- scope-boundary statement
- facilities

### 2. Document Storage

Uploaded documents must remain viewable after refresh and across users.

Backend needs:

- object storage write on upload
- stable storage URI
- document metadata row
- download/view endpoint

Status: local upload storage and `GET /v1/documents/{document_id}/download`
exist.

Suggested metadata:

```
documents
  document_id
  engagement_id
  filename
  mime_type
  uploaded_by
  uploaded_at
  processing_state
  storage_uri
  evidence_class
```

Object storage options:

- MinIO for local/staging
- S3-compatible storage for hosted environments

### 3. Pipeline Persistence

Persist pipeline state transitions:

```
not_ingested
ingested
typed
extracted
blocked
```

Backend may use its own internal vocabulary, but adapters must map it into S1
vocabulary before rendering.

Persist:

- pipeline run ID
- document ID
- stage statuses
- started/completed timestamps
- parser/classifier/extractor artifacts
- halt/error reasons

Status: local pipeline summary persistence exists.

### 4. Extraction Result Persistence

Persist extracted fields so Extraction Review can reload after refresh:

```
extracted_fields
  field_result_id
  document_id
  canonical_type_id
  backend_field_id
  value
  unit
  value_origin
  value_properties
  source_snippet
  source_context
  source_location
  review_status
```

Source location can remain null; UI must render `page location not available`.

Status: local extraction-result persistence and latest-result read endpoints
exist:

- `GET /v1/documents/{document_id}/extraction-result/latest`
- `GET /v1/evidence/{evidence_id}/extraction-result/latest`

### 5. Review Decision Persistence

Review actions need persistent storage:

- accept value
- correct value
- manual entry

The existing review-decision repository is a starting point. Confirm it supports
reload-after-refresh and shared environment semantics.

Status: accept/correct/manual entry submit review decisions in backend mode, and
the frontend loader replays latest saved decisions on refresh.

### 6. Audit Event Persistence

Do not enable audit-required writes until audit events survive restart.

Audit events must include:

- event ID
- document ID
- field key when applicable
- action
- old value
- new value
- actor
- timestamp
- source action/correlation ID for bulk operations

Bulk operations must persist one event per affected item, never one event for the
batch.

Audit-required S1 actions:

- accept detected type
- change type
- assign facility
- assign period
- bulk accept type
- re-extract
- accept value
- correct value
- manual entry

## Frontend Work Items

### 1. API Modules

Create S1 API modules under `frontend/features/s1/api/`.

Status: `s1Backend.ts` now wraps document listing, upload, processing,
extraction result loading, document download URL generation, and review
decision submission. It can be split into narrower files when the surface grows.

### 2. Adapter Expansion

Expand adapters under `frontend/features/s1/adapters/`:

- `engagementAdapter.ts`
- `evidenceAdapter.ts`
- `processingAdapter.ts`
- `classificationAdapter.ts`
- `fieldAdapter.ts`
- `reviewAdapter.ts`
- `auditAdapter.ts`

Adapters are the only place backend DTOs become S1 view models.

### 3. Data Hooks

Create hooks:

- `useS1Engagement`
- `useS1EvidenceWorkspace`
- `useS1ExtractionReview`
- `useS1Upload`
- `useS1ReviewActions`

Hooks select fixture or backend mode through the data-mode accessor.

### 4. Upload Flow

Replace the visual-only upload area in backend mode:

- choose files
- call backend upload endpoint
- persist document metadata and object
- start or queue pipeline processing
- refresh Evidence Workspace from backend state

Upload must not ask for facility, period, or type.

Status: implemented for backend mode. Upload persists the document and runs
processing, then refreshes the workspace from backend state.

### 5. Document Viewing

The Source pane download/view action should call the backend document endpoint and
retrieve the original uploaded object.

Status: implemented through the backend download endpoint.

If original document retrieval fails, render a degraded state naming what failed
and what remains unaffected.

### 6. Backend Mode Write Policy

Until audit persistence exists:

- backend reads may be enabled
- upload may be enabled if document storage is persistent
- audit-required actions must remain intent-only or dependency-blocked

Current split:

- review value decisions persist through the review API
- type/facility/period/audit-required workspace changes remain local intents
  until audit event persistence is implemented

After audit persistence exists:

- write actions call audit/review APIs
- local UI updates only after successful persistence or with explicit pending
  state
- refresh must show the saved result

## Acceptance Tests For Backend Mode

Run before inviting testers:

1. Create project -> refresh -> project remains.
2. Upload document -> refresh -> document remains.
3. View original document -> original opens/downloads.
4. Process document -> refresh -> pipeline state remains.
5. Extraction finishes -> refresh -> extracted fields remain.
6. Accept value -> refresh -> accepted state remains.
7. Correct value -> refresh -> correction remains and machine value is retained.
8. Manual entry -> refresh -> value remains marked human-keyed.
9. Bulk accept type -> audit event count equals selected document count.
10. Second tester can see only permitted project/data.

## Non-Goals For This Stage

- Do not hide backend gaps.
- Do not fake audit persistence in localStorage.
- Do not connect unsupported fields by guessing.
- Do not remove fixture mode.

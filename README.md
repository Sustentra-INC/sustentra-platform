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

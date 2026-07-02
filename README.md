# Sustentra Evidence Extraction Product Skeleton

This repository is the production-oriented skeleton for the Sustentra evidence extraction product.

## Repository Intent

- The Next.js frontend and FastAPI backend in this repository are the forward product architecture.
- The old Streamlit demo exists locally under `demo_package/` and is intentionally ignored.
- Preserved schemas, JSON libraries, and fixtures are copied into versioned folders for migration safety.

## Preserved Reference Assets

- Legacy schemas: `legacy-schemas/copied_from_streamlit_demo/`
- Reference JSON libraries and config: `reference-data/`
- Demo fixtures: `demo-fixtures/mock_outputs/`
- Legacy docs snapshot: `docs/legacy_streamlit_demo/`

## Pilot Scope

The first pilot focuses on evidence extraction and human review:

1. Upload evidence documents.
2. Run extraction and source traceability.
3. Review and approve fields.
4. Persist approved evidence records.

Validation, calculation, and gap analysis remain deferred or demo-only until powered by approved evidence.

## Local Development Skeleton

- Frontend: `frontend/` (Next.js app router skeleton)
- Backend: `backend/` (FastAPI skeleton)
- Contracts: `contracts/` (JSON Schemas, draft 2020-12)
- Docs: `docs/` (plan, pilot scope, API and migration notes)

## Next Milestones

- Wire backend routers to real storage and parser adapters.
- Connect frontend review workflow to backend pilot endpoints.
- Align downstream validation/calculation/gap schemas with approved evidence outputs.

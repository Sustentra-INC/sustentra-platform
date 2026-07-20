# Approved Evidence Projection (PR8)

PR8 adds the backend projection layer that turns persisted PR7 review decisions into downstream approved evidence records:

review_decisions -> approved_evidence

Approved evidence is the source of truth for later validation, calculation, reconciliation, and gap analysis stages.

## What PR8 adds

- Strict ApprovedEvidence contract in contracts/approved_evidence.schema.json.
- Strict Pydantic models for approved evidence aggregates and fields.
- Approved evidence repositories:
  - In-memory for tests.
  - JSONL persistence under local-data/approved-evidence/approved_evidence.jsonl.
- Projection service that:
  - reads review decisions,
  - selects the latest decision per field,
  - includes only accepted and edited field decisions,
  - persists projected approved evidence.
- API endpoints for projection and retrieval.

## ReviewDecision vs ApprovedEvidence

- ReviewDecision.reviewed_value is the reviewer action record from PR7.
- ApprovedEvidence.approved_value is the downstream source-of-truth value projected in PR8.

PR8 intentionally keeps these concepts separate.

## Inclusion and exclusion rules

Projection keeps only latest field decisions where decision is one of:

- accepted
- edited

Projection excludes latest field decisions where decision is one of:

- rejected
- needs_more_evidence

If a field was accepted earlier but later rejected, the field is excluded because latest-decision wins.

## Latest decision per field rule

For each field_name in one evidence/document projection:

- Sort by reviewed_at timestamp.
- If timestamps tie, later input order wins.
- Keep only that latest decision for status and inclusion evaluation.

## Review status outcomes

- in_review: no review decisions provided.
- no_approved_fields: latest decisions exist but none are accepted/edited.
- approved: all latest decisions are accepted/edited and at least one field exists.
- partially_approved: mix of approved and non-approved latest decisions.

## Local persistence

PR8 persists approved evidence locally in JSONL:

- local-data/approved-evidence/approved_evidence.jsonl

Review decisions remain in:

- local-data/review-decisions/review_decisions.jsonl

Both locations are under local-data/, which is git-ignored.

## API endpoints

- POST /v1/evidence/{evidence_id}/approved-evidence/project
- GET /v1/evidence/{evidence_id}/approved-evidence/latest
- GET /v1/approved-evidence/{approved_evidence_id}
- GET /v1/engagements/{engagement_id}/approved-evidence

Projection request body:

- engagement_id
- evidence_type

## Out of scope for PR8

PR8 does not implement:

- validation
- calculation
- reconciliation
- gap analysis
- frontend review UI
- RAG
- S2 methodology rules
- live OCR/Textract/OpenAI calls

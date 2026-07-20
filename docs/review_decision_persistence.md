# Review Decision Persistence (PR7)

PR7 adds the backend layer that lets a human reviewer make and persist a decision
on a PR6 extraction candidate:

```
extraction_candidate + reviewer action → persisted review_decision
```

It does **not** create approved evidence. Approved evidence projection is PR8.

## Three distinct concepts

```
ExtractionCandidate = machine suggestion (PR6)
ReviewDecision      = human action on that suggestion (PR7, this layer)
ApprovedEvidence    = downstream accepted/edited field record, created later (PR8)
```

A `ReviewDecision` deliberately uses `reviewed_value` / `reviewed_unit` (the
reviewer's action), **not** `approved_value` / `approved_unit` (which belong to
approved evidence in PR8).

## Decision enum semantics

| decision | reviewed_value / reviewed_unit |
|----------|--------------------------------|
| `accepted` | taken from the candidate's `normalized_value` / `unit`; providing a different value/unit raises `ValueError` (use `edited`) |
| `edited` | `reviewed_value` is **required**; `reviewed_unit` optional; reviewer-provided values are stored |
| `rejected` | both must be null; providing either raises `ValueError` |
| `needs_more_evidence` | both must be null; providing either raises `ValueError`; a reviewer note is encouraged but optional |

## candidate_snapshot purpose

Because there is no candidate repository yet, each review decision stores a deep
copy of the reviewed candidate in `candidate_snapshot` and a deep copy of its
`source_reference`. This makes every decision self-contained and auditable even
if the candidate is later regenerated. The service never mutates the input
candidate.

## Local JSONL persistence

The default file-backed repository writes one JSON object per line to:

```
local-data/review-decisions/review_decisions.jsonl
```

The entire `local-data/` tree is git-ignored — review decisions are local
runtime state and are never committed. Two repositories are provided:

- `InMemoryReviewDecisionRepository` — transient, used in tests;
- `JsonlReviewDecisionRepository` — appends to a JSONL file and reads it back,
  so data survives repository re-instantiation.

Both support: `save`, `list_all`, `list_by_evidence`, `list_by_document`,
`list_by_candidate`, `get_latest_by_candidate`, `get_latest_by_field`.

## API endpoints

- `PUT /v1/evidence/{evidence_id}/fields/{field_name}/review` — persist a
  decision. Body: `candidate`, `decision`, `reviewer_id`, optional
  `reviewed_value`, `reviewed_unit`, `reviewer_note`. The candidate's
  `evidence_id` and `field_name` must match the path (otherwise `400`).
  Legacy `reviewed_by` / `approved_value` / `approved_unit` are accepted as
  input aliases, but the response always uses `reviewer_id` / `reviewed_value` /
  `reviewed_unit`.
- `GET /v1/evidence/{evidence_id}/reviews`
- `GET /v1/documents/{document_id}/reviews`
- `GET /v1/candidates/{candidate_id}/reviews/latest` (`404` if none)

No authentication is added in PR7, and no approved evidence is created in any
response.

## What remains for PR8

PR8 will project accepted/edited review decisions into `approved_evidence`
records (using `approved_value` / `approved_unit`), which become the downstream
source of truth for calculation and reconciliation.

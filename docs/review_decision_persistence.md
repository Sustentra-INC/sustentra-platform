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

## Add-only, and the audit trail

A decision is never changed or removed. A changed mind is a new decision and the latest one wins
(`seq` in Postgres, file order in the JSONL file).

- **Postgres** (migration 0025): the app role `app_user` has SELECT and INSERT on `s1_review_decisions`;
  UPDATE, DELETE and TRUNCATE are revoked, and the RLS policy is split into a SELECT and an INSERT policy
  (as on `audit_logs`). The table's only foreign key is `org_id -> organizations ON DELETE RESTRICT`, so no
  cascade reaches it. Anything that needs more (a repair) is done by the migration/owner role, by hand.
  `import-s1-stores` therefore adds decision lines but never updates a stored one: a line changed since it was
  imported is counted as "changed since imported" and the row is kept. Claim (`claim-s1-data`) before importing.
- **JSONL**: appended one line per decision. Only `claim-s1-data` rewrites that file (stamping an owner on
  unowned lines, after a `.bak-<timestamp>` copy), as the operator's OS user, before the cutover.
- **Audit event**: every decision written by `PUT /v1/evidence/{id}/fields/{field}/review` adds one
  `audit_logs` event: `review_value_accepted`, `review_value_edited`, `review_value_rejected` or
  `review_value_more_evidence_requested`. It holds ids only (organization, actor, engagement as the target,
  and in the metadata the decision, review decision, candidate, field, document, evidence and pipeline run
  ids), never the value, unit, note or file name. With Postgres the event is inserted in the decision's own
  transaction (`S1_STORE=postgres`, and `postgres+jsonl`, where the file copy follows the commit): both
  are saved or neither, and a failure is returned to the caller. With `S1_STORE=jsonl` the decision is
  appended first and the event written after in its own transaction; if that fails the decision stays
  and an ERROR (`sustentra.review_audit`, with the decision's ids) is logged.
- A double submit adds two decisions and two events, as before (each submit has its own decision id).

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

# Pilot API Contract

## Endpoints

### POST /v1/engagements
Create an engagement shell for document and evidence lifecycle.

### GET /v1/engagements/{engagement_id}
Fetch engagement metadata and summary counts.

### POST /v1/engagements/{engagement_id}/documents
Register an uploaded document for processing.

### POST /v1/engagements/{engagement_id}/documents/upload
Upload a file and register it as a document (multipart: `file`, `document_role`, and optionally
`evidence_id` and `document_type`). Answers with the document; what it carries depends on `S1_PROCESSING`:

- `S1_PROCESSING=inline` (the default): 200 with the document, `processing_status` `not_started`, and no
  `processing_run` key. The read is asked for separately (`POST /v1/documents/{document_id}/processing-runs`).
- `S1_PROCESSING=queued`: 200 with the document, `processing_status` `queued`, and `processing_run`: the run the
  upload queued for the first read (`status` `queued`, `attempt` 0, as `GET /v1/processing-runs/{run_id}` returns it).
- If that run can't be queued, the upload still succeeds: 200 with the document as in inline mode. The server logs
  `upload_read_not_queued` on `sustentra.processing` with the document id, and the client asks for the read itself
  with `POST /v1/documents/{document_id}/processing-runs`.

Refusals are unchanged: 400, 404 (unknown evidence), 413 (file over the size limit) and 415 (a file type no reader opens).

### GET /v1/engagements/{engagement_id}/documents
List documents under an engagement.

### GET /v1/documents/{document_id}
Get one document record and processing status.

### POST /v1/documents/{document_id}/processing-runs
Ask for the document to be read (org_admin / org_member). Body, all optional:
`{"canonical_type_id_override": null, "include_optional": true, "include_deprecated": false}`.
Returns a ProcessingRun (`contracts/processing_run.schema.json`):

- `S1_PROCESSING=inline` (the default): the document is read in this request; 200 with the
  finished run (`completed`, or `failed` with `error_code` and the user-facing `error`).
- `S1_PROCESSING=queued`: the run is only queued; 202 with `status: "queued"`, and the
  document's `processing_status` becomes `queued`.
- A document has one active (queued or in_progress) run at a time: asking again returns that
  run (202); asking for a different type while it is active is a 409.
- 404 for a document of another organization, 400 when its stored file is missing, 403 for
  provider_admin.

### GET /v1/processing-runs/{run_id}
One processing run; 404 when it belongs to another organization.

### GET /v1/engagements/{engagement_id}/processing-runs
`{"engagement_id", "items"}`: each document's latest run in the engagement. The call to poll
while reads are queued or in progress.

### POST /v1/documents/{document_id}/pipeline/process
Older call: reads the document now, through the same executor (recorded as a processing run),
and answers with the pipeline's result, or 400 / 404 / 409 / 422 / 500.

### Methodology review (`/v1/engagements/{engagement_id}/methodology-review`)
The reviewer's decisions on the client's stated boundary and methods. Each decision field is one
`workpaper_items` row (kind `methodology`, `item_key` = field id), created on its first action.
`PUT .../workpaper-items/methodology/{key}` is refused (422): decisions change only through the actions below.

- `GET` (s1_reader; a provider_admin reads) answers
  `{"fields": [record...], "catalog": [def...], "groups": [{group, label}], "row_groups": [...], "ai": {...}}`.
  - `record`: `{field_id, suggestion, decision, history}`, and `user_added` (boolean; only rows the reviewer added can be deleted). A catalog def's `user_added` is the same
    flag as its record's. Reverting a reviewer-added row restores its blank value; at most 200 rows can be added
    per engagement (409 with a sentence). `GET .../workpaper-items?kind=methodology` lists the same record shape
    and skips removed rows.
    `suggestion` is `null` or `{value, quote, document_id, file_name, source_reference, origin: "ai", model,
    request_id, suggested_at}`. `decision` is `null` (pending) or `{status: pending|accepted|edited|rejected,
    value, reason?, by: {name, login}, at}`; a rejected decision has `value: null`. `history` is
    `[{at, by, action, to?}]` (the newest 50 events, fewer if the record would pass 32 KB; the audit log keeps the
    full trail), `action` one of accept, edit, reject, revert, add_row, remove_row.
  - `catalog`: `{field_id, group, group_label, label, kind: text|enum|entity|factor|gwp, allowed?, parts?, user_added}`, in page order: the fixed
    fields (reporting_period, consolidation_approach, `category:{scope1|location|market|biogenic}:...`,
    `exclusion:{boundary|inventory|materiality}`, gwp, `calculation:{approach|process}`), then the rows the
    reviewer added. `allowed` is a list for an enum, `{set, horizon}` for gwp (with `allowed_labels.set`),
    `{operational_control}` for an entity. `parts` (entity, factor, gwp only) lists the value's editors,
    `[{key, label, kind: text|list|percent|enum, allowed?}]`, so a blank new row can be drawn.
  - Values by kind: text is a string (at most 2000 characters, no null characters); enum one of `allowed`; gwp `{set, horizon}`;
    factor `{database, edition}`; entity `{name, facilities: [string], equity_share_pct, financial_control,
    operational_control}` (percents 0 to 100).
  - `ai`: `{enabled, reason_code, reason}`: `reason_code` is `off`, `not_configured`, `cap_reached`, `no_documents`, `not_built` or
    `null` and `reason` a sentence; until suggestions are built it is `not_built`. Later also provider, model, month spend and cap.
- `POST .../{field_id}/accept` takes the suggestion's value, or the value already set. `POST .../{field_id}/edit`
  `{value}`. `POST .../{field_id}/reject` `{reason}` (required, at most 500 characters). `POST
  .../{field_id}/revert` returns to pending. Each answers the updated record. Accept and reject only work from
  pending; edit works from any state; revert from any decided state.
- `POST .../rows` `{group: "entities"|"factor:scope1"|"factor:scope2"}` adds a row under a server-made id (201, the new record plus `field`, its catalog def). `DELETE .../{field_id}` removes a row the reviewer added (answers the record with `removed: true`); the
  row is marked removed, not deleted. A field from the report answers 409 "Reject it instead".
- Writes are s1_writer on an open engagement: another org 404, provider_admin 403, archived 409. A move the
  state does not allow is 409 and bad input 422, both with a sentence in `detail`; an unknown field is 404.
  Bodies forbid unknown fields; who acted and when come from the session. Each action writes one
  `methodology_decision` audit event with the field id, action and status only.

### GET /v1/engagements/{engagement_id}/evidence
List evidence entities produced under the engagement.

### GET /v1/evidence/{evidence_id}
Get one evidence record including candidate and review summary.

### PUT /v1/evidence/{evidence_id}/fields/{field_name}/review
Persist reviewer decision for a candidate field.

### GET /v1/engagements/{engagement_id}/approved-evidence
Return evidence records and approved fields only.

## Contract Source

JSON schema contracts are versioned in `contracts/` and should be treated as API truth for request/response payload shape.

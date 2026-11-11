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
  - `ai`: `{enabled, reason_code, reason, provider, model, month_spend_usd, cap_usd}`. `enabled` is true when
    Claude can be asked now; otherwise `reason_code` is `off` (AI_SUGGESTIONS_ENABLED is false), `not_configured`
    (no Claude client: no key or Bedrock region), `cap_reached` (this organization's spend this UTC month is at
    or over AI_MONTHLY_CAP_USD) or `no_documents` (no document whose latest type is a client-prepared summary
    type), and `reason` is the sentence to show; both are `null` when enabled. Checked in that order.
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
- `POST .../prefill` (s1_writer, open engagement, no body) asks Claude to propose values from the engagement's
  client-prepared summary documents (latest type in `calculation_lines.SUMMARY_TYPES`; at most 5 documents,
  1,500 lines and 150,000 characters, taken in document order). One synchronous call. Answers
  `{suggested, dropped: {reason: count}, kept_reviewer_decision, documents_read: [{document_id, file_name,
  truncated}], cost_usd, model}`.
  - Claude only suggests: each kept suggestion is written to the field's record `suggestion` (the shape above;
    `source_reference` is the parser's reference for the quoted line; a quote over 1,000 characters is stored cut
    with `quote_truncated: true`, after it was verified whole) and nothing else changes. Fields the
    reviewer has decided (accepted, edited, rejected) are left alone and counted in `kept_reviewer_decision`;
    a pending field's older suggestion is replaced. An entity or factor source Claude finds becomes a new
    record under a server-made id with `user_added: false`, unless a row with the same name (entity) or the
    same database and edition (factor) is already on the page.
  - A suggestion is kept only if its quote is printed on the cited line of the cited document and, for
    percentages and a factor edition with digits, the number is printed in the quote. `dropped` keys are
    exactly: `empty_value`, `unknown_line`, `quote_not_on_document`, `ambiguous_quote`, `value_not_in_quote`
    (from the locator), `unknown_document`, `invalid_value` (failed the field's validation) and `unknown_field`.
  - 409 with a sentence in `detail`: switched off, not configured, over the monthly limit (the `ai.reason`
    sentences), no documents ("Upload the company's GHG inventory report, boundary statement or methodology
    document first."), documents unreadable, or Claude refused or its answer was cut short or unusable (nothing
    is kept). 502 when Claude could not be reached.
  - Every call that was made is one row in `ai_usage` (outcome, tokens, cost, request id), refused or invalid
    ones included; a refused call before the request is not. One `methodology_prefill` audit event with outcome,
    counts and cost only.

### GET /v1/engagements/{engagement_id}/evidence
List evidence entities produced under the engagement.

### GET /v1/evidence/{evidence_id}
Get one evidence record including candidate and review summary.

### PUT /v1/evidence/{evidence_id}/fields/{field_name}/review
Persist reviewer decision for a candidate field.

### GET /v1/engagements/{engagement_id}/approved-evidence
Return evidence records and approved fields only.

### GET /v1/engagements/{engagement_id}/evidence-tree[?facility_id=<id>]
Every document of the engagement filed into the Evidence page's tree (reader; another org's
engagement is 404). Nothing is stored by this route.

```
{ blocks: { summary: [DocRow], summary_counts: counts,     // Block 1: summary documents and workbook
            unassigned: [DocRow], unassigned_counts: counts, // Block 2: no document type yet
            supporting: { scopes: [{scope, label, counts,    // Block 3, scopes s1 / s2 / biogenic
                          categories: [{category, label, counts,
                            level2s: [{level2, label, counts,
                              lines: [{line: CalculationLine, counts, documents: [DocRow]}]}]}]}],
                          unassigned: [DocRow], unassigned_counts: counts } },
  facilities: [{facility_id, name, address}],        // the engagement's Setup facilities
  lines: [CalculationLine],                          // system lines, then reviewers' own
  vehicle_groups: [{anchor_id, label, fuel}],        // settings.recalculation.vehicle_groups, with the
                                                     // anchor_id a mobile line (anchor_kind "vehicle_group") uses
  anchors_for_contractual: "company",                // a contractual line uses anchor_kind "company", this anchor_id
  set_aside: [{document_id, file_name, reason}] }    // withdrawn / duplicate / superseded: not filed
counts  = {documents, values, accepted, to_review, issues, pct_accepted}
DocRow  = {document_id, file_name, period_start, period_end, facility_id, facility_name,
           processing_status, detected_type, also_in: [lineKey], values, accepted,
           placement_from,   // send this as a move's "from" to move this row
           flags: []}        // "unknown_line": it was moved to a line that no longer exists
```

`CalculationLine = {key, scope, category, level2, level2_label, anchor_kind
("facility" | "vehicle_group" | "company"), anchor_id, label, facility_id | null,
created_by_user}`. The key is `<scope>:<category>:<level2-slug>:<anchor-slug>` (for example
`s1:stationary:natural-gas:fac-kc01`) and is built only by `calculation_lines.line_key`.
A document whose records map to several lines is listed under each, with only that line's
values counted. Every `counts` (block, scope, category, level 2, line) is computed by the server:
`documents` is distinct documents, and values are counted once per record however many places show
it, so nothing is double-counted; the client never adds counts up.

`?facility_id=<facility_id>` shows only placements at that Setup facility: rows whose `facility_id`
matches and lines whose `facility_id` matches (vehicle-group and company lines have none, so they are
left out), at every level, and all counts (including `issues`) are recomputed for that view.
`facilities`, `vehicle_groups` and `set_aside` are not filtered. A row's `facility_id` is its line's
facility, else the Setup facility of the records shown (null when none matches). Categories (fixed): stationary, mobile, fugitive, process (Scope 1);
purchased_energy, contractual (Scope 2); biogenic.

Where a record goes by default: the canonical type gives the category (a biomass fuel goes to
biogenic); the level 2 is the EPA fuel the recalculation resolves, electricity, steam /
heating / cooling, or the refrigerant; the anchor is the document decision's `facilityId`, else
the Setup facility matched by name or address (mobile: the one vehicle group that uses the
fuel). A record with a category but no level 2 or anchor, or a type with no line, is filed
under "Unassigned supporting evidence". Summary types (`calculation_lines.SUMMARY_TYPES`) go
to Block 1. For every level 2 that has a record, one line per Setup facility (per vehicle
group for mobile) exists (`created_by_user: false`).

**Moving documents.** Moves are stored in the document's workpaper item (kind `document`,
key = document id) under `payload.placements`: `[{"from": <line key | "block:summary" |
"block:unassigned" | "supporting:unassigned">, "to": <line key | the same fixed names>}]`,
applied in order to the default placements, one placement at a time. Send the row's
`placement_from` as `from`: a document filed under "Unassigned supporting evidence" because its
line was deleted has `placement_from: "supporting:unassigned"`, and a move from that moves every
placement shown there. A move whose `from` the document no longer has is ignored. A move to a line that does not exist files the document under
"Unassigned supporting evidence" with the flag `unknown_line`. The PUT replaces the whole payload:
**read the item, merge `placements` into it, keep every other key** (`facilityId`, `disposition`,
`relationships`, ...).

**Settings are replaced whole.** PATCH `/v1/engagements/{id}` replaces `settings` as a whole, so a
client that changes any setting must send `evidenceLines` back too (read it, change it, send it all),
or the reviewers' lines are lost.

**Reviewers' own lines** are saved in `settings.evidenceLines` through PATCH
`/v1/engagements/{id}`: `[{key?, scope?, category, level2?, level2_label, anchor_kind,
anchor_id?, label}]` (at most 200; labels at most 120 characters; `category` one of the fixed
list). The server fills in `key` (and `level2`, the slug of `level2_label`); a `key` that is
given must equal `line_key(...)`. A line the system already creates is refused with 422 (the
system's lines are not stored here and cannot be deleted).

### GET /v1/engagements/{engagement_id}/calculation-lines/{line_key}/schedule
One calculation line's schedule (reader; 404 with a plain message for an unknown line key, and
for another org's engagement).

```
{ line: CalculationLine, reporting_period: {start, end},
  coverage: [{month: "YYYY-MM", status: "counted" | "counted_in_part" | "not_reviewed" | "no_document",
              quantity, unit, document_ids, flags: []}],   // flags: "unconverted"
  identifiers: [{label, value, documents_with, documents_total}],   // facility, service address, account, meter
  values: [{service_period_start, service_period_end, days, quantity, unit, document_id, file_name,
            page, candidate_id, decided_by, decided_at, decision}],
  history: [{at, text}] }                                            // newest first
```

A month is `counted` when accepted values cover all its days, `counted_in_part` when they cover
some, `not_reviewed` when a document covers it but no accepted value does, and `no_document`
otherwise; the first and last month count only days inside the reporting period. A value's quantity is
spread evenly over its service period; a month with a value in a unit that cannot be added to the rest is
`counted_in_part` with the flag `unconverted`, and a month with no numeric quantity has `quantity: null`. `decided_by` is the
reviewer's name (their login when no name is on file).

## Contract Source

JSON schema contracts are versioned in `contracts/` and should be treated as API truth for request/response payload shape.

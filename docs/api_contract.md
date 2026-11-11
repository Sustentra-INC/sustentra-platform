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
  history: [{at, text}],                                             // newest first
  // schedule v2 (Claire's supporting-schedule spec); the keys above are unchanged
  rows: [{record_key, record_index, accepted,        // one row per record (document + period + meter)
          date: {start, end, days, label},           // label: "Service period" | "Transaction date" | "Service date"
          activity_quantity: {value, unit},          // the extracted value; the reviewed value once accepted
          cells: {<column_key>: {value, unit}},      // only the extra columns this row has a value for
          saved_by: {name, at} | null,               // who accepted or edited the quantity; null when not reviewed
          document_id, file_name, page, candidate_id}],
  columns: [{key, label, unit_in_cells: true}],      // date, activity_quantity, then (only when a row has a value,
                                                     // accepted or not) heat_content, carbon_content,
                                                     // vehicle_type, model_year, on_or_non_road, distance
  activity_quantity_note: string | null,             // "Activity quantity: fuel quantity combusted" ...
  identifier_groups: [{label, values: [{value, documents: [{document_id, file_name, matched_by?}]}],
                       not_found: [{document_id, file_name}], documents_with, documents_total,
                       matched_by?: [string]}] }     // matched_by on Facility only
```

`rows` lists every extracted record on the line, accepted or not. A row with `accepted: false` is present
but flagged; only accepted values feed the calculation, as before. The extra columns read the extracted
fields `heat_content`, `carbon_content`, `vehicle_type`, `model_year`, `on_or_non_road` and `distance`;
no extractor produces them yet, so today a line shows only Date and Activity quantity. `identifier_groups`
group the line's documents by identifier value; `not_found` holds documents without the identifier.
Facility is the Setup facility, and `matched_by` says how: "Chosen by the reviewer", "Facility name in
Setup" or "Service address in Setup". `identifiers` (one entry per value) is kept for older clients.

A month is `counted` when accepted values cover all its days, `counted_in_part` when they cover
some, `not_reviewed` when a document covers it but no accepted value does, and `no_document`
otherwise; the first and last month count only days inside the reporting period. A value's quantity is
spread evenly over its service period; a month with a value in a unit that cannot be added to the rest is
`counted_in_part` with the flag `unconverted`, and a month with no numeric quantity has `quantity: null`. `decided_by` is the
reviewer's name (their login when no name is on file).

## Contract Source

JSON schema contracts are versioned in `contracts/` and should be treated as API truth for request/response payload shape.

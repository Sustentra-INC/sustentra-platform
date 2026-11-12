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
- A document has one active (queued, in_progress or waiting_on_chunks) run at a time: asking
  again returns that run (202); asking for a different type while it is active is a 409.
- A large PDF in queued mode (more than `S1_CHUNK_THRESHOLD_PAGES`, 20) is read in page
  chunks: its run is `waiting_on_chunks` while the chunks are read, then `queued` again for
  assembly, then `completed`. See "Page chunks" below.
- 404 for a document of another organization, 400 when its stored file is missing, 403 for
  provider_admin.

### GET /v1/processing-runs/{run_id}
One processing run; 404 when it belongs to another organization.

#### Page chunks
A run that was split into page chunks carries (from `waiting_on_chunks` on, and after it ends)
`chunks: {total, completed, failed, failed_pages}`. `failed_pages` is `[[from, to], ...]`, the
1-based inclusive page ranges of chunks that failed after `S1_CHUNK_MAX_ATTEMPTS` (3) tries.
A run that was not chunked has no `chunks` key. The same object is on each item of
`GET /v1/engagements/{engagement_id}/processing-runs`.

How the read ends for a chunked document:
- Every chunk read: the run is `completed` and its pipeline run is read as for any document.
- A chunk failed: the run is still `completed` (the read ended), but its pipeline run is
  `partial` with a warning starting `pages_unread:` that lists the page ranges, and the
  values on those pages are missing. It never looks complete.
- More than `S1_MAX_DOCUMENT_PAGES` (500) pages: nothing is read; the pipeline run is `partial`
  with `halt_reason: {code: "document_too_long", message}` (the message says how many pages
  and to split the file).

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
          decision,                                  // "not_reviewed" | "rejected" | "needs_more_evidence" | "accepted" | "edited"
                                                     // (accepted is true for accepted and edited)
                                                     // record_key is opaque: use it as an id, never parse it
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

### GET /v1/engagements/{engagement_id}/recalculation: calculation lines

Every existing key and value is unchanged. Three keys are added, all computed by the backend
(the frontend only formats): `calculation_lines`, `calculation_unplaced`, `calculation_line_inputs`.
A line is the Evidence tree's line (same `key`, from `calculation_lines.line_key`): stationary fuel
x facility, mobile fuel x vehicle group, purchased electricity (location-based) x facility. The same
accepted, prorated records the categories counted are re-added per line and run through the same
calculator and factors, so the lines add up to the category.

```
calculation_lines: [{
  key, scope: "s1"|"s2"|"biogenic", category: "stationary"|"mobile"|"purchased_energy"|"biogenic",
  counts_toward: "stationary"|"mobile"|"purchased_energy",   // the category total this line rolls into
  level2, level2_key, label,                                  // label: facility or vehicle group
  facility_id, consolidated_share_pct,                        // facility lines only take consolidated_shares; others 100
  method: {route, equations: {CO2, CH4, N2O}},                // e.g. "Eq. 1", "Eq. 4" (on-road), "Eq. 5" (non-road)
  step1: {rows: [{period_start, period_end, document_id, evidence_code: null, file_name, candidate_id,
                  review: "accepted"|"edited", quantity, unit, share_in_period, counted_quantity,
                  counted_in_base}],                          // counted_in_base: counted_quantity in total.unit
          total: {quantity, unit}},                           // the rows' unit, or the base unit when they mix
  step2: {from_unit, to_unit, factor, source, result: {quantity, unit},   // factor 1 when no conversion
          distance: null | {quantity, unit: "mi", source},    // on-road mobile: an input, not a conversion
          implied_fuel_economy: null | {value, unit: "mi/gal", role: "reasonableness_check"}},
  step3: {gases: [{gas, activity: {value, unit}, ef: {value, unit, source}, unit_conversion, mass_t,
                   gwp: {value, source}, co2e_t, biogenic,
                   company_co2e_t?, difference_to_company_t?}]},   // the last two only when `company` exists
  results: {mass_t: {CO2, CH4, N2O}, gas_co2e_t: {...}, sum_co2e_t, total_co2e_t /* sum x share */,
            biogenic_co2_t, company_total_co2e_t?, company_gas_co2e_t?, difference_to_company_t?},
  company: null | {activity: {quantity, unit}, step2, step3, results},   // step3 mirrors step3 above
  reported_total_co2e_t: number|null, difference_t: number|null /* recomputed - reported */,
  difference_pct_of_base: number|null, status: "within"|"above"|"not_reported",
  inputs_incomplete: boolean, flags: [...]}]
```

- `unit_conversion` multiplies activity x factor into metric tons (kg 0.001, g 0.000001, lb 1/2,204.62).
- `evidence_code` is `null`: the app has no evidence codes for documents yet; use `document_id` and `file_name`.
- `step2.source` cites the unit conversion (`"fuel_units conversion table"`), `null` when the factor is 1.
- `step2.distance` is `null` except on an on-road mobile line: the distance the vehicle group states
  ("Vehicle group distance entered under Recalculation inputs"), an input and not a conversion.
  `step2.implied_fuel_economy` is that distance over the fuel on the line, a reasonableness check only;
  it is `null` when the line holds only part of the fuel or the fuel is shared by several groups.
- `difference_pct_of_base` is on the percent scale (4.6 means 4.6%). `status` and `difference_pct_of_base`
  use the existing comparison rule with the line's own `reported_lines` value as the base: the line's
  recomputed total against it, within the engagement's materiality tolerance. A line with no
  `reported_lines` value is `not_reported`.
- `inputs_incomplete` is true while the line's category (stationary, mobile, purchased electricity) has
  open `needs_input` or `awaiting_review` items, as the comparisons mark a partial total.
- `difference_to_company_t` is recomputed minus company, per gas row and in `results` (both with the share
  applied in `results`); `difference_t` stays recomputed minus reported.
- A biomass fuel sits on a `biogenic` line (scope `biogenic`). Its CO2 row has `biogenic: true`, `mass_t`
  the biogenic CO2 and `co2e_t` 0; `results.biogenic_co2_t` carries it and `results.mass_t.CO2` is 0, as in
  the category. On both sides the Step 3 `co2e_t` values add up to `results.sum_co2e_t`. Its CH4 and N2O
  count toward the stationary or mobile category through `counts_toward`.
- Mobile: CO2 from the fuel (Eq. 1) follows the records placed on the line; CH4 and N2O come from the
  vehicle group (distance, Eq. 4 on-road; fuel, Eq. 5 non-road). A group's line exists whenever its
  fuel has reviewed records.
- A company figure (`reported_lines` or `reported_activity`) for a known line (system or in
  `evidenceLines`) or for a key that names a Setup facility or vehicle group with a fuel the calculator
  knows, but that has no evidence, gives a line of zero with the company side and the flag `no_evidence`
  (`difference_t` is minus the reported value).
- A record with no line is listed in `calculation_unplaced` (same shape as a line, `key: null`, `target`,
  no company side), never dropped. `reason` is one of: `unknown_line` (filed on a line that no longer
  exists), `moved_to_another_place` (a reviewer filed it elsewhere), `fuel_shared_by_vehicle_groups`
  (mobile fuel used by two or more groups), `no_vehicle_group` (mobile fuel no group uses),
  `no_facility_match` (no Setup facility matches), `no_calculation_line`. Lines plus unplaced add up to the
  category on `sum_co2e_t`; a consolidated share below 100% scales `total_co2e_t` only.
- `calculation_line_inputs`: `{consolidated_shares, unknown_line_keys: [{setting, key}],
  unknown_facility_ids}`. A key that matches no line and names no facility or vehicle group is allowed
  and listed here, as is a `consolidated_shares` facility id that is not in Setup.
- A company activity that cannot be converted or run (unknown unit, other kind of unit, a line that mixes
  units) adds a `needs_input` item `{kind: "company_activity", key: <line key>, message}`. If the lines
  cannot be built at all, one item `{kind: "calculation_lines"}` is added and the three keys are empty.
  Neither changes a recalculated number or status.

Every `flags` code a line can carry:

| Code | Meaning |
| --- | --- |
| `fuel_chosen_by_reviewer` | The EPA fuel is the one the reviewer chose for this fuel code. |
| `fuel_auto_matched` | The EPA fuel was matched from the extracted fuel code without a choice. |
| `diesel_matched_to_distillate_fuel_oil_no_2` | Stationary diesel was matched to Distillate Fuel Oil No. 2. |
| `prorated_to_reporting_period` | A record's service period runs past the reporting period; only its share inside counts. |
| `no_reporting_period` | The engagement has no reporting period, so records count in full. |
| `no_service_period` | A record has no service period, so it counts in full. |
| `service_period_reversed` | A record's service period ends before it starts, so it counts in full. |
| `unit_converted` | The quantity was converted to the factor's unit (Step 2). |
| `biogenic_co2_reported_separately` | Biomass fuel: its CO2 is biogenic and is not in the line's CO2e. |
| `ch4_n2o_need_vehicle_groups` | Mobile fuel with no usable vehicle group: CH4 and N2O are not calculated. |
| `mixed_units_or_fuels` | The line mixes units or fuels; Step 2 shows the first, Step 3 lists every run. |
| `company_ch4_n2o_use_vehicle_group` | Mobile company side: CH4 and N2O still come from the vehicle group. |
| `no_evidence` | The company gave figures for this line but no reviewed record is on it. |
| `calculation_failed` | A calculator run for this line failed; the line shows what could be calculated. |

New optional settings under `settings.recalculation` (validated on PATCH, 422 with a message):

```
reported_lines:       {<line key>: number >= 0}                      // company total, t CO2e
reported_activity:    {<line key>: {quantity >= 0, unit: text}}      // company annual activity; drives `company`
consolidated_shares:  {<facility id>: 0..100}                        // default 100
gwp_set:              "AR4" | "AR5" (default) | "AR6"                // one set per engagement; the response says which
```

AR4 (IPCC AR4 WG1 Table 2.14: CO2 1, CH4 25, N2O 298) has no HFC, PFC, SF6 or NF3 values, like AR6:
a refrigerant gas needs `refrigerant_gwps` under AR4 (an open `needs_input` item says so).

## Contract Source

JSON schema contracts are versioned in `contracts/` and should be treated as API truth for request/response payload shape.

# Pilot API Contract

## Endpoints

### POST /v1/engagements
Create an engagement shell for document and evidence lifecycle.

### GET /v1/engagements/{engagement_id}
Fetch engagement metadata and summary counts.

### POST /v1/engagements/{engagement_id}/documents
Register an uploaded document for processing.

A client-supplied `evidence_id` (here and on upload) must be existing evidence of this engagement. Unknown evidence, another
organization's, and another engagement's all answer 404 "Evidence not found." and store nothing (SEC-004). The same holds for
`POST /v1/evidence/{evidence_id}/approved-evidence/project`, whose `engagement_id` must be the evidence's own.

### POST /v1/engagements/{engagement_id}/documents/upload
Upload a file and register it as a document (multipart: `file`, `document_role`, and optionally
`evidence_id`, `document_type` and `batch_id`). Answers with the document; what it carries depends on `S1_PROCESSING`:

- `S1_PROCESSING=inline` (the default): 200 with the document, `processing_status` `not_started`, and no
  `processing_run` key. The read is asked for separately (`POST /v1/documents/{document_id}/processing-runs`).
- `S1_PROCESSING=queued`: 200 with the document, `processing_status` `queued`, and `processing_run`: the run the
  upload queued for the first read (`status` `queued`, `attempt` 0, as `GET /v1/processing-runs/{run_id}` returns it).
- If that run can't be queued, the upload still succeeds: 200 with the document as in inline mode. The server logs
  `upload_read_not_queued` on `sustentra.processing` with the document id, and the client asks for the read itself
  with `POST /v1/documents/{document_id}/processing-runs`.

`batch_id` (optional) puts the document in a batch made with `POST .../document-batches`. A batch that does not
exist, is another organization's, or belongs to another engagement is a 404 ("Batch not found."), and nothing is
stored. The document then carries `batch_id`; without one it is `null`.

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

Pipeline runs (`contracts/pipeline_run.schema.json`, as read from `/pipeline/evidence/{id}/latest-run`)
have `canonical_type_source` of `classifier`, `content_check`, `override`, `ai` or `none`.
`ai` means Claude named the type from pages 1-2 and the reviewer must confirm it. An optional
`ai_routing` object (`canonical_type_id`, `quote`, `line`, `reason_code`, `page_number`,
`used`, `disagrees`, `review_required`) is present only when Claude was asked and its quote was
verified on the document; `used: false, disagrees: true` means it only disagreed with the
rules (the type is unchanged). `warnings` may carry `ai_type_disagrees`, `ai_unavailable` and
`ai_routing_ignored: <reason>`.

Extraction candidates (`contracts/extraction_candidate.schema.json`) may carry the
`validation_flags` `ai_suggested` (Claude read the value where the rules found nothing; confidence
at most 0.6; the reviewer must accept or correct it, and the calculation does not read it until
then), `ai_disagrees` (the rules read the value; Claude read another, in the optional
`ai_alternative {value, unit, source_reference}`; the value is unchanged) and `ai_conflict`
(Claude read two different values for the field; each is a candidate). `warnings` may carry
`ai_extraction: ...` (counts, dropped reasons, cost), `ai_pages_skipped` and `ai_time_budget`.

What a bill says about itself (EXT-025, `services/bill_notes.py`; the rule readers for fuel, electricity and steam
bills). Neither changes a value:

- `estimated_read`: a `validation_flags` entry on the `activity_quantity` candidate when the bill says a read was
  estimated: a sentence ("This bill is based on an ESTIMATED read", "usage was estimated"), an "ESTIMATED READ"
  heading, or a read-type column ("Read Type: Estimated / Estimate / EST"; "E", "E" in a "Read" or "Reading"
  column, or "853,925 (E)", each only with a legend "E = Estimated read"). A legend alone, "not estimated", fees
  ("Estimated Read Fee: $5.00"), conditions ("if we estimate your read"), dates and "not applicable" do not
  flag. In a multi-meter bill only the estimated meter's quantity is flagged. The review screen words it
  "Estimated read".
- `supersedes_reference`: an extra candidate (label "Replaces an earlier bill") on each record of a bill that is
  headed "REVISED STATEMENT" / "CORRECTED BILL" or has a sentence that starts "This bill/statement replaces,
  corrects or supersedes ..." Boilerplate that only mentions a correction does not count. Its value is the earlier
  bill's number or date as printed ("04/04/2025", "INV-2025-889"), or `revised` when it gives none; its
  `source_reference.reference_key` is that reference as a key (a date as ISO, a number upper-cased). Every bill
  also keeps its own statement date (ISO) and invoice or statement number in
  `source_reference.bill_ids` of its `activity_quantity` candidate (no extra value to review).
- Data quality (`quality_checks`, Q-003) then carries a `revised_bill_replaces_earlier` finding (severity `review`)
  when an earlier bill (the same source, account or facility, the same days, and not itself a revision) is also in
  the engagement. When the revised bill printed a date or number, only the bill whose `bill_ids` hold it counts;
  no match, no finding. One candidate gives `detail {suggestion: "mark_superseded", original_document_id,
  reference}`; several give `{suggestion: "mark_which", candidates, reference}` and name none. It is a suggestion:
  nothing is marked superseded until the reviewer does it on the Evidence screen. A pair matched by a printed
  reference is not also reported as an overlap (Q-004); a `revised` bill with no reference keeps the overlap
  finding.
- Account labels read for `account_number` now include "Customer No.", "Cust. No.", "Acct:" (also inline after
  other text) and similar. "Client ID" and "Customer ID" (CRM references) are not read. An account is never read
  from an email subject line or prose, and a value that is a phone number or longer than three words is rejected.
Extraction config rows may set `ai_only` (read by Claude only).

### GET /v1/processing-runs/{run_id}
One processing run; 404 when it belongs to another organization.

#### Page chunks
A run that was split into page chunks carries (from `waiting_on_chunks` on, and after it ends)
`chunks: {total, completed, failed, failed_pages}`. `failed_pages` is `[[from, to], ...]`, the
1-based inclusive page ranges of chunks that failed after `S1_CHUNK_MAX_ATTEMPTS` (3) tries,
plus one `[n, n]` for each page Textract could not read in a chunk that was kept on its last
attempt (`failed` counts failed chunks only).
A run that was not chunked has no `chunks` key. The same object is on each item of
`GET /v1/engagements/{engagement_id}/processing-runs`.

How the read ends for a chunked document:
- Every chunk read: the run is `completed` and its pipeline run is read as for any document.
- A chunk failed, or Textract could not read some pages: the run is still `completed` (the read
  ended), but its pipeline run is `partial` with a warning starting `pages_unread:` that lists the page ranges, and the
  values on those pages are missing. It never looks complete.
- More than `S1_MAX_DOCUMENT_PAGES` (500) pages: nothing is read; the pipeline run is `partial`
  with `halt_reason: {code: "document_too_long", message}` (the message says how many pages
  and to split the file).

### POST /v1/engagements/{engagement_id}/document-batches
Writers only (`org_admin`, `org_member`), on an active engagement. Optional body `{"label"}`. Answers 201 with
`{"batch_id", "engagement_id", "label", "created_at"}`. Files uploaded together carry the `batch_id`.

### GET /v1/engagements/{engagement_id}/document-batches/{batch_id}
How reading a batch stands. 404 for a batch that does not exist, is another organization's or another
engagement's. Answers:

- `items`: one per document of the batch, in upload order: `document_id`, `file_name`, `status`, `chunks`
  (`{total, completed, failed, failed_pages}` for a PDF read in page chunks, else `null`), `canonical_type_id`
  (`null` until classified), `halt_reason` (a sentence saying why it was not read in full, else `null`) and
  `records_found`.
- `status` is `not_started` (no read was ever asked for; `halt_reason` says to open it to start reading; it does not hold `complete` back), `queued` (no reader has it yet), `reading` (being read, or its chunks are, or it waits to be
  assembled), `done`, `partial` (read, but its pipeline run is partial: pages that failed, or nothing to
  review) or `failed`.
- `halt_code` is the halt's code (`unsupported_document`, `unreadable_document`, `ocr_required`,
  `password_protected`, `document_too_long`), or `null` when the document did not stop on a halt.
- `halt_reason` is a plain sentence, worded server-side from one map by `halt_code` (the same wording as the
  frontend's `HALT_REASONS`; `document_too_long` keeps its own sentence with the page counts). The pipeline's
  own text (the closest classifier match with its id and score, parser output) is never returned: it stays in
  the pipeline run record. For a failed run that is not a halt, the run's own plain error; for a partial run
  read in chunks, "Pages 11-20 could not be read."
- The same rule holds for `error` on a processing run (`GET /v1/processing-runs/{run_id}`, the engagement list
  and the `POST` answers): for a halt `error_code` it is the plain sentence, not the pipeline's text. The 422
  from the older `POST /v1/pipeline/process` says the plain sentence too; `password_protected` and
  `document_too_long` keep their own sentence there (it says what to ask the client for, or the page counts).
- Every other answer that carries a pipeline run is plain too: `GET /v1/pipeline/runs/{id}`,
  `GET /v1/pipeline/evidence/{evidence_id}/latest-run`, `latest_pipeline_run` in
  `GET /v1/pipeline/evidence/{evidence_id}/status`, and `pipeline_run` (and `extraction_result.halt_reason`) in the
  answers of `POST /v1/documents/{id}/pipeline/process` and the local dev tool. `halt_reason` is
  `{code, message}` with the plain sentence for the code (an unmapped code gets "Reading stopped. Try uploading the
  file again."). Each entry of `warnings` and `errors` keeps its code as a prefix (`pages_unread:`,
  `ai_type_disagrees:`, `type_corrected:`, `no_type:`, `pipeline_failed:` ...) and says a plain sentence: no type
  id, classifier score, parser output, exception text or Claude cost. The stored run record keeps the pipeline's own
  text. `GET .../extraction-result/latest` never carried the halt (its answer is the candidates and `status`).
  Still in the debug payloads of `POST .../pipeline/process` (not sentences): `classification_result` (scores, matched
  type ids) and `parser_output`; clients must not show them.
- `totals`: `{queued, reading, done, partial, failed, not_started}`.
- `complete`: `true` when nothing is queued or reading. Clients poll (every 3 s) until it is `true`.

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
  - `catalog`: `{field_id, group, group_label, label, kind: text|enum|entity|factor|gwp|date_range|entry_list|multiselect, allowed?, free?, shown_if_yes?, parts?, user_added}`, in page order: the fixed
    fields (reporting_period, consolidation_approach, `category:{scope1|location|market|biogenic}:...`,
    `boundary:{acquisitions|leased_space}` (text, `required: false`: hidden until a value or "Add an item"), `gas:{co2|ch4|n2o|hfcs|pfcs|sf6|nf3}` (group `gases`, enum Included / Declared absent / Not mentioned, `required: false`; kept apart from the Yes / No / Not detected category values; Claude may suggest only Included or Declared absent, with a quote that names the gas), `exclusion:{boundary|inventory|materiality}`, gwp, `calculation:{approach|process}`, `calculation:estimation` (entry_list, `required: false`), `calculation:source_records` (multiselect with free additions, `required: false`), `scope2:instruments` (multiselect, `required: false`, `shown_if_yes`)), then the rows the
    reviewer added. `allowed` is a list for an enum, `{set, horizon}` for gwp (horizon one of 100-year, 20-year, 500-year; with `allowed_labels.set`),
    `{operational_control}` for an entity. `parts` (entity, factor, gwp only) lists the value's editors,
    `[{key, label, kind: text|list|percent|enum, allowed?}]`, so a blank new row can be drawn.
  - Row states. The GET also answers `prefill_ran_at` (the time the last Claude prefill finished and stored its
    result, or `null`), and each listed field carries `display_state` and `shown`; each catalog def carries
    `required` (boolean). `display_state` is `has_value` (a suggestion, or a decision that is not a bare pending
    one), `not_detected` (a prefill finished, and there is no suggestion or decision) or `not_checked` (no prefill has
    finished). `required` true is "Must appear": always `shown`. `required` false is "Only if the company has a
    value": `shown` only once it has a value or the reviewer added it. Rows are always shown. Only `boundary:acquisitions`, `boundary:leased_space`, the seven `gas:*` fields and `calculation:estimation` are optional
    today; every other field is `required`. A refused prefill (no documents, off, over the limit) does not set the marker. The marker also records which fields the run covered (`prefill_covered`); a field the last run did not cover reads `not_checked`, and a run recorded before this list existed is taken to have covered only the fields the page had then, so a row added since reads "Not checked yet" instead of "Not detected". The marker and the
    added optional rows are kept in one extra `workpaper_items` row (`item_key` `meta:state`), never listed as a field.
  - GWP sets. The report may name more than one GWP set. The first set Claude finds fills the fixed `gwp` field; every other distinct set and horizon becomes a row (`gwp:<id>`, group `gwp`, label "GWP set", `user_added: false`) instead of being dropped; the reviewer can add rows (`POST .../rows` `{group: "gwp"}`, blank value `{set: "", horizon: ""}`) and remove the ones they added. Each set needs both the set (AR4, AR5, AR6 or the report's wording) and its horizon (20-year, 100-year or 500-year, with "year", "yr" and "GWP100" variants) named in its own quote, as whole tokens; when a quote names two sets, each set is paired with the horizon nearest to it. On a later run a pending suggestion on the fixed field keeps its set if the run still finds it, and a set already on a row is never also put in the fixed field. A set the fixed field already holds (suggested or decided), or one the reviewer rejected there, is not added again, and a reviewer's decision is never overwritten. "Identified by" and mismatch flags are not built yet.
  - Multi-select rows. `multiselect` (`scope2:instruments`, `calculation:source_records`) holds a list of `{option, wording}`: `option` is one of the catalog's `allowed` (matched ignoring case and spacing; a field with `free: true` also takes up to 10 options of the reviewer's own, at most 60 characters), `wording` is the company's own words beside it (at most 200, may be ""), no option twice, and "None" (instrument types only) stands alone. A decision needs at least one option: an empty list is refused ("None" is the explicit empty answer on the instrument types; source records can be rejected instead), and "None" in any case or spacing is refused as a free option. A free option that is a listed option selects that option. Claude suggests only listed options, never "None"; each option must be named in its own quote as a whole word or phrase ("records" is not REC, "release" is not a lease agreement), and a mention with a negation (not, no, never, without, none) within five words before it is dropped and counted as `negated`; and the suggestion carries `evidence` with one quote per option (the company's wording is kept only if it is in the quote). An option that fails is dropped and counted, and the others stand. Scope 2 instrument types (spec: "only if the company reports a market-based Scope 2 number") are `shown` while at least one market-based category (`shown_if_yes`) is Yes, meaning the reviewer accepted or edited it to Yes or, while it is undecided, Claude suggested Yes; No, Not detected and a rejected category do not count. A value, or "Add an item", keeps the row shown whatever the categories say. A pending Claude suggestion also keeps it shown, so nothing Claude claims is hidden; the field then carries `shown_note`, "Shown because Claude found it, although no market-based category is Yes."
  - Values by kind: entry_list (`calculation:estimation`, one entry per source type) is a list of at most 10 `{source_type, method}`, each text required (source type at most 60 characters and unique ignoring case and spacing, method at most 300); an empty list is allowed (every entry removed). A list suggestion also carries `evidence`: `[{label, quote, document_id, file_name, source_reference}]`, the quote behind each entry in the value's order (quotes up to 1,000 characters, `quote_truncated: true` when cut; the location keeps only page, sheet and cell; the top-level quote is the first entry's). The quotes of one suggestion share 12 KB: when they do not fit, the suggestion carries fewer entries, the first ones, and `entries_omitted` says how many were left out, so an entry is never shown without its quote. Claude's entries are each checked for their own quote on the page, and the source type must be named in its own quote as a whole token: one that fails is dropped and counted, the others stand; more than 10 are cut (`too_many_entries`). date_range (`reporting_period`) is `{start, end}`, each a real calendar date written `YYYY-MM-DD` (ASCII digits), with end not before start (otherwise 422 with a sentence). A record saved before this change may still hold the text it was; the GET returns it unchanged and the screen shows "Recorded as: <text>" until the reviewer enters two dates. Claude's reporting-period suggestion carries both dates in ISO form, and is kept only if both are printed in its quote (English month names, `1/1/2025` read month first, `2025-01-01`); otherwise it is dropped and counted as `value_not_in_quote`. text is a string (at most 2000 characters, no null characters); enum one of `allowed`; gwp `{set, horizon}`;
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
- `POST .../{field_id}/reveal` ("Add an item", no body) shows a hidden optional field and keeps it shown
  (answers `{field_id, shown: true}`; repeating it is fine). A field that is always shown answers 422, an unknown field or a row 404. It
  writes a `methodology_decision` audit event with action `reveal`.
- `POST .../rows` `{group: "entities"|"factor:scope1"|"factor:scope2"|"gwp"}` adds a row under a server-made id (201, the new record plus `field`, its catalog def). `DELETE .../{field_id}` removes a row the reviewer added (answers the record with `removed: true`); the
  row is marked removed, not deleted. A field from the report answers 409 "Reject it instead".
- Entities and the boundary sentence. `boundary:entities` (text, must appear, catalog `value_note: "Boundary sentence only"`) holds the sentence in which the document says what the boundary covers, when it names no entity: Claude's value must be printed in its own quote, must say what the boundary covers (a sentence about what is left out is dropped as `not_a_boundary_sentence`), and a document with no such sentence reads Not detected, never an invented one. An entity row's `equity_share_pct` and `financial_control` are each a number from 0 to 100 or `null` (not stated), and `operational_control` (the per-entity Yes / No) is `"Yes"`, `"No"` or `null` (a part flagged `optional: true`; a new row starts with all three `null`). An entity row comes only from an inclusion statement: the sentences that name the entity must carry inclusion wording and no exclusion wording ("excluded", "outside", "not included", "does not include"), otherwise it is dropped as `not_an_inclusion` (that sentence belongs to the exclusions). The Yes / No is set from the quote alone (Yes: "operational control" not negated, or "is included / inside the boundary"; No: "not under operational control" beside other inclusion wording; otherwise `null`), never from Claude's own value. Claude gives a percentage only when it is printed in the quote; an entity with no percentage is kept only when its name is printed in the quote. `name` stays editable on every entity row.
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
    same database and edition (factor) is already on the page or earlier in the same reply. Documents the
    reviewer set aside (withdrawn, duplicate, superseded) are not read.
  - A suggestion is kept only if its quote (at least 8 characters) is printed on the cited line of the cited
    document and, for percentages and a factor edition with digits, the number is printed in the quote; for
    the consolidation approach and the GWP set the quote must also name the choice (for example "operational
    control", "AR5" or "Fifth Assessment"). A too-short quote counts as `quote_not_on_document`. `dropped` keys are
    exactly: `empty_value`, `unknown_line`, `quote_not_on_document`, `ambiguous_quote`, `value_not_in_quote`
    (from the locator), `unknown_document`, `invalid_value` (failed the field's validation) and `unknown_field`.
  - 409 with a sentence in `detail`: switched off, not configured, over the monthly limit (the `ai.reason`
    sentences), no documents ("Upload the company's GHG inventory report, boundary statement or methodology
    document first."), a prefill already running for the organization, documents unreadable, or Claude refused or its answer was cut short or unusable (nothing
    is kept). 502 when Claude could not be reached, or when its answer could not be saved (the call is still
    recorded in the ledger; nothing was kept).
  - The call is made with no database transaction open; the ledger row is committed first, in its own
    transaction, then the suggestions and the audit event in another. The cap is exact within one app
    process (one prefill per organization at a time); across processes it can be passed by at most one
    in-flight call per process.
  - Every call that was made is one row in `ai_usage` (outcome, tokens, cost, request id), refused or invalid
    ones included; a refused call before the request is not. One `methodology_prefill` audit event with outcome,
    counts and cost only.

### GET /v1/engagements/{engagement_id}/evidence
List evidence entities produced under the engagement.

### GET /v1/evidence/{evidence_id}
Get one evidence record including candidate and review summary.

### PUT /v1/evidence/{evidence_id}/fields/{field_name}/review
Persist reviewer decision for a candidate field.

#### A re-read and earlier decisions (S1-BE-014)
A decision is stored under a candidate id that holds the record's index, and a re-read can renumber
records. `services/reviewed_evidence.effective_decision` is the one place that decides whether a
stored decision applies to an item of the latest read; every reader uses it (recalculation, the
evidence tree and schedule, the workpaper export, approved evidence, the methodology run, the review
screen). A decision applies only when its snapshot is the same field and the same record (record key
without the leading `r{index}`; the service period when a key is missing). An accept also needs the
same value and unit. An edit, reject or needs-more-evidence carries over when the record is the same,
and a changed extracted value adds the validation flag `extracted_value_changed_since_review`.
A decision that does not apply leaves the item unreviewed for every purpose; it is never deleted.

- `GET /v1/documents/{document_id}/extraction-result/latest` also carries `facility_suggestion`
  (`{facility_id, quote, source: "file_name" | "line", page_number}`) when Claude suggested a facility for a bill that names
  none; absent otherwise. A suggestion, never a placement.
- `GET /v1/documents/{document_id}/extraction-result/latest`: an item whose earlier decision no longer
  applies carries `review_reread_changed: true` (the screen says "The document was re-read and this value
  changed. Review it again."). Absent otherwise.
- `GET /v1/documents/{document_id}/reviews`: every decision, as before. After a re-read, one that applies to
  a value under another candidate id carries `applies_to_candidate_id`; one that applies to no value carries
  it as `null`. Absent when it applies to its own candidate.
- Schedule rows (`.../schedule`): `reread_changed` and `value_changed_since_review`, present only when true.
- `POST /v1/evidence/{evidence_id}/approved-evidence/project` projects only decisions that still apply.
  Each document of the evidence slot is judged by its own latest read, and a decision is matched only
  within its own document.
- `POST /v1/methodology/s2/run` drops approved fields whose review decision no longer applies (both the
  persisted and the non-persisted path); a field whose decision the server does not know is kept.
- Schedule history entries carry `superseded_by_reread: true` for a decision a re-read made void; it stays listed.
- Raw history by design: `GET /v1/evidence/{evidence_id}/reviews` and
  `GET /v1/candidates/{candidate_id}/reviews/latest` return the stored decisions as recorded (an audit
  trail of what each reviewer did, per evidence id or candidate id, with no read to judge them by).
  The screens that act on a decision use the guarded reads above. `review_decision_count` in the evidence
  status counts stored decisions.
- A decision with no candidate snapshot applies by candidate id only on a single-record document.

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
                                                     // anchor_id a mobile line (anchor_kind "vehicle_group") uses:
                                                     // the group's own group_id
  anchors_for_contractual: "company",                // a contractual line uses anchor_kind "company", this anchor_id
  set_aside: [{document_id, file_name, reason}] }    // withdrawn / duplicate / superseded: not filed
counts  = {documents, values, accepted, to_review, issues, pct_accepted}
DocRow  = {document_id, file_name, period_start, period_end, facility_id, facility_name,
           facility_note,    // when facility_id is null: why an account or meter number placed nothing, or null
           facility_suggestion, // Claude's suggestion while it awaits a decision (see "Claude's facility suggestion"), or null
           processing_status, detected_type, also_in: [lineKey], values, accepted,
           placement_from,   // send this as a move's "from" to move this row
           value_family,     // "stationary" | "mobile" | "electricity" | null: the calculation this row's
                             // values feed (null when mixed or when none reads them)
           flags: []}        // "unknown_line": it was moved to a line that no longer exists
```

`CalculationLine = {key, scope, category, level2, level2_label, anchor_kind
("facility" | "vehicle_group" | "company"), anchor_id, label, facility_id | null,
created_by_user, family, created_by?, created_at?, created_by_name?}`. `family` is the calculation the line feeds ("stationary", "mobile",
"electricity", or null when none reads it); a value placed on a line of another family is reported as
not placed. A reviewer's line (`created_by_user`)
carries `created_by` (the user id), `created_at` (ISO 8601 UTC) and `created_by_name` (full name, else
first and last name, else the login; null when the user is unknown). The server stamps `created_by` and
`created_at` once, when a line is first saved, and keeps them through a rename or a re-save; whatever a
client sends for them is ignored. Lines saved before this have none, and the tree shows "Added by a
reviewer". A deleted user is still named. The key is `<scope>:<category>:<level2-slug>:<anchor-slug>` (for example
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
"Unassigned supporting evidence" with the flag `unknown_line`. Placements are written only by the
Evidence actions below (a PUT of the item keeps the stored `placements`); the PUT replaces every other key
of the payload, so **read the item and keep the keys you do not change** (`facilityId`, `disposition`,
`relationships`, ...).

**Settings are replaced whole, except the reviewers' lines.** PATCH `/v1/engagements/{id}` replaces
`settings` as a whole. `settings.evidenceLines` (the lines reviewers added in Evidence) is the exception:
it changes only through the Evidence actions below, which lock the engagement, check the line and write an
audit event. A save takes the stored value under the engagement's row lock and ignores whatever the body
sends for `evidenceLines` (no error, so an autosave never fails on it). A stale tab's save can therefore
never delete, rename or bring back a line. POST `/v1/engagements` ignores it too. `GET` still returns the
lines in `settings.evidenceLines`.

**Reviewers' own lines** are stored in `settings.evidenceLines`: `[{key, scope, category, level2,
level2_label, anchor_kind, anchor_id, label, created_by, created_at}]` (at most 200; labels at most 120
characters; `category` one of the fixed list). The server builds `key` (and `level2`, the slug of
`level2_label`). A line the system already creates is refused with 422 (the system's lines are not stored
here and cannot be deleted).

**Anchors are checked (422, a plain sentence in `detail`).** When an Evidence action adds a line, it must sit on a facility of the same `settings.facilities`
(`facilityId`, or `name-<slug>` when it has none), a vehicle group of the same
`settings.recalculation.vehicle_groups` (its `group_id`), or the company (`company`, contractual
instruments only; a contractual line may also sit on a facility). A facility line on an engagement with no facilities is refused: "Add a facility in Setup first". A fuel or energy name with no letters or
numbers is refused: "Use letters or numbers in the name". A facility removed from Setup later never
blocks anything: the Evidence tree still shows the line with its documents.

### Evidence actions: lines and placements, each with an audit event
Line and placement changes are server actions. Each changes one thing, in one transaction, under the
engagement's row lock (so two simultaneous requests run one after the other and neither loses the
other's change), and writes one audit event with the actor from the session. Writers only
(`org_admin`, `org_member`): a provider admin gets 403, an archived engagement 409, another org's
engagement 404. Bodies reject unknown fields (422). Audit rows hold ids and labels, never a document's
text or file name.

| Request | Body | Answer |
|---|---|---|
| `POST /v1/engagements/{id}/evidence-lines` | `{category, level2_label, anchor_kind, anchor_id?, label, scope?}` | 201 `{line, evidenceLines}` |
| `PATCH /v1/engagements/{id}/evidence-lines/{line_key}` | `{label}` | 200 `{line, evidenceLines}` |
| `DELETE /v1/engagements/{id}/evidence-lines/{line_key}` | none | 200 `{documents_moved, documents, evidenceLines}` |
| `POST /v1/engagements/{id}/documents/{document_id}/placements` | `{from, to}` | 200 `{document_id, payload}` |
| `POST /v1/engagements/{id}/documents/{document_id}/facility` | `{facility_id, expected_facility_id?}` | 200 `{document_id, payload}` |

* **Create** checks the same as saving the setting (anchor on a Setup facility, vehicle group or the
  company; letters or numbers in the name; at most 200 lines; not a line the system creates), 422 with a
  sentence otherwise; a line that already exists is 409. The server builds the key and stamps
  `created_by` and `created_at`; a client cannot send them.
* **Rename** changes the label only (the key and the creator stay). A line another tab already deleted is
  404 "This line was already deleted. Reload to see the current lines."; a line the system creates is 422;
  a reviewer's line whose key the system now creates too (documents arrived for it) is 409. Renaming to the
  same label changes and logs nothing.
* **Delete** removes a line the reviewers added. Each document filed on it gets an explicit move to
  `supporting:unassigned` saved first, so adding the same line again later does not pull the documents
  back, and a document also on another line loses only this placement. All of it is one transaction: the
  documents move and the line goes, or nothing changes. `documents_moved` is how many documents moved;
  `documents` is `{document_id: payload}` for every document the delete changed (set-aside ones too, which
  keep a move out of the line for if they come back and are not counted), so a client can take them as saved.
  A document that cannot take the move fails the whole delete with 409 naming it. The same 404, 422 and 409
  as rename apply.
* **Move** needs `from` to be a place the document is in now (a line key, `block:summary`,
  `block:unassigned` or `supporting:unassigned`, as the row's `placement_from`); otherwise 409 "This
  document was already moved from there", nothing is saved and nothing is logged. `to` must be a line that
  exists or one of the three fixed places (422 otherwise); moving to where it is, 422; a document that is
  not on the Evidence page, 404. The saved `placements` chain is derived from where the document is filed
  after the move, not from its history: one move per default place of the document that is no longer where it
  started, in an order where a move out of a place runs before a move into it (two places swapping go through
  a free fixed place). It never has more moves than the document has default places, plus one per swap,
  however many times it was moved (history lives in the audit log). A document parked on a line that no
  longer exists stays on that line's key, so it returns there if the line comes back. The full chain is kept
  only when the derived one would not file the document in exactly the same places; a chain past 200 moves is
  409 naming the document. Other keys of the document's payload (`facilityId`, `disposition`, notes) are kept.
* **The old paths no longer change lines or placements.** PATCH `/v1/engagements/{id}` keeps the stored
  `evidenceLines` (see above). PUT `/v1/engagements/{id}/workpaper-items/document/{key}` takes the engagement
  lock, saves every other key of the payload, and keeps the stored `placements` (a first save has none): a
  stale tab's save cannot put a document back. Other kinds of workpaper item are unchanged. A client keeps its
  own copy of `evidenceLines` and of a document's payload from the action answers.

Audit events (`target_type` "engagement", `target_id` the engagement):

| `event_type` | `metadata` |
|---|---|
| `evidence_line_created` | `line_key, label, level2_label, category` |
| `evidence_line_renamed` | `line_key, old_label, new_label` |
| `evidence_line_deleted` | `line_key, label, documents_moved` |
| `evidence_document_moved` | `document_id, from, to, from_label, to_label` |
| `evidence_document_facility_set` | `document_id, facility_id, facility_name, suggested` |

`POST .../documents/{document_id}/facility` places a document on a Setup facility: it saves the reviewer's own facility
decision (`payload.facilityId`, which wins over every rule), under the engagement's row lock, and writes
`evidence_document_facility_set` (`suggested` is true when the facility is the one Claude suggested for the document). The
actor is the session's. Safe to repeat: when the document is already on that facility the answer is 200 with the saved
payload and nothing is written or logged. `expected_facility_id` (null for none) is the facility the page believes the
document is on; when it is sent and is not what is saved, 409 ("Another reviewer already chose a facility for this document.
Reload Evidence to see it.") and nothing is written. A document with saved moves (`placements`) is 409 ("This document was
moved by hand. Move it back to Unassigned first, or place it from the Evidence tree."). 422 for a facility that is not in Setup,
for any other key in the body, and for a kind of document that is not placed on a facility (vehicle fuel, summaries); 404 for
a document that is not on the Evidence page or an engagement of another org; writers only (a provider admin is 403).

#### Claude's facility suggestion (EXT-026)
For a bill that names no facility, Claude may suggest one. It is asked only when `place_on_facility` would place nothing for
every record with nothing to go on: no usable name, no usable address, and no account or meter number matched a Setup
facility (a bill whose own name or address matched nothing, or matched ambiguously, is never sent: "Choose the facility").
Vehicle fuel is not asked. Claude gets the Setup facilities (id, name, address), the file name and a bounded sample of the
text (pages 1 to 3, at most 150 lines and 8,000 characters) and answers a facility id or none, with a quote. The suggestion
is kept only when the id is in Setup, the quote is found in the file name or on a line of the sample as whole words, and the
quote holds a word that points at the chosen facility and no other: a word of its name or address that is in no other
facility, not in the company's name, not generic (plant, warehouse, road, a street suffix, a shared city) and not only digits.
A quote, or a quoted line, that names a facility id or talks to the assistant (AI, Claude, instructions, prompt, ignore) gives
none, and so does a facility with no such word. A document the reviewer already placed (on a facility still in Setup) is not
asked about. The prompt carries at most 50 facilities (name and address cut short) and a file name cut to 200 characters.
A file name or sample that also holds a word that points at another facility gives none (the document points two ways).
It is shown again when a saved choice's facility has left Setup.

Known limit: a single site's real word used for an unrelated reason (an instruction or a vendor address that names one site,
with none of the wording above) cannot be told from a bill that mentions the site, so it can still be suggested. That is why
it stays a suggestion with its quote, never a placement: a reviewer has to confirm it. It is stored with the
extraction result as `facility_suggestion` and shown, while the bill is unplaced and the reviewer has not chosen, on the
Evidence tree row as `facility_suggestion: {facility_id, facility_name, quote, where, label: "Suggested by Claude"}` and on
the review screen, each with one click, "Place on <facility>". Until that click the bill is unplaced, in the Evidence tree and
in the recalculation. It needs `AI_SUGGESTIONS_ENABLED`, a configured client and room under the organization's monthly cap
(feature `facility` on the usage ledger); with AI off there is no suggestion and no error.

### GET /v1/engagements/{engagement_id}/evidence-activity[?limit=50&cursor=]
The five events above for this engagement, newest first, 1 to 100 per page (an index on `audit_logs (org_id, target_type, target_id, created_at, id)` serves it) (`next_cursor` is null on the
last page; a cursor that does not decode is 400). Any reader of the engagement (`org_admin`,
`org_member`, `provider_admin`); another org's engagement is 404.

```
{ items: [{id, event_type, at, actor_name,   // the person's name, else their login; null when unknown
           line_key?, label?, level2_label?, old_label?, new_label?, documents_moved?,
           document_id?, from?, to?, from_label?, to_label?}],
  next_cursor: string | null }
```

### GET /v1/engagements/{engagement_id}/calculation-lines/{line_key}/schedule
One calculation line's schedule (reader; 404 with a plain message for an unknown line key, and
for another org's engagement).

```
{ line: CalculationLine, reporting_period: {start, end},
  calculated: bool,                                  // true when the recalculation has this line in calculation_lines
  coverage: [{month: "YYYY-MM", status: "counted" | "counted_in_part" | "not_reviewed" | "no_document",
              quantity, unit, document_ids, flags: [],     // flags: "unconverted"
              waiting_on: [string]}],                      // field labels the recalculation still awaits
  identifiers: [{label, value, documents_with, documents_total}],   // facility, service address, account, meter, statement date
  values: [{service_period_start, service_period_end, days, quantity, unit, document_id, file_name,
            page, candidate_id, decided_by, decided_at, decision, waiting_on: [string]}],
  history: [{action, actor_name, at, field, value, unit, file_name, page, count, documents?}],
      // newest first, entries with no time last, at most 200; history_total is the count before the cap
  history_total: number,
  // schedule v2 (Claire's supporting-schedule spec); the keys above are unchanged
  rows: [{record_key, record_index, accepted,        // one row per record (document + period + meter)
          decision,                                  // "not_reviewed" | "rejected" | "needs_more_evidence" | "accepted" | "edited"
                                                     // | "awaiting_other_fields" (quantity reviewed, but the
                                                     // recalculation still awaits other fields of the record)
                                                     // (accepted is true for accepted and edited, and only when the
                                                     // record is not in the recalculation's awaiting_review)
          waiting_on: [string],                      // labels of those fields ("Fuel type"); [] otherwise
          rejected_fields: [string],                 // labels of other required fields the reviewer rejected
                                                     // record_key is opaque: use it as an id, never parse it
          date: {start, end, days, label},           // label: "Service period" | "Statement period" | "Transaction date" | "Delivery date" | "Service date"
          activity_quantity: {value, unit, candidate_id, page, sheet, cell},       // the extracted value; the reviewed value once accepted
          cells: {<column_key>: {value, unit, candidate_id, page, sheet, cell}},     // only the extra columns this row has a value for
          saved_by: {name, at} | null,               // who accepted or edited the quantity; null when not reviewed
          document_id, file_name, page, candidate_id}],
  columns: [{key, label, unit_in_cells: true}],      // date, activity_quantity, then (only when a row has a value,
                                                     // accepted or not) heat_content, carbon_content,
                                                     // vehicle_type, model_year, on_or_non_road, distance
  activity_quantity_note: string | null,             // "Activity quantity: fuel quantity combusted" ...
  identifier_groups: [{label, values: [{value, documents: [{document_id, file_name, matched_by?, read_by_claude?}]}],
                       not_found: [{document_id, file_name}], documents_with, documents_total,
                       matched_by?: [string]}] }     // matched_by on Facility only
```

`history` entries: `action` is `extracted` (one system entry per batch: `count` values from `documents`
documents), `accepted`, `corrected` (an edit of a value that was read), `added` (a value the reviewer keyed
where the extractor found nothing: an `edited` decision on a placeholder candidate whose normalized value is
empty), `rejected` or `asked_for_more_evidence`. Every field of the line's records is logged, not only the
quantity (`field` is its label). `actor_name` comes from the session's reviewer; `value` and `unit` are the value
decided (for a rejection, the value that was read). Accepts by one person in one minute on different values fold
into one entry with `count` N and no field. The page words the sentence.

`rows` lists every extracted record on the line, accepted or not. A row with `accepted: false` is present
but flagged; only accepted values feed the calculation, as before. The extra columns read the extracted
fields `heat_content`, `carbon_content`, `vehicle_type`, `model_year`, `on_or_non_road` and `distance`;
no extractor produces them yet, so today a line shows only Date and Activity quantity. Every value in a row (the quantity and each extra cell) says where it was read: `candidate_id` (to open the review at that value), and `page` (PDF or image) or `sheet` and `cell` (workbook or CSV); missing parts are null, and the page then opens the document at page 1 and says so. `identifier_groups`
group the line's documents by identifier value; `not_found` holds documents without the identifier.
Facility is the Setup facility, and `matched_by` says how: "Chosen by the reviewer", "Facility name in
Setup" or "Service address in Setup". Facility and Statement date are listed for every line; Service address, Account number
and Meter number only for utility-bill lines (stationary natural gas, electricity, steam, heating, cooling).
Values that differ only by case, spacing or Unicode form (NFKC, so full-width digits match ASCII) fall in one group, shown in the first
spelling seen; a whitespace-only value counts as not found. `identifiers` (one entry per value) is kept for older clients.
Identifiers never feed a number, so a meter number, account number, statement date or service address that Claude read counts here before a reviewer has decided it, and its document says `read_by_claude: true` (a value a rule also read is not marked; a rejected reading does not count). Everything that feeds a calculation still ignores a reading until a reviewer accepts it.

A row counts (`accepted` true) only when its record is not in the recalculation's `awaiting_review`. When
the quantity is reviewed but another required field is not (for example `fuel_type`), the row has
`decision: "awaiting_other_fields"`, `accepted: false`, and `waiting_on` lists the field labels. `calculated`
is false when the line has no entry in the recalculation's `calculation_lines`; the page then shows
"Not calculated yet" instead of a link to the calculation. Months follow the same rule: a value awaiting
other fields does not count, and the month lists its labels in `waiting_on`.

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
  `no_facility_match` (no Setup facility matches), `identifier_on_two_facilities` (the bill's account or
  meter number is listed on two or more Setup facilities, so it is not placed), `no_calculation_line`. Lines plus unplaced add up to the
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

**Vehicle group ids.** Every group in `settings.recalculation.vehicle_groups` carries a `group_id`
(`vgid-` and 12 hex digits for a new group) that is also its line anchor: a mobile line is
`<scope>:mobile:<fuel>:<group_id>`. The server makes the id when the group is first saved (POST or PATCH of an
engagement) and keeps it through a rename, a reorder and the removal of other groups, so a document placed by hand
on a group's line stays on it. The id is not built from the name any more (`vg-none` and `z-rich` came from names
with no ASCII letters). Rules of a save:
- a group that sends the `group_id` of one of the engagement's stored groups keeps it. A client that sends no ids
  back is matched to the stored groups: first a group the same in every field (equal groups in order), then a
  renamed group (the same in every other field as exactly one stored group, and no other group of the save has
  that stored group's name), then a group with changed figures (the same fuel, vehicle type, fuel type and name as
  exactly one stored group). Anything less certain is a new group, so a rename plus a reorder never hands a group
  the id of another;
- a group with an id the engagement never had is a new group and gets a new id (the id sent is not trusted);
- a new group never takes the id of a group that was removed, so adding a removed group again gives a new line;
- an id that is not `vg-` or `vgid-` followed by lower-case letters, digits and hyphens (at most 70) is 422, and so
  is the same id twice. New ids use `vgid-`, which an old `vg-<slug>` anchor can never equal. Send `group_id` back unchanged, or leave it out for a new group.

Migration 0021 gave every stored group the anchor it had as its id (`vg-<label slug>`, numbered by order among equal
slugs), so every line key, user line, document placement (chains and documents parked on a removed line) and
recalculation reads exactly as before. Groups without an id (data written by older code) are read as if they had that
anchor. The downgrade removes the ids again only when that moves nothing: if any group's id is not the anchor the
older code would give it (a group was deleted or reordered, or added, since the upgrade) it refuses with an error
naming the engagement, and rewrites nothing.

AR4 (IPCC AR4 WG1 Table 2.14: CO2 1, CH4 25, N2O 298) has no HFC, PFC, SF6 or NF3 values, like AR6:
a refrigerant gas needs `refrigerant_gwps` under AR4 (an open `needs_input` item says so).

### GET /v1/provider/orgs/{org_id}
Provider admins only (an org admin or member gets 403, no session 401). 404 `Organization not found` for an
id that does not exist. Answers the organization (`id`, `name`, `slug`, `status`, `max_users`, `user_count`,
`created_at`, `updated_at`, as the list and the other org endpoints do) plus, for this detail only:

- `user_counts`: `{active, invited, suspended}`, the seats by status (deleted users are gone).
- `initial_admin`: the org's earliest-created `org_admin` that is not deleted, or `null` when it has none:
  `user_id`, `email`, `first_name`, `last_name`, `status` (`invited` | `active` | `suspended`), `invited_at`
  (when the user was created by the invite), `last_invite_sent_at` (the newest invite link, so a resend shows)
  and `invite_expired` (only while `invited`: the newest link is past its 24 hours; `false` otherwise).

No more than the provider typed when creating the org. Read in provider scope (`app.is_provider`).
"Resend invite" is the existing `POST /v1/orgs/{org_id}/invites/{user_id}/resend` (ORG-003), which a provider
admin may call for any org; it answers 409 when the user is not waiting for an invite.

## Contract Source

JSON schema contracts are versioned in `contracts/` and should be treated as API truth for request/response payload shape.

### Facility account and meter numbers (PROVISIONAL)

Approved by the product owner on 18 Nov 2026 as provisional: the ops lead may change the format of the client's
facility list. Each facility in `settings.facilities` may carry `accountNumbers: string[]` and, optionally,
`meterNumbers: string[]` (at most 50 each, at most 64 characters each, at least one digit, stored as typed). A
facility without them behaves exactly as before. A bad list is refused on save (422, a plain sentence). The same number
on two facilities saves; Setup shows "Account 4417-2290-31 is on two facilities. Bills with it won't be placed
automatically."

Placement uses them as the last step. The reviewer's choice, the facility name and the service address come first (the
name and address step answers match, ambiguous or none; the numbers are used only on none, never on ambiguous);
the bill's account number (then its meter number) is used **only when the bill gives no usable name and no usable
address**. A bill whose name or address matched nothing is never placed by its number: the Evidence tree row carries
`facility_note` ("Account 2001-7788 is listed on Tacoma Plant, but this bill's address (2210 Port of Tacoma Rd) is not
in Setup. Choose the facility.") and the reviewer chooses. A value a reviewer rejected or marked "needs more evidence",
and a value only Claude read, is never read for placement (name, address, account and meter number alike), on the
backend and on the screen.

A number matches only as a whole, never a partial one. NFKC and case folding apply, and invisible characters (a BOM)
are dropped. Spaces, dashes and dots separate groups: two numbers are the same when their groups are the same ("4417
2290 31" = "4417-2290-31"), or when one is written without separators and the characters are the same; "12-345" is not
"1234-5". A number needs at least 4 digits, on the bill and in Setup, to match. A number listed on two facilities, or an
account and a meter number that point at different facilities, place nothing: `facility_note` says why ("Account
7700-1234 is listed on two facilities. Choose the facility.") and the recalculation lists the record in
`calculation_unplaced` with `reason: "identifier_on_two_facilities"`. A bill placed this way is described as "Account
or meter number in Setup". Each record of a bill is placed on its own.

Not built yet, because the format is provisional and waits on the ops lead: a supplier per number (two utilities can
issue the same account number). The code is in `backend/app/services/facility_identifiers.py` (one matching function)
and `reviewed_evidence.place_on_facility` (the one placement decision); the frontend twin is
`frontend/features/s1/utils/facilityNumbers.ts` and `placeRecord` in `utils/documentView.ts`. Both sides run the shared
cases in `backend/tests/fixtures/facility_placement_cases.json` and the name and address probes in
`facility_match_probes.json`.

### Meter number and statement date (EXT-027)

Both are extraction targets (optional, display only) on every bill type: `meter_number` on stationary fuel
(`CT-S1-FUELQTY`), electricity and steam/heat/cooling bills, and `statement_date` (ISO date) on those and on mobile
fuel statements and refrigerant service invoices. The rule readers fill them; Claude fills one the rules missed, like
any other optional field. Neither ever feeds a calculation, and neither decides which facility a bill belongs to,
except that a meter number a Setup facility lists can place a bill (the provisional step above).

- **Statement date:** read only from a labelled field ("Statement Date", "Bill Date", "Invoice Date", "Billing Date",
  "Date Issued", "Stmt Date", "Report Date"). Never the service period (a range after the label is refused) and never
  a due date. A bare "Date" is not one.
- **Meter number:** read from "Meter No.", "Meter Number", "Meter #", "Meter ID", "Meter: ..." or a Meter column
  (also "Steam Meter"), with the account number's guard: at least 3 characters, a digit, not a date, an amount or a
  phone number ("Meter Reader Line: (555) 123-4567" is never read). On a bill of several meters each record keeps the
  meter of its own row; a bill that prints two different meters in prose has no single meter.
- They show on the review screen with the bill's other identifiers, and in the schedule's identifier groups ("Meter
  number" on utility lines, "Statement date" on every line). The workpaper export's Reviewed values sheet lists them
  like any extracted value.

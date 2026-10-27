# Pilot API Contract

## Endpoints

### POST /v1/engagements
Create an engagement shell for document and evidence lifecycle.

### GET /v1/engagements/{engagement_id}
Fetch engagement metadata and summary counts.

### POST /v1/engagements/{engagement_id}/documents
Register an uploaded document for processing.

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

## Contract Source

JSON schema contracts are versioned in `contracts/` and should be treated as API truth for request/response payload shape.

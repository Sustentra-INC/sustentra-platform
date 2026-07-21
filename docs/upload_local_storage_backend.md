# Upload + Local Storage Backend v0 (PR10)

PR10 adds a backend-controlled local upload/storage path so browser or dev clients can upload files without providing server-local paths manually.

## What PR10 adds

- Local storage service for uploaded bytes under ignored runtime storage.
- Document metadata repository persisted to local JSONL.
- Document upload service that stores file bytes and metadata.
- Multipart upload endpoint.
- Stored-document pipeline process endpoint that calls PR9 orchestration.
- Document retrieval and listing endpoints by document, engagement, and evidence.

## PR9 vs PR10 endpoint distinction

- PR9 local pipeline endpoint is for developer orchestration from a server-local path.
- PR10 upload endpoint is for browser/dev clients to put files into backend-controlled storage.

## Local storage and git safety

Uploaded files are stored under:

- local-data/uploads/

Document metadata is stored under:

- local-data/documents/documents.jsonl

These paths are runtime-only and ignored by git via local-data/.

Safe commit warning:

Never commit local-data uploads, private evidence files, .env, credentials, parser outputs, or generated local runtime data.

## Storage layout

PR10 stores files using a deterministic nested layout:

- local-data/uploads/{engagement_id}/{evidence_id}/{document_id}/{safe_file_name}

The storage service sanitizes file names and path components, rejects empty uploads, prevents path traversal, and avoids silent overwrite.

## API endpoints

- POST /v1/engagements/{engagement_id}/documents/upload
- POST /v1/engagements/{engagement_id}/documents
- GET /v1/documents/{document_id}
- GET /v1/engagements/{engagement_id}/documents
- GET /v1/evidence/{evidence_id}/documents
- POST /v1/documents/{document_id}/pipeline/process

Upload endpoint uses multipart form-data.
Metadata-only create remains available for compatibility but the upload endpoint is the primary flow.

## Process uploaded document behavior

The process endpoint uses stored metadata to resolve the local file path, then calls PR9 pipeline orchestration.

Flow:

- document_id -> metadata lookup
- storage_uri -> local path resolution
- document processing_status set to in_progress
- PR9 process_local_document call
- processing_status set to completed for completed/partial runs
- processing_status set to failed for failed runs

PR10 does not create review decisions and does not create approved evidence.

## Example curl commands

Upload:

```bash
curl -X POST "http://localhost:8000/v1/engagements/eng-demo-001/documents/upload" \
  -F "file=@sample-bill.pdf" \
  -F "document_role=source_evidence" \
  -F "uploaded_by=dev@example.com"
```

Process uploaded document:

```bash
curl -X POST "http://localhost:8000/v1/documents/{document_id}/pipeline/process" \
  -H "Content-Type: application/json" \
  -d '{"canonical_type_id_override":"CT-S1-FUELQTY","persist_run":true}'
```

## Current limitations

PR10 intentionally does not include:

- frontend UI wiring
- cloud object storage (S3/Azure Blob/GCS)
- authentication and authorization
- database migrations
- extraction algorithm changes
- review decision or approved evidence semantic changes
- validation, calculation, reconciliation, gap analysis, RAG, or S2 methodology logic

## Future replacement path

PR10 local storage abstractions are structured so LocalStorageService can be replaced later with cloud storage adapters while keeping upload and document metadata workflows consistent.

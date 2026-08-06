# S1 Shared Staging Pipeline Setup

This staging path runs the real S1 flow with shared durable services:

```
Frontend
-> FastAPI backend
-> PostgreSQL metadata/review/extraction repositories
-> MinIO document object storage
-> local extraction pipeline
```

## Start The Stack

From the repository root:

```bash
docker compose up
```

Services:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001
- PostgreSQL: localhost:5432

Default local credentials in `docker-compose.yml`:

- Postgres user/password/db: `sustentra` / `sustentra` / `sustentra`
- MinIO user/password: `sustentra` / `sustentra-password`
- MinIO bucket: `sustentra-documents`

## Runtime Switches

Backend:

```bash
SUSTENTRA_PERSISTENCE_BACKEND=postgres
DATABASE_URL=postgresql+psycopg2://sustentra:sustentra@postgres:5432/sustentra
SUSTENTRA_STORAGE_BACKEND=minio
SUSTENTRA_S3_ENDPOINT_URL=http://minio:9000
SUSTENTRA_S3_ACCESS_KEY_ID=sustentra
SUSTENTRA_S3_SECRET_ACCESS_KEY=sustentra-password
SUSTENTRA_S3_BUCKET=sustentra-documents
SUSTENTRA_LLM_EXTRACTION_ENABLED=false
OPENAI_API_KEY=
OPENAI_EXTRACTION_MODEL=gpt-4.1-mini
```

LLM extraction is optional but now implemented in the pipeline. Set
`SUSTENTRA_LLM_EXTRACTION_ENABLED=true` and provide `OPENAI_API_KEY` before
starting Docker Compose to run the structured LLM pass. The deterministic
extractor remains as fallback, and LLM candidates replace missing or obviously
overlong deterministic candidates.

Frontend:

```bash
NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8000
NEXT_PUBLIC_S1_DATA_MODE=backend
```

## What Persists

- Uploaded document objects persist in MinIO.
- Document metadata persists in `s1_documents`.
- Pipeline summaries persist in `s1_pipeline_runs`.
- Extraction results persist in `s1_extraction_results`.
- Review decisions persist in `s1_review_decisions`.

Tables are created by Alembic before the backend starts in Docker Compose:

```bash
alembic -c backend/alembic.ini upgrade head
```

The backend intentionally does not rely on runtime `create_all()` when
`SUSTENTRA_PERSISTENCE_BACKEND=postgres`.

## Smoke Test

1. Open http://localhost:3000.
2. Upload a document from the S1 upload area.
3. Wait for processing to finish.
4. Refresh the browser and confirm the document remains.
5. Open Extraction Review.
6. Use Download original and confirm the stored object opens.
7. Accept or correct a field.
8. Refresh and confirm the review state remains.

## Remaining Before Wider External Testing

- Add real user authentication and project permissions.
- Build a full Setup UI for project creation; the backend currently persists and
  seeds the known S1 engagement used by the workpaper.
- Persist audit events for type/facility/period/bulk workspace actions.
- Move table creation into Alembic migrations once the schema stabilizes.

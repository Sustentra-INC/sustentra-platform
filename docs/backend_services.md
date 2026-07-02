# Backend Service Skeleton

## API Routers

- engagements: engagement lifecycle operations.
- documents: document registration and lookup.
- processing_runs: extraction run lifecycle.
- evidence: evidence record retrieval.
- reviews: reviewer decisions per field.
- assistant: assistant endpoint shell.

## Service Layer Stubs

- ingestion_service: upload and metadata registration orchestration.
- processing_service: run lifecycle orchestration.
- classification_service: document role/type classification.
- extraction_service: candidate extraction normalization.
- review_service: decision persistence and audit metadata.
- approved_evidence_service: approved evidence projection.

## Adapter Layer Stubs

- parsers: textract/pdf/excel/image parser entry points.
- llm: OpenAI extraction adapter shell.
- storage: S3 read/write shell.
- persistence: SQLAlchemy session/bootstrap shell.

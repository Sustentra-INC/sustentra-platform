# Backend Pipeline Orchestration v0 (PR9)

PR9 adds a local backend orchestration layer that connects existing service stages into one coherent workflow:

local evidence file -> parse -> classify -> target planning -> candidate generation

## What PR9 adds

- Pipeline run contract at contracts/pipeline_run.schema.json.
- Pipeline run domain model at backend/app/domain/pipeline.py.
- Pipeline run repositories:
  - In-memory repository for tests.
  - JSONL repository at local-data/pipeline-runs/pipeline_runs.jsonl.
- Pipeline orchestration service at backend/app/services/pipeline_orchestration_service.py.
- Pipeline API router at backend/app/api/pipeline.py.
- Main app router registration for the new pipeline endpoints.

## How PR9 connects existing stages

PR9 orchestrates already-existing backend services from PR4, PR3, PR5, and PR6:

- ParserService parses a local file into parser_output.
- ClassificationService classifies document context.
- ExtractionTargetService resolves extraction targets.
- ExtractionService generates extraction candidates.

PR9 does not change these services' extraction or classification semantics.

## Relation to PR7 and PR8

PR9 can report cross-stage read-only status for an evidence_id by reading:

- review decision count from ReviewDecisionService
- latest approved evidence from ApprovedEvidenceService

PR9 does not create review decisions.
PR9 does not create approved evidence unless PR8 endpoints are separately called.

## Local process endpoint

POST /v1/pipeline/local/process-document is a local backend orchestration endpoint for development and testing.
It is not a production upload or storage endpoint.

Request includes:

- local_file_path
- engagement_id
- optional IDs and MIME/file metadata
- optional canonical_type_id_override

Response includes:

- pipeline_run summary
- parser_output
- classification_result
- extraction_targets
- extraction_result

## canonical_type_id override behavior

Resolution priority:

1. canonical_type_id_override
2. classifier primary_canonical_type_id when status supports target planning
3. none

When no canonical type can be used and no override is provided, target planning and candidate generation are skipped and the pipeline run status becomes partial.

## Pipeline status semantics

Overall status values:

- completed: parser succeeded and candidate_generation ran
- partial: parser succeeded but later stages were skipped or targets were not generated
- failed: parser failed or an orchestration-stage failure prevented run completion

Missing candidates are expected review inputs and do not fail the pipeline by themselves.

## Local JSONL persistence

Pipeline run summaries persist locally at:

- local-data/pipeline-runs/pipeline_runs.jsonl

Only summary metadata is persisted in PipelineRun.
Full parser text and full extraction payloads are not persisted in the run summary object.

## Remaining work after PR9

PR9 does not implement:

- production upload/storage
- frontend integration
- deployment/runtime infrastructure
- validation, calculation, reconciliation, or gap analysis
- RAG/S2 methodology engines
- extraction quality improvements

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

router = APIRouter(prefix="/v1", tags=["pipeline"])

_service = PipelineOrchestrationService()


def configure_service(service: PipelineOrchestrationService) -> None:
    global _service
    _service = service


class LocalProcessDocumentRequest(BaseModel):
    local_file_path: str
    engagement_id: str
    evidence_id: str | None = None
    document_id: str | None = None
    processing_run_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    canonical_type_id_override: str | None = None
    include_optional: bool = True
    include_deprecated: bool = False
    persist_run: bool = True


@router.post("/pipeline/local/process-document")
def process_local_document(payload: LocalProcessDocumentRequest) -> dict:
    try:
        result = _service.process_local_document(
            local_file_path=payload.local_file_path,
            engagement_id=payload.engagement_id,
            evidence_id=payload.evidence_id,
            document_id=payload.document_id,
            processing_run_id=payload.processing_run_id,
            file_name=payload.file_name,
            mime_type=payload.mime_type,
            canonical_type_id_override=payload.canonical_type_id_override,
            include_optional=payload.include_optional,
            include_deprecated=payload.include_deprecated,
            persist_run=payload.persist_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - safety path
        raise HTTPException(status_code=500, detail=f"Pipeline processing failed: {exc}") from exc

    pipeline_status = (
        result.get("pipeline_run", {}).get("status") if isinstance(result, dict) else None
    )
    if pipeline_status == "failed":
        detail = result.get("pipeline_run", {}).get("errors") or [
            "Pipeline run failed."
        ]
        raise HTTPException(status_code=500, detail=detail)

    return result


@router.get("/pipeline/runs/{pipeline_run_id}")
def get_pipeline_run(pipeline_run_id: str) -> dict:
    run = _service.get_pipeline_run(pipeline_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")
    return run


@router.get("/pipeline/evidence/{evidence_id}/latest-run")
def get_latest_run_by_evidence(evidence_id: str) -> dict:
    run = _service.get_latest_run_by_evidence(evidence_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No pipeline run found for evidence.")
    return run


@router.get("/pipeline/evidence/{evidence_id}/status")
def get_evidence_status(evidence_id: str) -> dict:
    return _service.get_evidence_status(evidence_id)

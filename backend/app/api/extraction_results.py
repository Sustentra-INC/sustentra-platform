from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

router = APIRouter(prefix="/v1", tags=["extraction-results"])

_pipeline_service = PipelineOrchestrationService()


def configure_service(service: PipelineOrchestrationService) -> None:
    """Swap the module-level service for tests and local wiring."""

    global _pipeline_service
    _pipeline_service = service


@router.get("/documents/{document_id}/extraction-result/latest")
def get_latest_document_extraction_result(document_id: str) -> dict:
    result = _pipeline_service.get_latest_extraction_result_by_document(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No extraction result found.")
    return result


@router.get("/evidence/{evidence_id}/extraction-result/latest")
def get_latest_evidence_extraction_result(evidence_id: str) -> dict:
    result = _pipeline_service.get_latest_extraction_result_by_evidence(evidence_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No extraction result found.")
    return result

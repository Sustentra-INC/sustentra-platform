from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

router = APIRouter(prefix="/v1", tags=["documents"])

_upload_service = DocumentUploadService()
_pipeline_service = PipelineOrchestrationService()
_storage_service = _upload_service.storage_service


def configure_services(
    upload_service: DocumentUploadService | None = None,
    pipeline_service: PipelineOrchestrationService | None = None,
    storage_service: LocalStorageService | None = None,
) -> None:
    """Swap module-level services for tests and local wiring."""

    global _upload_service, _pipeline_service, _storage_service
    if upload_service is not None:
        _upload_service = upload_service
        if storage_service is None:
            _storage_service = upload_service.storage_service
    if pipeline_service is not None:
        _pipeline_service = pipeline_service
    if storage_service is not None:
        _storage_service = storage_service


class CreateDocumentRequest(BaseModel):
    file_name: str
    mime_type: str
    storage_uri: str
    document_role: str
    document_type: str | None = None
    uploaded_by: str
    evidence_id: str | None = None
    processing_status: str = "queued"


class ProcessUploadedDocumentRequest(BaseModel):
    canonical_type_id_override: str | None = None
    include_optional: bool = True
    include_deprecated: bool = False
    persist_run: bool = True


@router.post("/engagements/{engagement_id}/documents")
def create_document(engagement_id: str, payload: CreateDocumentRequest) -> dict:
    try:
        return _upload_service.create_document_metadata(
            engagement_id=engagement_id,
            file_name=payload.file_name,
            mime_type=payload.mime_type,
            storage_uri=payload.storage_uri,
            document_role=payload.document_role,
            uploaded_by=payload.uploaded_by,
            evidence_id=payload.evidence_id,
            document_type=payload.document_type,
            processing_status=payload.processing_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/engagements/{engagement_id}/documents/upload")
async def upload_document(
    engagement_id: str,
    file: UploadFile = File(...),
    document_role: str = Form("source_evidence"),
    uploaded_by: str = Form(...),
    evidence_id: str | None = Form(None),
    document_type: str | None = Form(None),
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file name is required.")
    try:
        content = await file.read()
        mime_type = file.content_type or "application/octet-stream"
        return _upload_service.upload_document(
            engagement_id=engagement_id,
            file_name=file.filename,
            content=content,
            mime_type=mime_type,
            document_role=document_role,
            uploaded_by=uploaded_by,
            evidence_id=evidence_id,
            document_type=document_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/engagements/{engagement_id}/documents")
def list_documents(engagement_id: str) -> dict:
    return {
        "engagement_id": engagement_id,
        "items": _upload_service.list_documents(engagement_id),
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict:
    document = _upload_service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/evidence/{evidence_id}/documents")
def list_evidence_documents(evidence_id: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "items": _upload_service.list_documents_by_evidence(evidence_id),
    }


@router.post("/documents/{document_id}/pipeline/process")
def process_uploaded_document(
    document_id: str,
    payload: ProcessUploadedDocumentRequest,
) -> dict:
    document = _upload_service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    storage_uri = document.get("storage_uri")
    try:
        local_path = _storage_service.resolve_storage_uri(str(storage_uri))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not local_path.exists() or not local_path.is_file():
        raise HTTPException(status_code=400, detail="Stored document file is missing.")

    try:
        _upload_service.update_processing_status(document_id, "in_progress")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = _pipeline_service.process_local_document(
            local_file_path=str(local_path),
            engagement_id=str(document["engagement_id"]),
            evidence_id=document.get("evidence_id"),
            document_id=str(document["document_id"]),
            file_name=document.get("file_name"),
            mime_type=document.get("mime_type"),
            canonical_type_id_override=payload.canonical_type_id_override,
            include_optional=payload.include_optional,
            include_deprecated=payload.include_deprecated,
            persist_run=payload.persist_run,
        )
    except ValueError as exc:
        _upload_service.update_processing_status(document_id, "failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - safety path
        _upload_service.update_processing_status(document_id, "failed")
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline processing failed: {exc}",
        ) from exc

    pipeline_status = result.get("pipeline_run", {}).get("status")
    if pipeline_status == "failed":
        _upload_service.update_processing_status(document_id, "failed")
        detail = result.get("pipeline_run", {}).get("errors") or ["Pipeline run failed."]
        raise HTTPException(status_code=500, detail=detail)

    _upload_service.update_processing_status(document_id, "completed")
    return result

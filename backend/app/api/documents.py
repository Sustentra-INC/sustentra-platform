from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.app.api.s1_access import (
    evidence_free_or_own,
    org_of,
    require_visible,
    s1_reader,
    s1_writer,
    visible,
)
from backend.app.core.auth import CurrentUser

from backend.app.services.document_file_types import served_type
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

router = APIRouter(prefix="/v1", tags=["documents"])

_upload_service = DocumentUploadService()
_pipeline_service = PipelineOrchestrationService()
_storage_service = _upload_service.storage_service


def current_upload_service() -> DocumentUploadService:
    return _upload_service


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
    # Ignored: the uploader is the signed-in user (SEC-001). Kept for older clients.
    uploaded_by: str | None = None
    evidence_id: str | None = None
    processing_status: str = "queued"


class ProcessUploadedDocumentRequest(BaseModel):
    canonical_type_id_override: str | None = None
    include_optional: bool = True
    include_deprecated: bool = False
    persist_run: bool = True


def _uploader(user: CurrentUser) -> str:
    return user.email


def _require_evidence_slot(evidence_id: str | None, user: CurrentUser) -> None:
    # Attaching a document to another org's evidence must look like it does not exist.
    if evidence_id and not evidence_free_or_own(evidence_id, user):
        raise HTTPException(status_code=404, detail="Evidence not found.")


@router.post("/engagements/{engagement_id}/documents")
def create_document(
    engagement_id: str,
    payload: CreateDocumentRequest,
    user: CurrentUser = Depends(s1_writer),
) -> dict:
    org_id = org_of(user)
    _require_evidence_slot(payload.evidence_id, user)
    if not _storage_service.is_owned_by(payload.storage_uri, org_id):
        raise HTTPException(status_code=400, detail="storage_uri must point to a file uploaded by your organization.")
    try:
        return _upload_service.create_document_metadata(
            engagement_id=engagement_id,
            file_name=payload.file_name,
            mime_type=payload.mime_type,
            storage_uri=payload.storage_uri,
            document_role=payload.document_role,
            uploaded_by=_uploader(user),
            evidence_id=payload.evidence_id,
            document_type=payload.document_type,
            processing_status=payload.processing_status,
            org_id=org_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/engagements/{engagement_id}/documents/upload")
async def upload_document(
    engagement_id: str,
    file: UploadFile = File(...),
    document_role: str = Form("source_evidence"),
    uploaded_by: str | None = Form(None),  # ignored: the signed-in user uploads (SEC-001)
    evidence_id: str | None = Form(None),
    document_type: str | None = Form(None),
    user: CurrentUser = Depends(s1_writer),
) -> dict:
    org_id = org_of(user)
    _require_evidence_slot(evidence_id, user)
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
            uploaded_by=_uploader(user),
            evidence_id=evidence_id,
            document_type=document_type,
            org_id=org_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/engagements/{engagement_id}/documents")
def list_documents(engagement_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    return {
        "engagement_id": engagement_id,
        "items": visible(_upload_service.list_documents(engagement_id), user),
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    return require_visible(_upload_service.get_document(document_id), user, "Document not found.")


@router.get("/documents/{document_id}/extraction-result/latest")
def latest_extraction_result(document_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    """The candidates from the document's latest persisted pipeline run (S1-BE-001),
    in the shape the workpaper's field adapter reads."""

    require_visible(_upload_service.get_document(document_id), user, "Document not found.")
    results = visible(_pipeline_service.list_extraction_results_by_document(document_id), user)
    if not results:
        raise HTTPException(status_code=404, detail="Extraction result not found.")
    latest = results[-1]
    return {
        "evidence_id": latest.get("evidence_id"),
        "document_id": latest.get("document_id"),
        "pipeline_run_id": latest.get("pipeline_run_id"),
        "canonical_type_id": latest.get("canonical_type_id"),
        "status": latest.get("status"),
        "candidate_count": latest.get("candidate_count", 0),
        "items": latest.get("items") or [],
        "created_at": latest.get("created_at"),
    }


# Served-file headers (S1-BE-001). The API's own CSP/X-Frame-Options win over the
# proxy defaults (deploy/Caddyfile sets them with `?`), so only the preview can be
# framed, and only by the app itself.
_NO_STORE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
_DOWNLOAD_HEADERS = {
    **_NO_STORE,
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
    "X-Frame-Options": "DENY",
}
_PREVIEW_HEADERS = {**_NO_STORE, "X-Frame-Options": "SAMEORIGIN"}
# Chrome refuses to render a PDF under a `sandbox` CSP; images get the full lockdown.
_PREVIEW_CSP = {
    "application/pdf": "frame-ancestors 'self'",
    "image": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox",
}


def _stored_file(document_id: str, user: CurrentUser) -> tuple[dict, Path]:
    """The document (404 unless visible) and its file (404 when missing)."""

    document = require_visible(_upload_service.get_document(document_id), user, "Document not found.")
    missing = HTTPException(status_code=404, detail="Stored document file is missing.")
    storage_uri = str(document.get("storage_uri") or "")
    owner = document.get("org_id")
    # An owned document's file must sit in its org's folder (SEC-001); unowned
    # (pre-SEC-001, provider-only) files only need to be inside the upload root.
    if owner is not None and not _storage_service.is_owned_by(storage_uri, str(owner)):
        raise missing
    try:
        path = _storage_service.resolve_storage_uri(storage_uri)
    except ValueError:
        raise missing from None
    if not path.is_file():
        raise missing
    return document, path


def _download_name(document: dict, path: Path) -> str:
    name = str(document.get("file_name") or path.name)
    return "".join(ch for ch in name if ch.isprintable()) or path.name


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, user: CurrentUser = Depends(s1_reader)) -> FileResponse:
    document, path = _stored_file(document_id, user)
    return FileResponse(
        path,
        media_type=served_type(path, document.get("file_name")).media_type,
        filename=_download_name(document, path),
        content_disposition_type="attachment",
        headers=_DOWNLOAD_HEADERS,
    )


@router.get("/documents/{document_id}/preview")
def preview_document(document_id: str, user: CurrentUser = Depends(s1_reader)) -> FileResponse:
    document, path = _stored_file(document_id, user)
    kind = served_type(path, document.get("file_name"))
    if not kind.previewable:
        raise HTTPException(status_code=415, detail="Preview is not available for this file type.")
    csp = _PREVIEW_CSP["application/pdf" if kind.media_type == "application/pdf" else "image"]
    return FileResponse(
        path,
        media_type=kind.media_type,
        filename=_download_name(document, path),
        content_disposition_type="inline",
        headers={**_PREVIEW_HEADERS, "Content-Security-Policy": csp},
    )


@router.get("/evidence/{evidence_id}/documents")
def list_evidence_documents(evidence_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    return {
        "evidence_id": evidence_id,
        "items": visible(_upload_service.list_documents_by_evidence(evidence_id), user),
    }


@router.post("/documents/{document_id}/pipeline/process")
def process_uploaded_document(
    document_id: str,
    payload: ProcessUploadedDocumentRequest,
    user: CurrentUser = Depends(s1_writer),
) -> dict:
    document = require_visible(_upload_service.get_document(document_id), user, "Document not found.")
    org_id = org_of(user)

    storage_uri = document.get("storage_uri")
    if not _storage_service.is_owned_by(str(storage_uri), org_id):
        raise HTTPException(status_code=400, detail="Stored document file is missing.")
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
            org_id=org_id,
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

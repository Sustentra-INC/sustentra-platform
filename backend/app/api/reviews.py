from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.documents import current_upload_service
from backend.app.api.s1_access import (
    can_see,
    org_of,
    require_evidence,
    require_visible,
    s1_reader,
    s1_writer,
    visible,
)
from backend.app.core.auth import CurrentUser

from backend.app.repositories.review_repository import (
    DEFAULT_JSONL_PATH,
    JsonlReviewDecisionRepository,
)
from backend.app.services.review_decision_service import ReviewDecisionService

router = APIRouter(prefix="/v1", tags=["reviews"])

# Module-level service backed by local JSONL persistence (ignored by git).
_service = ReviewDecisionService(
    repository=JsonlReviewDecisionRepository(DEFAULT_JSONL_PATH)
)


def current_service():  # noqa: ANN201 - accessor for s1_access
    return _service


def configure_service(service: ReviewDecisionService) -> None:
    """Swap the module-level service (used by tests to inject a temp repo)."""

    global _service
    _service = service


class ReviewDecisionRequest(BaseModel):
    candidate: dict
    decision: str
    # Ignored: the reviewer is the signed-in user (SEC-001). Kept for older clients.
    reviewer_id: str | None = None
    reviewed_value: str | float | int | bool | None = None
    reviewed_unit: str | None = None
    reviewer_note: str | None = None
    # Backward-compatible aliases (output always uses the reviewed_* names).
    reviewed_by: str | None = None
    approved_value: str | float | int | bool | None = None
    approved_unit: str | None = None


@router.put("/evidence/{evidence_id}/fields/{field_name}/review")
def review_field(
    evidence_id: str,
    field_name: str,
    payload: ReviewDecisionRequest,
    user: CurrentUser = Depends(s1_writer),
) -> dict:
    candidate = payload.candidate
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=400, detail="candidate must be an object.")
    if candidate.get("evidence_id") != evidence_id:
        raise HTTPException(
            status_code=400, detail="candidate.evidence_id does not match path evidence_id."
        )
    if candidate.get("field_name") != field_name:
        raise HTTPException(
            status_code=400, detail="candidate.field_name does not match path field_name."
        )

    # Shape checks above reveal nothing; ownership is checked before anything is read.
    require_evidence(evidence_id, user)
    document_id = str(candidate.get("document_id") or "")
    expected_prefix = f"candidate::{evidence_id}::{document_id}::{field_name}"
    candidate_id = str(candidate.get("candidate_id") or "")
    if candidate_id != expected_prefix and not candidate_id.startswith(expected_prefix + "::"):
        raise HTTPException(status_code=400, detail="candidate_id does not match the evidence, document and field.")
    if not any(
        doc.get("document_id") == document_id and can_see(doc, user)
        for doc in current_upload_service().list_documents_by_evidence(evidence_id)
    ):
        raise HTTPException(status_code=404, detail="Document not found.")
    reviewer_id = user.email

    reviewed_value = (
        payload.reviewed_value if payload.reviewed_value is not None else payload.approved_value
    )
    reviewed_unit = (
        payload.reviewed_unit if payload.reviewed_unit is not None else payload.approved_unit
    )

    try:
        return _service.submit_decision(
            candidate=candidate,
            decision=payload.decision,
            reviewer_id=reviewer_id,
            reviewed_value=reviewed_value,
            reviewed_unit=reviewed_unit,
            reviewer_note=payload.reviewer_note,
            org_id=org_of(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/evidence/{evidence_id}/reviews")
def list_evidence_reviews(evidence_id: str, user: CurrentUser = Depends(s1_reader)) -> list[dict]:
    return visible(_service.list_by_evidence(evidence_id), user)


@router.get("/documents/{document_id}/reviews")
def list_document_reviews(document_id: str, user: CurrentUser = Depends(s1_reader)) -> list[dict]:
    return visible(_service.list_by_document(document_id), user)


@router.get("/candidates/{candidate_id}/reviews/latest")
def latest_candidate_review(candidate_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    own = visible(_service.list_by_candidate(candidate_id), user)
    return require_visible(own[-1] if own else None, user, "No review decision found for candidate.")

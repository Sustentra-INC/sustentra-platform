from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


def configure_service(service: ReviewDecisionService) -> None:
    """Swap the module-level service (used by tests to inject a temp repo)."""

    global _service
    _service = service


class ReviewDecisionRequest(BaseModel):
    candidate: dict
    decision: str
    reviewer_id: str | None = None
    reviewed_value: str | float | int | bool | None = None
    reviewed_unit: str | None = None
    reviewer_note: str | None = None
    # Backward-compatible aliases (output always uses the reviewed_* names).
    reviewed_by: str | None = None
    approved_value: str | float | int | bool | None = None
    approved_unit: str | None = None


@router.put("/evidence/{evidence_id}/fields/{field_name}/review")
def review_field(evidence_id: str, field_name: str, payload: ReviewDecisionRequest) -> dict:
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

    reviewer_id = payload.reviewer_id or payload.reviewed_by
    if not reviewer_id:
        raise HTTPException(status_code=400, detail="reviewer_id is required.")

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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/evidence/{evidence_id}/reviews")
def list_evidence_reviews(evidence_id: str) -> list[dict]:
    return _service.list_by_evidence(evidence_id)


@router.get("/documents/{document_id}/reviews")
def list_document_reviews(document_id: str) -> list[dict]:
    return _service.list_by_document(document_id)


@router.get("/candidates/{candidate_id}/reviews/latest")
def latest_candidate_review(candidate_id: str) -> dict:
    latest = _service.get_latest_by_candidate(candidate_id)
    if latest is None:
        raise HTTPException(status_code=404, detail="No review decision found for candidate.")
    return latest

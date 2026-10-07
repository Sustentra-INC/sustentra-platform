from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.s1_access import org_of, require_evidence, require_visible, s1_reader, s1_writer, visible
from backend.app.core.auth import CurrentUser

from backend.app.repositories.evidence_repository import (
    DEFAULT_JSONL_PATH as APPROVED_EVIDENCE_JSONL_PATH,
    JsonlApprovedEvidenceRepository,
)
from backend.app.repositories.review_repository import (
    DEFAULT_JSONL_PATH as REVIEW_DECISION_JSONL_PATH,
    JsonlReviewDecisionRepository,
)
from backend.app.services.approved_evidence_service import ApprovedEvidenceService

router = APIRouter(prefix="/v1", tags=["evidence"])

_service = ApprovedEvidenceService(
    review_repository=JsonlReviewDecisionRepository(REVIEW_DECISION_JSONL_PATH),
    approved_repository=JsonlApprovedEvidenceRepository(APPROVED_EVIDENCE_JSONL_PATH),
)


def current_service():  # noqa: ANN201 - accessor for s1_access
    return _service


def configure_service(service: ApprovedEvidenceService) -> None:
    """Swap the module-level service (used by tests to inject temp repos)."""

    global _service
    _service = service


class ApprovedEvidenceProjectionRequest(BaseModel):
    engagement_id: str
    evidence_type: str


@router.get("/engagements/{engagement_id}/evidence")
def list_evidence(engagement_id: str, user: CurrentUser = Depends(s1_reader)) -> dict[str, object]:
    # Placeholder (no evidence store yet): fixed demo payload, never another org's data.
    return {
        "engagement_id": engagement_id,
        "items": [
            {
                "evidence_id": "ev_demo_001",
                "document_id": "doc_demo_001",
                "evidence_type": "utility_bill",
                "review_status": "in_review"
            }
        ]
    }


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str, user: CurrentUser = Depends(s1_reader)) -> dict[str, object]:
    require_evidence(evidence_id, user)
    return {
        "evidence_id": evidence_id,
        "engagement_id": "eng_demo_001",
        "document_id": "doc_demo_001",
        "evidence_type": "utility_bill",
        "review_status": "in_review",
        "fields": []
    }


@router.post("/evidence/{evidence_id}/approved-evidence/project")
def project_approved_evidence(
    evidence_id: str,
    payload: ApprovedEvidenceProjectionRequest,
    user: CurrentUser = Depends(s1_writer),
) -> dict:
    require_evidence(evidence_id, user)
    try:
        return _service.project_by_evidence(
            evidence_id=evidence_id,
            engagement_id=payload.engagement_id,
            evidence_type=payload.evidence_type,
            org_id=org_of(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/evidence/{evidence_id}/approved-evidence/latest")
def get_latest_approved_evidence(evidence_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    return require_visible(_service.get_latest_by_evidence(evidence_id), user, "No approved evidence found.")


@router.get("/approved-evidence/{approved_evidence_id}")
def get_approved_evidence_by_id(approved_evidence_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    return require_visible(_service.get_by_id(approved_evidence_id), user, "Approved evidence not found.")


@router.get("/engagements/{engagement_id}/approved-evidence")
def list_approved_evidence(engagement_id: str, user: CurrentUser = Depends(s1_reader)) -> list[dict]:
    return visible(_service.list_by_engagement(engagement_id), user)

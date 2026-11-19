from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api import evidence as evidence_api
from backend.app.api.s1_access import org_of, require_evidence, s1_writer, visible
from backend.app.core.auth import CurrentUser

from backend.app.services.reviewed_evidence import stale_decision_ids
from backend.app.services.s2_orchestration_service import (
    S2OrchestrationService,
    build_default_s2_orchestration_service,
)

router = APIRouter(prefix="/v1", tags=["methodology"])

_service = build_default_s2_orchestration_service()


def configure_service(service: S2OrchestrationService) -> None:
    """Swap the module-level service for tests."""

    global _service
    _service = service


class S2RunRequest(BaseModel):
    approved_evidence: dict[str, Any]
    runtime_condition_values: dict[str, Any] | None = None
    persist_methodology_values: bool = Field(default=False)


def _without_stale_fields(stored: dict[str, Any], user: CurrentUser) -> dict[str, Any]:
    """The stored approved evidence without the fields whose review decision no longer applies to the
    document's latest read (it was re-read and the value changed): they are unreviewed, so they feed no
    methodology value. A field whose decision is not known here is kept."""

    from backend.app.api.documents import current_pipeline_service as pipeline_service
    from backend.app.api.reviews import current_service as review_service

    evidence_id = str(stored.get("evidence_id") or "")
    results = visible(pipeline_service().list_extraction_results_by_evidence(evidence_id), user)
    if not results:
        return stored
    stale = stale_decision_ids(results[-1].get("items") or [], visible(review_service().list_by_evidence(evidence_id), user))
    if not stale:
        return stored
    return {**stored, "fields": [f for f in stored.get("fields") or [] if str(f.get("review_decision_id")) not in stale]}


@router.post("/methodology/s2/run")
def run_s2_methodology(payload: S2RunRequest, user: CurrentUser = Depends(s1_writer)) -> dict:
    # The approved evidence must belong to the caller's org. A payload without an
    # evidence id is rejected by the service's validation (400).
    approved_evidence = payload.approved_evidence
    evidence_id = approved_evidence.get("evidence_id")
    if evidence_id:
        require_evidence(str(evidence_id), user)
    if payload.persist_methodology_values:
        # Persisting replaces stored values by approved_evidence_id: use the server's own
        # record (owned by the caller), never a client-supplied copy.
        stored = evidence_api.current_service().get_by_id(str(approved_evidence.get("approved_evidence_id") or ""))
        if stored is None or stored.get("org_id") != org_of(user) or stored.get("evidence_id") != evidence_id:
            raise HTTPException(status_code=404, detail="Approved evidence not found.")
        approved_evidence = _without_stale_fields(stored, user)
    try:
        return _service.run(
            approved_evidence,
            runtime_condition_values=payload.runtime_condition_values,
            persist_methodology_values=payload.persist_methodology_values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

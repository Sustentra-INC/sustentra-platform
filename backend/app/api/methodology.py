from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api import evidence as evidence_api
from backend.app.api.s1_access import org_of, require_evidence, s1_writer
from backend.app.core.auth import CurrentUser

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
        approved_evidence = stored
    try:
        return _service.run(
            approved_evidence,
            runtime_condition_values=payload.runtime_condition_values,
            persist_methodology_values=payload.persist_methodology_values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
def run_s2_methodology(payload: S2RunRequest) -> dict:
    try:
        return _service.run(
            payload.approved_evidence,
            runtime_condition_values=payload.runtime_condition_values,
            persist_methodology_values=payload.persist_methodology_values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

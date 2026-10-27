"""Processing runs: asking for a document to be read, and following the read
(contracts/processing_run.schema.json).

* POST /documents/{id}/processing-runs (writers): with S1_PROCESSING=inline (the default) the
  document is read in this request and the finished run comes back (200); with queued the
  run is only queued (202). Asking again while a run is active returns that run (202);
  asking for a different type while it is active is a 409.
* GET /processing-runs/{run_id}: one run (404 for another organization's).
* GET /engagements/{id}/processing-runs: each document's latest run, the one call the
  workspace polls while reads are in flight.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from backend.app.api import documents as documents_api
from backend.app.api.s1_access import can_see, org_of, s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.config import get_settings
from backend.app.repositories.processing_run_repository import ProcessingRun
from backend.app.services.document_processing_service import RunConflict, RunParams

router = APIRouter(prefix="/v1", tags=["processing-runs"])


class StartProcessingRunRequest(BaseModel):
    canonical_type_id_override: str | None = None
    include_optional: bool = True
    include_deprecated: bool = False


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def run_view(run: ProcessingRun) -> dict[str, Any]:
    """A run as the API returns it (ProcessingRun in contracts/processing_run.schema.json)."""

    return {
        "run_id": run.run_id,
        "document_id": run.document_id,
        "engagement_id": run.engagement_id,
        "evidence_id": run.evidence_id,
        "status": run.status,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "pipeline_version": get_settings().git_sha,
        "requested_by": run.requested_by,
        "attempt": run.attempts,
        "max_attempts": run.max_attempts,
        "canonical_type_id_override": run.params.get("canonical_type_id_override"),
        "pipeline_run_id": run.pipeline_run_id,
        "error_code": run.error_code,
        "error": run.error,
    }


def _visible(run: ProcessingRun, user: CurrentUser) -> bool:
    return can_see({"org_id": run.org_id}, user)


@router.post("/documents/{document_id}/processing-runs")
def start_processing_run(
    document_id: str,
    response: Response,
    payload: StartProcessingRunRequest | None = None,
    user: CurrentUser = Depends(s1_writer),
) -> dict[str, Any]:
    document = documents_api.processable_document(document_id, user)
    body = payload or StartProcessingRunRequest()
    service = documents_api.processing_service()
    try:
        run, created = service.request(
            document=document,
            org_id=org_of(user),
            requested_by=user.email,
            params=RunParams(
                canonical_type_id_override=body.canonical_type_id_override,
                include_optional=body.include_optional,
                include_deprecated=body.include_deprecated,
            ),
        )
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if get_settings().s1_processing == "queued":
        if created:
            service.mark_queued(run)
    elif run.status == "queued":
        # Inline: read it now. A run left queued (e.g. by a switch back from queued) is read too.
        finished, outcome = service.run_inline(run)
        if outcome is not None:
            return run_view(finished)
        run = finished
    response.status_code = 202
    return run_view(run)


@router.get("/processing-runs/{run_id}")
def get_processing_run(run_id: str, user: CurrentUser = Depends(s1_reader)) -> dict[str, Any]:
    run = documents_api.current_run_repository().get(run_id)
    if run is None or not _visible(run, user):
        raise HTTPException(status_code=404, detail="Processing run not found.")
    return run_view(run)


@router.get("/engagements/{engagement_id}/processing-runs")
def list_processing_runs(engagement_id: str, user: CurrentUser = Depends(s1_reader)) -> dict[str, Any]:
    runs = documents_api.current_run_repository().latest_per_document(engagement_id)
    return {"engagement_id": engagement_id, "items": [run_view(run) for run in runs if _visible(run, user)]}

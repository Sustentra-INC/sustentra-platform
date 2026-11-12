"""Document batches: files uploaded together, and one progress view over their reads.

* POST /engagements/{id}/document-batches (writers): creates a batch, ``{batch_id}``. Uploads
  to the same engagement then carry ``batch_id`` (documents.py).
* GET /engagements/{id}/document-batches/{batch_id}: per document its status, chunk progress,
  canonical type, a sentence saying why it stopped, and the records found; and the totals.

A document's status here is one of ``queued`` (waiting for a reader), ``reading``,
``done``, ``partial`` (read, but not all of it: pages that failed, or nothing to review) and
``failed``. A batch of another organization, or of another engagement, is a 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api import documents as documents_api
from backend.app.api.engagements import require_open_engagement
from backend.app.api.s1_access import can_see, org_of, s1_reader, s1_writer, visible
from backend.app.core.auth import CurrentUser
from backend.app.repositories.document_batch_repository import (
    DocumentBatch,
    DocumentBatchRepository,
)
from backend.app.repositories.document_chunk_repository import ChunkSummary
from backend.app.repositories.processing_run_repository import ProcessingRun

router = APIRouter(prefix="/v1", tags=["document-batches"])

# The batch table lives in Postgres whatever S1_STORE is (as the run queue).
_batch_repository: Any = DocumentBatchRepository()

STATUSES = ("queued", "reading", "done", "partial", "failed", "not_started")
NOT_STARTED_MESSAGE = "Reading hasn't started for this file. Open it to start reading."
READ_FAILED_MESSAGE = "Reading failed. Try uploading the file again."
BATCH_NOT_FOUND = "Batch not found."
_RUN_STATUS = {"queued": "queued", "in_progress": "reading", "waiting_on_chunks": "reading", "failed": "failed"}


def current_batch_repository() -> Any:
    return _batch_repository


def configure_batch_repository(repository: Any) -> None:
    """Swap the batch store, for tests."""

    global _batch_repository
    _batch_repository = repository


class CreateBatchRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)


def require_batch(batch_id: str | None, engagement_id: str, user: CurrentUser) -> DocumentBatch:
    """The batch, or 404 when it does not exist, is another organization's, or belongs to another
    engagement (the same answer for each, so nothing is revealed)."""

    batch = _batch_repository.get(batch_id) if batch_id else None
    if batch is None or not can_see({"org_id": batch.org_id}, user) or batch.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail=BATCH_NOT_FOUND)
    return batch


@router.post("/engagements/{engagement_id}/document-batches", status_code=201)
def create_batch(
    engagement_id: str,
    payload: CreateBatchRequest | None = None,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict = Depends(require_open_engagement),
) -> dict:
    batch = _batch_repository.create(
        org_id=org_of(user),
        engagement_id=engagement_id,
        created_by=user.email,
        label=(payload.label if payload else None) or None,
    )
    return {"batch_id": batch.id, "engagement_id": engagement_id, "label": batch.label,
            "created_at": batch.created_at.isoformat()}


def _pages(failed_pages: list[list[int]]) -> str:
    """'Page 4' or 'Pages 4, 9-12': the failed page ranges, in words."""

    spans = [str(start) if start == end else f"{start}-{end}" for start, end in failed_pages]
    single = len(failed_pages) == 1 and failed_pages[0][0] == failed_pages[0][1]
    return f"{'Page' if single else 'Pages'} {', '.join(spans)}"


def _row(
    document: dict[str, Any],
    run: ProcessingRun | None,
    chunks: ChunkSummary | None,
    pipeline_run: dict[str, Any] | None,
) -> dict[str, Any]:
    """One document of the batch, as the progress view shows it."""

    # No run at all: the upload stored the file but no read was ever asked for (it is not waiting).
    status = "not_started" if run is None else _RUN_STATUS.get(run.status, "done")
    if status == "queued" and chunks is not None:
        status = "reading"  # the chunks are read and the run waits to be assembled: not waiting to start
    halt: str | None = NOT_STARTED_MESSAGE if run is None else None
    if run is not None and run.status == "failed":
        halt = ((pipeline_run or {}).get("halt_reason") or {}).get("message") or run.error or READ_FAILED_MESSAGE
    elif run is not None and run.status == "completed" and pipeline_run is not None:
        if pipeline_run.get("status") == "failed":
            status = "failed"
        elif pipeline_run.get("status") == "partial":
            status = "partial"
        halt = (pipeline_run.get("halt_reason") or {}).get("message")
        if halt is None and chunks is not None and chunks.failed_pages:
            halt = f"{_pages(chunks.failed_pages)} could not be read."
    return {
        "document_id": document["document_id"],
        "file_name": document["file_name"],
        "status": status,
        "chunks": None if chunks is None else {
            "total": chunks.total, "completed": chunks.completed, "failed": chunks.failed,
            "failed_pages": chunks.failed_pages},
        "canonical_type_id": (pipeline_run or {}).get("canonical_type_id"),
        "halt_reason": halt,
        "records_found": int((pipeline_run or {}).get("found_candidate_count") or 0),
    }


@router.get("/engagements/{engagement_id}/document-batches/{batch_id}")
def get_batch(engagement_id: str, batch_id: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    batch = require_batch(batch_id, engagement_id, user)
    documents = [
        document for document in visible(documents_api.current_upload_service().list_documents_by_batch(batch.id), user)
        if document.get("engagement_id") == engagement_id
    ]
    runs = {run.document_id: run for run in documents_api.current_run_repository().latest_per_document(engagement_id)}
    batch_runs = [runs[d["document_id"]] for d in documents if d["document_id"] in runs]
    summaries = documents_api.current_chunk_repository().summaries([run.run_id for run in batch_runs])
    pipeline = documents_api.current_pipeline_service()

    items = []
    for document in documents:
        run = runs.get(document["document_id"])
        pipeline_run = None
        if run is not None and run.pipeline_run_id:
            pipeline_run = pipeline.get_pipeline_run(run.pipeline_run_id)
            if not can_see(pipeline_run, user):
                pipeline_run = None
        items.append(_row(document, run, summaries.get(run.run_id) if run else None, pipeline_run))

    totals = {status: sum(1 for item in items if item["status"] == status) for status in STATUSES}
    return {
        "batch_id": batch.id,
        "engagement_id": engagement_id,
        "label": batch.label,
        "created_at": batch.created_at.isoformat(),
        "items": items,
        "totals": totals,
        # Nothing is waiting or being read: the client stops asking. A document no read was asked
        # for (not_started) is not waiting on anything either.
        "complete": totals["queued"] == 0 and totals["reading"] == 0,
    }

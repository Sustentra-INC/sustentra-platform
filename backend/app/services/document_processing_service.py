"""Reading a document for a processing run: one executor for every way a run is read.

* ``S1_PROCESSING=inline`` (the default): POST /documents/{id}/processing-runs and the older
  POST /documents/{id}/pipeline/process read the document inside the request (``run_inline``),
  as before, and the read is recorded as a run.
* ``S1_PROCESSING=queued``: the request only queues the run; the reader process claims it
  and calls ``execute`` and then ``finish``.

``execute`` reads with the existing stores, so it needs the run's organization as the bound
S1 scope (the request's, or ``scoped(S1Scope.tenant(run.org_id))`` in the reader). RLS and
the evidence-owner claims then apply exactly as for a request.

The document's processing_status follows the run: in_progress while it is read, then
completed or failed (queued while a queued run waits).

How an attempt ends (``Outcome``):

| What happened                           | Run                                   | Read again |
|-----------------------------------------|---------------------------------------|------------|
| the pipeline recorded a run             | completed, with its pipeline_run_id   | -          |
| the pipeline run failed                 | failed: the halt's code and message,  | no         |
|                                         | with its pipeline_run_id              |            |
| the pipeline refused the input          | failed: invalid_request               | no         |
| the document or its file is gone        | failed: document_missing/file_missing | no         |
| anything else raised (store, database)  | queued again after 30s, then 120s     | yes        |

A run that keeps failing that way fails with ``worker_error`` after its last attempt; inline,
there is no second attempt.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.app.repositories.processing_run_repository import ProcessingRun

logger = logging.getLogger("sustentra.processing")

# Inline the request itself is the reader and renews nothing: the lease only matters when the
# API stops mid-read, after which the next request for the document takes the run over.
INLINE_LEASE_SECONDS = 900
RETRY_DELAYS_SECONDS = (30, 120)

PIPELINE_FAILED_MESSAGE = "Reading failed on our side. Try again; if it happens again, tell us."
WORKER_ERROR_MESSAGE = "Reading stopped because of a problem on our side. Try again; if it happens again, tell us."
FILE_MISSING_MESSAGE = "The stored file is missing. Upload it again."
DOCUMENT_MISSING_MESSAGE = "This document no longer exists. Upload it again."
STILL_READING_MESSAGE = "This document is still being read. Choose its type again once reading finishes."


def inline_worker_id() -> str:
    return f"inline:{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True)
class RunParams:
    """What a run reads the document as (stored in the run's ``params``)."""

    canonical_type_id_override: str | None = None
    include_optional: bool = True
    include_deprecated: bool = False
    persist_run: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_type_id_override": self.canonical_type_id_override,
            "include_optional": self.include_optional,
            "include_deprecated": self.include_deprecated,
            "persist_run": self.persist_run,
        }

    @classmethod
    def of(cls, run: ProcessingRun) -> RunParams:
        params = run.params
        return cls(
            canonical_type_id_override=params.get("canonical_type_id_override"),
            include_optional=bool(params.get("include_optional", True)),
            include_deprecated=bool(params.get("include_deprecated", False)),
            persist_run=bool(params.get("persist_run", True)),
        )


@dataclass(frozen=True)
class Outcome:
    """How one attempt at a run ended."""

    status: Literal["completed", "failed", "retry"]
    pipeline_run_id: str | None = None
    error_code: str | None = None
    error: str | None = None  # the message the user sees
    # The pipeline's whole result when this attempt read the document (the older endpoint
    # returns it), or ``{"pipeline_run": ...}`` when an earlier attempt already had.
    result: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None  # what was raised, for logs and the older endpoint

    @property
    def pipeline_run(self) -> dict[str, Any]:
        return dict(self.result.get("pipeline_run") or {})


class RunConflict(Exception):
    """The document already has an active run that reads it differently."""

    def __init__(self, run: ProcessingRun) -> None:
        super().__init__(STILL_READING_MESSAGE)
        self.run = run


class DocumentProcessingService:
    def __init__(
        self,
        runs: Any,
        upload_service: Any,
        pipeline_service: Any,
        storage_service: Any,
        *,
        worker_id: str | None = None,
    ) -> None:
        self._runs = runs
        self._uploads = upload_service
        self._pipeline = pipeline_service
        self._storage = storage_service
        self._worker_id = worker_id or inline_worker_id()

    @property
    def worker_id(self) -> str:
        return self._worker_id

    # --- asking for a read ------------------------------------------------------------------

    def request(
        self, *, document: dict[str, Any], org_id: str, requested_by: str, params: RunParams
    ) -> tuple[ProcessingRun, bool]:
        """A queued run for the document, or the active run it already has (``created`` False).

        Raises ``RunConflict`` when the active run reads the document with other params (another
        type), since a second read cannot start before it finishes.
        """

        run, created = self._runs.enqueue(
            org_id=org_id,
            engagement_id=str(document["engagement_id"]),
            document_id=str(document["document_id"]),
            evidence_id=document.get("evidence_id"),
            params=params.as_dict(),
            requested_by=requested_by,
        )
        if not created and RunParams.of(run) != params:
            raise RunConflict(run)
        return run, created

    def mark_queued(self, run: ProcessingRun) -> None:
        """Queued mode: the document waits for the reader."""

        self._set_status(run.document_id, "queued")

    def run_inline(self, run: ProcessingRun) -> tuple[ProcessingRun, Outcome | None]:
        """Read a queued run now, in this request. ``None`` when something else already took it."""

        started = self._runs.start(run, self._worker_id, INLINE_LEASE_SECONDS)
        if started is None:
            return self._runs.get(run.run_id) or run, None
        outcome = self.execute(started)
        return self.finish(started, outcome, retry=False), outcome

    # --- reading ------------------------------------------------------------------------------

    def execute(self, run: ProcessingRun) -> Outcome:
        """Read the run's document (one attempt). Never raises: every ending is an ``Outcome``."""

        document = self._uploads.get_document(run.document_id)
        if document is None:
            return Outcome("failed", error_code="document_missing", error=DOCUMENT_MISSING_MESSAGE)
        path = self._stored_file(document, run.org_id)
        if path is None:
            return Outcome("failed", error_code="file_missing", error=FILE_MISSING_MESSAGE)
        if not self._set_status(run.document_id, "in_progress"):
            return Outcome("failed", error_code="document_missing", error=DOCUMENT_MISSING_MESSAGE)

        if run.attempts > 1:  # an earlier attempt may have recorded its result before it stopped
            earlier = self._earlier_result(run, document)
            if earlier is not None:
                return earlier

        params = RunParams.of(run)
        try:
            result = self._pipeline.process_local_document(
                local_file_path=str(path),
                engagement_id=str(document["engagement_id"]),
                evidence_id=document.get("evidence_id"),
                document_id=str(document["document_id"]),
                processing_run_id=run.run_id,
                file_name=document.get("file_name"),
                mime_type=document.get("mime_type"),
                canonical_type_id_override=params.canonical_type_id_override,
                include_optional=params.include_optional,
                include_deprecated=params.include_deprecated,
                persist_run=params.persist_run,
                org_id=run.org_id,
            )
        except ValueError as exc:
            return Outcome("failed", error_code="invalid_request", error=str(exc), detail=str(exc))
        except Exception as exc:
            logger.exception("Reading document %s failed (processing run %s)", run.document_id, run.run_id)
            return Outcome("retry", error_code="worker_error", error=WORKER_ERROR_MESSAGE, detail=str(exc))
        return _from_pipeline_result(result)

    def _stored_file(self, document: dict[str, Any], org_id: str) -> Any:
        storage_uri = str(document.get("storage_uri") or "")
        if not self._storage.is_owned_by(storage_uri, org_id):
            return None
        try:
            path = self._storage.resolve_storage_uri(storage_uri)
        except ValueError:
            return None
        return path if path.is_file() else None

    def _earlier_result(self, run: ProcessingRun, document: dict[str, Any]) -> Outcome | None:
        evidence_id = document.get("evidence_id")
        if not evidence_id:
            return None
        recorded = [r for r in self._pipeline.list_runs_by_evidence(evidence_id)
                    if r.get("processing_run_id") == run.run_id]
        return _from_pipeline_result({"pipeline_run": recorded[-1]}) if recorded else None

    # --- recording how it ended -------------------------------------------------------------

    def finish(self, run: ProcessingRun, outcome: Outcome, *, retry: bool) -> ProcessingRun:
        """Record the outcome on the run and its document. ``retry``: whether a problem on our
        side may be read again later (the reader) or fails the run now (inline).

        Every update is fenced to this reader: if the run was taken over meanwhile (its lease
        ran out), nothing is recorded and the run is returned as it now stands.
        """

        worker = self._worker_id
        finished: ProcessingRun | None
        if outcome.status == "completed":
            finished = self._runs.finalize_completed(run, worker, str(outcome.pipeline_run_id))
            status = "completed"
        elif outcome.status == "failed":
            finished = self._runs.finalize_failed(run, worker, str(outcome.error_code), str(outcome.error),
                                                  outcome.pipeline_run_id)
            status = "failed"
        elif retry and run.attempts < run.max_attempts:
            delay = RETRY_DELAYS_SECONDS[min(run.attempts, len(RETRY_DELAYS_SECONDS)) - 1]
            finished = self._runs.retry_later(run, worker, delay, outcome.error_code)
            status = "queued"
        else:
            finished = self._runs.finalize_failed(run, worker, "worker_error", WORKER_ERROR_MESSAGE)
            status = "failed"
        if finished is None:
            return self._runs.get(run.run_id) or run
        self._set_status(run.document_id, status)
        return finished

    def _set_status(self, document_id: str, status: str) -> bool:
        try:
            self._uploads.update_processing_status(document_id, status)
        except KeyError:
            return False
        return True


def _from_pipeline_result(result: dict[str, Any]) -> Outcome:
    pipeline_run = result.get("pipeline_run") or {}
    pipeline_run_id = pipeline_run.get("pipeline_run_id")
    if pipeline_run.get("status") == "failed":
        # A halt is about the document (unreadable, corrupt, unsupported); without one the
        # pipeline itself broke. Either way the same file fails the same way again.
        halt = pipeline_run.get("halt_reason") or {}
        return Outcome("failed", pipeline_run_id=pipeline_run_id, error_code=halt.get("code") or "pipeline_failed",
                       error=halt.get("message") or PIPELINE_FAILED_MESSAGE, result=result)
    return Outcome("completed", pipeline_run_id=str(pipeline_run_id), result=result)

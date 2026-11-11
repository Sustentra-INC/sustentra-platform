"""The reader process: reads the documents whose processing runs are queued.

``python -m backend.app.workers.processing_reader``. It claims the oldest due run of any
organization (``SKIP LOCKED``, so several readers never take the same one), reads the document
with ``DocumentProcessingService`` in a daemon thread bound to the run's own organization, and
records how the read ended. While the read goes on, the calling thread supervises it:

* it renews the run's lease every ``heartbeat_seconds``; a run that loses its lease (this reader
  was too slow to renew it) goes on being read, but its ``finish`` is fenced and records nothing;
* a read that outlives ``max_run_seconds`` ends the process (``EXIT_OVERRAN``): Docker restarts
  the container and the run is queued again once its lease runs out;
* on SIGTERM the read gets ``shutdown_grace_seconds`` to finish, and then the run is put back
  in the queue without counting the attempt.

Every ``REQUEUE_EVERY_SECONDS`` the reader also puts back the runs whose reader stopped renewing
their lease (or fails them after their last attempt) and moves their documents' status with them.

The reader touches ``reader_health.ALIVE_FILE`` as it works, for the container's health check.
It is active whenever ``S1_STORE`` is Postgres-backed, whatever ``S1_PROCESSING`` says (inline,
it only picks up runs that were left queued, or whose API request died). With ``S1_STORE=jsonl``
it would write the same files as the api, so it opens no store at all and only idles.

Log lines carry ids, codes, counts and durations. A failure is logged as its exception type and
a code, never its message or traceback, which can hold SQL parameters.
"""

from __future__ import annotations

import logging
import os
import secrets
import signal
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from backend.app.core.config import Settings, get_settings
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.observability import configure_logging
from backend.app.repositories.processing_run_repository import ProcessingRun, ProcessingRunRepository
from backend.app.services.document_processing_service import (
    WORKER_ERROR_MESSAGE,
    DocumentProcessingService,
    Outcome,
)
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.workers import reader_health

EXIT_OVERRAN = 75  # EX_TEMPFAIL: a read ran past max_run_seconds
REQUEUE_EVERY_SECONDS = 30
IDLE_TOUCH_SECONDS = 30
ERROR_BACKOFF_SECONDS = (2, 5, 15, 30, 60)

logger = logging.getLogger("sustentra.reader")


def reader_worker_id() -> str:
    return f"reader:{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(3)}"


def reader_active(settings: Settings) -> tuple[bool, str]:
    """Whether the reader may read: not while the S1 records are the api's files on disk."""

    if settings.s1_store == "jsonl":
        return False, "S1_STORE=jsonl: the reader would write the same files as the api"
    return True, ""


@dataclass(frozen=True)
class ReaderSettings:
    poll_seconds: float
    lease_seconds: int  # whole seconds: claim_s1_processing_run takes an integer
    heartbeat_seconds: float
    max_run_seconds: float
    shutdown_grace_seconds: float
    # Only for the reader_started line.
    s1_store: str = ""
    s1_processing: str = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> ReaderSettings:
        return cls(
            poll_seconds=settings.s1_reader_poll_seconds,
            lease_seconds=settings.s1_reader_lease_seconds,
            heartbeat_seconds=settings.s1_reader_heartbeat_seconds,
            max_run_seconds=settings.s1_reader_max_run_seconds,
            shutdown_grace_seconds=settings.s1_reader_shutdown_grace_seconds,
            s1_store=settings.s1_store,
            s1_processing=settings.s1_processing,
        )


def _failure(exc: BaseException, code: str) -> dict[str, str]:
    """What a log line may say about a failure: its type and a code, never its message."""

    return {"error_type": type(exc).__name__, "error_code": code}


def _touch(path: Path) -> bool:
    try:
        path.touch()
    except OSError as exc:
        logger.warning("reader_alive_file_failed", extra=_failure(exc, "alive_file"))
        return False
    return True


def _age_ms(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - moment).total_seconds() * 1000))


class ProcessingReader:
    def __init__(
        self,
        runs: Any,
        uploads: Any,
        pipeline: Any,
        storage: Any,
        *,
        settings: ReaderSettings,
        worker_id: str | None = None,
        stop: threading.Event | None = None,
        alive_file: Path | None = None,
        exit: Callable[[int], NoReturn] = os._exit,
        wait: Callable[[float], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runs = runs
        self._uploads = uploads
        self._pipeline = pipeline
        self._storage = storage
        self.settings = settings
        self.worker_id = worker_id or reader_worker_id()
        self.stop = stop if stop is not None else threading.Event()
        self._alive_file = alive_file
        self._exit = exit
        self._wait = wait or self.stop.wait
        self._clock = clock

    def request_stop(self, *_: object) -> None:
        """Signal handler: finish the read in progress (within the grace period), then stop."""

        self.stop.set()

    def _touch_alive(self) -> None:
        _touch(self._alive_file or reader_health.ALIVE_FILE)  # the module's file is read at call time

    # --- runs whose reader stopped -------------------------------------------------------------

    def requeue_expired(self) -> int:
        """Put back the runs whose lease ran out (failing those out of attempts), and their documents."""

        expired = self._runs.requeue_expired()
        failed = 0
        for item in expired:
            status = "queued" if item.status == "queued" else "failed"
            if status == "failed":
                failed += 1
            try:
                with scoped(S1Scope.tenant(item.org_id)):
                    self._uploads.update_processing_status(item.document_id, status)
            except KeyError:
                pass  # the document is gone
            except Exception as exc:  # one document must not leave the others' status behind
                logger.warning("processing_run_status_failed",
                               extra={"run_id": item.run_id, **_failure(exc, "status_failed")})
        if expired:
            logger.info("processing_runs_requeued", extra={"count": len(expired), "failed": failed})
        return len(expired)

    # --- one run -----------------------------------------------------------------------------

    def run_once(self) -> ProcessingRun | None:
        """Claim the oldest due run and read it. ``None`` when nothing is due."""

        run = self._runs.claim(self.worker_id, self.settings.lease_seconds)
        if run is None:
            return None
        started = self._clock()
        logger.info("processing_run_claimed", extra={
            "run_id": run.run_id, "org_id": run.org_id, "document_id": run.document_id,
            "attempt": run.attempts, "wait_ms": _age_ms(run.created_at)})

        service = DocumentProcessingService(self._runs, self._uploads, self._pipeline, self._storage,
                                            worker_id=self.worker_id)
        result: dict[str, ProcessingRun] = {}
        thread = threading.Thread(target=self._read, args=(service, run, result), name="reader-read", daemon=True)
        thread.start()

        if not self._supervise(run, thread, started):
            return self._release(run)
        finished = result.get("finished") or self._current(run)
        logger.info("processing_run_finished", extra={
            "run_id": run.run_id, "status": finished.status, "error_code": finished.error_code,
            "attempt": finished.attempts, "duration_ms": int((self._clock() - started) * 1000)})
        return finished

    def _read(self, service: DocumentProcessingService, run: ProcessingRun, result: dict[str, ProcessingRun]) -> None:
        """The read thread: execute and record, in the run's own organization."""

        try:
            with scoped(S1Scope.tenant(run.org_id)):
                outcome = service.execute(run)
                result["finished"] = service.finish(run, outcome, retry=True)
        except Exception as exc:
            logger.error("processing_run_crashed", extra={"run_id": run.run_id, **_failure(exc, "worker_error")})
            try:
                with scoped(S1Scope.tenant(run.org_id)):
                    result["finished"] = service.finish(
                        run, Outcome("retry", error_code="worker_error", error=WORKER_ERROR_MESSAGE), retry=True)
            except Exception as again:  # the run is left for its lease to expire
                logger.error("processing_run_finish_failed",
                             extra={"run_id": run.run_id, **_failure(again, "finish_failed")})

    def _supervise(self, run: ProcessingRun, thread: threading.Thread, started: float) -> bool:
        """Watch the read until it ends. ``False``: the reader is stopping and the read is not done."""

        s = self.settings
        tick = min(1.0, s.heartbeat_seconds)
        next_heartbeat = started + s.heartbeat_seconds
        lost = False
        stopping_since: float | None = None
        while True:
            thread.join(timeout=tick)
            if not thread.is_alive():
                return True
            now = self._clock()
            self._touch_alive()
            if now - started > s.max_run_seconds:
                logger.error("processing_run_overran",
                             extra={"run_id": run.run_id, "elapsed_s": round(now - started, 1)})
                self._exit(EXIT_OVERRAN)
            if not lost and now >= next_heartbeat:
                next_heartbeat = now + s.heartbeat_seconds
                lost = not self._renew(run)
            if self.stop.is_set():
                if stopping_since is None:
                    stopping_since = now
                if now - stopping_since >= s.shutdown_grace_seconds:
                    return False

    def _renew(self, run: ProcessingRun) -> bool:
        """Renew the lease. ``False`` once it is lost; a failed attempt is retried at the next beat."""

        try:
            renewed = self._runs.heartbeat(run, self.worker_id, self.settings.lease_seconds)
        except Exception as exc:
            logger.warning("processing_run_heartbeat_failed",
                           extra={"run_id": run.run_id, **_failure(exc, "heartbeat_failed")})
            return True
        if renewed is None:
            logger.warning("processing_run_lost_lease", extra={"run_id": run.run_id})
            return False
        return True

    def _current(self, run: ProcessingRun) -> ProcessingRun:
        with scoped(S1Scope.tenant(run.org_id)):  # get() reads in the bound scope
            return self._runs.get(run.run_id) or run

    def _release(self, run: ProcessingRun) -> ProcessingRun:
        """The reader is stopping and the read is not done: the run goes back in the queue."""

        with scoped(S1Scope.tenant(run.org_id)):
            released = self._runs.release(run, self.worker_id)
            if released is None:  # the run is someone else's now
                return self._runs.get(run.run_id) or run
            try:
                self._uploads.update_processing_status(run.document_id, "queued")
            except KeyError:
                pass
        logger.info("processing_run_released", extra={
            "run_id": run.run_id, "document_id": run.document_id, "attempt": released.attempts})
        return released

    # --- the loop ------------------------------------------------------------------------------

    def run_forever(self) -> int:
        s = self.settings
        logger.info("reader_started", extra={
            "worker_id": self.worker_id, "s1_store": s.s1_store, "s1_processing": s.s1_processing,
            "poll_seconds": s.poll_seconds, "lease_seconds": s.lease_seconds,
            "heartbeat_seconds": s.heartbeat_seconds, "max_run_seconds": s.max_run_seconds})
        failures = 0
        last_requeue: float | None = None
        while not self.stop.is_set():
            try:
                self._touch_alive()
                now = self._clock()
                if last_requeue is None or now - last_requeue >= REQUEUE_EVERY_SECONDS:
                    last_requeue = now  # before the call: a failing requeue must not block the claims
                    self.requeue_expired()
                ran = self.run_once()
                failures = 0
                if ran is None:
                    self._wait(s.poll_seconds)
            except Exception as exc:
                failures += 1
                backoff = ERROR_BACKOFF_SECONDS[min(failures, len(ERROR_BACKOFF_SECONDS)) - 1]
                logger.error("reader_error", extra={"backoff_s": backoff, "failures": failures,
                                                    **_failure(exc, "reader_error")})
                self._wait(backoff)
        logger.info("reader_stopped")
        return 0


def build_reader(settings: Settings, stop: threading.Event) -> ProcessingReader:
    """The reader on the real stores. Only here are the services (and so the stores) built."""

    uploads = DocumentUploadService()
    return ProcessingReader(
        ProcessingRunRepository(), uploads, PipelineOrchestrationService(), uploads.storage_service,
        settings=ReaderSettings.from_settings(settings), stop=stop)


def idle(stop: threading.Event, reason: str, alive_file: Path | None = None) -> int:
    """Stay up, healthy and doing nothing until stopped (the reader may not read here)."""

    logger.info("reader_idle", extra={"reason": reason})
    while True:
        _touch(alive_file or reader_health.ALIVE_FILE)  # before the first look at stop, too
        if stop.wait(IDLE_TOUCH_SECONDS):
            return 0


def main(stop: threading.Event | None = None) -> int:
    configure_logging()
    settings = get_settings()
    stop = stop if stop is not None else threading.Event()

    def stop_on_signal(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, stop_on_signal)
    signal.signal(signal.SIGINT, stop_on_signal)

    active, reason = reader_active(settings)
    if not active:
        return idle(stop, reason)
    return build_reader(settings, stop).run_forever()


if __name__ == "__main__":
    code = main()
    logging.shutdown()
    os._exit(code)  # a read thread may still be running: don't wait for it

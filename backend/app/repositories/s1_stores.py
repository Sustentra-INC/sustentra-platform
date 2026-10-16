"""Which S1 document stores the app uses, from S1_STORE (``Settings.s1_store``):

    jsonl           JSONL files and the uploads folder on the server's disk
    postgres+jsonl  Postgres, with every write also made to the files, so switching back to
                    jsonl loses nothing (the cutover's safety net)
    postgres        Postgres only

Services take these as their default stores; tests still inject their own.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

from backend.app.core.config import get_settings
from backend.app.repositories.document_repository import JsonlDocumentRepository, PostgresDocumentRepository
from backend.app.repositories.evidence_repository import (
    JsonlApprovedEvidenceRepository,
    PostgresApprovedEvidenceRepository,
)
from backend.app.repositories.extraction_result_repository import (
    JsonlExtractionResultRepository,
    PostgresExtractionResultRepository,
)
from backend.app.repositories.pipeline_repository import JsonlPipelineRunRepository, PostgresPipelineRunRepository
from backend.app.repositories.review_repository import JsonlReviewDecisionRepository, PostgresReviewDecisionRepository
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.postgres_file_store import PostgresFileStore

logger = logging.getLogger("sustentra.s1_store")


class MirroredRepository:
    """Reads from Postgres; every save is also appended to the JSONL file. A failed file
    write is logged, not raised: Postgres already holds the record and is what is read."""

    def __init__(self, primary: Any, mirror: Any) -> None:
        self._primary = primary
        self._mirror = mirror

    def save(self, record: Any) -> dict:
        saved = self._primary.save(record)
        try:
            self._mirror.save(saved)
        except Exception:
            logger.exception("S1 mirror write to %s failed", getattr(self._mirror, "path", "the JSONL file"))
        return saved

    def update_processing_status(self, document_id: str, processing_status: str) -> dict:
        existing = self._primary.get_by_id(document_id)
        if existing is None:
            raise KeyError(f"Document not found: {document_id}")
        updated = copy.deepcopy(existing)
        updated["processing_status"] = processing_status
        return self.save(updated)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)


class MirroredFileStore:
    """Files in Postgres; each upload is also written to the uploads folder under the same
    storage URI. As with the records, a failed disk write is logged, not raised."""

    def __init__(self, primary: PostgresFileStore, mirror: LocalStorageService) -> None:
        self._primary = primary
        self._mirror = mirror

    def save_upload(self, **kwargs: Any) -> dict:
        result = self._primary.save_upload(**kwargs)
        try:
            path = self._mirror.resolve_storage_uri(result["storage_uri"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(kwargs["content"]))
        except Exception:
            logger.exception("S1 mirror write of %s to disk failed", result["storage_uri"])
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)


def _pick(jsonl: Callable[[], Any], postgres: Callable[[], Any]) -> Any:
    store = get_settings().s1_store
    if store == "jsonl":
        return jsonl()
    if store == "postgres":
        return postgres()
    return MirroredRepository(postgres(), jsonl())


def documents() -> Any:
    return _pick(JsonlDocumentRepository, PostgresDocumentRepository)


def pipeline_runs() -> Any:
    return _pick(JsonlPipelineRunRepository, PostgresPipelineRunRepository)


def extraction_results() -> Any:
    return _pick(JsonlExtractionResultRepository, PostgresExtractionResultRepository)


def review_decisions() -> Any:
    return _pick(JsonlReviewDecisionRepository, PostgresReviewDecisionRepository)


def approved_evidence() -> Any:
    return _pick(JsonlApprovedEvidenceRepository, PostgresApprovedEvidenceRepository)


def files() -> Any:
    store = get_settings().s1_store
    if store == "jsonl":
        return LocalStorageService()
    if store == "postgres":
        return PostgresFileStore()
    return MirroredFileStore(PostgresFileStore(), LocalStorageService())

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backend.app.domain.document import Document
from backend.app.repositories.document_repository import JsonlDocumentRepository
from backend.app.services.local_storage_service import LocalStorageService

_ALLOWED_PROCESSING_STATUSES = {
    "not_started",
    "queued",
    "in_progress",
    "completed",
    "failed",
}


class DocumentUploadService:
    def __init__(
        self,
        storage_service: Any | None = None,
        document_repository: Any | None = None,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[str, str], str] | None = None,
    ) -> None:
        self._storage_service = storage_service or LocalStorageService()
        self._document_repository = document_repository or JsonlDocumentRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or self._default_id_factory

    @property
    def storage_service(self) -> Any:
        return self._storage_service

    def upload_document(
        self,
        *,
        engagement_id: str,
        file_name: str,
        content: bytes,
        mime_type: str,
        document_role: str,
        uploaded_by: str,
        evidence_id: str | None = None,
        document_type: str | None = None,
    ) -> dict:
        self._require_non_empty(engagement_id, "engagement_id")
        self._require_non_empty(file_name, "file_name")
        self._require_non_empty(mime_type, "mime_type")
        self._require_non_empty(document_role, "document_role")
        self._require_non_empty(uploaded_by, "uploaded_by")

        resolved_evidence_id = str(evidence_id or self._new_id("evidence", engagement_id))
        document_id = self._new_id("document", engagement_id)

        upload_result = self._storage_service.save_upload(
            file_name=file_name,
            content=bytes(content),
            engagement_id=engagement_id,
            evidence_id=resolved_evidence_id,
            document_id=document_id,
        )

        model = Document(
            document_id=document_id,
            engagement_id=engagement_id,
            evidence_id=resolved_evidence_id,
            file_name=upload_result["stored_file_name"],
            mime_type=mime_type,
            storage_uri=upload_result["storage_uri"],
            document_role=document_role,
            document_type=document_type,
            uploaded_by=uploaded_by,
            uploaded_at=self._clock(),
            processing_status="not_started",
        )
        return self._document_repository.save(model.model_dump())

    def create_document_metadata(
        self,
        *,
        engagement_id: str,
        file_name: str,
        mime_type: str,
        storage_uri: str,
        document_role: str,
        uploaded_by: str,
        evidence_id: str | None = None,
        document_type: str | None = None,
        processing_status: str = "queued",
    ) -> dict:
        self._require_non_empty(engagement_id, "engagement_id")
        self._require_non_empty(file_name, "file_name")
        self._require_non_empty(mime_type, "mime_type")
        self._require_non_empty(storage_uri, "storage_uri")
        self._require_non_empty(document_role, "document_role")
        if Path(storage_uri).is_absolute():
            raise ValueError("storage_uri must be a relative path.")
        self._require_non_empty(uploaded_by, "uploaded_by")
        self._validate_processing_status(processing_status)

        model = Document(
            document_id=self._new_id("document", engagement_id),
            engagement_id=engagement_id,
            evidence_id=str(evidence_id) if evidence_id else None,
            file_name=file_name,
            mime_type=mime_type,
            storage_uri=storage_uri,
            document_role=document_role,
            document_type=document_type,
            uploaded_by=uploaded_by,
            uploaded_at=self._clock(),
            processing_status=processing_status,
        )
        return self._document_repository.save(model.model_dump())

    def get_document(self, document_id: str) -> dict | None:
        self._require_non_empty(document_id, "document_id")
        return self._document_repository.get_by_id(document_id)

    def list_documents(self, engagement_id: str) -> list[dict]:
        self._require_non_empty(engagement_id, "engagement_id")
        return self._document_repository.list_by_engagement(engagement_id)

    def list_documents_by_evidence(self, evidence_id: str) -> list[dict]:
        self._require_non_empty(evidence_id, "evidence_id")
        return self._document_repository.list_by_evidence(evidence_id)

    def update_processing_status(self, document_id: str, processing_status: str) -> dict:
        self._require_non_empty(document_id, "document_id")
        self._validate_processing_status(processing_status)
        return self._document_repository.update_processing_status(document_id, processing_status)

    def _new_id(self, prefix: str, engagement_id: str) -> str:
        return str(self._id_factory(prefix, engagement_id))

    @staticmethod
    def _default_id_factory(prefix: str, engagement_id: str) -> str:
        return f"{prefix}::{engagement_id}::{uuid4().hex[:12]}"

    @staticmethod
    def _require_non_empty(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required.")

    @staticmethod
    def _validate_processing_status(value: str) -> None:
        if value not in _ALLOWED_PROCESSING_STATUSES:
            raise ValueError(
                f"Invalid processing_status '{value}'. Allowed: {sorted(_ALLOWED_PROCESSING_STATUSES)}."
            )

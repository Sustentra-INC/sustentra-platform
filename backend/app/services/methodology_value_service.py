"""Projection from approved evidence into methodology value snapshots."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid5, NAMESPACE_URL

from backend.app.domain.methodology_value import (
    MethodologyValue,
    MethodologyValueProjectionResult,
)
from backend.app.repositories.methodology_value_repository import (
    InMemoryMethodologyValueRepository,
)
from backend.app.services.approved_evidence_mapping_service import (
    ApprovedEvidenceMappingService,
)
from backend.app.services.methodology_registry_service import MethodologyRegistryService


class MethodologyValueService:
    """Creates engagement-specific methodology values from approved evidence."""

    def __init__(
        self,
        mapping_service: ApprovedEvidenceMappingService,
        methodology_registry: MethodologyRegistryService,
        repository: Any | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._mapping_service = mapping_service
        self._registry = methodology_registry
        self._repository = repository or InMemoryMethodologyValueRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def project_approved_evidence(
        self,
        approved_evidence: dict,
        *,
        persist: bool = True,
    ) -> dict:
        """Project one ApprovedEvidence aggregate into methodology values."""

        self._validate_approved_evidence(approved_evidence)
        created_at = self._clock()
        values: list[MethodologyValue] = []
        unmapped_fields: list[str] = []

        for field in approved_evidence["fields"]:
            field_name = str(field["field_name"])
            mappings = self._mapping_service.list_by_approved_field(
                str(approved_evidence["evidence_type"]),
                field_name,
            )
            if not mappings:
                unmapped_fields.append(field_name)
                continue
            for mapping in mappings:
                row = self._registry.get_row(mapping.methodology_field_id)
                values.append(
                    MethodologyValue(
                        methodology_value_id=self._methodology_value_id(
                            approved_evidence,
                            field,
                            mapping.methodology_field_id,
                            mapping.data_schema_field,
                        ),
                        engagement_id=str(approved_evidence["engagement_id"]),
                        evidence_id=str(approved_evidence["evidence_id"]),
                        document_id=str(approved_evidence["document_id"]),
                        methodology_field_id=mapping.methodology_field_id,
                        data_schema_field=mapping.data_schema_field,
                        grain=row.grain if row else None,
                        record_key=self._record_key(approved_evidence, field),
                        approved_value=field.get("approved_value"),
                        approved_unit=field.get("approved_unit"),
                        source_reference=copy.deepcopy(field["source_reference"]),
                        approved_evidence_id=str(
                            approved_evidence["approved_evidence_id"]
                        ),
                        review_decision_id=str(field["review_decision_id"]),
                        value_origin="approved_evidence",
                        created_at=created_at,
                    )
                )

        if persist:
            self._repository.replace_for_approved_evidence(
                str(approved_evidence["approved_evidence_id"]),
                values,
            )

        result = MethodologyValueProjectionResult(
            approved_evidence_id=str(approved_evidence["approved_evidence_id"]),
            engagement_id=str(approved_evidence["engagement_id"]),
            evidence_id=str(approved_evidence["evidence_id"]),
            document_id=str(approved_evidence["document_id"]),
            methodology_value_count=len(values),
            unmapped_fields=unmapped_fields,
            methodology_values=values,
        )
        return result.model_dump()

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return self._repository.list_by_engagement(engagement_id)

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._repository.list_by_evidence(evidence_id)

    def list_by_approved_evidence(self, approved_evidence_id: str) -> list[dict]:
        return self._repository.list_by_approved_evidence(approved_evidence_id)

    @staticmethod
    def _validate_approved_evidence(approved_evidence: Any) -> None:
        if not isinstance(approved_evidence, dict):
            raise ValueError("approved_evidence must be a dictionary.")
        required = (
            "approved_evidence_id",
            "engagement_id",
            "evidence_id",
            "document_id",
            "evidence_type",
            "fields",
        )
        missing = [field for field in required if field not in approved_evidence]
        if missing:
            raise ValueError(f"approved_evidence missing required field(s): {missing}.")
        if not isinstance(approved_evidence["fields"], list):
            raise ValueError("approved_evidence.fields must be a list.")
        for index, field in enumerate(approved_evidence["fields"], start=1):
            if not isinstance(field, dict):
                raise ValueError(f"approved_evidence field #{index} must be a dictionary.")
            field_required = (
                "field_name",
                "approved_value",
                "approved_unit",
                "source_reference",
                "review_decision_id",
            )
            field_missing = [
                item for item in field_required if item not in field
            ]
            if field_missing:
                raise ValueError(
                    f"approved_evidence field #{index} missing required field(s): "
                    f"{field_missing}."
                )
            if not isinstance(field["source_reference"], dict):
                raise ValueError(
                    f"approved_evidence field #{index}.source_reference must be an object."
                )

    @staticmethod
    def _record_key(approved_evidence: dict, field: dict) -> str:
        source_reference = field.get("source_reference") or {}
        for key in ("record_key", "record_id", "row_id", "line_item_id"):
            value = source_reference.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return "::".join(
            [
                str(approved_evidence["evidence_id"]),
                str(approved_evidence["document_id"]),
                str(field["field_name"]),
            ]
        )

    @staticmethod
    def _methodology_value_id(
        approved_evidence: dict,
        field: dict,
        methodology_field_id: str,
        data_schema_field: str,
    ) -> str:
        raw_key = "::".join(
            [
                str(approved_evidence["approved_evidence_id"]),
                str(field["review_decision_id"]),
                methodology_field_id,
                data_schema_field,
            ]
        )
        return f"methodology-value::{uuid5(NAMESPACE_URL, raw_key).hex}"

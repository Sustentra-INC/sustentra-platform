"""Loader for S1 approved-evidence to methodology Field_ID mappings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MappingStatus = Literal["confirmed", "provisional", "needs_domain_review", "deprecated"]

ALLOWED_MAPPING_STATUSES: frozenset[str] = frozenset(
    {"confirmed", "provisional", "needs_domain_review", "deprecated"}
)

DEFAULT_MAPPING_SEED_PATH = (
    Path(__file__).resolve().parents[3]
    / "reference-data"
    / "methodology"
    / "approved_evidence_field_mapping_seed.json"
)


@dataclass(frozen=True)
class ApprovedEvidenceFieldMapping:
    """One definition-level mapping from an approved S1 field to methodology."""

    canonical_type_id: str
    approved_field_name: str
    methodology_field_id: str
    data_schema_field: str
    mapping_status: MappingStatus
    notes: str | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.canonical_type_id,
            self.approved_field_name,
            self.methodology_field_id,
            self.data_schema_field,
        )


class ApprovedEvidenceMappingLoaderError(RuntimeError):
    """Base error for approved evidence mapping loading failures."""


class ApprovedEvidenceMappingSourceNotFoundError(ApprovedEvidenceMappingLoaderError):
    """Raised when the configured mapping seed is missing."""


class ApprovedEvidenceMappingDataError(ApprovedEvidenceMappingLoaderError):
    """Raised when mapping seed data is structurally invalid."""


def load_default_approved_evidence_mappings() -> tuple[ApprovedEvidenceFieldMapping, ...]:
    """Load the checked-in provisional mapping seed."""

    return load_approved_evidence_mappings(DEFAULT_MAPPING_SEED_PATH)


def load_approved_evidence_mappings(
    path: Path,
) -> tuple[ApprovedEvidenceFieldMapping, ...]:
    """Load and structurally validate approved evidence mappings from JSON."""

    if not path.exists() or not path.is_file():
        raise ApprovedEvidenceMappingSourceNotFoundError(
            f"Approved evidence mapping seed not found at: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApprovedEvidenceMappingDataError(
            f"Approved evidence mapping seed is not valid JSON: {path}"
        ) from exc

    raw_mappings = _mapping_records(payload)
    mappings = tuple(
        _parse_mapping(raw_mapping, index=index)
        for index, raw_mapping in enumerate(raw_mappings, start=1)
    )
    _validate_no_duplicate_keys(mappings)
    return mappings


def _mapping_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ApprovedEvidenceMappingDataError(
            "Approved evidence mapping seed must be a JSON object."
        )
    records = payload.get("mappings")
    if not isinstance(records, list):
        raise ApprovedEvidenceMappingDataError(
            "Approved evidence mapping seed must contain a 'mappings' list."
        )
    if not records:
        raise ApprovedEvidenceMappingDataError(
            "Approved evidence mapping seed must contain at least one mapping."
        )
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ApprovedEvidenceMappingDataError(
                f"Mapping record #{index} must be a JSON object."
            )
    return records


def _parse_mapping(
    raw_mapping: dict[str, Any],
    *,
    index: int,
) -> ApprovedEvidenceFieldMapping:
    canonical_type_id = _required_text(raw_mapping, "canonical_type_id", index)
    approved_field_name = _required_text(raw_mapping, "approved_field_name", index)
    methodology_field_id = _required_text(raw_mapping, "methodology_field_id", index)
    data_schema_field = _required_text(raw_mapping, "data_schema_field", index)
    mapping_status = _required_text(raw_mapping, "mapping_status", index)
    if mapping_status not in ALLOWED_MAPPING_STATUSES:
        raise ApprovedEvidenceMappingDataError(
            f"Mapping record #{index} has invalid mapping_status "
            f"'{mapping_status}'. Expected one of {sorted(ALLOWED_MAPPING_STATUSES)}."
        )
    return ApprovedEvidenceFieldMapping(
        canonical_type_id=canonical_type_id,
        approved_field_name=approved_field_name,
        methodology_field_id=methodology_field_id,
        data_schema_field=data_schema_field,
        mapping_status=mapping_status,  # type: ignore[arg-type]
        notes=_optional_text(raw_mapping.get("notes")),
    )


def _required_text(
    raw_mapping: dict[str, Any],
    field_name: str,
    index: int,
) -> str:
    value = _optional_text(raw_mapping.get(field_name))
    if value is None:
        raise ApprovedEvidenceMappingDataError(
            f"Mapping record #{index} missing required field '{field_name}'."
        )
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_no_duplicate_keys(
    mappings: tuple[ApprovedEvidenceFieldMapping, ...],
) -> None:
    seen: set[tuple[str, str, str, str]] = set()
    for mapping in mappings:
        if mapping.key in seen:
            raise ApprovedEvidenceMappingDataError(
                "Duplicate approved evidence mapping key: "
                f"{mapping.key}."
            )
        seen.add(mapping.key)

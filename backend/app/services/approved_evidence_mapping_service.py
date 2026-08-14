"""Approved evidence to methodology mapping service for Subsystem 2 PR4."""

from __future__ import annotations

from collections import defaultdict

from backend.app.reference.approved_evidence_mapping_loader import (
    ALLOWED_MAPPING_STATUSES,
    ApprovedEvidenceFieldMapping,
    MappingStatus,
)
from backend.app.services.methodology_registry_service import MethodologyRegistryService


class ApprovedEvidenceMappingValidationError(RuntimeError):
    """Raised when structurally loaded mappings do not resolve to methodology."""


class ApprovedEvidenceMappingService:
    """Queryable mapping index from approved S1 fields to methodology fields."""

    def __init__(
        self,
        mappings: tuple[ApprovedEvidenceFieldMapping, ...],
        methodology_registry: MethodologyRegistryService,
    ) -> None:
        self._mappings = mappings
        self._registry = methodology_registry
        self._validate_methodology_references()
        self._by_canonical_type = self._index_by_canonical_type()
        self._by_approved_field = self._index_by_approved_field()
        self._by_methodology_field = self._index_by_methodology_field()
        self._by_status = self._index_by_status()

    def list_mappings(
        self,
        *,
        include_deprecated: bool = False,
    ) -> tuple[ApprovedEvidenceFieldMapping, ...]:
        """List mapping definitions, excluding deprecated mappings by default."""

        return tuple(
            mapping
            for mapping in self._mappings
            if include_deprecated or mapping.mapping_status != "deprecated"
        )

    def list_by_canonical_type(
        self,
        canonical_type_id: str,
        *,
        include_deprecated: bool = False,
    ) -> tuple[ApprovedEvidenceFieldMapping, ...]:
        """List mappings for a canonical approved-evidence type."""

        return _filter_deprecated(
            self._by_canonical_type.get(_normalize_key(canonical_type_id), ()),
            include_deprecated=include_deprecated,
        )

    def list_by_approved_field(
        self,
        canonical_type_id: str,
        approved_field_name: str,
        *,
        include_deprecated: bool = False,
    ) -> tuple[ApprovedEvidenceFieldMapping, ...]:
        """List mappings for an approved field.

        This intentionally returns a tuple because one approved field may map to
        multiple methodology targets.
        """

        key = (_normalize_key(canonical_type_id), _normalize_key(approved_field_name))
        return _filter_deprecated(
            self._by_approved_field.get(key, ()),
            include_deprecated=include_deprecated,
        )

    def get_mapping(
        self,
        canonical_type_id: str,
        approved_field_name: str,
        methodology_field_id: str,
        data_schema_field: str,
    ) -> ApprovedEvidenceFieldMapping | None:
        """Return a singular mapping by its full logical key."""

        for mapping in self.list_by_approved_field(
            canonical_type_id,
            approved_field_name,
            include_deprecated=True,
        ):
            if (
                mapping.methodology_field_id == methodology_field_id
                and mapping.data_schema_field == data_schema_field
            ):
                return mapping
        return None

    def list_by_methodology_field(
        self,
        field_id: str,
        *,
        include_deprecated: bool = False,
    ) -> tuple[ApprovedEvidenceFieldMapping, ...]:
        """List approved-evidence mappings that can populate a Methodology Field_ID."""

        return _filter_deprecated(
            self._by_methodology_field.get(field_id, ()),
            include_deprecated=include_deprecated,
        )

    def list_by_status(
        self,
        status: MappingStatus,
    ) -> tuple[ApprovedEvidenceFieldMapping, ...]:
        """List mappings with a given status, including deprecated when requested."""

        return tuple(self._by_status.get(status, ()))

    def list_unconfirmed(self) -> tuple[ApprovedEvidenceFieldMapping, ...]:
        """List mappings that still need ESG/domain confirmation."""

        return tuple(
            mapping
            for mapping in self._mappings
            if mapping.mapping_status in {"provisional", "needs_domain_review"}
        )

    def _validate_methodology_references(self) -> None:
        for mapping in self._mappings:
            row = self._registry.get_row(mapping.methodology_field_id)
            if row is None:
                raise ApprovedEvidenceMappingValidationError(
                    "Approved evidence mapping references unknown methodology "
                    f"Field_ID '{mapping.methodology_field_id}' for "
                    f"{mapping.canonical_type_id}/{mapping.approved_field_name}."
                )
            if mapping.data_schema_field not in row.data_schema_fields:
                raise ApprovedEvidenceMappingValidationError(
                    "Approved evidence mapping references data_schema_field "
                    f"'{mapping.data_schema_field}' that is not present on "
                    f"{mapping.methodology_field_id}. Available fields: "
                    f"{row.data_schema_fields}."
                )

    def _index_by_canonical_type(
        self,
    ) -> dict[str, tuple[ApprovedEvidenceFieldMapping, ...]]:
        indexed: defaultdict[str, list[ApprovedEvidenceFieldMapping]] = defaultdict(list)
        for mapping in self._mappings:
            indexed[_normalize_key(mapping.canonical_type_id)].append(mapping)
        return {key: tuple(value) for key, value in indexed.items()}

    def _index_by_approved_field(
        self,
    ) -> dict[tuple[str, str], tuple[ApprovedEvidenceFieldMapping, ...]]:
        indexed: defaultdict[
            tuple[str, str], list[ApprovedEvidenceFieldMapping]
        ] = defaultdict(list)
        for mapping in self._mappings:
            indexed[
                (
                    _normalize_key(mapping.canonical_type_id),
                    _normalize_key(mapping.approved_field_name),
                )
            ].append(mapping)
        return {key: tuple(value) for key, value in indexed.items()}

    def _index_by_methodology_field(
        self,
    ) -> dict[str, tuple[ApprovedEvidenceFieldMapping, ...]]:
        indexed: defaultdict[str, list[ApprovedEvidenceFieldMapping]] = defaultdict(list)
        for mapping in self._mappings:
            indexed[mapping.methodology_field_id].append(mapping)
        return {key: tuple(value) for key, value in indexed.items()}

    def _index_by_status(
        self,
    ) -> dict[MappingStatus, tuple[ApprovedEvidenceFieldMapping, ...]]:
        indexed: defaultdict[MappingStatus, list[ApprovedEvidenceFieldMapping]] = (
            defaultdict(list)
        )
        for mapping in self._mappings:
            if mapping.mapping_status not in ALLOWED_MAPPING_STATUSES:
                continue
            indexed[mapping.mapping_status].append(mapping)
        return {key: tuple(value) for key, value in indexed.items()}


def _filter_deprecated(
    mappings: tuple[ApprovedEvidenceFieldMapping, ...],
    *,
    include_deprecated: bool,
) -> tuple[ApprovedEvidenceFieldMapping, ...]:
    if include_deprecated:
        return mappings
    return tuple(mapping for mapping in mappings if mapping.mapping_status != "deprecated")


def _normalize_key(value: str) -> str:
    return value.strip().casefold()

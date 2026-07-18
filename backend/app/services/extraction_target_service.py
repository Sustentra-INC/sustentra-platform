"""Extraction target service (PR5).

Answers "given a classified document canonical_type_id, which fields should S1
try to extract?" by selecting extraction configs and returning target metadata
dictionaries.

This service performs **no** value extraction: it never inspects ``parser_output``
and never produces ``extraction_candidate`` records (that is PR6). Targets carry
only configuration/target metadata, never extracted values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from backend.app.reference.extraction_config_loader import (
    ExtractionConfig,
    load_default_extraction_configs,
)

# Deterministic ordering for required_status.
_REQUIRED_STATUS_ORDER = {"core": 0, "conditional": 1, "optional": 2, "derived": 3}

_EXCLUDED_BY_DEFAULT_POPULATION = {"deprecated", "archived"}

_TARGET_FIELDS = (
    "extraction_config_id",
    "field_id",
    "field_label",
    "canonical_type_id",
    "value_type",
    "required_status",
    "expected_units",
    "source_reference_required",
    "anchor_labels",
    "value_patterns",
    "unit_patterns",
    "table_hints",
    "sheet_hints",
    "validation_hints",
    "extraction_methods",
    "normalization",
    "population_status",
    "version",
)


class ExtractionTargetService:
    """Selects extraction targets for a classified canonical type."""

    def __init__(
        self,
        configs: Sequence[ExtractionConfig] | None = None,
        repo_root: Path | None = None,
    ) -> None:
        if configs is None:
            configs = load_default_extraction_configs(repo_root=repo_root)
        self._configs: tuple[ExtractionConfig, ...] = tuple(configs)

        self._by_canonical_type: dict[str, list[ExtractionConfig]] = {}
        for config in self._configs:
            self._by_canonical_type.setdefault(config.canonical_type_id, []).append(config)

    @property
    def configs(self) -> tuple[ExtractionConfig, ...]:
        return self._configs

    def get_targets_for_canonical_type(
        self,
        canonical_type_id: str,
        include_optional: bool = True,
        include_deprecated: bool = False,
    ) -> list[dict]:
        """Return ordered target dicts for a single canonical type."""

        matches = self._by_canonical_type.get(canonical_type_id, [])
        selected: list[ExtractionConfig] = []
        for config in matches:
            if not include_deprecated and config.population_status in _EXCLUDED_BY_DEFAULT_POPULATION:
                continue
            if not include_optional and config.required_status == "optional":
                continue
            selected.append(config)

        selected.sort(
            key=lambda config: (
                _REQUIRED_STATUS_ORDER.get(config.required_status, 99),
                config.field_id,
            )
        )
        return [self._to_target(config) for config in selected]

    def get_targets_for_classification_result(
        self,
        classification_result: dict,
        include_optional: bool = True,
        include_deprecated: bool = False,
    ) -> list[dict]:
        """Return target dicts for a document_classification_result-shaped dict.

        Design:
            * ``classified``           -> targets for ``primary_canonical_type_id``
            * ``multi_type_candidate`` -> aggregated targets across the primary
              type and every distinct ``candidate_matches`` canonical type
            * ``low_confidence`` / ``unclassified`` / ``failed`` / other
              -> empty list (no targets are attempted without a confident type)
        """

        status = classification_result.get("status")

        if status == "classified":
            canonical_type_id = classification_result.get("primary_canonical_type_id")
            if not canonical_type_id:
                return []
            return self.get_targets_for_canonical_type(
                canonical_type_id,
                include_optional=include_optional,
                include_deprecated=include_deprecated,
            )

        if status == "multi_type_candidate":
            canonical_type_ids = self._collect_candidate_canonical_type_ids(classification_result)
            targets: list[dict] = []
            seen_target_ids: set[str] = set()
            for canonical_type_id in canonical_type_ids:
                for target in self.get_targets_for_canonical_type(
                    canonical_type_id,
                    include_optional=include_optional,
                    include_deprecated=include_deprecated,
                ):
                    if target["target_id"] not in seen_target_ids:
                        seen_target_ids.add(target["target_id"])
                        targets.append(target)
            return targets

        # low_confidence, unclassified, failed, or unknown status.
        return []

    @staticmethod
    def _collect_candidate_canonical_type_ids(classification_result: dict) -> list[str]:
        ordered: list[str] = []
        primary = classification_result.get("primary_canonical_type_id")
        if primary:
            ordered.append(primary)
        for candidate in classification_result.get("candidate_matches", []) or []:
            if not isinstance(candidate, dict):
                continue
            canonical_type_id = candidate.get("canonical_type_id")
            if canonical_type_id and canonical_type_id not in ordered:
                ordered.append(canonical_type_id)
        return ordered

    @staticmethod
    def _to_target(config: ExtractionConfig) -> dict:
        target = {
            "target_id": f"target::{config.canonical_type_id}::{config.field_id}",
        }
        for field in _TARGET_FIELDS:
            target[field] = getattr(config, field)
        return target

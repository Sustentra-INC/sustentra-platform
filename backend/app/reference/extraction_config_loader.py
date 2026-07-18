"""Extraction config loader (PR5).

Loads and validates the handwritten extraction config seed
(`reference-data/extraction-config/extraction_config_seed.json`) into typed,
immutable ``ExtractionConfig`` records. This loader only reads configuration
metadata; it performs no value extraction and does not read ``parser_output``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALUE_TYPES = {
    "string",
    "number",
    "integer",
    "boolean",
    "date",
    "date_range",
    "currency",
    "quantity",
    "percentage",
    "object",
    "array",
}

REQUIRED_STATUSES = {"core", "conditional", "optional", "derived"}

EXTRACTION_METHODS = {
    "anchor_text",
    "regex",
    "table_lookup",
    "key_value_pair",
    "excel_cell",
    "llm_structured",
    "manual_entry",
}

POPULATION_STATUSES = {"populated", "provisional", "deprecated", "archived"}

CANONICAL_TYPE_ID_PATTERN = re.compile(r"^CT-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
LAST_REVIEWED_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REQUIRED_FIELDS = (
    "extraction_config_id",
    "field_id",
    "field_label",
    "canonical_type_id",
    "value_type",
    "required_status",
    "source_reference_required",
    "extraction_methods",
    "normalization",
    "population_status",
    "version",
)

TUPLE_FIELDS = (
    "expected_units",
    "anchor_labels",
    "value_patterns",
    "unit_patterns",
    "table_hints",
    "sheet_hints",
    "validation_hints",
    "extraction_methods",
)


class ExtractionConfigLoaderError(ValueError):
    """Base error for extraction config loading/validation failures."""


class ExtractionConfigNotFoundError(ExtractionConfigLoaderError):
    """Raised when the extraction config seed file cannot be located."""


@dataclass(frozen=True)
class ExtractionConfig:
    extraction_config_id: str
    field_id: str
    field_label: str
    description: str | None
    canonical_type_id: str
    value_type: str
    required_status: str
    expected_units: tuple[str, ...]
    source_reference_required: bool
    anchor_labels: tuple[str, ...]
    value_patterns: tuple[str, ...]
    unit_patterns: tuple[str, ...]
    table_hints: tuple[str, ...]
    sheet_hints: tuple[str, ...]
    validation_hints: tuple[str, ...]
    extraction_methods: tuple[str, ...]
    normalization: dict[str, Any]
    regulatory_field_id: str | None
    notes: str | None
    population_status: str
    version: str
    last_reviewed: str | None


def find_default_extraction_config_path(repo_root: Path | None = None) -> Path:
    """Return the path to the default extraction config seed under reference-data."""

    root = repo_root.resolve() if repo_root is not None else Path(__file__).resolve().parents[3]
    seed_path = root / "reference-data" / "extraction-config" / "extraction_config_seed.json"
    if not seed_path.exists() or not seed_path.is_file():
        raise ExtractionConfigNotFoundError(
            f"Extraction config seed not found at: {seed_path}"
        )
    return seed_path


def load_default_extraction_configs(repo_root: Path | None = None) -> tuple[ExtractionConfig, ...]:
    """Load extraction configs from the default reference-data seed location."""

    return load_extraction_configs(find_default_extraction_config_path(repo_root=repo_root))


def load_extraction_configs(config_path: Path) -> tuple[ExtractionConfig, ...]:
    """Load and validate an extraction config JSON array into typed records."""

    path = Path(config_path)
    if not path.exists() or not path.is_file():
        raise ExtractionConfigNotFoundError(f"Extraction config file not found at: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ExtractionConfigLoaderError(f"Extraction config is not valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise ExtractionConfigLoaderError(
            "Extraction config top-level value must be a JSON array."
        )

    configs: list[ExtractionConfig] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ExtractionConfigLoaderError(
                f"Extraction config row {index} must be a JSON object."
            )

        config = _parse_row(row, index)

        if config.extraction_config_id in seen_ids:
            raise ExtractionConfigLoaderError(
                f"Duplicate extraction_config_id: '{config.extraction_config_id}'."
            )
        seen_ids.add(config.extraction_config_id)

        pair = (config.canonical_type_id, config.field_id)
        if pair in seen_pairs:
            raise ExtractionConfigLoaderError(
                "Duplicate (canonical_type_id, field_id) pair: "
                f"('{config.canonical_type_id}', '{config.field_id}')."
            )
        seen_pairs.add(pair)

        configs.append(config)

    return tuple(configs)


def _parse_row(row: dict[str, Any], index: int) -> ExtractionConfig:
    missing = [field for field in REQUIRED_FIELDS if field not in row or row[field] is None]
    if missing:
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index} is missing required field(s): {missing}."
        )

    extraction_config_id = _required_text(row, "extraction_config_id", index)
    field_id = _required_text(row, "field_id", index)
    field_label = _required_text(row, "field_label", index)
    canonical_type_id = _required_text(row, "canonical_type_id", index)
    if not CANONICAL_TYPE_ID_PATTERN.match(canonical_type_id):
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: invalid canonical_type_id "
            f"'{canonical_type_id}' (expected pattern CT-XXX...)."
        )

    value_type = _required_text(row, "value_type", index)
    _validate_enum(value_type, VALUE_TYPES, "value_type", index)

    required_status = _required_text(row, "required_status", index)
    _validate_enum(required_status, REQUIRED_STATUSES, "required_status", index)

    population_status = _required_text(row, "population_status", index)
    _validate_enum(population_status, POPULATION_STATUSES, "population_status", index)

    version = _required_text(row, "version", index)

    source_reference_required = row["source_reference_required"]
    if not isinstance(source_reference_required, bool):
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: source_reference_required must be a boolean."
        )

    normalization = row["normalization"]
    if not isinstance(normalization, dict):
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: normalization must be an object."
        )

    tuples: dict[str, tuple[str, ...]] = {
        name: _to_tuple(row.get(name)) for name in TUPLE_FIELDS
    }

    if not tuples["extraction_methods"]:
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: extraction_methods must not be empty."
        )
    for method in tuples["extraction_methods"]:
        _validate_enum(method, EXTRACTION_METHODS, "extraction_methods", index)

    last_reviewed = _optional_text(row.get("last_reviewed"))
    if last_reviewed is not None and not LAST_REVIEWED_PATTERN.match(last_reviewed):
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: last_reviewed must be YYYY-MM-DD or null."
        )

    return ExtractionConfig(
        extraction_config_id=extraction_config_id,
        field_id=field_id,
        field_label=field_label,
        description=_optional_text(row.get("description")),
        canonical_type_id=canonical_type_id,
        value_type=value_type,
        required_status=required_status,
        expected_units=tuples["expected_units"],
        source_reference_required=source_reference_required,
        anchor_labels=tuples["anchor_labels"],
        value_patterns=tuples["value_patterns"],
        unit_patterns=tuples["unit_patterns"],
        table_hints=tuples["table_hints"],
        sheet_hints=tuples["sheet_hints"],
        validation_hints=tuples["validation_hints"],
        extraction_methods=tuples["extraction_methods"],
        normalization=normalization,
        regulatory_field_id=_optional_text(row.get("regulatory_field_id")),
        notes=_optional_text(row.get("notes")),
        population_status=population_status,
        version=version,
        last_reviewed=last_reviewed,
    )


def _required_text(row: dict[str, Any], key: str, index: int) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: '{key}' must be a non-empty string."
        )
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    trimmed = value.strip()
    return trimmed or None


def _validate_enum(value: str, allowed: set[str], field_name: str, index: int) -> None:
    if value not in allowed:
        raise ExtractionConfigLoaderError(
            f"Extraction config row {index}: invalid {field_name} '{value}'. "
            f"Allowed: {sorted(allowed)}."
        )


def _to_tuple(value: Any) -> tuple[str, ...]:
    """Normalize None / pipe-delimited string / list into a tuple of strings."""

    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("|")]
        return tuple(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return tuple(result)
    raise ExtractionConfigLoaderError(
        f"Expected string, list, or null for a list-like field, got {type(value).__name__}."
    )

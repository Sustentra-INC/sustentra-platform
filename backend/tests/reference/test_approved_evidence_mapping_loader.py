from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.reference.approved_evidence_mapping_loader import (
    ApprovedEvidenceMappingDataError,
    load_approved_evidence_mappings,
    load_default_approved_evidence_mappings,
)


def test_default_approved_evidence_mapping_seed_loads() -> None:
    mappings = load_default_approved_evidence_mappings()

    assert len(mappings) == 6
    assert {mapping.mapping_status for mapping in mappings} == {
        "provisional",
        "needs_domain_review",
    }
    assert mappings[0].canonical_type_id == "CT-S1-FUELQTY"
    assert mappings[0].key == (
        "CT-S1-FUELQTY",
        "fuel_type",
        "S1-STC-010",
        "fuel_type",
    )


def test_mapping_loader_rejects_missing_required_field(tmp_path: Path) -> None:
    path = _write_seed(
        tmp_path,
        [
            {
                "canonical_type_id": "CT-S1-FUELQTY",
                "approved_field_name": "activity_quantity",
                "methodology_field_id": "S1-STC-010",
                "mapping_status": "provisional",
            }
        ],
    )

    with pytest.raises(ApprovedEvidenceMappingDataError, match="data_schema_field"):
        load_approved_evidence_mappings(path)


def test_mapping_loader_rejects_invalid_status(tmp_path: Path) -> None:
    path = _write_seed(
        tmp_path,
        [
            _mapping(mapping_status="ready"),
        ],
    )

    with pytest.raises(ApprovedEvidenceMappingDataError, match="invalid mapping_status"):
        load_approved_evidence_mappings(path)


def test_mapping_loader_rejects_exact_duplicate_key(tmp_path: Path) -> None:
    path = _write_seed(
        tmp_path,
        [
            _mapping(),
            _mapping(),
        ],
    )

    with pytest.raises(ApprovedEvidenceMappingDataError, match="Duplicate"):
        load_approved_evidence_mappings(path)


def test_mapping_loader_allows_same_source_field_to_multiple_targets(
    tmp_path: Path,
) -> None:
    path = _write_seed(
        tmp_path,
        [
            _mapping(data_schema_field="quantity_combusted"),
            _mapping(data_schema_field="quantity_unit"),
        ],
    )

    mappings = load_approved_evidence_mappings(path)

    assert len(mappings) == 2
    assert {
        (mapping.approved_field_name, mapping.data_schema_field)
        for mapping in mappings
    } == {
        ("activity_quantity", "quantity_combusted"),
        ("activity_quantity", "quantity_unit"),
    }


def _write_seed(
    tmp_path: Path,
    mappings: list[dict[str, str]],
) -> Path:
    path = tmp_path / "mapping_seed.json"
    path.write_text(json.dumps({"mappings": mappings}), encoding="utf-8")
    return path


def _mapping(
    *,
    canonical_type_id: str = "CT-S1-FUELQTY",
    approved_field_name: str = "activity_quantity",
    methodology_field_id: str = "S1-STC-010",
    data_schema_field: str = "quantity_combusted",
    mapping_status: str = "provisional",
) -> dict[str, str]:
    return {
        "canonical_type_id": canonical_type_id,
        "approved_field_name": approved_field_name,
        "methodology_field_id": methodology_field_id,
        "data_schema_field": data_schema_field,
        "mapping_status": mapping_status,
        "notes": "Test mapping",
    }

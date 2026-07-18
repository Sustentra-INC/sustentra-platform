import json
from pathlib import Path

import pytest

from backend.app.reference.extraction_config_loader import (
    ExtractionConfigLoaderError,
    ExtractionConfigNotFoundError,
    find_default_extraction_config_path,
    load_default_extraction_configs,
    load_extraction_configs,
)


def _valid_config(**overrides) -> dict:
    base = {
        "extraction_config_id": "EC-TEST-1",
        "field_id": "activity_quantity",
        "field_label": "Activity quantity",
        "description": "desc",
        "canonical_type_id": "CT-S1-FUELQTY",
        "value_type": "quantity",
        "required_status": "core",
        "expected_units": ["MMBtu", "therm"],
        "source_reference_required": True,
        "anchor_labels": ["Total Usage", "Usage"],
        "value_patterns": ["\\d+"],
        "unit_patterns": ["MMBtu"],
        "table_hints": ["usage table"],
        "sheet_hints": [],
        "validation_hints": ["positive"],
        "extraction_methods": ["anchor_text", "regex"],
        "normalization": {"target_unit": "MMBtu"},
        "regulatory_field_id": None,
        "notes": None,
        "population_status": "provisional",
        "version": "v0.1",
        "last_reviewed": None,
    }
    base.update(overrides)
    return base


def _write(tmp_path: Path, data) -> Path:
    path = tmp_path / "configs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_loads_valid_config(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config()])
    configs = load_extraction_configs(path)
    assert len(configs) == 1
    assert configs[0].extraction_config_id == "EC-TEST-1"


def test_top_level_non_array_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, {"not": "an array"})
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_missing_required_field_fails(tmp_path: Path) -> None:
    row = _valid_config()
    del row["value_type"]
    path = _write(tmp_path, [row])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_duplicate_extraction_config_id_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [_valid_config(), _valid_config(field_id="fuel_type")],
    )
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_duplicate_canonical_type_and_field_pair_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [_valid_config(), _valid_config(extraction_config_id="EC-TEST-2")],
    )
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_pipe_delimited_string_normalizes_to_tuple(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(anchor_labels="Total Usage|Gas Used|Usage")])
    configs = load_extraction_configs(path)
    assert configs[0].anchor_labels == ("Total Usage", "Gas Used", "Usage")


def test_list_field_normalizes_to_tuple(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(expected_units=["MMBtu", "therm", "ccf"])])
    configs = load_extraction_configs(path)
    assert configs[0].expected_units == ("MMBtu", "therm", "ccf")


def test_invalid_value_type_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(value_type="not_a_type")])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_invalid_required_status_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(required_status="mandatory")])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_invalid_extraction_method_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(extraction_methods=["anchor_text", "magic"])])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_empty_extraction_methods_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(extraction_methods=[])])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_invalid_population_status_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(population_status="draft")])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_invalid_canonical_type_id_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(canonical_type_id="fuelqty")])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_source_reference_required_must_be_bool(tmp_path: Path) -> None:
    path = _write(tmp_path, [_valid_config(source_reference_required="yes")])
    with pytest.raises(ExtractionConfigLoaderError):
        load_extraction_configs(path)


def test_missing_file_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(ExtractionConfigNotFoundError):
        load_extraction_configs(tmp_path / "nope.json")


def test_real_seed_file_loads_with_at_least_six_configs() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    seed_path = find_default_extraction_config_path(repo_root=repo_root)
    assert seed_path.exists()

    configs = load_default_extraction_configs(repo_root=repo_root)
    assert len(configs) >= 6
    for config in configs:
        assert config.population_status == "provisional"
        assert config.version == "v0.1"
        assert config.extraction_methods

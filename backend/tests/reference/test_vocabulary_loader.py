from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from backend.app.reference.vocabulary_loader import (  # noqa: E402
    VocabularyColumnError,
    VocabularyDataError,
    find_default_vocabulary_workbook,
    load_default_vocabulary_library,
    load_vocabulary_library,
)


def _canonical_headers() -> list[str]:
    return [
        "canonical_type_id",
        "canonical_name",
        "definition",
        "data_category",
        "ghg_scope",
        "content_inventory_coarse",
        "common_aliases",
        "source_basis",
        "population_status",
        "source_version",
        "last_reviewed",
    ]


def _variant_headers() -> list[str]:
    return [
        "variant_id",
        "canonical_type_id",
        "variant_archetype",
        "issuer_origin",
        "jurisdiction_region",
        "filename_patterns",
        "layout_features",
        "header_terms",
        "key_phrases",
        "multi_type",
        "confidence_threshold_default",
        "calibration_status",
        "source_exemplar",
        "population_status",
    ]


def _write_workbook(
    path: Path,
    canonical_rows: list[list[object]],
    variant_rows: list[list[object]],
    canonical_headers: list[str] | None = None,
    variant_headers: list[str] | None = None,
) -> Path:
    workbook = openpyxl.Workbook()

    canonical_sheet = workbook.active
    canonical_sheet.title = "Canonical_Types"
    canonical_sheet.append(canonical_headers or _canonical_headers())
    for row in canonical_rows:
        canonical_sheet.append(row)

    variant_sheet = workbook.create_sheet("Variants")
    variant_sheet.append(variant_headers or _variant_headers())
    for row in variant_rows:
        variant_sheet.append(row)

    workbook.save(path)
    return path


def _sample_canonical_row(canonical_type_id: str = "CT-GAS-BILL") -> list[object]:
    return [
        canonical_type_id,
        "Natural gas utility bill",
        "Evidence of natural gas usage charges",
        "activity_data",
        "Scope 1",
        "stationary_combustion",
        "gas|utility|invoice",
        "Vocabulary_Library_v1.0",
        "provisional",
        "v1.0",
        "2026-07-01",
    ]


def _sample_variant_row(
    variant_id: str = "VR-GAS-UTILITY",
    canonical_type_id: str = "CT-GAS-BILL",
    multi_type: object = "FALSE",
    threshold: object = 0.8,
) -> list[object]:
    return [
        variant_id,
        canonical_type_id,
        "Retail utility invoice",
        "utility",
        "US",
        "gas|bill",
        "usage table|account summary",
        "Natural Gas|Billing Period",
        "MMBtu|service address",
        multi_type,
        threshold,
        "provisional",
        "sample.pdf",
        "provisional",
    ]


def test_loads_valid_vocabulary_workbook(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row()],
        variant_rows=[_sample_variant_row()],
    )

    library = load_vocabulary_library(workbook_path)

    assert len(library.canonical_types) == 1
    assert len(library.variants) == 1
    assert library.canonical_types[0].canonical_type_id == "CT-GAS-BILL"
    assert library.variants[0].variant_id == "VR-GAS-UTILITY"


def test_missing_required_canonical_column_raises(tmp_path: Path) -> None:
    bad_headers = [header for header in _canonical_headers() if header != "definition"]
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row()[:-1]],
        variant_rows=[_sample_variant_row()],
        canonical_headers=bad_headers,
    )

    with pytest.raises(VocabularyColumnError):
        load_vocabulary_library(workbook_path)


def test_missing_required_variant_column_raises(tmp_path: Path) -> None:
    bad_headers = [header for header in _variant_headers() if header != "key_phrases"]
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row()],
        variant_rows=[_sample_variant_row()[:-1]],
        variant_headers=bad_headers,
    )

    with pytest.raises(VocabularyColumnError):
        load_vocabulary_library(workbook_path)


def test_orphan_variant_canonical_type_fails(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row("CT-ELECTRIC")],
        variant_rows=[_sample_variant_row(canonical_type_id="CT-NOT-FOUND")],
    )

    with pytest.raises(VocabularyDataError):
        load_vocabulary_library(workbook_path)


def test_multi_type_boolean_parsing(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row(), _sample_canonical_row("CT-ELEC")],
        variant_rows=[
            _sample_variant_row("VR-A", "CT-GAS-BILL", multi_type="TRUE", threshold=0.8),
            _sample_variant_row("VR-B", "CT-ELEC", multi_type=False, threshold=0.8),
        ],
    )

    library = load_vocabulary_library(workbook_path)

    assert library.variant_by_id["VR-A"].multi_type is True
    assert library.variant_by_id["VR-B"].multi_type is False


def test_confidence_threshold_parsing_numeric_and_provisional(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row(), _sample_canonical_row("CT-ELEC")],
        variant_rows=[
            _sample_variant_row("VR-NUM", "CT-GAS-BILL", threshold=0.75),
            _sample_variant_row("VR-TEXT", "CT-ELEC", threshold="0.80 (provisional)"),
        ],
    )

    library = load_vocabulary_library(workbook_path)

    assert library.variant_by_id["VR-NUM"].confidence_threshold_default == pytest.approx(0.75)
    assert library.variant_by_id["VR-TEXT"].confidence_threshold_default == pytest.approx(0.80)
    assert library.variant_by_id["VR-TEXT"].confidence_threshold_raw == "0.80 (provisional)"


def test_pipe_delimited_fields_normalize_to_tuples(tmp_path: Path) -> None:
    canonical = _sample_canonical_row()
    canonical[6] = " gas | utility | invoice | "

    variant = _sample_variant_row()
    variant[5] = "bill | utility"
    variant[6] = "usage table| account summary "
    variant[7] = "Natural Gas|Billing Period"
    variant[8] = " MMBtu | service address |"

    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[canonical],
        variant_rows=[variant],
    )

    library = load_vocabulary_library(workbook_path)

    assert library.canonical_types[0].common_aliases == ("gas", "utility", "invoice")
    assert library.variants[0].filename_patterns == ("bill", "utility")
    assert library.variants[0].layout_features == ("usage table", "account summary")
    assert library.variants[0].header_terms == ("Natural Gas", "Billing Period")
    assert library.variants[0].key_phrases == ("MMBtu", "service address")


def test_loader_indexes_are_built(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "Vocabulary_Library_v1.0.xlsx",
        canonical_rows=[_sample_canonical_row(), _sample_canonical_row("CT-ELECTRIC")],
        variant_rows=[
            _sample_variant_row("VR-GAS", "CT-GAS-BILL"),
            _sample_variant_row("VR-ELEC", "CT-ELECTRIC"),
        ],
    )

    library = load_vocabulary_library(workbook_path)

    assert "CT-GAS-BILL" in library.canonical_by_id
    assert "VR-GAS" in library.variant_by_id
    assert library.variants_by_canonical_type_id["CT-GAS-BILL"][0].variant_id == "VR-GAS"


def test_load_default_vocabulary_library_if_reference_workbook_exists() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    try:
        workbook_path = find_default_vocabulary_workbook(repo_root=repo_root)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"No default vocabulary workbook available: {exc}")

    library = load_default_vocabulary_library(repo_root=repo_root)

    assert workbook_path.exists()
    assert len(library.canonical_types) > 0
    assert len(library.variants) > 0
    assert len(library.canonical_by_id) == len(library.canonical_types)
    assert len(library.variant_by_id) == len(library.variants)
    for variant in library.variants:
        assert 0 <= variant.confidence_threshold_default <= 1

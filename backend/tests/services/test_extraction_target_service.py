from pathlib import Path

from backend.app.reference.extraction_config_loader import ExtractionConfig
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService

CANDIDATE_FIELDS_NOT_ALLOWED = {"raw_value", "normalized_value", "confidence"}

REQUIRED_TARGET_FIELDS = [
    "target_id",
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
]


def _config(
    extraction_config_id: str,
    field_id: str,
    canonical_type_id: str,
    required_status: str = "core",
    population_status: str = "provisional",
) -> ExtractionConfig:
    return ExtractionConfig(
        extraction_config_id=extraction_config_id,
        field_id=field_id,
        field_label=field_id.replace("_", " ").title(),
        description=None,
        canonical_type_id=canonical_type_id,
        value_type="string",
        required_status=required_status,
        expected_units=(),
        source_reference_required=True,
        anchor_labels=(),
        value_patterns=(),
        unit_patterns=(),
        table_hints=(),
        sheet_hints=(),
        validation_hints=(),
        extraction_methods=("anchor_text",),
        normalization={},
        regulatory_field_id=None,
        notes=None,
        population_status=population_status,
        version="v0.1",
        last_reviewed=None,
    )


def _sample_configs() -> list[ExtractionConfig]:
    return [
        _config("EC-A-OPT", "zeta_optional", "CT-S1-FUELQTY", required_status="optional"),
        _config("EC-A-CORE2", "beta_core", "CT-S1-FUELQTY", required_status="core"),
        _config("EC-A-CORE1", "alpha_core", "CT-S1-FUELQTY", required_status="core"),
        _config("EC-A-COND", "gamma_conditional", "CT-S1-FUELQTY", required_status="conditional"),
        _config("EC-A-DEP", "legacy_field", "CT-S1-FUELQTY", population_status="deprecated"),
        _config("EC-B-CORE", "fuel_type", "CT-S1-MOBFUEL", required_status="core"),
    ]


def test_returns_targets_for_canonical_type() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    targets = service.get_targets_for_canonical_type("CT-S1-MOBFUEL")
    assert len(targets) == 1
    assert targets[0]["field_id"] == "fuel_type"
    assert targets[0]["target_id"] == "target::CT-S1-MOBFUEL::fuel_type"


def test_unknown_canonical_type_returns_empty() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    assert service.get_targets_for_canonical_type("CT-DOES-NOT-EXIST") == []


def test_deprecated_excluded_by_default() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    field_ids = {t["field_id"] for t in service.get_targets_for_canonical_type("CT-S1-FUELQTY")}
    assert "legacy_field" not in field_ids


def test_deprecated_included_when_requested() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    field_ids = {
        t["field_id"]
        for t in service.get_targets_for_canonical_type("CT-S1-FUELQTY", include_deprecated=True)
    }
    assert "legacy_field" in field_ids


def test_optional_excluded_when_requested() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    field_ids = {
        t["field_id"]
        for t in service.get_targets_for_canonical_type("CT-S1-FUELQTY", include_optional=False)
    }
    assert "zeta_optional" not in field_ids


def test_target_order_is_deterministic() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    ordered = [t["field_id"] for t in service.get_targets_for_canonical_type("CT-S1-FUELQTY")]
    # core (alpha, beta) -> conditional (gamma) -> optional (zeta), each field_id asc.
    assert ordered == ["alpha_core", "beta_core", "gamma_conditional", "zeta_optional"]


def test_classification_result_classified() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    result = {"status": "classified", "primary_canonical_type_id": "CT-S1-MOBFUEL"}
    targets = service.get_targets_for_classification_result(result)
    assert [t["field_id"] for t in targets] == ["fuel_type"]


def test_classification_result_multi_type_aggregates() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    result = {
        "status": "multi_type_candidate",
        "primary_canonical_type_id": "CT-S1-FUELQTY",
        "candidate_matches": [
            {"canonical_type_id": "CT-S1-FUELQTY"},
            {"canonical_type_id": "CT-S1-MOBFUEL"},
        ],
    }
    targets = service.get_targets_for_classification_result(result)
    canonical_types = {t["canonical_type_id"] for t in targets}
    assert canonical_types == {"CT-S1-FUELQTY", "CT-S1-MOBFUEL"}
    # No duplicate target_ids across aggregated types.
    target_ids = [t["target_id"] for t in targets]
    assert len(target_ids) == len(set(target_ids))


def test_classification_result_low_confidence_returns_empty() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    result = {"status": "low_confidence", "primary_canonical_type_id": "CT-S1-FUELQTY"}
    assert service.get_targets_for_classification_result(result) == []


def test_classification_result_unclassified_returns_empty() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    result = {"status": "unclassified", "primary_canonical_type_id": None}
    assert service.get_targets_for_classification_result(result) == []


def test_target_dict_includes_required_fields() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    target = service.get_targets_for_canonical_type("CT-S1-MOBFUEL")[0]
    for field in REQUIRED_TARGET_FIELDS:
        assert field in target


def test_no_extraction_candidate_fields_are_produced() -> None:
    service = ExtractionTargetService(configs=_sample_configs())
    for target in service.get_targets_for_canonical_type("CT-S1-FUELQTY"):
        assert CANDIDATE_FIELDS_NOT_ALLOWED.isdisjoint(target.keys())


def test_service_loads_real_seed_by_default() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    service = ExtractionTargetService(repo_root=repo_root)
    targets = service.get_targets_for_canonical_type("CT-S1-FUELQTY")
    assert targets, "expected seed targets for CT-S1-FUELQTY"
    assert all(t["canonical_type_id"] == "CT-S1-FUELQTY" for t in targets)


def test_extraction_service_plan_targets_delegates() -> None:
    target_service = ExtractionTargetService(configs=_sample_configs())
    service = ExtractionService(target_service=target_service)
    result = {"status": "classified", "primary_canonical_type_id": "CT-S1-MOBFUEL"}
    targets = service.plan_targets(result)
    assert [t["field_id"] for t in targets] == ["fuel_type"]

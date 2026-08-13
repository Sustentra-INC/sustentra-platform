"""Tests for the intake profile schema seed (Phase A).

Two halves:

* Positive tests - the committed seed passes every check and honours the
  invariants the mapping and CLAUDE.md require.
* Negative tests - deliberately corrupted copies of the seed are REJECTED. A
  validator that cannot fail proves nothing, so each guard is tested by breaking
  it on an in-memory copy. The committed files are never modified.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "intake/scripts/validate_profile_schema.py"


def _load_validator():
    """Import the validator by path (intake/ is config + scripts, not a package)."""
    spec = importlib.util.spec_from_file_location("validate_profile_schema", VALIDATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


@pytest.fixture(scope="module")
def seed() -> dict[str, Any]:
    return json.loads((REPO_ROOT / validator.SEED_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index() -> dict[str, Any]:
    return json.loads((REPO_ROOT / validator.INDEX_PATH).read_text(encoding="utf-8"))


@pytest.fixture
def report() -> Any:
    return validator.Report(quiet=True)


# --------------------------------------------------------------------------
# Positive: the committed seed is valid
# --------------------------------------------------------------------------


def test_seed_passes_full_validation() -> None:
    result = validator.validate(REPO_ROOT, quiet=True)
    assert result.errors == [], "\n".join(result.errors)
    assert result.checks_run >= 15


def test_every_numbered_mapping_row_is_covered_exactly_once(seed: dict[str, Any]) -> None:
    mapping_text = (REPO_ROOT / validator.MAPPING_PATH).read_text(encoding="utf-8")
    expected = set(validator.MAPPING_ROW_PATTERN.findall(mapping_text))
    actual = [
        datapoint["mapping_ref"]
        for datapoint in seed["datapoints"]
        if validator.NUMBERED_REF_PATTERN.match(datapoint["mapping_ref"])
    ]
    assert expected == set(actual)
    assert len(actual) == len(set(actual))
    # Sections 1-6 of mapping v0.2: 7 + 7 + 4 + 3 + 5 + 5 numbered rows.
    assert len(expected) == 31


def test_section_seven_and_eight_counts(seed: dict[str, Any]) -> None:
    kinds = [datapoint["kind"] for datapoint in seed["datapoints"]]
    assert kinds.count("method_route") == validator.EXPECTED_METHOD_ROUTE_COUNT
    assert kinds.count("provenance_layer") == validator.EXPECTED_PROVENANCE_COUNT
    assert len(seed["datapoints"]) == 38


def test_datapoint_ids_are_unique(seed: dict[str, Any]) -> None:
    ids = [datapoint["datapoint_id"] for datapoint in seed["datapoints"]]
    assert len(ids) == len(set(ids))


def test_every_methodology_reference_exists(seed: dict[str, Any], index: dict[str, Any]) -> None:
    fields = index["methodology_fields"]
    for datapoint in seed["datapoints"]:
        for entry in datapoint["populates"]:
            if entry["target_type"] != "methodology_field":
                continue
            assert entry["field_id"] in fields, entry["field_id"]
            real = set(fields[entry["field_id"]]["schema_fields"])
            assert set(entry["schema_fields"]) <= real, entry


def test_every_evidence_reference_exists(seed: dict[str, Any]) -> None:
    library = json.loads(
        (REPO_ROOT / validator.EVIDENCE_LIBRARY_PATH).read_text(encoding="utf-8")
    )
    known = {entry["evidence_type_id"] for entry in library["evidence_types"]}
    for datapoint in seed["datapoints"]:
        assert set(datapoint["evidence_triggered"]) <= known, datapoint["datapoint_id"]


def test_escalation_classes_are_controlled(seed: dict[str, Any]) -> None:
    for datapoint in seed["datapoints"]:
        assert datapoint["class"] in {"AUTO", "HUMAN", "SYSTEM"}


def test_provisional_entries_are_flagged_for_signoff(seed: dict[str, Any]) -> None:
    """CLAUDE.md rule 6: unapproved methodology defaults must never be silent."""
    flagged = set(seed["open_items"]["pending_expert_signoff"]["datapoint_ids"])
    provisional = {
        datapoint["datapoint_id"] for datapoint in seed["datapoints"] if datapoint["provisional"]
    }
    assert provisional == flagged
    for datapoint in seed["datapoints"]:
        if datapoint["provisional"]:
            assert datapoint.get("requires_signoff"), datapoint["datapoint_id"]
            default = datapoint.get("provisional_default")
            if default is not None:
                assert default["status"] != "approved", datapoint["datapoint_id"]


def test_todd_signoff_items_match_the_spec_open_items(seed: dict[str, Any]) -> None:
    """SPEC section 10 lists consolidation, base year, GWP, significance, method routes."""
    flagged = set(seed["open_items"]["pending_expert_signoff"]["datapoint_ids"])
    assert {"BND-2.1", "BND-2.4", "BND-2.6", "BND-2.7"} <= flagged
    method_routes = {
        datapoint["datapoint_id"]
        for datapoint in seed["datapoints"]
        if datapoint["kind"] == "method_route"
    }
    assert method_routes <= flagged


def test_completeness_record_is_not_an_exclusion(seed: dict[str, Any]) -> None:
    """Mapping v0.2 FAIL 5: 'screened, not present' must never write EXC-010."""
    rules = [
        datapoint
        for datapoint in seed["datapoints"]
        if datapoint["kind"] == "completeness_rule"
    ]
    assert rules, "the seed must encode the screened-not-present rule"
    for rule in rules:
        field_ids = {
            entry.get("field_id")
            for entry in rule["populates"]
            if entry["target_type"] == "methodology_field"
        }
        assert "EXC-010" not in field_ids
    # EXC-010 is still used, but only for genuine significance-based exclusions.
    exclusion_users = {
        datapoint["datapoint_id"]
        for datapoint in seed["datapoints"]
        for entry in datapoint["populates"]
        if entry.get("field_id") == "EXC-010"
    }
    assert exclusion_users == {"BND-2.7"}


def test_items_never_asked_carry_no_question_content(seed: dict[str, Any]) -> None:
    for datapoint in seed["datapoints"]:
        if datapoint["kind"] in {
            "method_route",
            "provenance_layer",
            "system_assignment",
            "not_asked_v1",
        }:
            assert datapoint["question_content_ref"] is None, datapoint["datapoint_id"]
        if datapoint["kind"] == "question":
            assert isinstance(datapoint["question_content_ref"], str)


def test_sf6_is_recorded_but_not_asked(seed: dict[str, Any]) -> None:
    """SPEC section 8 scope cut - recorded so the omission stays traceable."""
    sf6 = next(d for d in seed["datapoints"] if d["datapoint_id"] == "S1FUG-5.5")
    assert sf6["v1_status"] == "not_asked"
    assert sf6["populates"] == []
    assert sf6["evidence_triggered"] == []
    assert "S1FUG-5.5" in seed["open_items"]["not_in_scope_v1"]["datapoint_ids"]


def test_inferred_classes_are_flagged_for_confirmation(seed: dict[str, Any]) -> None:
    inferred = {
        datapoint["datapoint_id"]
        for datapoint in seed["datapoints"]
        if datapoint["class_source"] == "inferred_pending_confirmation"
    }
    assert inferred == set(seed["open_items"]["pending_class_confirmation"]["datapoint_ids"])


def test_seed_declares_no_new_emissions_datapoints(seed: dict[str, Any]) -> None:
    """The mapping's core principle: intake defines no new emissions data points."""
    allowed = {"methodology_field", "intake_field", "legacy_field"}
    for datapoint in seed["datapoints"]:
        for entry in datapoint["populates"]:
            assert entry["target_type"] in allowed, entry


# --------------------------------------------------------------------------
# Negative: the validator rejects corrupted seeds
# --------------------------------------------------------------------------


def test_invented_field_id_is_rejected(seed, index, report) -> None:
    broken = copy.deepcopy(seed)
    broken["datapoints"][0]["populates"] = [
        {
            "target_type": "methodology_field",
            "field_id": "XYZ-999",
            "schema_fields": ["made_up_field"],
        }
    ]
    validator.check_methodology_references(broken, index, report)
    assert any("XYZ-999" in error for error in report.errors)


def test_invented_sub_field_is_rejected(seed, index, report) -> None:
    broken = copy.deepcopy(seed)
    entry = next(
        e
        for datapoint in broken["datapoints"]
        for e in datapoint["populates"]
        if e["target_type"] == "methodology_field"
    )
    entry["schema_fields"] = ["definitely_not_a_real_sub_field"]
    validator.check_methodology_references(broken, index, report)
    assert any("definitely_not_a_real_sub_field" in error for error in report.errors)


def test_invented_evidence_type_is_rejected(seed, index, report) -> None:
    broken = copy.deepcopy(seed)
    broken["datapoints"][0]["evidence_triggered"] = ["J2-999"]
    validator.check_evidence_references(broken, index, REPO_ROOT, report)
    assert any("J2-999" in error for error in report.errors)


def test_duplicate_datapoint_id_is_rejected(seed, report) -> None:
    broken = copy.deepcopy(seed)
    broken["datapoints"].append(copy.deepcopy(broken["datapoints"][0]))
    validator.check_structure(broken, report)
    assert any("duplicate datapoint_id" in error for error in report.errors)


def test_undefined_applicability_condition_is_rejected(seed, report) -> None:
    broken = copy.deepcopy(seed)
    broken["datapoints"][0]["applicability"]["condition_ref"] = "no_such_condition"
    validator.check_structure(broken, report)
    assert any("no_such_condition" in error for error in report.errors)


def test_unflagged_provisional_default_is_rejected(seed, report) -> None:
    broken = copy.deepcopy(seed)
    broken["open_items"]["pending_expert_signoff"]["datapoint_ids"] = []
    validator.check_open_items(broken, report)
    assert any("pending_expert_signoff" in error for error in report.errors)


def test_completeness_rule_writing_exclusion_is_rejected(seed, report) -> None:
    broken = copy.deepcopy(seed)
    rule = next(d for d in broken["datapoints"] if d["kind"] == "completeness_rule")
    rule["populates"].append(
        {
            "target_type": "methodology_field",
            "field_id": "EXC-010",
            "schema_fields": ["exclusion_rationale"],
        }
    )
    validator.check_completeness_vs_exclusion(broken, report)
    assert any("EXC-010" in error for error in report.errors)


def test_dropped_mapping_row_is_rejected(seed, report) -> None:
    broken = copy.deepcopy(seed)
    broken["datapoints"] = [
        datapoint for datapoint in broken["datapoints"] if datapoint["mapping_ref"] != "1.1"
    ]
    validator.check_mapping_coverage(broken, REPO_ROOT, report)
    assert any("1.1" in error for error in report.errors)


def test_invented_method_route_is_rejected(seed, index, report) -> None:
    broken = copy.deepcopy(seed)
    route = next(d for d in broken["datapoints"] if d["kind"] == "method_route")
    route["method_route"]["default_route"] = "vibes_based"
    validator.check_method_routes(broken, index, report)
    assert any("vibes_based" in error for error in report.errors)


def test_unresolvable_legacy_path_is_rejected(seed, report) -> None:
    broken = copy.deepcopy(seed)
    entry = next(
        e
        for datapoint in broken["datapoints"]
        for e in datapoint["populates"]
        if e["target_type"] == "legacy_field"
    )
    entry["field_path"] = "company_and_facility_profile.not_a_real_property"
    validator.check_legacy_references(broken, REPO_ROOT, report)
    assert any("not_a_real_property" in error for error in report.errors)


# --------------------------------------------------------------------------
# The committed index must stay in step with the source workbooks
# --------------------------------------------------------------------------


def test_committed_index_is_not_stale() -> None:
    pytest.importorskip("openpyxl")
    extractor_spec = importlib.util.spec_from_file_location(
        "extract_methodology_field_index",
        REPO_ROOT / "intake/scripts/extract_methodology_field_index.py",
    )
    assert extractor_spec and extractor_spec.loader
    extractor = importlib.util.module_from_spec(extractor_spec)
    extractor_spec.loader.exec_module(extractor)

    regenerated = extractor.build_index(REPO_ROOT)
    committed = json.loads((REPO_ROOT / validator.INDEX_PATH).read_text(encoding="utf-8"))
    assert regenerated == committed, (
        "intake/config/methodology_field_index.json is stale; "
        "re-run intake/scripts/extract_methodology_field_index.py"
    )

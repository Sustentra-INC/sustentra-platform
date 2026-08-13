"""Traceability: the seed form invents nothing.

Every input on the form must trace back to a seed-form datapoint in the Phase A
profile schema, and every field it claims to populate must exist in the
methodology field index, the legacy schema, or be an explicit intake-only field.
This is CLAUDE.md rule 3 applied to Phase B.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intake.backend.config import (
    load_controlled_vocabularies,
    load_profile_schema,
    load_seed_form,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIELD_INDEX = json.loads(
    (REPO_ROOT / "intake/config/methodology_field_index.json").read_text(encoding="utf-8")
)


def _form_fields() -> list[dict]:
    return [field for step in load_seed_form()["steps"] for field in step["fields"]]


def _seed_datapoints() -> dict[str, dict]:
    return {
        datapoint["datapoint_id"]: datapoint
        for datapoint in load_profile_schema()["datapoints"]
        if datapoint["section"] == "seed_form"
    }


# -- coverage ---------------------------------------------------------------


def test_every_seed_datapoint_has_at_least_one_input() -> None:
    covered = {field["datapoint_id"] for field in _form_fields()}
    assert covered == set(_seed_datapoints())


def test_every_field_references_a_real_seed_datapoint() -> None:
    known = set(_seed_datapoints())
    for field in _form_fields():
        assert field["datapoint_id"] in known, field["field_id"]


def test_step_datapoint_lists_match_their_fields() -> None:
    for step in load_seed_form()["steps"]:
        declared = set(step["datapoint_ids"])
        used = {field["datapoint_id"] for field in step["fields"]}
        assert declared == used, step["step_id"]


def test_field_ids_are_unique_within_a_step() -> None:
    for step in load_seed_form()["steps"]:
        ids = [field["field_id"] for field in step["fields"]]
        assert len(ids) == len(set(ids)), step["step_id"]


# -- referential integrity --------------------------------------------------


def test_every_methodology_target_exists() -> None:
    fields = FIELD_INDEX["methodology_fields"]
    for field in _form_fields():
        for target in field["populates"]:
            if target["target_type"] != "methodology_field":
                continue
            field_id = target["field_id"]
            assert field_id in fields, f"{field['field_id']} -> unknown {field_id}"
            assert target["schema_field"] in fields[field_id]["schema_fields"], (
                f"{field['field_id']} -> {field_id}.{target['schema_field']} is not a real "
                f"data schema field"
            )


def test_every_legacy_target_resolves() -> None:
    for field in _form_fields():
        for target in field["populates"]:
            if target["target_type"] != "legacy_field":
                continue
            schema = json.loads(
                (REPO_ROOT / target["source_schema"]).read_text(encoding="utf-8")
            )
            node = schema
            for part in target["field_path"].split("."):
                node = node.get("properties", {})[part]
            assert node is not None


def test_every_form_target_is_declared_by_its_datapoint() -> None:
    """A form input may only populate what its datapoint already declares.

    Covers all three target types. This is the rule-3 critical path: the form
    cannot quietly feed a methodology field the mapping never assigned to that
    question, and it cannot invent intake state either.
    """
    datapoints = _seed_datapoints()
    for field in _form_fields():
        declared = datapoints[field["datapoint_id"]]["populates"]
        for target in field["populates"]:
            if target["target_type"] == "methodology_field":
                match = [
                    entry
                    for entry in declared
                    if entry.get("field_id") == target["field_id"]
                    and target["schema_field"] in entry.get("schema_fields", [])
                ]
            elif target["target_type"] == "intake_field":
                match = [
                    entry
                    for entry in declared
                    if entry.get("field_path") == target["field_path"]
                    and target["intake_field"] in entry.get("intake_fields", [])
                ]
            else:
                match = [
                    entry for entry in declared if entry.get("field_path") == target["field_path"]
                ]
            assert match, (
                f"{field['field_id']} populates {target} which "
                f"{field['datapoint_id']} does not declare"
            )


def test_seed_1_7_records_the_raw_ownership_fact() -> None:
    """Schema v0.1.1: the seed form has a declared home for owned/leased.

    The boundary determination itself stays unset until BND-2.3.
    """
    declared = _seed_datapoints()["SEED-1.7"]["populates"]
    intake_paths = {
        entry["field_path"] for entry in declared if entry["target_type"] == "intake_field"
    }
    assert intake_paths == {"profile.sites[].ownership", "profile.sites[].ownership_note"}

    methodology = [entry for entry in declared if entry["target_type"] == "methodology_field"]
    assert methodology[0]["field_id"] == "ORG-050"
    assert "operational_control_over_asset_flag" in methodology[0]["schema_fields"]


def test_option_vocabularies_exist() -> None:
    vocabularies = load_controlled_vocabularies()["vocabularies"]
    for field in _form_fields():
        ref = field.get("options_ref", "")
        if isinstance(ref, str) and ref.startswith("vocabulary:"):
            assert ref.split(":", 1)[1] in vocabularies, field["field_id"]


def test_committed_vocabularies_are_not_stale() -> None:
    pytest.importorskip("openpyxl")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "extract_controlled_vocabularies",
        REPO_ROOT / "intake/scripts/extract_controlled_vocabularies.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build_vocabularies(REPO_ROOT) == load_controlled_vocabularies()


# -- provisional and deferred handling --------------------------------------


def test_provisional_fields_declare_an_owner_and_a_reason() -> None:
    for field in _form_fields():
        if field.get("provisional"):
            assert field.get("requires_signoff"), field["field_id"]
            assert field.get("provisional_reason"), field["field_id"]


def test_the_two_known_gaps_are_the_only_provisional_inputs() -> None:
    """Founder-approved: these ship as free text pending Todd's sign-off."""
    provisional = {field["field_id"] for field in _form_fields() if field.get("provisional")}
    assert provisional == {"operational_status", "fiscal_year_basis"}


def test_provisional_inputs_are_free_text_not_invented_dropdowns() -> None:
    for field in _form_fields():
        if field.get("provisional"):
            assert field["input"] == "text"
            assert "options" not in field


def test_deferred_boundary_fields_reference_real_methodology_fields() -> None:
    fields = FIELD_INDEX["methodology_fields"]
    datapoint_ids = {
        datapoint["datapoint_id"] for datapoint in load_profile_schema()["datapoints"]
    }
    for step in load_seed_form()["steps"]:
        for deferred in step.get("deferred_fields", []):
            assert deferred["field_id"] in fields
            assert deferred["schema_field"] in fields[deferred["field_id"]]["schema_fields"]
            assert deferred["deferred_to_datapoint"] in datapoint_ids


def test_derived_inputs_name_the_field_they_derive_from() -> None:
    known = {field["field_id"] for field in _form_fields()}
    for field in _form_fields():
        if field["input"] == "derived":
            assert field["derived_from"] in known, field["field_id"]

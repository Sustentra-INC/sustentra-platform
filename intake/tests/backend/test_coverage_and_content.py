"""Coverage maths, and traceability of the question content back to Phase A."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intake.backend.config import load_controlled_vocabularies, load_profile_schema
from intake.backend.services.question_content import (
    load_question_content,
    load_question_content_document,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIELD_INDEX = json.loads(
    (REPO_ROOT / "intake/config/methodology_field_index.json").read_text(encoding="utf-8")
)


def _interview_datapoints() -> dict[str, dict]:
    return {
        datapoint["datapoint_id"]: datapoint
        for datapoint in load_profile_schema()["datapoints"]
        if datapoint["section"]
        not in ("seed_form", "method_routing", "provenance")
        and datapoint["kind"] == "question"
        and datapoint["v1_status"] == "active"
    }


def _fields() -> list[tuple[str, dict]]:
    return [
        (datapoint_id, field)
        for datapoint_id, content in load_question_content().items()
        for field in content["fields"]
    ]


# -- content covers exactly the interview -----------------------------------


def test_every_interview_question_has_content() -> None:
    """A question with no content could never be asked."""
    assert set(load_question_content()) == set(_interview_datapoints())


def test_there_are_twenty_one_interview_questions() -> None:
    assert len(load_question_content()) == 21


def test_content_is_marked_placeholder_copy() -> None:
    """SPEC section 10: final wording follows the Vocabulary Library review."""
    assert load_question_content_document()["copy_status"] == "placeholder"


def test_every_question_has_a_plain_language_explainer() -> None:
    """SPEC section 3: every question carries a canned 'What does this mean?'."""
    for datapoint_id, content in load_question_content().items():
        assert len(content["explainer"]) > 40, datapoint_id
        assert content["question"].endswith("?"), datapoint_id


# -- referential integrity --------------------------------------------------


def test_every_populated_field_exists_in_the_methodology_index() -> None:
    fields = FIELD_INDEX["methodology_fields"]
    for datapoint_id, field in _fields():
        target = field.get("populates")
        if not target:
            continue
        assert target["field_id"] in fields, f"{datapoint_id}.{field['field_id']}"
        assert target["schema_field"] in fields[target["field_id"]]["schema_fields"], (
            f"{datapoint_id}.{field['field_id']} -> "
            f"{target['field_id']}.{target['schema_field']}"
        )


def test_content_targets_agree_with_the_phase_a_schema() -> None:
    """A question may only populate what its data point declares."""
    datapoints = _interview_datapoints()
    for datapoint_id, field in _fields():
        target = field.get("populates")
        if not target:
            continue
        declared = [
            entry
            for entry in datapoints[datapoint_id]["populates"]
            if entry["target_type"] == "methodology_field"
            and entry["field_id"] == target["field_id"]
            and target["schema_field"] in entry["schema_fields"]
        ]
        assert declared, (
            f"{datapoint_id}.{field['field_id']} populates {target}, which "
            f"{datapoint_id} does not declare"
        )


def test_option_vocabularies_exist() -> None:
    vocabularies = load_controlled_vocabularies()["vocabularies"]
    for datapoint_id, field in _fields():
        ref = field.get("options_ref", "")
        if isinstance(ref, str) and ref.startswith("vocabulary:"):
            assert ref.split(":", 1)[1] in vocabularies, f"{datapoint_id}.{field['field_id']}"


def test_reveal_conditions_reference_a_field_on_the_same_question() -> None:
    for datapoint_id, content in load_question_content().items():
        known = {field["field_id"] for field in content["fields"]} | {"present"}
        for field in content["fields"]:
            reveal = field.get("reveal_when")
            if reveal:
                assert reveal["field"] in known, f"{datapoint_id}.{field['field_id']}"


# -- provisional handling ---------------------------------------------------


def test_provisional_fields_declare_an_owner_and_a_reason() -> None:
    for datapoint_id, field in _fields():
        if field.get("provisional"):
            assert field.get("requires_signoff"), f"{datapoint_id}.{field['field_id']}"
            assert field.get("provisional_reason"), f"{datapoint_id}.{field['field_id']}"


def test_fields_without_a_vocabulary_are_free_text_not_invented_dropdowns() -> None:
    """The approved approach: flag it, never make up the options."""
    for datapoint_id, field in _fields():
        if field.get("provisional") and field["input"] == "select":
            assert field.get("options_ref"), (
                f"{datapoint_id}.{field['field_id']} is a provisional dropdown with "
                "hardcoded options"
            )


def test_the_missing_vocabularies_are_the_ones_we_reported() -> None:
    provisional = {
        f"{datapoint_id}.{field['field_id']}"
        for datapoint_id, field in _fields()
        if field.get("provisional")
    }
    assert provisional == {
        "BND-2.1.consolidation_approach",
        "BND-2.4.base_year",
        "BND-2.7.exclusion_rationale",
        "S1MOB-4.1.vehicle_type",
        "S1FUG-5.1.gas_type",
        "S1FUG-5.2.gas_type",
        "S1FUG-5.3.gas_types",
        "S2-6.5.instrument_type",
    }


# -- coverage ---------------------------------------------------------------


@pytest.fixture
def interview(harness):
    seeded = harness.seeded_org(sites=2)
    seeded["sites"] = [site["site_id"] for site in harness.sites.list_by_org(seeded["org_id"])]
    return seeded


def test_coverage_starts_at_zero(harness, interview) -> None:
    coverage = harness.coverage_service.coverage(interview["org_id"])
    assert coverage["complete"] == 0
    assert coverage["total"] > 0
    assert coverage["label"] == f"0 of {coverage['total']} complete"


def test_coverage_counts_only_applicable_questions(harness, interview) -> None:
    """The blend question is not counted until a fuel source exists."""
    total = harness.coverage_service.coverage(interview["org_id"])["total"]
    ids = {
        state["datapoint_id"]
        for state in harness.interview_engine.applicable_states(interview["org_id"])
    }
    assert "S1STC-3.3" not in ids
    assert total == len(ids | set()) or total > 0


def test_answering_advances_the_meter(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    before = harness.coverage_service.coverage(org_id)["complete"]
    harness.interview_engine.submit_answer(
        org_id=org_id, datapoint_id="S1STC-3.2", scope_ref=site,
        answer={"present": False}, actor_id="usr_1",
    )
    assert harness.coverage_service.coverage(org_id)["complete"] == before + 1


def test_a_yes_can_increase_the_total(harness, interview) -> None:
    """Answering yes reveals a follow-up, so there is genuinely more to do."""
    org_id, site = interview["org_id"], interview["sites"][0]
    before = harness.coverage_service.coverage(org_id)["total"]
    harness.interview_engine.submit_answer(
        org_id=org_id, datapoint_id="S1STC-3.1", scope_ref=site,
        answer={"present": True, "equipment": ["Boiler"]}, actor_id="usr_1",
    )
    assert harness.coverage_service.coverage(org_id)["total"] > before


def test_the_meter_explains_that_the_total_moves(harness, interview) -> None:
    assert "can change" in harness.coverage_service.coverage(interview["org_id"])["note"]


def test_escalated_questions_are_not_counted_as_complete(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    before = harness.coverage_service.coverage(org_id)
    harness.interview_engine.not_sure(org_id, "S1FUG-5.4", site, actor_id="usr_1")
    after = harness.coverage_service.coverage(org_id)
    assert after["complete"] == before["complete"]
    assert after["escalated"] == 1


def test_a_team_resolution_counts_as_complete(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    result = harness.interview_engine.not_sure(org_id, "S1FUG-5.4", site, actor_id="usr_1")
    before = harness.coverage_service.coverage(org_id)["complete"]
    harness.escalation_service.resolve(
        result["escalation"]["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    assert harness.coverage_service.coverage(org_id)["complete"] == before + 1


def test_coverage_breaks_down_by_section(harness, interview) -> None:
    sections = harness.coverage_service.coverage(interview["org_id"])["sections"]
    labels = [section["label"] for section in sections]
    assert "Boundary" in labels
    assert sections == sorted(sections, key=lambda item: item["order"])

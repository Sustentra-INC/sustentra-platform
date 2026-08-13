"""Deterministic applicability evaluation.

Includes the cases the interview depends on getting right: a site-scoped
condition must not be satisfied by a different site's answer, and a malformed
rule must fail loudly rather than silently dropping a question.
"""

from __future__ import annotations

import pytest

from intake.backend.config import load_profile_schema
from intake.backend.services.applicability_service import (
    ApplicabilityError,
    ApplicabilityService,
)

FILM = {"industry_overlay_id": "film"}
GENERAL = {"industry_overlay_id": "general"}


def _answer(datapoint_id: str, scope_ref: str | None, **value) -> dict:
    return {"datapoint_id": datapoint_id, "scope_ref": scope_ref, "value": value}


@pytest.fixture
def service() -> ApplicabilityService:
    return ApplicabilityService()


# -- coverage of the schema -------------------------------------------------


def test_every_condition_used_by_the_schema_is_defined(service) -> None:
    """A question referencing an undefined condition could never be asked."""
    schema = load_profile_schema()
    used = {dp["applicability"]["condition_ref"] for dp in schema["datapoints"]}
    used |= {
        trigger["condition_ref"]
        for dp in schema["datapoints"]
        for trigger in dp["escalation_triggers"]
    }
    assert used <= set(service.conditions), sorted(used - set(service.conditions))


def test_phase_a_named_conditions_all_have_predicates_now(service) -> None:
    schema = load_profile_schema()
    for name in schema["applicability_conditions"]:
        assert name in service.conditions, name
        assert service.conditions[name]["predicate"]


# -- basic operators --------------------------------------------------------


def test_always_applies(service) -> None:
    assert service.is_applicable("always", profile={}, states=[]) is True


def test_film_only_question_is_skipped_for_general(service) -> None:
    assert service.is_applicable("industry_is_film", profile=FILM, states=[]) is True
    assert service.is_applicable("industry_is_film", profile=GENERAL, states=[]) is False


def test_multi_entity_defaults_to_false(service) -> None:
    """Single-entity SMEs are the common case; BND-2.2 stays hidden."""
    assert service.is_applicable("more_than_one_legal_entity", profile={}, states=[]) is False


def test_multi_entity_gap_is_declared_not_hidden(service) -> None:
    unresolved = service.unresolved_conditions()
    assert "more_than_one_legal_entity" in unresolved
    assert unresolved["more_than_one_legal_entity"]["default_when_absent"] is False


# -- answer-driven conditions ----------------------------------------------


def test_fleet_condition_follows_the_fleet_answer(service) -> None:
    assert service.is_applicable("mobile_fleet_present", profile={}, states=[]) is False
    yes = [_answer("S1MOB-4.1", None, present=True)]
    assert service.is_applicable("mobile_fleet_present", profile={}, states=yes) is True
    no = [_answer("S1MOB-4.1", None, present=False)]
    assert service.is_applicable("mobile_fleet_present", profile={}, states=no) is False


def test_biogenic_question_appears_when_any_fuel_source_exists(service) -> None:
    states = [_answer("S1STC-3.1", "ste_1", present=True)]
    assert (
        service.is_applicable(
            "stationary_or_mobile_fuel_present", profile={}, states=states, scope_ref="ste_1"
        )
        is True
    )


def test_site_scoped_condition_ignores_another_site(service) -> None:
    """Fuel at site 1 must not switch on the blend question at site 2."""
    states = [_answer("S1STC-3.1", "ste_1", present=True)]
    assert (
        service.is_applicable(
            "stationary_or_mobile_fuel_present", profile={}, states=states, scope_ref="ste_2"
        )
        is False
    )


def test_org_wide_answer_reaches_every_site(service) -> None:
    """A fleet is org-wide, so it switches on the blend question at any site."""
    states = [_answer("S1MOB-4.1", None, present=True)]
    assert (
        service.is_applicable(
            "stationary_or_mobile_fuel_present", profile={}, states=states, scope_ref="ste_9"
        )
        is True
    )


def test_self_answer_conditions(service) -> None:
    yes = {"value": {"present": True}}
    no = {"value": {"present": False}}
    assert service.is_applicable("answer_is_yes", profile={}, states=[], self_state=yes) is True
    assert service.is_applicable("answer_is_yes", profile={}, states=[], self_state=no) is False
    assert (
        service.is_applicable("screening_answer_negative", profile={}, states=[], self_state=no)
        is True
    )


def test_selling_energy_condition_is_site_scoped(service) -> None:
    states = [_answer("S2-6.4", "ste_1", sells_energy_or_attributes=True)]
    assert (
        service.is_applicable(
            "selling_energy_or_attributes", profile={}, states=states, scope_ref="ste_1"
        )
        is True
    )
    assert (
        service.is_applicable(
            "selling_energy_or_attributes", profile={}, states=states, scope_ref="ste_2"
        )
        is False
    )


def test_unanswered_questions_do_not_satisfy_conditions(service) -> None:
    unanswered = [{"datapoint_id": "S1MOB-4.1", "scope_ref": None, "value": None}]
    assert service.is_applicable("mobile_fleet_present", profile={}, states=unanswered) is False


# -- failure modes ----------------------------------------------------------


def test_unknown_condition_raises(service) -> None:
    with pytest.raises(ApplicabilityError):
        service.is_applicable("no_such_condition", profile={}, states=[])


def test_unknown_operator_raises_rather_than_returning_false() -> None:
    """A typo must not quietly hide a question the client should answer."""
    broken = ApplicabilityService(
        {"conditions": {"bad": {"predicate": {"whenever": {"field": "x"}}}}}
    )
    with pytest.raises(ApplicabilityError):
        broken.is_applicable("bad", profile={}, states=[])


def test_multi_operator_predicate_raises() -> None:
    broken = ApplicabilityService(
        {"conditions": {"bad": {"predicate": {"always": True, "any": []}}}}
    )
    with pytest.raises(ApplicabilityError):
        broken.is_applicable("bad", profile={}, states=[])


def test_predicate_without_a_comparison_raises() -> None:
    broken = ApplicabilityService(
        {"conditions": {"bad": {"predicate": {"profile": {"field": "x"}}}}}
    )
    with pytest.raises(ApplicabilityError):
        broken.is_applicable("bad", profile={}, states=[])


def test_nested_operators_compose() -> None:
    service = ApplicabilityService(
        {
            "conditions": {
                "combo": {
                    "predicate": {
                        "all": [
                            {"profile": {"field": "industry_overlay_id", "equals": "film"}},
                            {"not": {"profile": {"field": "multi_entity", "equals": True}}},
                        ]
                    }
                }
            }
        }
    )
    assert service.is_applicable("combo", profile=FILM, states=[]) is True
    assert (
        service.is_applicable("combo", profile={**FILM, "multi_entity": True}, states=[]) is False
    )

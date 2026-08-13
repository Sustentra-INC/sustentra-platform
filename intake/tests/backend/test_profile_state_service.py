"""Instantiation, seed back-fill and system assignments (Phase C1)."""

from __future__ import annotations

import pytest

from intake.backend.config import default_gwp_set

SEED_DATAPOINTS = {f"SEED-1.{n}" for n in range(1, 8)}
ORG_GRAIN_QUESTIONS = {"BND-2.1", "BND-2.2", "BND-2.4", "BND-2.5", "BND-2.7"}
SITE_GRAIN_QUESTIONS = {
    "BND-2.3",
    "S1STC-3.1",
    "S1STC-3.2",
    "S1STC-3.3",
    "S1FUG-5.1",
    "S1FUG-5.2",
    "S1FUG-5.3",
    "S1FUG-5.4",
    "S2-6.1",
    "S2-6.2",
    "S2-6.3",
    "S2-6.4",
    "S2-6.5",
}
METHOD_ROUTES = {"MRT-7.1", "MRT-7.2", "MRT-7.3", "MRT-7.4", "MRT-7.5"}


def _ids(states: list[dict]) -> set[str]:
    return {state["datapoint_id"] for state in states}


# -- instantiation ----------------------------------------------------------


def test_interview_questions_are_instantiated(harness) -> None:
    seeded = harness.seeded_org(sites=1)
    states = harness.states.list_by_org(seeded["org_id"])
    assert ORG_GRAIN_QUESTIONS <= _ids(states)
    assert SITE_GRAIN_QUESTIONS <= _ids(states)


def test_each_site_gets_its_own_copy_of_the_screening_tree(harness) -> None:
    """SPEC section 3: one copy of the tree per site."""
    seeded = harness.seeded_org(sites=3)
    org_id = seeded["org_id"]
    for datapoint_id in sorted(SITE_GRAIN_QUESTIONS):
        scopes = {
            state["scope_ref"]
            for state in harness.states.list_for_datapoint(org_id, datapoint_id)
        }
        assert len(scopes) == 3, datapoint_id
        assert None not in scopes


def test_org_grain_questions_are_asked_once(harness) -> None:
    seeded = harness.seeded_org(sites=3)
    for datapoint_id in sorted(ORG_GRAIN_QUESTIONS):
        states = harness.states.list_for_datapoint(seeded["org_id"], datapoint_id)
        assert len(states) == 1, datapoint_id
        assert states[0]["scope_ref"] is None


def test_interview_questions_start_unasked(harness) -> None:
    seeded = harness.seeded_org()
    unanswered = [
        state
        for state in harness.states.list_by_org(seeded["org_id"])
        if state["datapoint_id"] in SITE_GRAIN_QUESTIONS | ORG_GRAIN_QUESTIONS
    ]
    assert unanswered and all(state["status"] == "unasked" for state in unanswered)


def test_sf6_is_not_instantiated(harness) -> None:
    """S1FUG-5.5 is out of scope for v1 and must not appear as a question."""
    seeded = harness.seeded_org()
    assert "S1FUG-5.5" not in _ids(harness.states.list_by_org(seeded["org_id"]))


def test_the_completeness_rule_is_not_a_question(harness) -> None:
    seeded = harness.seeded_org()
    assert "S1STC-3.4" not in _ids(harness.states.list_by_org(seeded["org_id"]))


def test_vehicle_group_states_wait_for_the_fleet_answer(harness) -> None:
    seeded = harness.seeded_org()
    assert "S1MOB-4.3" not in _ids(harness.states.list_by_org(seeded["org_id"]))

    created = harness.profile_state_service.instantiate_vehicle_groups(
        seeded["org_id"], ["veh_grp_1", "veh_grp_2"]
    )
    assert len(created) == 2
    scopes = {
        state["scope_ref"]
        for state in harness.states.list_for_datapoint(seeded["org_id"], "S1MOB-4.3")
    }
    assert scopes == {"veh_grp_1", "veh_grp_2"}


# -- back-fill --------------------------------------------------------------


def test_seed_answers_are_backfilled(harness) -> None:
    """The Phase B debt: seed submissions become answered states."""
    seeded = harness.seeded_org()
    org_id = seeded["org_id"]
    for datapoint_id in sorted(SEED_DATAPOINTS):
        states = harness.states.list_for_datapoint(org_id, datapoint_id)
        assert states, datapoint_id
        assert all(state["status"] == "answered" for state in states), datapoint_id


def test_backfilled_company_answers_carry_the_real_values(harness) -> None:
    seeded = harness.seeded_org()
    value = harness.state(seeded["org_id"], "SEED-1.1")["value"]
    assert value["legal_name"] == "Northlight Studios Ltd"
    assert value["reporting_year"] == 2025


def test_backfilled_site_answers_are_per_site(harness) -> None:
    seeded = harness.seeded_org(sites=2)
    states = harness.states.list_for_datapoint(seeded["org_id"], "SEED-1.3")
    names = {state["value"]["site_name"] for state in states}
    assert names == {"Stage 1", "Stage 2"}


def test_backfill_is_attributed_to_the_person_who_submitted(harness) -> None:
    seeded = harness.seeded_org()
    provenance = harness.state(seeded["org_id"], "SEED-1.1")["provenance"]
    assert provenance["answered_by"] == "user"
    assert provenance["actor_id"] == seeded["owner"]["user_id"]


def test_provisional_seed_answers_stay_flagged(harness) -> None:
    seeded = harness.seeded_org()
    site_state = harness.states.list_for_datapoint(seeded["org_id"], "SEED-1.3")[0]
    assert "operational_status" in site_state["provisional_fields"]


def test_initialise_is_idempotent(harness) -> None:
    seeded = harness.seeded_org(sites=2)
    org_id = seeded["org_id"]
    first = len(harness.states.list_by_org(org_id))
    audit_before = len(harness.audit.list_by_org(org_id))

    again = harness.profile_state_service.initialise(org_id)

    assert len(harness.states.list_by_org(org_id)) == first
    assert again["instantiated"] == []
    assert again["backfilled"] == []
    assert len(harness.audit.list_by_org(org_id)) == audit_before


def test_a_new_site_gets_its_states_on_re_initialise(harness) -> None:
    from intake.tests.conftest import company_payload, site_payload

    seeded = harness.seeded_org(sites=1)
    org_id = seeded["org_id"]
    existing_id = harness.sites.list_by_org(org_id)[0]["site_id"]

    harness.seed_form_service.submit(
        org_id=org_id,
        submitted_by=seeded["owner"]["user_id"],
        payload={
            "company": company_payload(),
            "sites": [
                site_payload(site_id=existing_id, site_name="Stage 1"),
                site_payload(site_name="Second Lot"),
            ],
        },
    )
    summary = harness.profile_state_service.initialise(org_id)
    assert summary["sites"] == 2
    assert any("S2-6.1" in entry for entry in summary["instantiated"])


def test_resubmitting_without_site_ids_creates_new_sites(harness) -> None:
    """Documents a known Phase B gap rather than leaving it to be discovered.

    The seed form loads blank, so a client who revisits it and submits again
    duplicates their sites. The fix is to prefill the form from existing
    answers, which belongs with the interview work; this test pins the current
    behaviour so the change is deliberate when it happens.
    """
    from intake.tests.conftest import company_payload, site_payload

    seeded = harness.seeded_org(sites=1)
    org_id = seeded["org_id"]
    harness.seed_form_service.submit(
        org_id=org_id,
        submitted_by=seeded["owner"]["user_id"],
        payload={"company": company_payload(), "sites": [site_payload(site_name="Stage 1")]},
    )
    assert len(harness.sites.list_by_org(org_id)) == 2, "known gap: sites duplicate"


def test_nothing_is_backfilled_before_the_seed_form(harness) -> None:
    created = harness.create_org()
    summary = harness.profile_state_service.initialise(created["org"]["org_id"])
    assert summary["backfilled"] == []
    assert summary["sites"] == 0


def test_unknown_org_is_rejected(harness) -> None:
    with pytest.raises(ValueError):
        harness.profile_state_service.initialise("org_missing")


# -- system assignments -----------------------------------------------------


def test_method_routes_are_system_assigned(harness) -> None:
    seeded = harness.seeded_org()
    for datapoint_id in sorted(METHOD_ROUTES):
        state = harness.state(seeded["org_id"], datapoint_id)
        assert state["status"] == "answered"
        assert state["provenance"]["answered_by"] == "system"
        assert state["value"]["verifier_overridable"] is True


def test_gwp_set_comes_from_the_emission_factor_library(harness) -> None:
    """BND-2.6 is assigned from the library rather than invented."""
    seeded = harness.seeded_org()
    value = harness.state(seeded["org_id"], "BND-2.6")["value"]
    library = default_gwp_set()
    assert value["gwp_set_id"] == library["gwp_set_id"]
    assert value["gwp_ar_edition"] == library["assessment_report"]
    assert value["gwp_time_horizon"] == library["time_horizon_years"]
    assert "CO2" in value["gases_included"]


def test_system_assignments_are_flagged_provisional(harness) -> None:
    """CLAUDE.md rule 6: unapproved methodology defaults are never silent."""
    seeded = harness.seeded_org()
    for datapoint_id in sorted(METHOD_ROUTES | {"BND-2.6"}):
        assert harness.state(seeded["org_id"], datapoint_id)["provisional_fields"]


def test_system_assignments_are_never_asked_of_the_client(harness) -> None:
    seeded = harness.seeded_org()
    assigned = [
        state
        for state in harness.states.list_by_org(seeded["org_id"])
        if state["datapoint_id"] in METHOD_ROUTES | {"BND-2.6"}
    ]
    assert all(state["provenance"]["answered_by"] == "system" for state in assigned)

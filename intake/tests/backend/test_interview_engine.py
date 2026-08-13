"""The deterministic interview engine: ordering, answering, escalation."""

from __future__ import annotations

import pytest

from intake.backend.services.interview_engine import AnswerValidationError


@pytest.fixture
def interview(harness):
    seeded = harness.seeded_org(sites=2)
    seeded["sites"] = [site["site_id"] for site in harness.sites.list_by_org(seeded["org_id"])]
    seeded["harness"] = harness
    return seeded


def _answer(harness, org_id, datapoint_id, scope_ref, **answer):
    return harness.interview_engine.submit_answer(
        org_id=org_id,
        datapoint_id=datapoint_id,
        scope_ref=scope_ref,
        answer=answer,
        actor_id="usr_1",
    )


# -- selection and ordering -------------------------------------------------


def test_the_interview_starts_with_a_question(harness, interview) -> None:
    question = harness.interview_engine.next_question(interview["org_id"])
    assert question is not None
    assert question["question"]
    assert question["explainer"]
    assert question["not_sure_allowed"] is True


def test_company_level_questions_come_before_site_questions(harness, interview) -> None:
    states = harness.interview_engine.applicable_states(interview["org_id"])
    grains = [
        harness.interview_engine._datapoints[state["datapoint_id"]]["grain"] for state in states
    ]
    assert grains.index("org") < grains.index("site")


def test_each_site_is_worked_through_as_a_block(harness, interview) -> None:
    states = harness.interview_engine.applicable_states(interview["org_id"])
    site_scopes = [
        state["scope_ref"]
        for state in states
        if harness.interview_engine._datapoints[state["datapoint_id"]]["grain"] == "site"
    ]
    # All of one site's questions, then all of the next: no interleaving.
    assert site_scopes == sorted(site_scopes, key=site_scopes.index)
    first = site_scopes[0]
    assert site_scopes[: site_scopes.count(first)] == [first] * site_scopes.count(first)


def test_seed_answers_are_not_asked_again(harness, interview) -> None:
    states = harness.interview_engine.applicable_states(interview["org_id"])
    assert not any(state["datapoint_id"].startswith("SEED-") for state in states)


def test_system_assignments_are_never_asked(harness, interview) -> None:
    states = harness.interview_engine.applicable_states(interview["org_id"])
    ids = {state["datapoint_id"] for state in states}
    assert not ids & {"BND-2.6", "MRT-7.1", "MRT-7.5"}


def test_film_only_question_appears_for_a_film_client(harness, interview) -> None:
    ids = {
        state["datapoint_id"]
        for state in harness.interview_engine.applicable_states(interview["org_id"])
    }
    assert "S1MOB-4.2" in ids


def test_multi_entity_question_is_hidden_by_default(harness, interview) -> None:
    ids = {
        state["datapoint_id"]
        for state in harness.interview_engine.applicable_states(interview["org_id"])
    }
    assert "BND-2.2" not in ids


def test_the_question_carries_its_site_name(harness, interview) -> None:
    state = harness.states.find(interview["org_id"], "S1STC-3.1", interview["sites"][0])
    assert harness.interview_engine.render(state)["scope_label"] == "Stage 1"


def test_answering_everything_ends_the_interview(harness, interview) -> None:
    org_id = interview["org_id"]
    guard = 0
    while (question := harness.interview_engine.next_question(org_id)) is not None:
        guard += 1
        assert guard < 200, "the interview did not converge"
        answer = {"present": False} if question["answer_shape"] == "yes_no" else {}
        for field in question["fields"]:
            if not field.get("required") or field.get("reveal_when"):
                continue
            answer[field["field_id"]] = _sample(field)
        _answer(harness, org_id, question["datapoint_id"], question["scope_ref"], **answer)
    assert harness.coverage_service.coverage(org_id)["is_complete"] is True


def _sample(field: dict):
    return {
        "yes_no": False,
        "number": 1,
        "list": ["Item"],
        "date": "2025-06-01",
        "select": (field.get("options") or [{"value": "x"}])[0]["value"],
    }.get(field["input"], "text answer")


# -- answering --------------------------------------------------------------


def test_a_yes_answer_is_recorded_as_answered(harness, interview) -> None:
    result = _answer(
        harness, interview["org_id"], "S1STC-3.1", interview["sites"][0],
        present=True, equipment=["Gas boiler"],
    )
    assert result["status"] == "answered"
    assert result["state"]["value"]["equipment"] == ["Gas boiler"]


def test_a_no_answer_is_a_completeness_record(harness, interview) -> None:
    """Screening 'no' is 'we looked and it isn't here', not an exclusion."""
    result = _answer(harness, interview["org_id"], "S1STC-3.1", interview["sites"][0], present=False)
    assert result["status"] == "not_present"
    assert result["state"]["value"]["present"] is False
    assert "EXC-010" not in str(result["state"]["value"])


def test_required_follow_up_is_enforced_only_when_revealed(harness, interview) -> None:
    # 'no' needs nothing further...
    _answer(harness, interview["org_id"], "S1STC-3.1", interview["sites"][1], present=False)
    # ...but 'yes' needs the equipment list.
    with pytest.raises(AnswerValidationError) as exc:
        _answer(harness, interview["org_id"], "S1STC-3.1", interview["sites"][0], present=True)
    assert {"equipment"} == {error["field"] for error in exc.value.errors}


def test_a_missing_yes_no_answer_is_rejected(harness, interview) -> None:
    with pytest.raises(AnswerValidationError) as exc:
        _answer(harness, interview["org_id"], "S1STC-3.1", interview["sites"][0])
    assert exc.value.errors[0]["field"] == "present"


def test_an_invented_dropdown_value_is_rejected(harness, interview) -> None:
    with pytest.raises(AnswerValidationError) as exc:
        _answer(
            harness, interview["org_id"], "BND-2.3", interview["sites"][0],
            party_role="chief_vibes_officer", operational_control_over_asset_flag=True,
        )
    assert exc.value.errors[0]["field"] == "party_role"


def test_a_real_dropdown_value_is_accepted(harness, interview) -> None:
    result = _answer(
        harness, interview["org_id"], "BND-2.3", interview["sites"][0],
        party_role="lessee", operational_control_over_asset_flag=True,
    )
    assert result["state"]["value"]["party_role"] == "lessee"


def test_boundary_question_resolves_what_the_seed_form_deferred(harness, interview) -> None:
    """BND-2.3 is where ORG-050's control flag finally gets set."""
    result = _answer(
        harness, interview["org_id"], "BND-2.3", interview["sites"][0],
        party_role="lessee", operational_control_over_asset_flag=True,
    )
    assert result["state"]["value"]["operational_control_over_asset_flag"] is True


def test_a_bad_number_is_rejected(harness, interview) -> None:
    with pytest.raises(AnswerValidationError):
        _answer(
            harness, interview["org_id"], "S1FUG-5.1", interview["sites"][0],
            present=True, equipment_count="lots", has_service_records=True,
        )


def test_unknown_question_is_rejected(harness, interview) -> None:
    with pytest.raises(AnswerValidationError):
        _answer(harness, interview["org_id"], "NOPE-9.9", None, present=True)


def test_answers_do_not_leak_between_sites(harness, interview) -> None:
    org_id, (site_a, site_b) = interview["org_id"], interview["sites"]
    _answer(harness, org_id, "S1STC-3.1", site_a, present=True, equipment=["Boiler"])
    assert harness.states.find(org_id, "S1STC-3.1", site_b)["status"] == "unasked"


# -- applicability in motion ------------------------------------------------


def test_a_no_answer_hides_the_follow_up_question(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    _answer(harness, org_id, "S1STC-3.1", site, present=False)
    _answer(harness, org_id, "S1STC-3.2", site, present=False)
    _answer(harness, org_id, "S1MOB-4.1", None, present=False)

    ids = {
        (state["datapoint_id"], state["scope_ref"])
        for state in harness.interview_engine.applicable_states(org_id)
    }
    assert ("S1STC-3.3", site) not in ids


def test_a_yes_answer_reveals_the_follow_up_question(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    _answer(harness, org_id, "S1STC-3.1", site, present=True, equipment=["Gas boiler"])
    ids = {
        (state["datapoint_id"], state["scope_ref"])
        for state in harness.interview_engine.applicable_states(org_id)
    }
    assert ("S1STC-3.3", site) in ids


def test_a_fleet_answer_creates_vehicle_group_questions(harness, interview) -> None:
    org_id = interview["org_id"]
    result = _answer(
        harness, org_id, "S1MOB-4.1", None,
        present=True, fleet_groups=["Shuttle vans", "Forklifts"],
    )
    assert len(result["created_scopes"]) == 2
    scopes = {
        state["scope_ref"] for state in harness.states.list_for_datapoint(org_id, "S1MOB-4.3")
    }
    assert len(scopes) == 2


# -- escalation -------------------------------------------------------------


def test_not_sure_escalates_and_keeps_going(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    result = harness.interview_engine.not_sure(org_id, "S1FUG-5.4", site, actor_id="usr_1")

    assert result["explainer"]
    assert "within 24 hours" in result["message"]
    assert harness.states.find(org_id, "S1FUG-5.4", site)["status"] == "escalated"

    following = harness.interview_engine.next_question(org_id)
    assert following is not None
    assert (following["datapoint_id"], following["scope_ref"]) != ("S1FUG-5.4", site)


def test_escalated_questions_are_skipped_not_repeated(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    harness.interview_engine.not_sure(org_id, "S1FUG-5.4", site, actor_id="usr_1")
    for _ in range(5):
        question = harness.interview_engine.next_question(org_id)
        assert (question["datapoint_id"], question["scope_ref"]) != ("S1FUG-5.4", site)
        _answer(
            harness, org_id, question["datapoint_id"], question["scope_ref"],
            **_full_answer(question),
        )


def _full_answer(question: dict) -> dict:
    """A minimal valid answer: 'no' to screenings, samples for required fields."""
    answer = {"present": False} if question["answer_shape"] == "yes_no" else {}
    for field in question["fields"]:
        if field.get("required") and not field.get("reveal_when"):
            answer[field["field_id"]] = _sample(field)
    return answer


def test_a_yes_to_process_sources_escalates_automatically(harness, interview) -> None:
    """Mapping 5.4: the workbook flags process calculations as human-only."""
    org_id, site = interview["org_id"], interview["sites"][0]
    result = _answer(
        harness, org_id, "S1FUG-5.4", site, present=True, description="Small treatment plant"
    )
    assert result["escalated"] is True
    assert result["escalation"]["trigger"] == "condition_met"


def test_a_no_to_process_sources_does_not_escalate(harness, interview) -> None:
    result = _answer(harness, interview["org_id"], "S1FUG-5.4", interview["sites"][0], present=False)
    assert result["escalated"] is False


def test_selling_power_escalates(harness, interview) -> None:
    """Mapping 6.4: selling energy or attributes risks double counting."""
    org_id, site = interview["org_id"], interview["sites"][0]
    result = _answer(
        harness, org_id, "S2-6.4", site,
        present=True, distribution_scenario="grid", sells_energy_or_attributes=True,
    )
    assert result["escalated"] is True


def test_generating_without_selling_does_not_escalate(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    result = _answer(
        harness, org_id, "S2-6.4", site,
        present=True, distribution_scenario="owned_operated_onsite",
        sells_energy_or_attributes=False,
    )
    assert result["escalated"] is False


def test_escalation_carries_the_client_context(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    result = harness.interview_engine.not_sure(org_id, "S1FUG-5.4", site, actor_id="usr_1")
    context = result["escalation"]["seed_context"]
    assert context["legal_name"] == "Northlight Studios Ltd"
    assert context["site_name"] == "Stage 1"


def test_a_resolved_escalation_lets_the_question_close(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["sites"][0]
    result = harness.interview_engine.not_sure(org_id, "S1FUG-5.4", site, actor_id="usr_1")
    harness.escalation_service.resolve(
        result["escalation"]["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    assert harness.states.find(org_id, "S1FUG-5.4", site)["status"] == "resolved"

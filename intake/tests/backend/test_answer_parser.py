"""Reading free-text answers: the proposal, the guardrails, and the failure paths.

Every test uses the scripted client - no test in this repo may make a real
model call.
"""

from __future__ import annotations

import pytest

from intake.backend.adapters.llm import (
    DisabledLLMClient,
    LLMBudgetExceeded,
    LLMUnavailable,
    ScriptedLLMClient,
    TurnBudget,
    build_llm_client,
    new_budget,
)
from intake.backend.config import load_llm_config
from intake.backend.services.answer_parser import AnswerParser

REFRIGERANT_Q = "S1FUG-5.1"


def _reply(fields: dict, confidence: float, **extra) -> dict:
    return {
        "fields": fields,
        "confidence": confidence,
        "summary": "12 air conditioning units, refrigerant R-410A.",
        "unresolved": [],
        "clarifying_question": None,
        **extra,
    }


@pytest.fixture
def interview(harness):
    seeded = harness.seeded_org(sites=1)
    seeded["site"] = harness.sites.list_by_org(seeded["org_id"])[0]["site_id"]
    return seeded


def _parse(harness, interview, text: str):
    return harness.answer_parser.parse(
        org_id=interview["org_id"],
        datapoint_id=REFRIGERANT_Q,
        scope_ref=interview["site"],
        text=text,
        actor_id="usr_1",
        settings=harness.settings,
    )


# -- configuration is safe by default ---------------------------------------


def test_the_default_adapter_makes_no_calls() -> None:
    """Nothing in this repo can make a paid call without being switched on."""
    assert load_llm_config()["adapter"] == "disabled"
    assert isinstance(build_llm_client(), DisabledLLMClient)


def test_the_disabled_client_says_so_rather_than_failing_obscurely() -> None:
    with pytest.raises(LLMUnavailable) as exc:
        DisabledLLMClient().complete_json("parse_answer", {}, new_budget())
    assert "is configured" in str(exc.value)
    assert "OPENAI_API_KEY" in str(exc.value)


def test_the_call_budget_is_two_per_turn() -> None:
    """SPEC section 6: one parse, one rephrase, no more."""
    assert load_llm_config()["max_calls_per_turn"] == 2


def test_the_budget_is_enforced() -> None:
    budget = TurnBudget(max_calls=2)
    budget.spend("parse_answer")
    budget.spend("rephrase_explainer")
    with pytest.raises(LLMBudgetExceeded):
        budget.spend("parse_answer")


def test_an_unknown_adapter_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_llm_client({"adapter": "telepathy"})


# -- a confident reading -----------------------------------------------------


def test_a_confident_reading_is_proposed_not_written(harness, interview) -> None:
    """The model proposes; the client confirms; only then is anything stored."""
    harness.llm.queue(
        "parse_answer",
        _reply({"present": True, "equipment_count": 12, "gas_type": "R-410A"}, 0.92),
    )
    outcome = _parse(harness, interview, "we've got about 12 aircon units, the R-410A ones")

    assert outcome.status == "proposed"
    assert outcome.proposal["equipment_count"] == 12
    assert outcome.proposal["gas_type"] == "R-410A"
    assert outcome.summary
    assert harness.state(interview["org_id"], REFRIGERANT_Q, interview["site"])["status"] == (
        "unasked"
    ), "nothing may be written before the client confirms"


def test_confirming_a_proposal_records_it_as_ai_assisted(harness, interview) -> None:
    harness.llm.queue(
        "parse_answer", _reply({"present": True, "equipment_count": 12}, 0.9)
    )
    outcome = _parse(harness, interview, "twelve units")

    harness.interview_engine.submit_answer(
        org_id=interview["org_id"],
        datapoint_id=REFRIGERANT_Q,
        scope_ref=interview["site"],
        answer={**outcome.proposal, "has_service_records": True},
        actor_id="usr_1",
        ai_assisted=True,
    )
    state = harness.state(interview["org_id"], REFRIGERANT_Q, interview["site"])
    assert state["status"] == "answered"
    assert state["ai_assisted"] is True
    assert state["provenance"]["answered_by"] == "user", "the client owns the answer"


# -- guardrails on what the model returns ------------------------------------


def test_an_invented_field_is_dropped(harness, interview) -> None:
    harness.llm.queue(
        "parse_answer",
        _reply({"present": True, "equipment_count": 3, "annual_emissions_tco2e": 41.2}, 0.95),
    )
    outcome = _parse(harness, interview, "three units")

    assert "annual_emissions_tco2e" not in outcome.proposal
    assert "annual_emissions_tco2e" in outcome.dropped_fields


def test_a_value_outside_a_closed_vocabulary_is_dropped(harness, interview) -> None:
    """BND-2.3 party_role is a closed workbook vocabulary."""
    harness.llm.queue("parse_answer", _reply({"party_role": "building_manager"}, 0.95))
    outcome = harness.answer_parser.parse(
        org_id=interview["org_id"],
        datapoint_id="BND-2.3",
        scope_ref=interview["site"],
        text="we're sort of the building manager",
        actor_id="usr_1",
        settings=harness.settings,
    )
    assert "party_role" not in outcome.proposal
    assert "party_role" in outcome.dropped_fields


def test_free_text_wording_is_passed_through_not_normalised(harness, interview) -> None:
    """Provisional fields have no agreed list, so the client's words are kept."""
    harness.llm.queue(
        "parse_answer", _reply({"present": True, "gas_type": "R-410A", "equipment_count": 2}, 0.9)
    )
    outcome = _parse(harness, interview, "the R-410A ones")
    assert outcome.proposal["gas_type"] == "R-410A"


def test_a_missing_confidence_is_treated_as_no_confidence(harness, interview) -> None:
    harness.llm.queue("parse_answer", {"fields": {"present": True}, "summary": "yes"})
    assert _parse(harness, interview, "yes").status == "clarify"


def test_a_nonsense_confidence_is_treated_as_no_confidence(harness, interview) -> None:
    harness.llm.queue(
        "parse_answer", _reply({"present": True}, "very confident")  # type: ignore[arg-type]
    )
    assert _parse(harness, interview, "yes").status == "clarify"


# -- clarify, then escalate --------------------------------------------------


def test_a_low_confidence_reading_asks_one_clarifying_question(harness, interview) -> None:
    harness.llm.queue(
        "parse_answer",
        _reply({}, 0.3, clarifying_question="Are those units ones your company maintains?"),
    )
    outcome = _parse(harness, interview, "there's some cooling stuff maybe")

    assert outcome.status == "clarify"
    assert outcome.clarifying_question.startswith("Are those units")
    assert outcome.attempts == 1
    assert harness.escalation_service.list_open(interview["org_id"]) == []


def test_a_second_failure_escalates(harness, interview) -> None:
    """SPEC section 3, trigger b: two failed attempts go to a human."""
    harness.llm.queue("parse_answer", _reply({}, 0.2))
    harness.llm.queue("parse_answer", _reply({}, 0.25))

    _parse(harness, interview, "not really sure")
    outcome = _parse(harness, interview, "still not sure sorry")

    assert outcome.status == "escalated"
    assert outcome.attempts == 2
    assert "passed it to the Sustentra team" in outcome.message
    open_items = harness.escalation_service.list_open(interview["org_id"])
    assert [item["trigger"] for item in open_items] == ["failed_clarification"]


def test_attempts_are_recorded_on_the_state_and_audited(harness, interview) -> None:
    harness.llm.queue("parse_answer", _reply({}, 0.1))
    _parse(harness, interview, "dunno")

    state = harness.state(interview["org_id"], REFRIGERANT_Q, interview["site"])
    assert state["clarification_attempts"] == 1
    entries = harness.audit.list_for_datapoint(
        interview["org_id"], REFRIGERANT_Q, interview["site"]
    )
    assert any(entry["field"] == "clarification_attempts" for entry in entries)


def test_the_escalation_carries_what_the_client_tried(harness, interview) -> None:
    harness.llm.queue("parse_answer", _reply({}, 0.2))
    harness.llm.queue("parse_answer", _reply({}, 0.2))
    _parse(harness, interview, "first go")
    outcome = _parse(harness, interview, "second go")
    assert outcome.escalation["answer_attempts"][0]["answer"] == "second go"


# -- failure is safe ---------------------------------------------------------


def test_no_model_configured_sends_the_question_to_a_human(harness, interview) -> None:
    """The answer is never guessed at and never silently lost."""
    parser = AnswerParser(
        llm_client=DisabledLLMClient(),
        state_repository=harness.states,
        org_repository=harness.orgs,
        site_repository=harness.sites,
        state_machine=harness.state_machine,
        escalations=harness.escalation_service,
        question_content=harness.question_content,
    )
    outcome = parser.parse(
        org_id=interview["org_id"],
        datapoint_id=REFRIGERANT_Q,
        scope_ref=interview["site"],
        text="twelve aircon units",
        actor_id="usr_1",
        settings=harness.settings,
    )
    assert outcome.status == "escalated"
    assert harness.state(interview["org_id"], REFRIGERANT_Q, interview["site"])["status"] == (
        "escalated"
    )


def test_an_unknown_question_is_rejected(harness, interview) -> None:
    with pytest.raises(ValueError):
        harness.answer_parser.parse(
            org_id=interview["org_id"],
            datapoint_id="NOPE-9.9",
            scope_ref=None,
            text="hello",
            actor_id="usr_1",
            settings=harness.settings,
        )


def test_the_prompt_is_rendered_even_for_the_scripted_client(harness, interview) -> None:
    """A prompt that cannot render should fail in tests, not in production."""
    harness.llm.queue("parse_answer", _reply({"present": True}, 0.9))
    _parse(harness, interview, "yes twelve units")
    assert harness.llm.calls[0]["prompt_id"] == "parse_answer"
    assert harness.llm.calls[0]["rendered_chars"] > 500


def test_the_scripted_client_refuses_to_invent_a_response() -> None:
    """An unscripted call is a test bug, and should look like one."""
    variables = {
        "question": "q",
        "explainer": "e",
        "field_spec": "[]",
        "client_answer": "a",
        "context": "{}",
    }
    with pytest.raises(LLMUnavailable):
        ScriptedLLMClient().complete_json("parse_answer", variables, TurnBudget(max_calls=2))

"""Contradiction rules, the rephrase path, and the prompt files themselves."""

from __future__ import annotations

import pytest

from intake.backend.config import load_contradiction_rules
from intake.backend.services.prompt_library import (
    PromptError,
    get_prompt,
    load_prompts,
)


@pytest.fixture
def interview(harness):
    seeded = harness.seeded_org(sites=1)
    seeded["site"] = harness.sites.list_by_org(seeded["org_id"])[0]["site_id"]
    return seeded


def _answer(harness, org_id, datapoint_id, scope_ref, **answer):
    return harness.interview_engine.submit_answer(
        org_id=org_id,
        datapoint_id=datapoint_id,
        scope_ref=scope_ref,
        answer=answer,
        actor_id="usr_1",
    )


# -- prompts are files, and they are sound ----------------------------------


def test_prompts_live_as_files_not_inline_strings() -> None:
    """CLAUDE.md: prompts are files under intake/prompts/."""
    assert set(load_prompts()) == {"parse_answer", "rephrase_explainer"}


def test_every_prompt_declares_the_variables_it_uses() -> None:
    for prompt_id in load_prompts():
        prompt = get_prompt(prompt_id)
        assert prompt.variables
        assert prompt.version


def test_rendering_without_a_variable_fails_loudly() -> None:
    """A prompt with a hole in it must never reach a model."""
    with pytest.raises(PromptError) as exc:
        get_prompt("parse_answer").render({"question": "q"})
    assert "missing variables" in str(exc.value)


def test_rendering_substitutes_every_variable() -> None:
    rendered = get_prompt("rephrase_explainer").render(
        {"question": "Q-MARKER", "explainer": "E-MARKER", "context": "C-MARKER"}
    )
    assert "Q-MARKER" in rendered and "E-MARKER" in rendered and "C-MARKER" in rendered
    assert "{question}" not in rendered


def test_the_parse_prompt_tells_the_model_not_to_guess() -> None:
    """The single most important instruction in the file."""
    body = get_prompt("parse_answer").body.lower()
    assert "never invent a field" in body
    assert "never guess" in body


def test_an_unknown_prompt_raises() -> None:
    with pytest.raises(PromptError):
        get_prompt("no_such_prompt")


# -- the rephrase path -------------------------------------------------------


def test_not_sure_offers_another_explanation_then_escalates(harness, interview) -> None:
    """SPEC section 3: canned explainer, one rephrase, then a human."""
    harness.llm.queue(
        "rephrase_explainer",
        {
            "explainer": "Look for a metal box outside with a fan in it.",
            "suggests_escalation": False,
        },
    )
    result = harness.interview_engine.not_sure(
        interview["org_id"], "S1FUG-5.1", interview["site"], actor_id="usr_1"
    )

    assert result["another_way"].startswith("Look for a metal box")
    assert result["explainer"], "the canned explainer is still returned"
    assert "24 hours" in result["message"]
    assert harness.state(interview["org_id"], "S1FUG-5.1", interview["site"])["status"] == (
        "escalated"
    )


def test_not_sure_still_works_with_no_model(harness, interview) -> None:
    """Losing the rephrase costs a nicety, never the client's place."""
    result = harness.interview_engine.not_sure(
        interview["org_id"], "S1FUG-5.1", interview["site"], actor_id="usr_1"
    )
    assert result["another_way"] is None
    assert result["explainer"]
    assert harness.escalation_service.list_open(interview["org_id"])


def test_the_rephrase_uses_at_most_one_call(harness, interview) -> None:
    harness.llm.queue("rephrase_explainer", {"explainer": "Another way.", "suggests_escalation": False})
    harness.interview_engine.not_sure(
        interview["org_id"], "S1FUG-5.1", interview["site"], actor_id="usr_1"
    )
    assert len(harness.llm.calls) == 1


# -- contradictions ----------------------------------------------------------


def test_the_starting_rule_set_is_the_four_we_agreed() -> None:
    assert set(load_contradiction_rules()["rules"]) == {
        "fleet_route_without_fleet",
        "allocation_without_shared_metering",
        "blend_without_any_fuel",
        "lessee_role_on_owned_site",
    }


def test_every_rule_explains_itself_to_the_client() -> None:
    for name, rule in load_contradiction_rules()["rules"].items():
        assert rule["client_message"], name
        assert rule["description"], name
        assert rule["datapoint_id"], name


def test_a_consistent_answer_raises_nothing(harness, interview) -> None:
    result = _answer(
        harness, interview["org_id"], "S2-6.2", interview["site"],
        present=True, allocation_basis="floor_area",
    )
    # S2-6.2 is HUMAN class so it is confirmed by a person, but not as a conflict.
    assert result["escalation"]["trigger"] == "human_class_datapoint"


def test_allocation_without_shared_metering_is_caught(harness, interview) -> None:
    """They said the site is not shared, but told us how to split the bill."""
    result = _answer(
        harness, interview["org_id"], "S2-6.2", interview["site"],
        present=False, allocation_basis="floor_area",
    )
    assert result["escalated"] is True
    assert result["escalation"]["trigger"] == "contradiction"
    assert "not shared" in result["escalation"]["client_message"]


def test_a_blend_with_no_fuel_anywhere_is_caught(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["site"]
    _answer(harness, org_id, "S1STC-3.1", site, present=False)
    _answer(harness, org_id, "S1STC-3.2", site, present=False)
    _answer(harness, org_id, "S1MOB-4.1", None, present=False)

    result = _answer(harness, org_id, "S1STC-3.3", site, present=True, blend_source="B20")
    assert result["escalated"] is True
    assert result["escalation"]["trigger"] == "contradiction"


def test_a_blend_with_fuel_present_is_fine(harness, interview) -> None:
    org_id, site = interview["org_id"], interview["site"]
    _answer(harness, org_id, "S1STC-3.1", site, present=True, equipment=["Boiler"])
    result = _answer(harness, org_id, "S1STC-3.3", site, present=True, blend_source="B20")
    assert result["escalated"] is False


def test_a_tenant_role_on_an_owned_site_is_caught(harness) -> None:
    """The interview answer conflicts with a seed-form fact."""
    from intake.tests.conftest import company_payload, site_payload

    created = harness.create_org()
    org_id = created["org"]["org_id"]
    harness.seed_form_service.submit(
        org_id=org_id,
        submitted_by=created["owner"]["user_id"],
        payload={
            "company": company_payload(),
            "sites": [site_payload(ownership="owned", lease_type="")],
        },
    )
    harness.profile_state_service.initialise(org_id)
    site = harness.sites.list_by_org(org_id)[0]["site_id"]

    result = _answer(
        harness, org_id, "BND-2.3", site,
        party_role="lessee", operational_control_over_asset_flag=True,
    )
    assert result["escalation"]["trigger"] == "contradiction"
    assert "recorded as owned" in result["escalation"]["client_message"]


def test_an_owner_occupier_on_an_owned_site_is_fine(harness) -> None:
    from intake.tests.conftest import company_payload, site_payload

    created = harness.create_org()
    org_id = created["org"]["org_id"]
    harness.seed_form_service.submit(
        org_id=org_id,
        submitted_by=created["owner"]["user_id"],
        payload={
            "company": company_payload(),
            "sites": [site_payload(ownership="owned", lease_type="")],
        },
    )
    harness.profile_state_service.initialise(org_id)
    site = harness.sites.list_by_org(org_id)[0]["site_id"]

    result = _answer(
        harness, org_id, "BND-2.3", site,
        party_role="owner_occupier", operational_control_over_asset_flag=True,
    )
    assert result["escalation"]["trigger"] == "human_class_datapoint"


def test_a_contradiction_is_never_decided_by_a_model(harness, interview) -> None:
    """The rules are predicates; no model call is made to find a conflict."""
    _answer(
        harness, interview["org_id"], "S2-6.2", interview["site"],
        present=False, allocation_basis="floor_area",
    )
    assert harness.llm.calls == []

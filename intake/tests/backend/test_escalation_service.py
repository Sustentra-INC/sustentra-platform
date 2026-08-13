"""Escalation records (Phase C1). No emails are sent from here - that is Phase D."""

from __future__ import annotations

import pytest

from intake.backend.services.escalation_service import EscalationError

DATAPOINT = "S1FUG-5.4"


def _open(harness, org_id: str, scope_ref: str, trigger: str = "user_requested_help") -> dict:
    return harness.escalation_service.open(
        org_id=org_id,
        datapoint_id=DATAPOINT,
        scope_ref=scope_ref,
        trigger=trigger,
        question_label="On-site wastewater treatment or other industrial processes?",
        actor_id="usr_1",
        answer_attempts=[{"attempt": 1, "text": "not sure"}],
        seed_context={"legal_name": "Northlight Studios Ltd"},
    )


@pytest.fixture
def seeded(harness):
    result = harness.seeded_org(sites=1)
    result["site_id"] = harness.sites.list_by_org(result["org_id"])[0]["site_id"]
    return result


# -- opening ----------------------------------------------------------------


def test_opening_an_escalation_moves_the_state(harness, seeded) -> None:
    _open(harness, seeded["org_id"], seeded["site_id"])
    state = harness.state(seeded["org_id"], DATAPOINT, seeded["site_id"])
    assert state["status"] == "escalated"
    assert state["escalation_id"]


def test_escalation_carries_what_a_reviewer_needs(harness, seeded) -> None:
    """SPEC section 3: the question, the attempts, and the seed context."""
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    assert record["question_label"].startswith("On-site wastewater")
    assert record["answer_attempts"] == [{"attempt": 1, "text": "not sure"}]
    assert record["seed_context"]["legal_name"] == "Northlight Studios Ltd"
    assert record["status"] == "pending_auditor_review"


def test_escalation_reuses_the_gap_ticket_vocabulary(harness, seeded) -> None:
    """SPEC section 5 asks for gap_ticket_schema shape 'where sensible'."""
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    assert record["ticket_type"] == "clarification_request"
    assert record["status"] == "pending_auditor_review"
    assert record["ticket_version"] == 1
    assert record["audit_trail"][0]["action"] == "opened"


def test_user_requested_help_is_marked_as_such(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"], trigger="user_requested_help")
    assert record["detection_origin"] == "user_requested"


def test_system_triggers_are_marked_system_detected(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"], trigger="condition_met")
    assert record["detection_origin"] == "system_detected"


def test_opening_twice_returns_the_same_escalation(harness, seeded) -> None:
    first = _open(harness, seeded["org_id"], seeded["site_id"])
    second = _open(harness, seeded["org_id"], seeded["site_id"])
    assert first["escalation_id"] == second["escalation_id"]
    assert len(harness.escalation_service.list_open(seeded["org_id"])) == 1


def test_escalating_an_unknown_state_is_rejected(harness, seeded) -> None:
    with pytest.raises(EscalationError):
        harness.escalation_service.open(
            org_id=seeded["org_id"],
            datapoint_id=DATAPOINT,
            scope_ref="ste_does_not_exist",
            trigger="condition_met",
            question_label="x",
            actor_id="usr_1",
        )


def test_the_same_question_at_another_site_is_a_separate_escalation(harness) -> None:
    seeded = harness.seeded_org(sites=2)
    org_id = seeded["org_id"]
    sites = [site["site_id"] for site in harness.sites.list_by_org(org_id)]
    _open(harness, org_id, sites[0])
    _open(harness, org_id, sites[1])
    assert len(harness.escalation_service.list_open(org_id)) == 2


# -- blocking ---------------------------------------------------------------


def test_open_escalations_are_reported_as_blocked(harness, seeded) -> None:
    _open(harness, seeded["org_id"], seeded["site_id"])
    assert harness.escalation_service.blocked_datapoints(seeded["org_id"]) == {
        (DATAPOINT, seeded["site_id"])
    }


def test_an_escalation_does_not_block_other_questions(harness, seeded) -> None:
    """SPEC section 4: escalations block dependants, never the interview."""
    _open(harness, seeded["org_id"], seeded["site_id"])
    others = [
        state
        for state in harness.states.list_by_org(seeded["org_id"])
        if state["datapoint_id"] != DATAPOINT
    ]
    assert others
    assert all(state["status"] != "escalated" for state in others)


# -- resolution -------------------------------------------------------------


def test_resolution_writes_the_answer_into_the_profile(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    harness.escalation_service.resolve(
        record["escalation_id"],
        value={"present": False},
        actor_id="rev_1",
        resolution_note="No process sources; confirmed by phone.",
    )

    state = harness.state(seeded["org_id"], DATAPOINT, seeded["site_id"])
    assert state["status"] == "resolved"
    assert state["value"] == {"present": False}
    assert state["provenance"]["answered_by"] == "team"


def test_resolution_is_recorded_on_the_escalation(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    resolved = harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "rev_1"
    assert resolved["resolved_at"]
    assert resolved["ticket_version"] == 2
    assert [entry["action"] for entry in resolved["audit_trail"]] == ["opened", "resolved"]


def test_resolved_escalations_leave_the_open_queue(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    assert harness.escalation_service.list_open(seeded["org_id"]) == []
    assert harness.escalation_service.blocked_datapoints(seeded["org_id"]) == set()


def test_resolving_twice_is_rejected(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    with pytest.raises(EscalationError):
        harness.escalation_service.resolve(
            record["escalation_id"], value={"present": True}, actor_id="rev_1"
        )


def test_resolving_an_unknown_escalation_is_rejected(harness) -> None:
    with pytest.raises(EscalationError):
        harness.escalation_service.resolve("esc_nope", value={}, actor_id="rev_1")


def test_resolution_is_audited(harness, seeded) -> None:
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1", resolution_note="ok"
    )
    entries = harness.audit.list_for_datapoint(seeded["org_id"], DATAPOINT, seeded["site_id"])
    statuses = [(e["old_value"], e["new_value"]) for e in entries if e["field"] == "status"]
    assert ("escalated", "resolved") in statuses


def test_no_email_is_sent_in_phase_c(harness, seeded) -> None:
    """Emails and the reviewer queue are Phase D."""
    before = len(harness.mailbox.sent)
    record = _open(harness, seeded["org_id"], seeded["site_id"])
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    assert len(harness.mailbox.sent) == before

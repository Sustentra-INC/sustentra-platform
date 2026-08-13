"""State machine behaviour: every legal transition, and every illegal one.

The transition table is the enforcement point for SPEC section 4, so it is
tested exhaustively rather than by example: for all 64 status pairs, exactly the
declared ones are accepted.
"""

from __future__ import annotations

import pytest

from intake.backend.services.state_machine import ALLOWED, TransitionError

ALL_STATUSES = sorted(ALLOWED)

LEGAL_PAIRS = [(src, dst) for src, targets in ALLOWED.items() for dst in sorted(targets)]
ILLEGAL_PAIRS = [
    (src, dst)
    for src in ALL_STATUSES
    for dst in ALL_STATUSES
    if dst not in ALLOWED[src]
]


def _state(harness, status: str = "unasked") -> dict:
    created = harness.state_machine.create(
        org_id="org_test",
        datapoint_id="S1STC-3.1",
        grain="site",
        scope_ref="ste_1",
        actor_id="usr_1",
    )
    if status == "unasked":
        return created
    # Walk to the requested status through legal steps.
    path = {
        "asked": ["asked"],
        "answered": ["asked", "answered"],
        "unknown": ["asked", "unknown"],
        "not_present": ["not_present"],
        "pending_documents": ["asked", "pending_documents"],
        "escalated": ["asked", "escalated"],
        "resolved": ["asked", "escalated", "resolved"],
    }[status]
    state = created
    for step in path:
        state = harness.state_machine.transition(state, step, actor_id="usr_1")
    return state


# -- creation ---------------------------------------------------------------


def test_states_start_unasked(harness) -> None:
    assert _state(harness)["status"] == "unasked"


def test_create_is_idempotent(harness) -> None:
    first = _state(harness)
    second = harness.state_machine.create(
        org_id="org_test",
        datapoint_id="S1STC-3.1",
        grain="site",
        scope_ref="ste_1",
        actor_id="usr_1",
    )
    assert first["state_id"] == second["state_id"]
    assert len(harness.states.list_by_org("org_test")) == 1


def test_same_question_at_two_sites_is_two_states(harness) -> None:
    _state(harness)
    harness.state_machine.create(
        org_id="org_test",
        datapoint_id="S1STC-3.1",
        grain="site",
        scope_ref="ste_2",
        actor_id="usr_1",
    )
    assert len(harness.states.list_for_datapoint("org_test", "S1STC-3.1")) == 2


# -- the transition table ---------------------------------------------------


@pytest.mark.parametrize(("source", "target"), LEGAL_PAIRS)
def test_declared_transitions_are_accepted(harness, source: str, target: str) -> None:
    state = _state(harness, source)
    assert harness.state_machine.transition(state, target, actor_id="usr_1")["status"] == target


@pytest.mark.parametrize(("source", "target"), ILLEGAL_PAIRS)
def test_undeclared_transitions_are_rejected(harness, source: str, target: str) -> None:
    state = _state(harness, source)
    with pytest.raises(TransitionError):
        harness.state_machine.transition(state, target, actor_id="usr_1")


def test_resolved_is_terminal(harness) -> None:
    assert ALLOWED["resolved"] == set()


def test_unknown_status_is_rejected(harness) -> None:
    state = _state(harness)
    with pytest.raises(TransitionError):
        harness.state_machine.transition(state, "invented_status", actor_id="usr_1")


# -- audit trail ------------------------------------------------------------


def test_creation_and_changes_are_audited(harness) -> None:
    state = _state(harness)
    state = harness.state_machine.mark_asked(state, actor_id="usr_1")
    harness.state_machine.record_answer(state, value={"present": True}, actor_id="usr_1")

    actions = [entry["action"] for entry in harness.audit.list_by_org("org_test")]
    assert actions == ["state_created", "status_changed", "status_changed", "value_changed"]


def test_audit_records_old_and_new_and_who(harness) -> None:
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_7")
    entry = [e for e in harness.audit.list_by_org("org_test") if e["field"] == "status"][-1]
    assert (entry["old_value"], entry["new_value"]) == ("unasked", "asked")
    assert entry["actor_id"] == "usr_7"
    assert entry["at"]


def test_history_is_kept_not_overwritten(harness) -> None:
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_1")
    state = harness.state_machine.record_answer(state, {"present": True}, actor_id="usr_1")
    harness.state_machine.record_answer(state, {"present": False}, actor_id="usr_1")

    history = harness.states.history(state["state_id"])
    assert len(history) >= 3
    assert harness.state_machine._states.find("org_test", "S1STC-3.1", "ste_1")["value"] == {
        "present": False
    }


def test_re_answering_does_not_log_a_status_change(harness) -> None:
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_1")
    state = harness.state_machine.record_answer(state, {"present": True}, actor_id="usr_1")
    before = len(harness.audit.list_by_org("org_test"))
    harness.state_machine.record_answer(state, {"present": False}, actor_id="usr_1")
    added = [e["action"] for e in harness.audit.list_by_org("org_test")[before:]]
    assert added == ["value_changed"]


# -- the completeness / exclusion split -------------------------------------


def test_screening_no_records_a_completeness_state(harness) -> None:
    """Mapping v0.2 FAIL 5: 'screened, not present' is not an exclusion."""
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_1")
    updated = harness.state_machine.record_not_present(
        state, actor_id="usr_1", source_category="STC"
    )
    assert updated["status"] == "not_present"
    assert updated["value"] == {"present": False, "screened_source_category": "STC"}
    reason = [e for e in harness.audit.list_by_org("org_test") if e["field"] == "status"][-1]
    assert "not an EXC-010 exclusion" in reason["reason"]


def test_completeness_record_never_writes_exc_010(harness) -> None:
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_1")
    updated = harness.state_machine.record_not_present(state, actor_id="usr_1")
    assert "EXC-010" not in str(updated["value"])


def test_a_client_can_correct_not_present_to_yes(harness) -> None:
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_1")
    state = harness.state_machine.record_not_present(state, actor_id="usr_1")
    assert harness.state_machine.record_answer(
        state, {"present": True}, actor_id="usr_1"
    )["status"] == "answered"


# -- provenance -------------------------------------------------------------


def test_answers_record_who_supplied_them(harness) -> None:
    state = harness.state_machine.mark_asked(_state(harness), actor_id="usr_1")
    updated = harness.state_machine.record_answer(
        state, {"present": True}, actor_id="usr_1", value_basis="asserted"
    )
    assert updated["provenance"]["answered_by"] == "user"
    assert updated["provenance"]["value_basis"] == "asserted"


def test_team_resolution_is_attributed_to_the_team(harness) -> None:
    state = _state(harness, "escalated")
    resolved = harness.state_machine.resolve(
        state, value={"present": True}, actor_id="rev_1", resolution_note="confirmed with client"
    )
    assert resolved["status"] == "resolved"
    assert resolved["provenance"]["answered_by"] == "team"
    assert resolved["provenance"]["note"] == "confirmed with client"

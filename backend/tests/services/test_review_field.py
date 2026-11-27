"""The shared review-field state machine on its own (Methodology and calculation lines both use it)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.services import methodology_review, review_field as rf
from backend.app.services.request_service import Actor

NOW = datetime(2026, 11, 26, tzinfo=UTC)
ME = Actor(user_id="u", name="Me", login="me@x.test")


def upper(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise rf.ReviewInvalid(f"'F': {value!r} is not text.")
    return value.upper()


def record(**kw: Any) -> dict:
    return {"field_id": "f", "suggestion": None, "decision": None, "history": [], **kw}


def test_methodology_keeps_its_names_and_limits_from_the_shared_machine() -> None:
    assert methodology_review.MethodologyConflict is rf.ReviewConflict
    assert methodology_review.MethodologyInvalid is rf.ReviewInvalid
    assert methodology_review.PENDING == rf.PENDING and methodology_review.STATUSES == rf.STATUSES
    assert (methodology_review.MAX_HISTORY, methodology_review.MAX_VALUE_HISTORY, methodology_review.MAX_REASON,
            methodology_review.HISTORY_ROOM) == (50, 10, 500, 10 * 1024)
    assert methodology_review.status_of(record()) == "pending"


def test_accept_copies_only_the_named_keys_from_the_suggestion() -> None:
    suggestion = {"value": "a", "unit": "kg", "quote": "q"}
    done = rf.accept(record(suggestion=suggestion), "F", upper, ME, NOW, carry=("unit",))
    assert done["decision"] == {"status": "accepted", "value": "A", "unit": "kg", "by": {"name": "Me", "login": "me@x.test"},
                                "at": done["decision"]["at"]}
    plain = rf.accept(record(suggestion=suggestion), "F", upper, ME, NOW)
    assert "unit" not in plain["decision"]


def test_revert_restores_only_the_named_extras_and_only_short_text() -> None:
    first = rf.edit(record(), upper, "a", ME, NOW, extra={"unit": "kg", "reason": "r", "kind": "k"})
    second = rf.edit(first, upper, "b", ME, NOW)
    back = rf.revert(second, "F", upper, lambda: None, ME, NOW, extras=("unit", "reason"))
    assert back["decision"]["value"] == "A" and back["decision"]["unit"] == "kg" and back["decision"]["reason"] == "r"
    assert "kind" not in back["decision"]  # not named: not restored
    bare = rf.revert(second, "F", upper, lambda: None, ME, NOW)
    assert "unit" not in bare["decision"] and "reason" not in bare["decision"]  # Methodology's behaviour
    hostile = {**second, "value_history": [{"status": "edited", "value": "a", "unit": "x" * 501, "reason": "a\x00b"}]}
    odd = rf.revert(hostile, "F", upper, lambda: None, ME, NOW, extras=("unit", "reason"))
    assert "unit" not in odd["decision"] and "reason" not in odd["decision"]


def test_a_saved_decision_that_no_longer_validates_blocks_the_revert() -> None:
    stale = record(decision={"status": "edited", "value": "b"},
                   value_history=[{"status": "edited", "value": 5}, ])
    with pytest.raises(rf.ReviewConflict, match="can no longer be restored.*no longer fits"):
        rf.revert(stale, "F", upper, lambda: None, ME, NOW)
    with pytest.raises(rf.ReviewConflict, match="not a decision"):
        rf.revert({**stale, "value_history": ["junk"]}, "F", upper, lambda: None, ME, NOW)
    with pytest.raises(rf.ReviewConflict, match="too large to keep"):
        rf.revert(record(decision={"status": "edited", "value": "b"}, previous_lost=True), "F", upper,
                  lambda: None, ME, NOW)


def test_revert_with_no_earlier_decision_goes_to_the_detected_value_or_to_blank() -> None:
    detected = rf.edit(record(suggestion={"value": "a"}), upper, "z", ME, NOW)
    assert rf.revert(detected, "F", upper, lambda: None, ME, NOW)["history"][-1]["restored"] == "detected"
    row = rf.edit(record(user_added=True), upper, "z", ME, NOW)
    blank = rf.revert(row, "F", upper, lambda: "BLANK", ME, NOW)
    assert blank["decision"]["value"] == "BLANK" and blank["history"][-1]["restored"] == "empty"


def test_clean_reason() -> None:
    assert rf.clean_reason("  why ") == "why" and rf.clean_reason(None) is None and rf.clean_reason("  ") is None
    for bad in (5, "a\x00", "x" * 501):
        with pytest.raises(rf.ReviewInvalid):
            rf.clean_reason(bad)
    with pytest.raises(rf.ReviewInvalid, match="needed here"):
        rf.clean_reason(None, missing="A reason is needed here.")

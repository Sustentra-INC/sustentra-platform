"""Reviewer decisions on calculation lines: the rules (no database), on a hand-made trace and on a real one."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.app.services import calc_line_review as c
from backend.app.services.request_service import Actor
from backend.app.services.review_field import ReviewConflict, ReviewInvalid
from backend.app.services.workpaper_item_service import ITEM_KEY
from backend.tests.services.calc_trace.recalc_scenarios import scenarios

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
ANN = Actor(user_id="u1", name="Ann Reviewer", login="ann@acme.test")
SCHEMA = json.loads((Path(__file__).parents[3] / "contracts" / "calculation_trace.schema.json").read_text())

SUGGESTION = {"origin": "ai", "value": "eq3", "reason": "The bill gives carbon content", "quote": "C = 14.4",
              "source": {"kind": "document", "document_id": "DOC-1", "file_name": "bill.pdf"}, "model": "m",
              "request_id": "r1", "suggested_at": "2026-11-25T10:00:00.000Z"}


def trace() -> dict[str, Any]:
    return {
        "choices": [{"id": "method", "label": "Calculation method", "chosen": "eq1", "chosen_by": "default",
                     "options": [{"id": "eq1", "label": "Eq. 1", "available": True},
                                 {"id": "eq2", "label": "Eq. 2", "available": False,
                                  "why_unavailable": "No heat content in evidence"},
                                 {"id": "eq3", "label": "Eq. 3", "available": True}]}],
        "inputs": {
            "activity.total": {
                "id": "activity.total", "label": "Activity data", "kind": "evidence_sum",
                "company": {"value": 2380.0, "unit": "gal", "status": "accepted"},
                "recomputed": {"value": 2350.0, "unit": "gal", "status": "accepted"},
                "rows": [{"id": "DOC-1/c1", "label": "Bill", "recomputed": {"value": 2350.0, "unit": "gal",
                                                                             "status": "accepted"}}]},
            "grid_region": {"id": "grid_region", "label": "Grid region", "kind": "company_input",
                            "company": None, "recomputed": {"value": "CAMX", "unit": None, "status": "accepted"}},
            "empty": {"id": "empty", "label": "Not yet known", "kind": "company_input", "company": None,
                      "recomputed": None},
        },
    }


def new() -> dict[str, Any]:
    return c.new_record("s")


def choose(record: dict, option: Any = "eq3", **kw: Any) -> dict:
    kw.setdefault("reason", "The bill gives carbon content")
    return c.decide_choice(record, trace()["choices"][0], "choose", option_id=option, actor=ANN, now=NOW, **kw)


def edit(record: dict, value: Any, side: str = "recomputed", input_id: str = "activity.total", **kw: Any) -> dict:
    t = trace()
    found = c.find_input(t, input_id)
    assert found is not None
    kw.setdefault("reason", "Bill total corrected from the invoice")
    return c.decide_input(record, found[0], found[1], side, "edit", value=value, actor=ANN, now=NOW, **kw)


def act_input(record: dict, action: str, side: str = "recomputed", input_id: str = "activity.total", **kw: Any) -> dict:
    found = c.find_input(trace(), input_id)
    assert found is not None
    return c.decide_input(record, found[0], found[1], side, action, actor=ANN, now=NOW, **kw)


def act_choice(record: dict, action: str, choice: dict | None = None, **kw: Any) -> dict:
    return c.decide_choice(record, choice or trace()["choices"][0], action, actor=ANN, now=NOW, **kw)


# --- accept / choose or edit / reject / revert -------------------------------------------------------

def test_choice_table_pending_accepted_and_the_second_accept_is_a_409() -> None:
    offered = copy.deepcopy(trace()["choices"][0])
    offered["suggestion"] = SUGGESTION
    accepted = c.decide_choice(new(), offered, "accept", actor=ANN, now=NOW)
    assert accepted["decision"]["status"] == "accepted" and accepted["decision"]["value"] == "eq3"
    assert accepted["history"][-1]["action"] == "accept"
    with pytest.raises(ReviewConflict, match="already accepted"):
        c.decide_choice(accepted, offered, "accept", actor=ANN, now=NOW)  # a duplicate submit
    with pytest.raises(ReviewConflict, match="already accepted"):
        c.decide_choice(accepted, offered, "reject", reason="no", actor=ANN, now=NOW)


def test_accept_with_nothing_suggested_is_a_409_that_says_what_to_do() -> None:
    with pytest.raises(ReviewConflict, match="nothing to accept.*Pick an option instead"):
        act_choice(new(), "accept")


def test_choose_edits_and_revert_returns_the_previous_value() -> None:
    first = choose(new(), "eq3")
    assert first["decision"] == {"status": "edited", "value": "eq3", "reason": "The bill gives carbon content",
                                 "by": {"name": "Ann Reviewer", "login": "ann@acme.test"}, "at": first["decision"]["at"]}
    second = choose(first, "eq1")  # the default needs no reason
    assert second["decision"]["value"] == "eq1" and [d["value"] for d in second["value_history"]] == ["eq3"]
    back = act_choice(second, "revert")
    assert back["decision"]["value"] == "eq3" and back["decision"]["status"] == "edited"
    assert back["decision"]["reason"] == "The bill gives carbon content"  # restored with the value
    assert back["history"][-1] == {**back["history"][-1], "action": "revert", "restored": "previous", "to": "eq3"}
    pending = act_choice(back, "revert")
    assert pending["decision"]["status"] == "pending" and pending["history"][-1]["restored"] == "empty"
    with pytest.raises(ReviewConflict, match="already pending"):
        act_choice(pending, "revert")


def test_reject_needs_a_reason_and_revert_after_reject_restores_the_decision_before() -> None:
    with pytest.raises(ReviewInvalid, match="reason is required"):
        act_choice(new(), "reject")
    with pytest.raises(ReviewInvalid, match="reason is required"):
        act_choice(new(), "reject", reason="   ")
    with pytest.raises(ReviewInvalid, match="at most 500"):
        act_choice(new(), "reject", reason="x" * 501)
    rejected = act_choice(new(), "reject", reason="Not what the bill says")
    assert rejected["decision"] == {**rejected["decision"], "status": "rejected", "value": None,
                                    "reason": "Not what the bill says"}
    after = choose(rejected, "eq3")  # a rejected choice can be decided again
    assert [d["status"] for d in after["value_history"]] == ["rejected"]
    assert act_choice(after, "revert")["decision"]["status"] == "rejected"


def test_choose_an_unavailable_option_is_a_409_with_the_reason() -> None:
    with pytest.raises(ReviewConflict, match="Eq. 2.*No heat content in evidence"):
        choose(new(), "eq2")


@pytest.mark.parametrize("bad", ["eq9", "", None, 3, ["eq1"], {"id": "eq1"}])
def test_choose_something_that_is_not_an_option_is_a_422(bad: Any) -> None:
    with pytest.raises(ReviewInvalid):
        choose(new(), bad)


def test_choose_other_than_the_default_needs_a_reason_but_the_default_does_not() -> None:
    with pytest.raises(ReviewInvalid, match="Say why 'Calculation method' is not left as it is"):
        choose(new(), "eq3", reason=None)
    assert choose(new(), "eq1", reason=None)["decision"]["value"] == "eq1"
    assert "reason" not in choose(new(), "eq1", reason=None)["decision"]


def test_a_stored_option_that_is_no_longer_available_blocks_the_revert_with_a_sentence() -> None:
    chosen = choose(choose(new(), "eq3"), "eq1")
    gone = trace()["choices"][0]
    gone["options"][2]["available"] = False
    gone["options"][2]["why_unavailable"] = "No carbon content in evidence"
    with pytest.raises(ReviewConflict, match="No carbon content in evidence"):
        c.decide_choice(chosen, gone, "revert", actor=ANN, now=NOW)


# --- inputs -----------------------------------------------------------------------------------------------

def test_a_recomputed_edit_without_a_reason_is_a_422_and_with_one_is_reviewer_entered() -> None:
    for reason in (None, "", "   "):
        with pytest.raises(ReviewInvalid, match="reason is required"):
            edit(new(), 2400, reason=reason)
    done = edit(new(), "2,400.5")
    assert done["decision"]["value"] == 2400.5 and done["decision"]["kind"] == "reviewer_entered"
    assert done["decision"]["unit"] == "gal" and done["decision"]["reason"] == "Bill total corrected from the invoice"
    assert done["decision"]["by"] == {"name": "Ann Reviewer", "login": "ann@acme.test"}


def test_a_company_edit_needs_no_reason_and_is_a_company_input() -> None:
    done = edit(new(), 2380, side="company", reason=None, document_id="DOC-9")
    assert done["decision"]["kind"] == "company_input" and "reason" not in done["decision"]
    assert done["decision"]["document_id"] == "DOC-9"


def test_input_edit_accept_revert_table() -> None:
    first = edit(new(), 2400)
    second = edit(first, 2500)
    assert second["decision"]["value"] == 2500 and [d["value"] for d in second["value_history"]] == [2400]
    reverted = act_input(second, "revert")
    assert reverted["decision"]["value"] == 2400 and reverted["decision"]["unit"] == "gal"
    assert reverted["decision"]["kind"] == "reviewer_entered" and reverted["decision"]["reason"]
    with pytest.raises(ReviewConflict, match="already edited"):
        act_input(first, "accept")
    with pytest.raises(ReviewConflict, match="already edited"):
        act_input(first, "reject", reason="no")
    with pytest.raises(ReviewConflict, match="already pending"):
        act_input(new(), "revert")


def test_accept_takes_the_stored_suggestion_with_its_unit() -> None:
    record = {**new(), "suggestion": {**SUGGESTION, "value": 2351.5, "unit": "gal"}}
    done = act_input(record, "accept", side="company")
    assert done["decision"]["status"] == "accepted" and done["decision"]["value"] == 2351.5
    assert done["decision"]["unit"] == "gal"
    with pytest.raises(ReviewConflict, match="nothing to accept"):
        act_input(new(), "accept")


def test_accept_takes_the_suggestion_the_trace_carries() -> None:
    t = trace()
    t["inputs"]["activity.total"]["company"]["suggestion"] = {**SUGGESTION, "value": 2380, "unit": "gal"}
    found = c.find_input(t, "activity.total")
    assert found is not None
    done = c.decide_input(new(), found[0], None, "company", "accept", actor=ANN, now=NOW)
    assert done["decision"]["value"] == 2380 and done["suggestion"]["request_id"] == "r1"


def test_row_inputs_are_decided_on_the_row() -> None:
    assert c.find_input(trace(), "activity.total/DOC-1/c1") is not None
    assert c.find_input(trace(), "activity.total/nope") is None
    assert c.find_input(trace(), "nope") is None and c.find_input(trace(), "activity.total/") is None
    done = edit(new(), 100, input_id="activity.total/DOC-1/c1")
    assert done["decision"]["value"] == 100 and done["decision"]["unit"] == "gal"


@pytest.mark.parametrize("bad", [None, True, False, float("nan"), float("inf"), -float("inf"), 1e16, "abc", "",
                                 "   ", "1e999", "nan", [1], {"v": 1}, "x" * 201, "12\x00"])
def test_hostile_numbers_are_a_422(bad: Any) -> None:
    with pytest.raises(ReviewInvalid):
        edit(new(), bad)


def test_wrong_units_are_a_422_and_the_inputs_own_unit_is_used_when_none_is_given() -> None:
    with pytest.raises(ReviewInvalid, match="is in gal: enter the value in gal"):
        edit(new(), 2400, unit="kWh")
    assert edit(new(), 2400, unit="gallon")["decision"]["unit"] == "gallon"  # the same unit by another name
    assert edit(new(), 2400, unit=" ")["decision"]["unit"] == "gal"
    with pytest.raises(ReviewInvalid, match="unit is not valid"):
        edit(new(), 2400, unit="g\x00al")
    with pytest.raises(ReviewInvalid, match="unit is not valid"):
        edit(new(), 2400, unit="x" * 41)
    with pytest.raises(ReviewInvalid, match="unit is not valid"):
        edit(new(), 2400, unit=5)


def test_text_inputs_take_text_and_keep_unicode() -> None:
    done = edit(new(), "  AKGD – Alaska ✓ ", input_id="grid_region")
    assert done["decision"]["value"] == "AKGD – Alaska ✓" and "unit" not in done["decision"]
    with pytest.raises(ReviewInvalid, match="takes text"):
        edit(new(), 5, input_id="grid_region")
    with pytest.raises(ReviewInvalid):
        edit(new(), "bad\nvalue", input_id="grid_region")


def test_an_input_with_no_value_yet_takes_a_number_or_text() -> None:
    assert edit(new(), 12, side="company", input_id="empty")["decision"]["value"] == 12
    assert edit(new(), "x", side="company", input_id="empty")["decision"]["value"] == "x"


def test_bad_side_action_reason_and_document_id() -> None:
    with pytest.raises(ReviewInvalid, match="side"):
        act_input(new(), "revert", side="both")
    with pytest.raises(ReviewInvalid, match="not an action on an input"):
        act_input(new(), "choose")
    with pytest.raises(ReviewInvalid, match="not an action on a choice"):
        act_choice(new(), "edit")
    with pytest.raises(ReviewInvalid, match="at most 500"):
        edit(new(), 1, reason="x" * 501)
    with pytest.raises(ReviewInvalid, match="reason must be text"):
        edit(new(), 1, reason=5)
    with pytest.raises(ReviewInvalid, match="document id"):
        edit(new(), 1, side="company", document_id="D\x00")
    with pytest.raises(ReviewInvalid, match="document id"):
        edit(new(), 1, side="company", document_id="D" * 201)


def test_a_long_history_stays_inside_the_size_limit_and_never_loses_the_last_value() -> None:
    record = new()
    for n in range(80):
        record = edit(record, 1000 + n, reason="r" * 400)
    assert record["decision"]["value"] == 1079 and len(record["history"]) <= 50 and len(record["value_history"]) <= 10
    assert len(json.dumps(record).encode()) <= 32 * 1024


# --- keys, events and what the trace shows ---------------------------------------------------------------

def test_item_keys_fit_the_workpaper_key_rule_for_any_line_key() -> None:
    longest = "s1:" + "a" * 197
    keys = {c.item_key(longest, c.stream_of("input", "activity.total", side), seq)
            for side in c.SIDES for seq in (1, 2, 999)}
    assert len(keys) == 6 and all(ITEM_KEY.match(k) and len(k) <= 200 for k in keys)
    assert c.item_key("a", "s", 1) != c.item_key("b", "s", 1) != c.item_key("a", "t", 1)


def test_clean_id() -> None:
    assert c.clean_id("equation:CO2", "x") == "equation:CO2"
    for bad in ("", "  ", None, 5, "a\x00b", "a\nb", "x" * 201):
        with pytest.raises(ReviewInvalid):
            c.clean_id(bad, "choice id")


def test_decisions_on_lines_that_no_longer_exist_are_kept_and_reported_as_orphaned() -> None:
    def event(line: str, value: str) -> dict:
        record = choose(new(), value)
        return {"line_key": line, "stream": "choice|method|", "target": "choice", "target_id": "method", "side": None,
                "seq": 1, "record": record}

    placed, orphaned = c.split_orphans([event("line-a", "eq3"), event("renamed-old", "eq1")], ["line-a", "line-b"])
    assert [p["line_key"] for p in placed] == ["line-a"] and [o["line_key"] for o in orphaned] == ["renamed-old"]
    assert orphaned[0]["decision"]["value"] == "eq1" and orphaned[0]["decision"]["by"] == "Ann Reviewer"
    assert c.split_orphans([], []) == ([], [])
    assert c.split_orphans([event("line-a", "eq3")], []) == ([], [c.public_event(event("line-a", "eq3"))])


def test_the_trace_shows_decisions_without_moving_any_value() -> None:
    t = trace()
    records = {
        c.stream_of("choice", "method"): choose(new(), "eq3"),
        c.stream_of("input", "activity.total", "recomputed"): edit(new(), 2400),
        c.stream_of("input", "activity.total", "company"): {**new(), "suggestion": {**SUGGESTION, "value": 2380}},
        c.stream_of("input", "activity.total/DOC-1/c1", "recomputed"): edit(new(), 100,
                                                                          input_id="activity.total/DOC-1/c1"),
        c.stream_of("input", "empty", "company"): edit(new(), 7, side="company", input_id="empty"),
        c.stream_of("input", "gone", "company"): edit(new(), 7, side="company"),  # not in this trace: ignored
    }
    shown = c.with_decisions(t, records)
    assert shown["choices"][0]["decision"]["value"] == "eq3" and shown["choices"][0]["chosen"] == "eq1"
    total = shown["inputs"]["activity.total"]
    assert total["recomputed"]["decision"]["value"] == 2400 and total["recomputed"]["value"] == 2350.0
    assert total["recomputed"]["decision"]["by"] == "Ann Reviewer" and total["recomputed"]["status"] == "accepted"
    assert total["company"]["suggestion"]["request_id"] == "r1" and "decision" not in total["company"]
    assert total["rows"][0]["recomputed"]["decision"]["value"] == 100
    assert shown["inputs"]["empty"]["company"] == {**shown["inputs"]["empty"]["company"], "value": None,
                                                    "status": "not_reported"}
    assert shown["inputs"]["empty"]["company"]["decision"]["value"] == 7
    assert t == trace()  # the input trace is not changed


def test_a_real_trace_with_decisions_still_validates_against_the_schema() -> None:
    lines = [ln for ln in scenarios()["company"]["calculation_lines"] if ln.get("trace")]
    assert lines
    validator = jsonschema.Draft202012Validator(SCHEMA)
    for line in lines:
        t = line["trace"]
        records: dict[str, dict] = {}
        for choice in t["choices"]:
            record = c.decide_choice(new(), choice, "choose", option_id=choice["chosen"], actor=ANN, now=NOW)
            records[c.stream_of("choice", choice["id"])] = record
        for input_id, item in t["inputs"].items():
            found = c.find_input(t, input_id)
            assert found is not None
            unit = (item.get("recomputed") or item.get("company") or {}).get("unit")
            numeric = isinstance((item.get("recomputed") or {}).get("value"), (int, float))
            records[c.stream_of("input", input_id, "recomputed")] = c.decide_input(
                new(), found[0], None, "recomputed", "edit", value=5 if numeric else "text", unit=unit,
                reason="because", document_id="DOC-1", actor=ANN, now=NOW)
        shown = c.with_decisions(t, records)
        validator.validate(shown)
        assert shown["result"] == t["result"] and shown["steps"] == t["steps"]

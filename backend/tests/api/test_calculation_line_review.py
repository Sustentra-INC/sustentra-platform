"""Reviewer decisions on calculation lines through the app: roles, orgs, hostile ids, the actions, the audit trail
and what the trace endpoint shows. The engine runs for real on a fake store; the decision rows live in a list that
behaves like the add-only table (the SQL has its own tests, ``tests/db/test_calc_line_review_db.py``)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient

from backend.app.api import calculation_line_review as review_api
from backend.app.api import engagements as engagements_api
from backend.app.api.s1_access import s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.main import app
from backend.app.services import calc_line_review
from backend.app.services.review_field import ReviewConflict
from backend.tests.api.conftest import ORG_A, ORG_B
from backend.tests.api.test_recalculation import ENGAGEMENT, wired  # noqa: F401 - the fixture
from backend.tests.services.test_engagement_recalculation_service import FakeStore

BASE = "/v1/engagements/ENG-1/calculation-lines"


class Rows:
    """The add-only table: events appended, the highest ``seq`` of a stream is current."""

    status: dict[str, str]

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []

    async def current(self, db: Any, engagement_id: Any, line_key: str | None = None) -> list[dict[str, Any]]:
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for e in self.events:
            if line_key is None or e["line_key"] == line_key:
                latest[(e["line_key"], e["stream"])] = e
        return list(latest.values())

    async def append(self, db: Any, **kw: Any) -> dict[str, Any]:
        seq = kw["previous_seq"] + 1
        if any(e["line_key"] == kw["line_key"] and e["stream"] == kw["stream"] and e["seq"] == seq
               for e in self.events):
            raise ReviewConflict("This decision was changed by someone else a moment ago.")
        event = {k: kw[k] for k in ("line_key", "stream", "target", "target_id", "side", "record")} | {"seq": seq}
        self.events.append(event)
        return event

    async def lock(self, *args: Any) -> None:
        return None

    async def audit_event(self, db: Any, event_type: str, **kw: Any) -> None:
        self.audit.append({"event_type": event_type, **kw})


@pytest.fixture
def rows(monkeypatch: pytest.MonkeyPatch, wired: FakeStore) -> Rows:  # noqa: F811
    store = Rows()

    async def visible(db: Any, engagement_id: str, user: Any) -> dict[str, Any]:
        if engagement_id != "ENG-1" or (not user.is_provider and user.org_id != ORG_A):
            raise HTTPException(status_code=404, detail="Engagement not found.")
        return {**ENGAGEMENT, "status": "active"}

    status = {"value": "active"}

    async def open_engagement(engagement_id: str, user: CurrentUser = Depends(s1_writer)) -> dict[str, Any]:
        # what ``require_open_engagement`` does (the API tests' autouse override replaces it with a stub)
        row = await visible(None, engagement_id, user)
        if status["value"] != "active":
            raise HTTPException(status_code=409, detail="Engagement is archived.")
        return row

    app.dependency_overrides[engagements_api.require_open_engagement] = open_engagement
    store.status = status
    monkeypatch.setattr(review_api, "_visible", visible)
    monkeypatch.setattr(calc_line_review, "current", store.current)
    monkeypatch.setattr(calc_line_review, "append", store.append)
    monkeypatch.setattr(calc_line_review, "lock", store.lock)
    monkeypatch.setattr(review_api, "write_audit_event", store.audit_event)
    return store


def trace_of(client: TestClient) -> tuple[str, dict[str, Any]]:
    lines = client.get("/v1/engagements/ENG-1/recalculation").json()["calculation_lines"]
    key = lines[0]["key"]
    return key, client.get(f"/v1/engagements/ENG-1/recalculation/lines/{key}/trace").json()["trace"]


def test_choose_the_default_edit_an_input_and_see_both_on_the_trace(act_as, rows: Rows) -> None:  # noqa: ANN001
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, before = trace_of(client)
        choice = before["choices"][0]
        assert "decision" not in choice
        chosen = client.post(f"{BASE}/{key}/choices/{choice['id']}",
                             json={"action": "choose", "option_id": choice["chosen"]})
        assert chosen.status_code == 200, chosen.text
        assert chosen.json()["decision"]["status"] == "edited" and chosen.json()["decision"]["by"] == "org_member.aaaaaaaa@example.com"

        unit = before["inputs"]["activity.total"]["recomputed"]["unit"]
        edited = client.post(f"{BASE}/{key}/inputs/activity.total/recomputed",
                             json={"action": "edit", "value": 1300, "unit": unit, "reason": "Corrected from invoice"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["decision"]["kind"] == "reviewer_entered" and edited.json()["seq"] == 1

        fetched = client.get(f"/v1/engagements/ENG-1/recalculation/lines/{key}/trace").json()
        again = fetched["trace"]
        assert again["choices"][0]["decision"]["value"] == choice["chosen"]
        assert again["inputs"]["activity.total"]["recomputed"]["decision"]["value"] == 1300
        # applied: the recomputed side is worked with the edited activity, the chosen (default) route unchanged
        assert again["inputs"]["activity.total"]["recomputed"]["value"] == 1300
        assert again["inputs"]["activity.total"]["recomputed"]["status"] == "edited"
        old = before["inputs"]["activity.total"]["recomputed"]["value"]
        assert again["result"]["recomputed"] == pytest.approx(before["result"]["recomputed"] * 1300 / old, rel=1e-9)
        assert again["choices"][0]["chosen"] == choice["chosen"] and again["choices"][0]["chosen_by"] == "reviewer"
        assert {(d["id"], d["status"]) for d in fetched["decisions"]["applied"]} == {
            (choice["id"], "edited"), ("activity.total", "edited")}
        # the decision endpoints still check against the automatic working: choosing the default needs no reason
        assert client.post(f"{BASE}/{key}/choices/{choice['id']}",
                           json={"action": "choose", "option_id": choice["chosen"]}).status_code == 200
    assert [a["metadata"]["action"] for a in rows.audit] == ["choose", "edit", "choose"]
    assert all(a["event_type"] == "calc_line_decision" and a["target_id"] == "ENG-1" for a in rows.audit)
    blob = repr(rows.audit)
    assert "Corrected from invoice" not in blob and "1300" not in blob  # never a value or reason


def test_row_inputs_and_revert_and_a_duplicate_submit(act_as, rows: Rows) -> None:  # noqa: ANN001
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, t = trace_of(client)
        row = t["inputs"]["activity.total"]["rows"][0]["id"]
        path = f"{BASE}/{key}/inputs/activity.total/{row}/recomputed"
        body = {"action": "edit", "value": 5, "reason": "typo"}
        assert client.post(path, json=body).status_code == 200
        assert client.post(path, json={**body, "value": 6}).status_code == 200
        reverted = client.post(path, json={"action": "revert"})
        assert reverted.status_code == 200 and reverted.json()["decision"]["value"] == 5
        assert reverted.json()["seq"] == 3
        client.post(path, json={"action": "revert"})  # back to pending
        assert client.post(path, json={"action": "revert"}).status_code == 409  # a double click: already pending
        accepted_twice = f"{BASE}/{key}/inputs/activity.total/company"
        assert client.post(accepted_twice, json={"action": "edit", "value": 7}).status_code == 200
        assert client.post(accepted_twice, json={"action": "accept"}).status_code == 409
        shown = client.get(f"/v1/engagements/ENG-1/recalculation/lines/{key}/trace").json()["trace"]
        assert shown["inputs"]["activity.total"]["rows"][0]["recomputed"]["decision"]["status"] == "pending"
        assert shown["inputs"]["activity.total"]["company"]["decision"]["kind"] == "company_input"


def test_refusals_are_409_and_422_with_sentences_and_write_nothing(act_as, rows: Rows) -> None:  # noqa: ANN001
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, t = trace_of(client)
        choice = t["choices"][0]["id"]
        no_reason = client.post(f"{BASE}/{key}/inputs/activity.total/recomputed", json={"action": "edit", "value": 5})
        assert no_reason.status_code == 422 and "reason is required" in no_reason.json()["detail"]
        assert client.post(f"{BASE}/{key}/choices/{choice}", json={"action": "choose"}).status_code == 422
        unknown_option = client.post(f"{BASE}/{key}/choices/{choice}", json={"action": "choose", "option_id": "zzz",
                                                                              "reason": "x"})
        assert unknown_option.status_code == 422
        nothing = client.post(f"{BASE}/{key}/choices/{choice}", json={"action": "accept"})
        assert nothing.status_code == 409 and "nothing to accept" in nothing.json()["detail"]
        for value in (True, "abc", 1e30, "nan", [1]):
            bad = client.post(f"{BASE}/{key}/inputs/activity.total/recomputed",
                              json={"action": "edit", "value": value, "reason": "r"})
            assert bad.status_code == 422, value
        wrong_unit = client.post(f"{BASE}/{key}/inputs/activity.total/recomputed",
                                 json={"action": "edit", "value": 5, "unit": "furlongs", "reason": "r"})
        assert wrong_unit.status_code == 422 and "enter the value in" in wrong_unit.json()["detail"]
    assert rows.events == [] and rows.audit == []


def test_hostile_ids_and_bodies(act_as, rows: Rows) -> None:  # noqa: ANN001
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, t = trace_of(client)
        choice = t["choices"][0]["id"]
        ok_body = {"action": "revert"}
        # a malformed line key is a 422 (never reaches the engine), a well-formed one the engagement lacks is a 404
        for bad_key in ("has space", "a" * 201, "é", "-leading", ".dot", "a%00b", "semi;colon"):
            assert client.post(f"{BASE}/{bad_key}/choices/{choice}", json=ok_body).status_code == 422, bad_key
            assert client.post(f"{BASE}/{bad_key}/inputs/activity.total/company", json=ok_body).status_code == 422
        assert client.post(f"{BASE}/s1:stationary:nope:none/choices/{choice}", json=ok_body).status_code == 404
        assert client.post(f"{BASE}/{'a' * 200}/choices/{choice}", json=ok_body).status_code == 404
        # ids the line does not have
        assert client.post(f"{BASE}/{key}/choices/nope", json=ok_body).status_code == 404
        assert client.post(f"{BASE}/{key}/choices/{'c' * 500}", json=ok_body).status_code == 422
        assert client.post(f"{BASE}/{key}/choices/%00", json=ok_body).status_code == 422
        assert client.post(f"{BASE}/{key}/inputs/nope/company", json=ok_body).status_code == 404
        assert client.post(f"{BASE}/{key}/inputs/activity.total/not-a-row/company", json=ok_body).status_code == 404
        assert client.post(f"{BASE}/{key}/inputs/activity.total/both", json=ok_body).status_code == 422
        # bodies
        path = f"{BASE}/{key}/choices/{choice}"
        assert client.post(path, json={"action": "choose", "option_id": "x", "extra": 1}).status_code == 422
        assert client.post(path, json={"action": "delete"}).status_code == 422
        assert client.post(path, json={}).status_code == 422
        assert client.post(path, json={"action": "reject", "reason": "r" * 2001}).status_code == 422
        assert client.post(f"{BASE}/{key}/inputs/activity.total/company",
                           json={"action": "edit", "value": 1, "by": "someone else"}).status_code == 422
    assert rows.events == []


def test_roles_orgs_and_sessions(act_as, rows: Rows) -> None:  # noqa: ANN001
    with TestClient(app) as client:
        path = f"{BASE}/x/choices/method"
        inputs = f"{BASE}/x/inputs/activity.total/company"
        act_as("provider_admin")  # support reads, never writes
        assert client.post(path, json={"action": "revert"}).status_code == 403
        assert client.post(inputs, json={"action": "revert"}).status_code == 403
        assert client.get(f"{BASE}/decisions").status_code == 200
        act_as("org_member", ORG_B)  # another org's engagement is a 404, even with a malformed line key
        assert client.post(path, json={"action": "revert"}).status_code == 404
        assert client.post(f"{BASE}/has space/choices/method", json={"action": "revert"}).status_code == 404
        assert client.get(f"{BASE}/decisions").status_code == 404
        act_as(None)
        assert client.post(path, json={"action": "revert"}).status_code == 401
        assert client.get(f"{BASE}/decisions").status_code == 401
    assert rows.events == []


def test_an_archived_engagement_takes_no_decision(act_as, rows: Rows) -> None:  # noqa: ANN001
    rows.status["value"] = "archived"
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        assert client.post(f"{BASE}/x/choices/method", json={"action": "revert"}).status_code == 409


def test_a_decision_on_a_line_that_is_gone_is_kept_and_listed_as_orphaned(act_as, rows: Rows) -> None:  # noqa: ANN001
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, t = trace_of(client)
        path = f"{BASE}/{key}/inputs/activity.total/recomputed"
        assert client.post(path, json={"action": "edit", "value": 9, "reason": "r"}).status_code == 200
        listed = client.get(f"{BASE}/decisions").json()
        assert [d["line_key"] for d in listed["decisions"]] == [key] and listed["orphaned_decisions"] == []
        # the line is renamed: its key changes, the stored decision stays where it was
        rows.events[0]["line_key"] = "s2:purchased_energy:electricity:old-name"
        listed = client.get(f"{BASE}/decisions").json()
        assert listed["decisions"] == []
        [orphan] = listed["orphaned_decisions"]
        assert orphan["line_key"] == "s2:purchased_energy:electricity:old-name" and orphan["decision"]["value"] == 9
        # and it is not shown on, nor applied to, the line that exists now
        shown = client.get(f"/v1/engagements/ENG-1/recalculation/lines/{key}/trace").json()["trace"]
        assert "decision" not in shown["inputs"]["activity.total"]["recomputed"]
        assert shown["result"] == t["result"]
        # the recalculation reports it as orphaned
        report = client.get("/v1/engagements/ENG-1/recalculation").json()["calculation_line_decisions"]
        assert [o["line_key"] for o in report["orphaned"]] == ["s2:purchased_energy:electricity:old-name"]


def test_a_value_that_would_reach_the_arithmetic_is_checked_first(act_as, rows: Rows) -> None:  # noqa: ANN001
    """Zero, a negative value, NaN or infinity as text, or a value in another unit: 422, nothing written. An input set
    for the whole engagement (a GWP, the share, the unit conversion): 409. The company's side may be 0."""

    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, t = trace_of(client)
        unit = t["inputs"]["activity.total"]["recomputed"]["unit"]
        row = t["inputs"]["activity.total"]["rows"][0]["id"]
        for path in (f"{BASE}/{key}/inputs/activity.total/recomputed", f"{BASE}/{key}/inputs/ef.CO2/recomputed",
                     f"{BASE}/{key}/inputs/activity.total/{row}/recomputed"):
            for value in (0, -1, -0.0, "0", "-5", "NaN", "nan", "Infinity", "-inf"):
                bad = client.post(path, json={"action": "edit", "value": value, "reason": "r"})
                assert bad.status_code == 422, (path, value)
                assert "above 0" in bad.json()["detail"] or "between" in bad.json()["detail"], bad.json()
        wrong = client.post(f"{BASE}/{key}/inputs/activity.total/recomputed",
                            json={"action": "edit", "value": 5, "unit": "kWh" if unit != "kWh" else "therm",
                                  "reason": "r"})
        assert wrong.status_code == 422 and "enter the value in" in wrong.json()["detail"]
        for input_id in ("gwp.CO2", "share", "unit_conversion"):
            refused = client.post(f"{BASE}/{key}/inputs/{input_id}/recomputed",
                                  json={"action": "edit", "value": 2, "reason": "r"})
            assert refused.status_code == 409, input_id
            assert "can't be changed for one line" in refused.json()["detail"]
        assert rows.events == [] and rows.audit == []
        # the company's side is never an operand: a company that reported 0 can be recorded as such
        company = client.post(f"{BASE}/{key}/inputs/activity.total/company", json={"action": "edit", "value": 0})
        assert company.status_code == 200, company.text


def test_a_hand_written_row_that_slips_past_the_checks_never_reaches_a_total(act_as, rows: Rows) -> None:  # noqa: ANN001
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        key, t = trace_of(client)
        before = client.get("/v1/engagements/ENG-1/recalculation").json()
        rows.events.append({"line_key": key, "stream": "input|activity.total|recomputed", "target": "input",
                            "target_id": "activity.total", "side": "recomputed", "seq": 1, "record": {"decision": {
                                "status": "edited", "value": -40, "by": {"name": "x"}, "at": "now"}}})
        after = client.get("/v1/engagements/ENG-1/recalculation").json()
        line = next(ln for ln in after["calculation_lines"] if ln["key"] == key)
        assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["invalid_value"]
        assert after["categories"] == before["categories"] and after["scope_totals"] == before["scope_totals"]

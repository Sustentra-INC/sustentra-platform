"""The reviewer queue (Phase D2).

The screen the Sustentra team works: everything waiting on us, oldest first,
with enough context on each item to answer without opening anything else. The
access rule matters as much as the data - a client must never see another
client's questions, and only Sustentra staff see the queue at all.
"""

from __future__ import annotations

import pytest

from intake.tests.conftest import company_payload, site_payload

DATAPOINT = "S1FUG-5.4"
QUESTION = "On-site wastewater treatment or other industrial processes?"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded(client):
    harness = client.harness
    result = harness.seeded_org(sites=1)
    result["site_id"] = harness.sites.list_by_org(result["org_id"])[0]["site_id"]
    result["reviewer"] = harness.reviewer_token(result["org_id"])
    result["client_token"] = harness.sign_in()
    return result


def _open(client, seeded, datapoint: str = DATAPOINT, trigger: str = "condition_met") -> dict:
    return client.harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=datapoint,
        scope_ref=seeded["site_id"],
        trigger=trigger,
        question_label=QUESTION,
        actor_id="usr_1",
        answer_attempts=[{"attempt": 1, "text": "not sure, ask the facilities team"}],
        seed_context={"legal_name": "Northlight Studios Ltd", "trigger_reason": "client asked"},
    )


# -- access -----------------------------------------------------------------


def test_the_queue_needs_a_sign_in(client) -> None:
    assert client.get("/v1/intake/review/queue").status_code == 401


def test_a_client_cannot_open_the_queue(client, seeded) -> None:
    response = client.get("/v1/intake/review/queue", headers=_auth(seeded["client_token"]))
    assert response.status_code == 403
    assert "Sustentra staff" in response.json()["detail"]


def test_a_client_cannot_read_an_escalation(client, seeded) -> None:
    record = _open(client, seeded)
    response = client.get(
        f"/v1/intake/review/escalations/{record['escalation_id']}",
        headers=_auth(seeded["client_token"]),
    )
    assert response.status_code == 403


def test_a_client_cannot_resolve_an_escalation(client, seeded) -> None:
    record = _open(client, seeded)
    response = client.post(
        f"/v1/intake/review/escalations/{record['escalation_id']}/resolve",
        json={"value": {"present": False}},
        headers=_auth(seeded["client_token"]),
    )
    assert response.status_code == 403


# -- the queue --------------------------------------------------------------


def test_an_empty_queue_is_empty(client, seeded) -> None:
    body = client.get("/v1/intake/review/queue", headers=_auth(seeded["reviewer"])).json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["sla_hours"] == client.harness.settings.escalation.sla_hours


def test_the_queue_lists_what_is_waiting(client, seeded) -> None:
    _open(client, seeded)
    body = client.get("/v1/intake/review/queue", headers=_auth(seeded["reviewer"])).json()

    assert body["count"] == 1
    item = body["items"][0]
    assert item["client"] == "Northlight Studios Ltd"
    assert item["site"] == "Stage 1"
    assert item["question"] == QUESTION
    assert item["datapoint_id"] == DATAPOINT
    assert item["why"] == "client asked"


def test_the_queue_is_oldest_first(client, seeded) -> None:
    first = _open(client, seeded, datapoint=DATAPOINT)
    client.harness.clock.advance(hours=1)
    second = _open(client, seeded, datapoint="S1STC-3.1")

    body = client.get("/v1/intake/review/queue", headers=_auth(seeded["reviewer"])).json()
    assert [item["escalation_id"] for item in body["items"]] == [
        first["escalation_id"],
        second["escalation_id"],
    ]


def test_the_queue_shows_the_sla_clock(client, seeded) -> None:
    _open(client, seeded)
    client.harness.clock.advance(hours=3)

    item = client.get(
        "/v1/intake/review/queue", headers=_auth(seeded["reviewer"])
    ).json()["items"][0]
    assert item["hours_open"] == 3.0
    assert item["past_sla"] is False


def test_a_late_question_is_flagged(client, seeded) -> None:
    _open(client, seeded)
    client.harness.clock.advance(hours=client.harness.settings.escalation.sla_hours + 1)

    item = client.get(
        "/v1/intake/review/queue", headers=_auth(seeded["reviewer"])
    ).json()["items"][0]
    assert item["past_sla"] is True


def test_a_reviewer_sees_every_client(client, seeded) -> None:
    """The one place org scoping is deliberately crossed."""
    harness = client.harness
    other = harness.create_org(legal_name="Harbour Post", email="two@example.com")
    other_id = other["org"]["org_id"]
    harness.seed_form_service.submit(
        org_id=other_id,
        submitted_by=other["owner"]["user_id"],
        payload={
            "company": company_payload(legal_name="Harbour Post Ltd"),
            "sites": [site_payload()],
        },
    )
    harness.profile_state_service.initialise(other_id)
    harness.escalation_service.open(
        org_id=other_id,
        datapoint_id=DATAPOINT,
        scope_ref=harness.sites.list_by_org(other_id)[0]["site_id"],
        trigger="condition_met",
        question_label=QUESTION,
        actor_id="usr_2",
    )
    _open(client, seeded)

    body = client.get("/v1/intake/review/queue", headers=_auth(seeded["reviewer"])).json()
    assert {item["client"] for item in body["items"]} == {
        "Northlight Studios Ltd",
        "Harbour Post Ltd",
    }


def test_resolved_questions_leave_the_queue(client, seeded) -> None:
    record = _open(client, seeded)
    client.post(
        f"/v1/intake/review/escalations/{record['escalation_id']}/resolve",
        json={"value": {"present": False}},
        headers=_auth(seeded["reviewer"]),
    )
    body = client.get("/v1/intake/review/queue", headers=_auth(seeded["reviewer"])).json()
    assert body["count"] == 0


# -- one escalation ---------------------------------------------------------


def test_detail_carries_what_is_needed_to_answer(client, seeded) -> None:
    record = _open(client, seeded)
    body = client.get(
        f"/v1/intake/review/escalations/{record['escalation_id']}",
        headers=_auth(seeded["reviewer"]),
    ).json()

    assert body["question"] == QUESTION
    assert body["client"] == "Northlight Studios Ltd"
    assert body["explainer"]  # the plain-language note the client saw
    assert body["attempts"][0]["text"].startswith("not sure")
    assert body["seed_context"]["legal_name"] == "Northlight Studios Ltd"
    assert body["status"] == "pending_auditor_review"
    assert isinstance(body["answer_fields"], list)


def test_detail_shows_the_history_of_the_data_point(client, seeded) -> None:
    record = _open(client, seeded)
    body = client.get(
        f"/v1/intake/review/escalations/{record['escalation_id']}",
        headers=_auth(seeded["reviewer"]),
    ).json()

    transitions = [(entry["from"], entry["to"]) for entry in body["history"]]
    assert ("asked", "escalated") in transitions


def test_an_unknown_escalation_is_a_404(client, seeded) -> None:
    response = client.get(
        "/v1/intake/review/escalations/esc_000000000000",
        headers=_auth(seeded["reviewer"]),
    )
    assert response.status_code == 404


# -- resolving --------------------------------------------------------------


def test_resolving_writes_the_answer_into_the_profile(client, seeded) -> None:
    record = _open(client, seeded)
    response = client.post(
        f"/v1/intake/review/escalations/{record['escalation_id']}/resolve",
        json={"value": {"present": False}, "resolution_note": "Confirmed by phone."},
        headers=_auth(seeded["reviewer"]),
    )
    assert response.status_code == 200
    assert response.json()["queue_count"] == 0

    state = client.harness.state(seeded["org_id"], DATAPOINT, seeded["site_id"])
    assert state["status"] == "resolved"
    assert state["value"] == {"present": False}
    assert state["provenance"]["answered_by"] == "team"


def test_the_resolver_is_recorded_by_name(client, seeded) -> None:
    """Never anonymous: a team answer is attributed like any other."""
    record = _open(client, seeded)
    client.post(
        f"/v1/intake/review/escalations/{record['escalation_id']}/resolve",
        json={"value": {"present": True}},
        headers=_auth(seeded["reviewer"]),
    )
    saved = client.harness.escalations.get(record["escalation_id"])
    assert saved["resolved_by"] == "reviewer@sustentra.com"


def test_resolving_with_no_answer_is_rejected(client, seeded) -> None:
    record = _open(client, seeded)
    response = client.post(
        f"/v1/intake/review/escalations/{record['escalation_id']}/resolve",
        json={"value": {}},
        headers=_auth(seeded["reviewer"]),
    )
    assert response.status_code == 400


def test_resolving_twice_is_rejected(client, seeded) -> None:
    record = _open(client, seeded)
    payload = {"value": {"present": False}}
    url = f"/v1/intake/review/escalations/{record['escalation_id']}/resolve"
    client.post(url, json=payload, headers=_auth(seeded["reviewer"]))

    second = client.post(url, json=payload, headers=_auth(seeded["reviewer"]))
    assert second.status_code == 400


def test_resolving_tells_the_client(client, seeded) -> None:
    record = _open(client, seeded)
    client.post(
        f"/v1/intake/review/escalations/{record['escalation_id']}/resolve",
        json={"value": {"present": False}},
        headers=_auth(seeded["reviewer"]),
    )
    sent = [m for m in client.harness.mailbox.sent if m.template_id == "escalation_resolved"]
    assert len(sent) == 1
    assert sent[0].to == "ada@northlight.example"

"""The two success metrics (Phase F).

SPEC section 2: percentage completed with zero escalations, and median
time-to-complete. These tests are mostly about the two places the metric could
quietly lie - counting a client as finished when questions are still with our
team, and reporting a median off one data point as though it meant something.
"""

from __future__ import annotations

import pytest

STC = "S1STC-3.1"
WASTEWATER = "S1FUG-5.4"


@pytest.fixture
def seeded(harness):
    result = harness.seeded_org(sites=1)
    result["site_id"] = harness.sites.list_by_org(result["org_id"])[0]["site_id"]
    return result


def _sign_in(harness, email: str = "owner@example.com") -> None:
    """Give the org a session, which is what starts the clock."""
    harness.sign_in(email)


def _settle_everything(harness, org_id: str) -> None:
    """Answer every applicable question the blunt way."""
    for state in harness.interview_engine.applicable_states(org_id):
        current = harness.state(org_id, state["datapoint_id"], state.get("scope_ref"))
        if current["status"] in {"answered", "not_present", "resolved"}:
            continue
        if current["status"] == "unasked":
            current = harness.state_machine.mark_asked(current, actor_id="usr_1")
        if current["status"] == "escalated":
            continue
        harness.state_machine.record_answer(
            current, value={"present": False}, actor_id="usr_1"
        )


def _escalate(harness, seeded, datapoint: str, trigger: str) -> dict:
    return harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=datapoint,
        scope_ref=seeded["site_id"],
        trigger=trigger,
        question_label="A question",
        actor_id="usr_1",
    )


# -- starting ---------------------------------------------------------------


def test_a_client_who_never_signed_in_has_not_started(harness) -> None:
    """Creating a company internally is not the client starting."""
    created = harness.create_org()
    journey = harness.metrics_service.journey(created["org"]["org_id"])
    assert journey["started_at"] is None
    assert journey["is_complete"] is False


def test_the_clock_starts_at_first_sign_in(harness, seeded) -> None:
    _sign_in(harness)
    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["started_at"] is not None


def test_an_unknown_company_has_no_journey(harness) -> None:
    assert harness.metrics_service.journey("org_000000000000") is None


# -- completing -------------------------------------------------------------


def test_a_client_part_way_through_is_not_complete(harness, seeded) -> None:
    _sign_in(harness)
    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["is_complete"] is False
    assert journey["still_open"] > 0
    assert journey["hours_to_complete"] is None


def test_answering_everything_completes_the_profile(harness, seeded) -> None:
    _sign_in(harness)
    harness.clock.advance(hours=3)
    _settle_everything(harness, seeded["org_id"])

    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["is_complete"] is True
    assert journey["still_open"] == 0
    assert journey["hours_to_complete"] == 3.0


def test_a_question_still_with_the_team_means_not_complete(harness, seeded) -> None:
    """The founder's definition: complete means actually resolved.

    A client who answered everything but has a question sitting with us is not
    finished - not for the inventory, which is what this measures.
    """
    _sign_in(harness)
    _settle_everything(harness, seeded["org_id"])
    _escalate(harness, seeded, WASTEWATER, "user_requested_help")

    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["is_complete"] is False
    assert journey["escalations_open"] == 1


def test_resolving_the_last_question_completes_it(harness, seeded) -> None:
    _sign_in(harness)
    record = _escalate(harness, seeded, WASTEWATER, "user_requested_help")
    _settle_everything(harness, seeded["org_id"])
    assert harness.metrics_service.journey(seeded["org_id"])["is_complete"] is False

    harness.clock.advance(hours=5)
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="reviewer@sustentra.com"
    )
    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["is_complete"] is True


def test_time_to_complete_includes_our_turnaround(harness, seeded) -> None:
    """A consequence of the founder's definition, stated out loud."""
    _sign_in(harness)
    record = _escalate(harness, seeded, WASTEWATER, "user_requested_help")
    _settle_everything(harness, seeded["org_id"])

    harness.clock.advance(hours=20)  # the team takes its time
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="reviewer@sustentra.com"
    )
    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["hours_to_complete"] == 20.0
    assert any("Sustentra team" in note for note in harness.metrics_service.summary()["caveats"])


# -- stuck vs routine -------------------------------------------------------


def test_a_routine_confirmation_is_not_being_stuck(harness, seeded) -> None:
    """Every boundary answer escalates by design; that is not a failure."""
    _sign_in(harness)
    _escalate(harness, seeded, STC, "human_class_datapoint")

    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["escalations_routine"] == 1
    assert journey["escalations_stuck"] == 0
    assert journey["got_stuck"] is False


@pytest.mark.parametrize(
    "trigger", ["contradiction", "failed_clarification", "user_requested_help"]
)
def test_these_triggers_mean_the_client_was_stuck(harness, seeded, trigger: str) -> None:
    _sign_in(harness)
    _escalate(harness, seeded, STC, trigger)

    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["escalations_stuck"] == 1
    assert journey["got_stuck"] is True


def test_which_triggers_count_as_stuck_is_config(harness, seeded) -> None:
    harness.settings.metrics.stuck_triggers = ["human_class_datapoint"]
    _sign_in(harness)
    _escalate(harness, seeded, STC, "human_class_datapoint")

    assert harness.metrics_service.journey(seeded["org_id"])["got_stuck"] is True


# -- the summary ------------------------------------------------------------


def test_an_empty_platform_reports_nothing_rather_than_zero(harness) -> None:
    """"No clients yet" and "no clients succeeded" must not read the same."""
    summary = harness.metrics_service.summary()
    assert summary["clients_total"] == 0
    assert summary["completion_rate"] is None
    assert summary["median_hours_to_complete"] is None
    assert any("nothing to average" in note for note in summary["caveats"])


def test_both_numbers_are_reported(harness, seeded) -> None:
    """The literal metric, and the one that measures onboarding."""
    _sign_in(harness)
    _escalate(harness, seeded, STC, "human_class_datapoint")
    _settle_everything(harness, seeded["org_id"])
    harness.escalation_service.resolve(
        harness.escalations.list_open(seeded["org_id"])[0]["escalation_id"],
        value={"present": False},
        actor_id="reviewer@sustentra.com",
    )

    summary = harness.metrics_service.summary()
    assert summary["clients_complete"] == 1
    # They generated a routine confirmation, so the literal metric reads 0%...
    assert summary["zero_escalation_rate"] == 0.0
    # ...while the useful one correctly reads 100%: they never got stuck.
    assert summary["no_stuck_rate"] == 100.0


def test_a_median_off_one_client_is_flagged_as_meaningless(harness, seeded) -> None:
    _sign_in(harness)
    harness.clock.advance(hours=2)
    _settle_everything(harness, seeded["org_id"])

    summary = harness.metrics_service.summary()
    assert summary["sample_size"] == 1
    assert summary["enough_data"] is False
    assert any("mean anything" in note for note in summary["caveats"])
    # The number is still reported - flagged, not hidden.
    assert summary["median_hours_to_complete"] == 2.0


def test_the_median_is_a_median_not_an_average(harness) -> None:
    """One client who wanders off for a fortnight must not move the number."""
    from intake.tests.conftest import company_payload, site_payload

    durations = [1, 2, 400]
    for index, hours in enumerate(durations):
        created = harness.create_org(
            legal_name=f"Client {index}", email=f"owner{index}@example.com"
        )
        org_id = created["org"]["org_id"]
        harness.seed_form_service.submit(
            org_id=org_id,
            submitted_by=created["owner"]["user_id"],
            payload={"company": company_payload(), "sites": [site_payload()]},
        )
        harness.profile_state_service.initialise(org_id)
        harness.sign_in(f"owner{index}@example.com")
        harness.clock.advance(hours=hours)
        _settle_everything(harness, org_id)

    summary = harness.metrics_service.summary()
    assert summary["clients_complete"] == 3
    # The median sits with the typical client, not with the outlier.
    assert summary["median_hours_to_complete"] < 100
    assert summary["slowest_hours"] >= 400


def test_every_client_is_listed_so_you_can_see_who_is_stuck(harness, seeded) -> None:
    _sign_in(harness)
    summary = harness.metrics_service.summary()
    assert [item["legal_name"] for item in summary["clients"]] == ["Northlight Studios Ltd"]


# -- over the API -----------------------------------------------------------


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_metrics_need_a_sign_in(client) -> None:
    assert client.get("/v1/intake/metrics").status_code == 401


def test_a_client_cannot_read_the_metrics(client) -> None:
    harness = client.harness
    harness.seeded_org(sites=1)
    token = harness.sign_in()

    response = client.get("/v1/intake/metrics", headers=_auth(token))
    assert response.status_code == 403
    assert "Sustentra staff" in response.json()["detail"]


def test_a_reviewer_reads_the_metrics(client) -> None:
    harness = client.harness
    seeded = harness.seeded_org(sites=1)
    token = harness.reviewer_token(seeded["org_id"])

    body = client.get("/v1/intake/metrics", headers=_auth(token)).json()
    assert "median_hours_to_complete" in body
    assert body["clients_total"] >= 1


def test_one_client_journey_over_the_api(client) -> None:
    harness = client.harness
    seeded = harness.seeded_org(sites=1)
    token = harness.reviewer_token(seeded["org_id"])

    body = client.get(
        f"/v1/intake/metrics/orgs/{seeded['org_id']}", headers=_auth(token)
    ).json()
    assert body["legal_name"] == "Northlight Studios Ltd"


def test_an_unknown_company_is_a_404(client) -> None:
    harness = client.harness
    seeded = harness.seeded_org(sites=1)
    token = harness.reviewer_token(seeded["org_id"])

    response = client.get(
        "/v1/intake/metrics/orgs/org_000000000000", headers=_auth(token)
    )
    assert response.status_code == 404


def test_a_settled_state_with_an_escalation_still_open_is_not_complete(
    harness, seeded
) -> None:
    """Guards against the two records drifting apart.

    Normally impossible: the state machine only lets an escalated point move to
    resolved. But if the escalation record were ever left open while the state
    settled, reporting that client as finished would hide a question still
    sitting with our team. So the drift is constructed here on purpose - the
    state is settled properly, through the state machine, and only the
    escalation record is put back into the open state behind its back.
    """
    _sign_in(harness)
    record = _escalate(harness, seeded, WASTEWATER, "user_requested_help")
    _settle_everything(harness, seeded["org_id"])
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="reviewer@sustentra.com"
    )
    # Everything is genuinely finished at this point.
    assert harness.metrics_service.journey(seeded["org_id"])["is_complete"] is True

    # Now the drift: the answer stays settled and audited, the ticket reopens.
    harness.escalations.save(
        {**harness.escalations.get(record["escalation_id"]), "status": "pending_auditor_review"}
    )

    journey = harness.metrics_service.journey(seeded["org_id"])
    assert journey["is_complete"] is False
    assert journey["escalations_open"] == 1

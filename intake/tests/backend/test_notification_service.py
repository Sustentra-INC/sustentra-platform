"""Escalation emails (Phase D2).

Covers the three things SPEC section 3 asks for - a notice when an escalation
opens, a reminder while it stays open, a note to the client when it is answered
- plus the founder-approved batching rule: routine confirmations are digested,
anything that means a client is stuck goes out immediately.
"""

from __future__ import annotations

import pytest

from intake.tests.conftest import company_payload, site_payload

DATAPOINT = "S1FUG-5.4"
QUESTION = "On-site wastewater treatment or other industrial processes?"


@pytest.fixture
def seeded(harness):
    result = harness.seeded_org(sites=1)
    result["site_id"] = harness.sites.list_by_org(result["org_id"])[0]["site_id"]
    return result


def _open(harness, seeded, trigger: str = "condition_met", datapoint: str = DATAPOINT) -> dict:
    return harness.escalation_service.open(
        org_id=seeded["org_id"],
        datapoint_id=datapoint,
        scope_ref=seeded["site_id"],
        trigger=trigger,
        question_label=QUESTION,
        actor_id="usr_1",
        answer_attempts=[{"attempt": 1, "text": "not sure"}],
        seed_context={"legal_name": "Northlight Studios Ltd"},
    )


def _to_team(harness, template_id: str) -> list:
    return [
        message
        for message in harness.mailbox.sent
        if message.template_id == template_id
    ]


# -- addresses --------------------------------------------------------------


def test_both_named_contacts_are_notified(harness) -> None:
    """SPEC section 11 names two people; neither is hardcoded."""
    assert harness.notification_service.team_addresses == [
        harness.settings.escalation.primary_email,
        harness.settings.escalation.secondary_email,
    ]


def test_addresses_come_from_config(harness, seeded) -> None:
    harness.settings.escalation.primary_email = "someone@example.com"
    _open(harness, seeded, trigger="contradiction")
    recipients = {message.to for message in _to_team(harness, "escalation_urgent")}
    assert "someone@example.com" in recipients


# -- urgent vs batched ------------------------------------------------------


@pytest.mark.parametrize(
    "trigger", ["contradiction", "failed_clarification", "user_requested_help"]
)
def test_a_stuck_client_is_emailed_immediately(harness, seeded, trigger: str) -> None:
    record = _open(harness, seeded, trigger=trigger)
    urgent = _to_team(harness, "escalation_urgent")
    assert len(urgent) == 2  # one per team address
    assert harness.escalations.get(record["escalation_id"])["notified_at"]


def test_a_routine_confirmation_waits_for_the_digest(harness, seeded) -> None:
    """The batching rule: boundary confirmations must not bury the real ones."""
    record = _open(harness, seeded, trigger="human_class_datapoint")
    assert _to_team(harness, "escalation_urgent") == []
    assert harness.escalations.get(record["escalation_id"])["notified_at"] is None


def test_the_urgent_email_says_what_the_client_tried(harness, seeded) -> None:
    _open(harness, seeded, trigger="user_requested_help")
    body = _to_team(harness, "escalation_urgent")[0].body
    assert "not sure" in body
    assert QUESTION in body
    assert "Stage 1" in body  # the site, so nobody has to look it up
    assert str(harness.settings.escalation.sla_hours) in body


# -- digests ----------------------------------------------------------------


def test_one_digest_per_client_covers_every_waiting_question(harness, seeded) -> None:
    _open(harness, seeded, trigger="human_class_datapoint", datapoint=DATAPOINT)
    _open(harness, seeded, trigger="condition_met", datapoint="S1STC-3.1")

    sent = harness.notification_service.send_pending_digests()
    assert sent == [{"org_id": seeded["org_id"], "count": 2}]

    digests = _to_team(harness, "escalation_digest")
    assert len(digests) == 2  # two addresses, one digest each
    assert "2 question(s)" in digests[0].subject
    assert digests[0].body.count(QUESTION) >= 1


def test_each_client_gets_their_own_digest(harness) -> None:
    first = harness.seeded_org(sites=1)
    first["site_id"] = harness.sites.list_by_org(first["org_id"])[0]["site_id"]
    second = harness.create_org(legal_name="Harbour Post", email="two@example.com")
    harness.seed_form_service.submit(
        org_id=second["org"]["org_id"],
        submitted_by=second["owner"]["user_id"],
        payload={
            "company": company_payload(legal_name="Harbour Post Ltd"),
            "sites": [site_payload()],
        },
    )
    harness.profile_state_service.initialise(second["org"]["org_id"])
    second_site = harness.sites.list_by_org(second["org"]["org_id"])[0]["site_id"]

    _open(harness, first, trigger="human_class_datapoint")
    harness.escalation_service.open(
        org_id=second["org"]["org_id"],
        datapoint_id=DATAPOINT,
        scope_ref=second_site,
        trigger="human_class_datapoint",
        question_label=QUESTION,
        actor_id="usr_2",
    )

    sent = harness.notification_service.send_pending_digests()
    assert {item["org_id"] for item in sent} == {
        first["org_id"],
        second["org"]["org_id"],
    }
    subjects = {message.subject for message in _to_team(harness, "escalation_digest")}
    assert any("Northlight" in subject for subject in subjects)
    assert any("Harbour Post" in subject for subject in subjects)


def test_a_digest_is_not_sent_twice(harness, seeded) -> None:
    _open(harness, seeded, trigger="human_class_datapoint")
    harness.notification_service.send_pending_digests()
    before = len(harness.mailbox.sent)

    assert harness.notification_service.send_pending_digests() == []
    assert len(harness.mailbox.sent) == before


def test_an_already_emailed_urgent_is_left_out_of_the_digest(harness, seeded) -> None:
    _open(harness, seeded, trigger="contradiction", datapoint=DATAPOINT)
    _open(harness, seeded, trigger="human_class_datapoint", datapoint="S1STC-3.1")

    sent = harness.notification_service.send_pending_digests()
    assert sent == [{"org_id": seeded["org_id"], "count": 1}]


def test_resolved_escalations_are_not_digested(harness, seeded) -> None:
    record = _open(harness, seeded, trigger="human_class_datapoint")
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    assert harness.notification_service.send_pending_digests() == []


# -- reminders --------------------------------------------------------------


def test_nothing_is_reminded_before_the_window(harness, seeded) -> None:
    _open(harness, seeded, trigger="human_class_datapoint")
    harness.clock.advance(hours=harness.settings.escalation.reminder_hours - 1)
    assert harness.notification_service.send_due_reminders() == []


def test_a_reminder_goes_out_after_the_window(harness, seeded) -> None:
    record = _open(harness, seeded, trigger="human_class_datapoint")
    harness.clock.advance(hours=harness.settings.escalation.reminder_hours)

    sent = harness.notification_service.send_due_reminders()
    assert sent == [{"org_id": seeded["org_id"], "count": 1}]
    reminder = _to_team(harness, "escalation_reminder")[0]
    assert "12" in reminder.subject
    assert harness.escalations.get(record["escalation_id"])["reminded_at"]


def test_running_the_reminder_job_twice_sends_one_reminder(harness, seeded) -> None:
    """Idempotent, so an overlapping cron run is harmless."""
    _open(harness, seeded, trigger="human_class_datapoint")
    harness.clock.advance(hours=13)
    harness.notification_service.send_due_reminders()
    before = len(harness.mailbox.sent)

    assert harness.notification_service.send_due_reminders() == []
    assert len(harness.mailbox.sent) == before


def test_a_resolved_escalation_is_never_reminded_about(harness, seeded) -> None:
    record = _open(harness, seeded, trigger="human_class_datapoint")
    harness.escalation_service.resolve(
        record["escalation_id"], value={"present": False}, actor_id="rev_1"
    )
    harness.clock.advance(hours=48)
    assert harness.notification_service.send_due_reminders() == []


def test_the_reminder_window_is_config(harness, seeded) -> None:
    harness.settings.escalation.reminder_hours = 2
    _open(harness, seeded, trigger="human_class_datapoint")
    harness.clock.advance(hours=3)
    assert harness.notification_service.send_due_reminders()


# -- telling the client -----------------------------------------------------


def test_the_client_is_told_when_their_question_is_answered(harness, seeded) -> None:
    record = _open(harness, seeded, trigger="user_requested_help")
    harness.escalation_service.resolve(
        record["escalation_id"],
        value={"present": False},
        actor_id="rev_1",
        resolution_note="No process sources; confirmed by phone.",
    )

    resolved = [m for m in harness.mailbox.sent if m.template_id == "escalation_resolved"]
    assert len(resolved) == 1
    assert resolved[0].to == "ada@northlight.example"  # the responsible party
    assert QUESTION in resolved[0].body
    assert "confirmed by phone" in resolved[0].body


def test_no_client_email_without_a_responsible_party(harness, seeded) -> None:
    """Never guess an address: say nothing rather than mail the wrong person."""
    org = dict(harness.orgs.get(seeded["org_id"]))
    org["responsible_party"] = {}
    harness.orgs.save(org)

    record = _open(harness, seeded, trigger="human_class_datapoint")
    result = harness.notification_service.notify_resolved(
        harness.escalation_service.resolve(
            record["escalation_id"], value={"present": False}, actor_id="rev_1"
        )
    )
    assert result["sent"] is False


# -- the scheduled command --------------------------------------------------


def test_a_dry_run_does_not_swallow_the_real_emails(harness, seeded) -> None:
    """A dry run that stamped notified_at would silently lose the digest."""
    from intake.scripts.send_escalation_notices import _ReadOnlyNotifier

    record = _open(harness, seeded, trigger="human_class_datapoint")
    preview = _ReadOnlyNotifier(
        escalation_repository=harness.escalations,
        org_repository=harness.orgs,
        site_repository=harness.sites,
        email_service=harness.email_service,
        settings=harness.settings,
        clock=harness.clock,
    )
    assert preview.send_pending_digests() == [{"org_id": seeded["org_id"], "count": 1}]
    assert harness.escalations.get(record["escalation_id"])["notified_at"] is None

    # The real run still has it to send.
    assert harness.notification_service.send_pending_digests() == [
        {"org_id": seeded["org_id"], "count": 1}
    ]

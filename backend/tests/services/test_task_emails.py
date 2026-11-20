"""The task emails say who did what and link to the app. Nothing about the work is in them."""

from __future__ import annotations

from backend.app.services import otp_delivery
from backend.app.services.otp_delivery import MAX_SUBJECT_CHARS, render_email

ASSIGNED = {
    "email_subject": "Debo Okafor assigned you a task in Sustentra", "requested_by": "Debo Okafor",
    "link": "https://app.sustentra.test/org/acme/tasks", "sender_name": "Sustentra Team",
}


def test_assigned_email_says_who_and_links_to_the_app() -> None:
    mail = render_email("task_assigned", ASSIGNED)
    assert mail.subject == "Debo Okafor assigned you a task in Sustentra"
    for body in (mail.text_body, mail.html_body):
        assert "Debo Okafor assigned you a task in Sustentra." in body
        assert "https://app.sustentra.test/org/acme/tasks" in body
    assert "Sign in to see the details" in mail.text_body and "Sign in to see the details" in mail.html_body


def test_a_name_is_escaped_in_html_and_non_ascii_names_render() -> None:
    mail = render_email("task_assigned", {**ASSIGNED, "requested_by": "Zoë <b>排放</b>"})
    assert "Zoë <b>排放</b>" in mail.text_body
    assert "<b>排放</b>" not in mail.html_body and "&lt;b&gt;" in mail.html_body


def test_completed_email_differs_for_the_requester_and_for_admins() -> None:
    base = {"email_subject": "x", "completed_by": "Vivian Reyes", "link": "https://app.sustentra.test/org/acme/tasks",
            "sender_name": "Sustentra Team"}
    mine = render_email("task_completed", {**base, "requested_by_you": True})
    other = render_email("task_completed", {**base, "requested_by_you": False})
    assert "Vivian Reyes completed a task you requested in Sustentra." in mine.text_body
    assert "Vivian Reyes completed a task in Sustentra." in other.text_body
    assert "you requested" not in other.html_body and "you requested" in mine.html_body


def test_templates_take_no_task_details() -> None:
    """Even if a caller passed them, the templates would not print a title, engagement, note or due date."""
    leaky = {**ASSIGNED, "title": "TITLE-X", "engagement": "ENG-X", "note": "NOTE-X", "due_date": "DUE-X"}
    for name, extra in (("task_assigned", {}), ("task_completed", {"completed_by": "V", "requested_by_you": True})):
        mail = render_email(name, {**leaky, **extra})
        for body in (mail.subject, mail.text_body, mail.html_body):
            assert not any(x in body for x in ("TITLE-X", "ENG-X", "NOTE-X", "DUE-X"))


def test_subject_is_one_clipped_line_and_defaults_when_missing() -> None:
    mail = render_email("task_assigned", {**ASSIGNED, "email_subject": "a\r\nBcc: x@evil.test\t" + "z" * 400})
    assert "\n" not in mail.subject and "\r" not in mail.subject and len(mail.subject) <= MAX_SUBJECT_CHARS
    assert render_email("task_assigned", {k: v for k, v in ASSIGNED.items() if k != "email_subject"}).subject == (
        "A task was assigned to you in Sustentra")


def test_deliver_task_email_reports_failure_without_raising(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("down")

    monkeypatch.setattr(otp_delivery, "send_email", boom)
    assert otp_delivery.deliver_task_email("task_assigned", "a@b.test", ASSIGNED) is False
    monkeypatch.setattr(otp_delivery, "send_email", lambda *_a, **_k: None)
    assert otp_delivery.deliver_task_email("task_assigned", "a@b.test", ASSIGNED) is True

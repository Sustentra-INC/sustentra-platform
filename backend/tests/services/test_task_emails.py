"""The task emails render for any title, name and engagement, and never carry more than they should."""

from __future__ import annotations

from backend.app.services import otp_delivery
from backend.app.services.otp_delivery import MAX_SUBJECT_CHARS, render_email

ASSIGNED = {
    "email_subject": "Debo Okafor assigned you a task: Überprüfen 排放", "title": "Überprüfen <b>排放</b> & “quotes”",
    "requested_by": "Debo Okafor", "engagement": "FY25 Footprint", "due_date": "1 Dec 2026",
    "link": "https://app.sustentra.test/org/acme/evidence?doc=d1&line=2", "sender_name": "Sustentra Team",
}


def test_assigned_email_has_title_who_engagement_due_and_link() -> None:
    mail = render_email("task_assigned", ASSIGNED)
    assert mail.subject == "Debo Okafor assigned you a task: Überprüfen 排放"
    for body in (mail.text_body, mail.html_body):
        assert "Debo Okafor" in body and "FY25 Footprint" in body and "1 Dec 2026" in body
        assert "https://app.sustentra.test/org/acme/evidence?doc=d1" in body
    assert "Open in Sustentra" in mail.text_body and "Open in Sustentra" in mail.html_body
    assert "Überprüfen <b>排放</b>" in mail.text_body
    assert "<b>排放</b>" not in mail.html_body and "&lt;b&gt;" in mail.html_body  # HTML-escaped, not injected


def test_assigned_email_without_engagement_or_due_date_skips_those_lines() -> None:
    mail = render_email("task_assigned", {**ASSIGNED, "engagement": None, "due_date": ""})
    assert "Engagement" not in mail.text_body and "Due" not in mail.text_body


def test_completed_email() -> None:
    mail = render_email("task_completed", {
        "email_subject": "Vivian Reyes completed a task: x", "title": "x", "completed_by": "Vivian Reyes",
        "requested_by": "Debo Okafor", "engagement": None, "link": "https://app.sustentra.test/org/acme/tasks",
        "sender_name": "Sustentra Team"})
    assert mail.subject == "Vivian Reyes completed a task: x"
    assert "Vivian Reyes" in mail.text_body and "Debo Okafor" in mail.text_body and "Open in Sustentra" in mail.html_body


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

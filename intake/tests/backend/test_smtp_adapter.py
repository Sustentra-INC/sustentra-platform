"""The SMTP sender (Phase D2).

The first adapter here that can reach a real person, so these tests are mostly
about it staying off: nothing is sent unless someone deliberately configures a
host, and credentials never come from a config file.

No test opens a socket - ``smtplib.SMTP`` is replaced with a recorder.
"""

from __future__ import annotations

import pytest

from intake.backend.adapters import smtp_email
from intake.backend.adapters.smtp_email import SmtpEmailSender
from intake.backend.config import load_settings
from intake.backend.services.email_service import EmailMessage, build_sender


class FakeSMTP:
    """Records what would have gone over the wire."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args: tuple | None = None
        self.messages: list = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username, password) -> None:
        self.login_args = (username, password)

    def send_message(self, mime) -> None:
        self.messages.append(mime)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtp_email.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _message() -> EmailMessage:
    return EmailMessage(
        to="vivian@sustentra.com",
        from_address="no-reply@sustentra.com",
        subject="Needs a look",
        body="One question is waiting.",
        template_id="escalation_urgent",
        created_at="2026-08-13T09:00:00+00:00",
    )


# -- staying off ------------------------------------------------------------


def test_the_default_adapter_is_still_the_local_outbox() -> None:
    """Shipping SMTP must not switch it on."""
    from intake.backend.services.email_service import OutboxEmailSender

    assert load_settings().email.adapter == "outbox"
    assert isinstance(build_sender(), OutboxEmailSender)


def test_smtp_refuses_to_start_without_a_host() -> None:
    with pytest.raises(ValueError) as error:
        SmtpEmailSender(host="")
    assert "outbox" in str(error.value)  # tells you how to stay safe


def test_selecting_smtp_without_a_host_fails_loudly() -> None:
    settings = load_settings().model_copy(deep=True)
    settings.email.adapter = "smtp"
    settings.email.smtp_host = ""
    with pytest.raises(ValueError):
        build_sender(settings)


def test_an_unknown_adapter_is_rejected() -> None:
    settings = load_settings().model_copy(deep=True)
    settings.email.adapter = "sendgrid"
    with pytest.raises(ValueError):
        build_sender(settings)


# -- sending ----------------------------------------------------------------


def test_a_configured_host_is_used(smtp) -> None:
    settings = load_settings().model_copy(deep=True)
    settings.email.adapter = "smtp"
    settings.email.smtp_host = "mail.example.com"
    settings.email.smtp_port = 2525

    result = build_sender(settings).send(_message())
    assert result == {
        "delivery": "smtp",
        "to": "vivian@sustentra.com",
        "host": "mail.example.com",
    }
    server = smtp.instances[0]
    assert (server.host, server.port) == ("mail.example.com", 2525)
    assert server.messages[0]["Subject"] == "Needs a look"
    assert server.messages[0]["To"] == "vivian@sustentra.com"


def test_tls_is_on_by_default(smtp) -> None:
    SmtpEmailSender(host="mail.example.com").send(_message())
    assert smtp.instances[0].started_tls is True


def test_tls_can_be_turned_off_for_a_local_relay(smtp) -> None:
    SmtpEmailSender(host="localhost", port=25, use_tls=False).send(_message())
    assert smtp.instances[0].started_tls is False


# -- credentials ------------------------------------------------------------


def test_credentials_come_from_the_environment(smtp, monkeypatch) -> None:
    monkeypatch.setenv(smtp_email.USERNAME_ENV, "postmaster")
    monkeypatch.setenv(smtp_email.PASSWORD_ENV, "s3cret")

    SmtpEmailSender(host="mail.example.com").send(_message())
    assert smtp.instances[0].login_args == ("postmaster", "s3cret")


def test_no_credentials_means_no_login(smtp, monkeypatch) -> None:
    """Local relays need none, and a half-set credential must not be sent."""
    monkeypatch.delenv(smtp_email.USERNAME_ENV, raising=False)
    monkeypatch.delenv(smtp_email.PASSWORD_ENV, raising=False)

    SmtpEmailSender(host="mail.example.com").send(_message())
    assert smtp.instances[0].login_args is None


def test_a_username_with_no_password_does_not_log_in(smtp, monkeypatch) -> None:
    monkeypatch.setenv(smtp_email.USERNAME_ENV, "postmaster")
    monkeypatch.delenv(smtp_email.PASSWORD_ENV, raising=False)

    SmtpEmailSender(host="mail.example.com").send(_message())
    assert smtp.instances[0].login_args is None


def test_no_credential_is_ever_read_from_config() -> None:
    """Passwords belong in the environment; the config file must not carry one."""
    import json
    from pathlib import Path

    raw = json.loads(
        Path("intake/config/intake_settings.json").read_text(encoding="utf-8")
    )
    keys = " ".join(raw["email"].keys()).lower()
    assert "password" not in keys
    assert "username" not in keys

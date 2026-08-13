"""SMTP sender for the email port (Phase D2).

The first adapter in this repo that can reach a real person, so it is switched
off unless deliberately configured: ``email.adapter`` stays ``outbox`` by
default, and this adapter refuses to construct without a host.

Credentials come from the environment, never from a config file: ``INTAKE_SMTP_
USERNAME`` and ``INTAKE_SMTP_PASSWORD``. A host with no credentials is allowed,
since local relays and some internal gateways need none.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage as MimeMessage
from typing import Any

from intake.backend.services.email_service import EmailMessage, EmailSender

USERNAME_ENV = "INTAKE_SMTP_USERNAME"
PASSWORD_ENV = "INTAKE_SMTP_PASSWORD"


class SmtpEmailSender(EmailSender):
    """Delivers over SMTP. Raises rather than silently dropping a message."""

    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int = 587,
        use_tls: bool = True,
        timeout_seconds: int = 20,
    ) -> None:
        if not host:
            raise ValueError(
                "SMTP is selected but no host is set. Set INTAKE_SMTP_HOST, or leave "
                "email.adapter as 'outbox' to keep writing messages to a local file."
            )
        self._host = host
        self._port = port
        self._use_tls = use_tls
        self._timeout = timeout_seconds

    def send(self, message: EmailMessage) -> dict[str, Any]:
        mime = MimeMessage()
        mime["To"] = message.to
        mime["From"] = message.from_address
        mime["Subject"] = message.subject
        mime.set_content(message.body)

        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
            if self._use_tls:
                server.starttls()
            username = os.environ.get(USERNAME_ENV)
            password = os.environ.get(PASSWORD_ENV)
            if username and password:
                server.login(username, password)
            server.send_message(mime)

        return {"delivery": "smtp", "to": message.to, "host": self._host}

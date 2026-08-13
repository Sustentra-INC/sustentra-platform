"""Email sending port and adapters (intake Stage 0+).

The service depends on the ``EmailSender`` port, never on a provider. Two
adapters ship in Phase B:

* ``OutboxEmailSender`` - appends the rendered message to a gitignored JSONL
  file and sends nothing. This is the configured default: the whole flow is
  runnable and testable locally with no credentials and no risk of mailing a
  real person.
* ``InMemoryEmailSender`` - same contract, for tests.

A real provider (SES, SendGrid, ...) is a third adapter implementing the same
port. None is configured in v1; ``build_sender`` raises for unknown adapters
rather than silently degrading to a no-op.

Message bodies come from ``intake/config/email_templates.json`` - copy is
config, not literals in code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from intake.backend.config import REPO_ROOT, IntakeSettings, load_settings

EMAIL_TEMPLATES_PATH = REPO_ROOT / "intake/config/email_templates.json"


class EmailMessage(BaseModel):
    to: str
    from_address: str
    subject: str
    body: str
    template_id: str
    created_at: str


def _load_templates() -> dict[str, Any]:
    return json.loads(EMAIL_TEMPLATES_PATH.read_text(encoding="utf-8"))["templates"]


def render_template(template_id: str, context: dict[str, Any]) -> tuple[str, str]:
    """Render (subject, body) for a template, or raise if context is incomplete."""
    templates = _load_templates()
    try:
        template = templates[template_id]
    except KeyError:
        raise KeyError(f"unknown email template {template_id!r}") from None

    missing = [key for key in template.get("required_context", []) if key not in context]
    if missing:
        raise ValueError(f"template {template_id!r} is missing context keys: {missing}")

    try:
        subject = template["subject"].format(**context)
        body = template["body"].format(**context)
    except KeyError as exc:
        raise ValueError(f"template {template_id!r} references unknown placeholder {exc}") from exc
    return subject, body


class EmailSender:
    """Port. Implementations deliver a rendered message somewhere."""

    def send(self, message: EmailMessage) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


class InMemoryEmailSender(EmailSender):
    """Collects messages in memory. Used by tests."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> dict[str, Any]:
        self.sent.append(message)
        return {"delivery": "memory", "to": message.to}

    def last_to(self, email: str) -> EmailMessage | None:
        matches = [message for message in self.sent if message.to == email]
        return matches[-1] if matches else None


class OutboxEmailSender(EmailSender):
    """Writes messages to a local JSONL outbox. Sends no real email."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def send(self, message: EmailMessage) -> dict[str, Any]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message.model_dump(), ensure_ascii=False) + "\n")
        return {"delivery": "outbox", "to": message.to, "path": str(self._path)}

    def messages(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        return [
            json.loads(line)
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def build_sender(settings: IntakeSettings | None = None) -> EmailSender:
    """Construct the configured sender. Unknown adapters are an error."""
    settings = settings or load_settings()
    adapter = settings.email.adapter
    if adapter == "outbox":
        return OutboxEmailSender(Path(settings.email.outbox_path))
    if adapter == "memory":
        return InMemoryEmailSender()
    if adapter == "smtp":
        # Imported here so the SMTP module is only loaded when it is chosen.
        from intake.backend.adapters.smtp_email import SmtpEmailSender

        return SmtpEmailSender(
            host=settings.email.smtp_host,
            port=settings.email.smtp_port,
            use_tls=settings.email.smtp_use_tls,
        )
    raise ValueError(
        f"unknown email adapter {adapter!r}. No real email provider is configured in v1; "
        "add an adapter implementing EmailSender and register it here."
    )


class EmailService:
    """Renders templates and hands them to the configured sender."""

    def __init__(
        self,
        sender: EmailSender | None = None,
        settings: IntakeSettings | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._sender = sender or build_sender(self._settings)

    @property
    def sender(self) -> EmailSender:
        return self._sender

    def send_template(self, template_id: str, to: str, context: dict[str, Any]) -> EmailMessage:
        subject, body = render_template(template_id, context)
        message = EmailMessage(
            to=to,
            from_address=self._settings.email.from_address,
            subject=subject,
            body=body,
            template_id=template_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._sender.send(message)
        return message

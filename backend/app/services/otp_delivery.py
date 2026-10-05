"""Shared email sender and auth/invite adapters (EMAIL-001 / MVP-16).

Auth flows depend on these stable adapters (FastAPI dependency seams):

    deliver_login_otp(to, code)         # AUTH-005, via get_otp_sender()
    deliver_password_reset(to, link)    # AUTH-006, via get_reset_sender()

Environment behavior:

- local/test: SMTP multipart (plain + HTML) to Mailpit
- staging/prod: SESv2 SendEmail multipart (plain + HTML)

`send_email(template, to, variables)` is the shared implementation used by
all adapters. Rendering/transport errors are contained and logged by adapter
boundaries so auth requests never fail because email delivery failed.

MVP-19 invitation flow is not wired yet; this module exposes `deliver_invite`
and `get_invite_sender` as adapter contracts for future integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError

from ..core.config import Settings, get_settings

logger = logging.getLogger("sustentra.email")

OTP_TTL_MINUTES = 10
RESET_TTL_MINUTES = 15
INVITE_TTL_HOURS = 24
SENDER_NAME = "Sustentra Team"

EmailTemplateName = Literal["login_otp", "invite", "password_reset"]


@dataclass(frozen=True)
class _TemplateSpec:
    subject: str
    text_template: str
    html_template: str


TEMPLATE_SPECS: dict[str, _TemplateSpec] = {
    "login_otp": _TemplateSpec(
        subject="Your Sustentra sign-in code",
        text_template="login_otp.txt.j2",
        html_template="login_otp.html.j2",
    ),
    "invite": _TemplateSpec(
        subject="You are invited to Sustentra",
        text_template="invite.txt.j2",
        html_template="invite.html.j2",
    ),
    "password_reset": _TemplateSpec(
        subject="Reset your Sustentra password",
        text_template="password_reset.txt.j2",
        html_template="password_reset.html.j2",
    ),
}

_TEMPLATE_DIR = Path(__file__).resolve().parent / "email_templates"

OtpSender = Callable[[str, str], None]  # (to, code)
ResetSender = Callable[[str, str], None]  # (to, link)
InviteSender = Callable[[str, str], None]  # (to, invite_link)


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text_body: str
    html_body: str


@lru_cache(maxsize=1)
def _template_environment() -> Environment:
    def _autoescape(template_name: str | None) -> bool:
        if template_name is None:
            return False
        return template_name.endswith((".html", ".htm", ".xml", ".html.j2"))

    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=_autoescape,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def mask_email(address: str) -> str:
    """Mask local part and domain for logs.

    We intentionally hide the whole domain to keep recipient details minimal.
    """

    local, _, domain = address.partition("@")
    if not local or not domain:
        return "***"
    return f"{local[:1]}***@***"


def _template_spec(template: str) -> _TemplateSpec:
    spec = TEMPLATE_SPECS.get(template)
    if spec is None:
        raise ValueError(f"Unsupported email template '{template}'.")
    return spec


def render_email(template: str, variables: dict[str, Any]) -> RenderedEmail:
    spec = _template_spec(template)
    environment = _template_environment()
    text_body = environment.get_template(spec.text_template).render(**variables)
    html_body = environment.get_template(spec.html_template).render(**variables)
    return RenderedEmail(subject=spec.subject, text_body=text_body, html_body=html_body)


def _from_header(settings: Settings) -> str:
    sender_address = settings.ses_from_address or "no-reply@localhost"
    return f"{SENDER_NAME} <{sender_address}>"


def _send_smtp(settings: Settings, to: str, email: RenderedEmail) -> None:
    message = EmailMessage()
    message["From"] = _from_header(settings)
    message["To"] = to
    message["Subject"] = email.subject
    message.set_content(email.text_body, subtype="plain", charset="utf-8")
    message.add_alternative(email.html_body, subtype="html", charset="utf-8")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


def _send_ses(settings: Settings, to: str, email: RenderedEmail) -> None:
    """SES transport using the SESv2 SendEmail payload shape.

    Mapping requirements to SESv2:

    - Sender identity -> FromEmailAddress
    - Recipient(s) -> Destination.ToAddresses
    - Subject/body (plain + HTML) -> Content.Simple.Subject / Content.Simple.Body
    """

    import boto3  # imported lazily: not needed for local SMTP paths

    if not settings.ses_from_address:
        raise RuntimeError("SES_FROM_ADDRESS is required for staging/prod email sending")

    boto3.client("sesv2").send_email(
        FromEmailAddress=settings.ses_from_address,
        Destination={"ToAddresses": [to]},
        Content={
            "Simple": {
                "Subject": {"Data": email.subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": email.text_body, "Charset": "UTF-8"},
                    "Html": {"Data": email.html_body, "Charset": "UTF-8"},
                },
            }
        },
    )


def send_email(template: str, to: str, variables: dict[str, Any]) -> None:
    settings = get_settings()
    rendered = render_email(template, variables)
    if settings.is_production_like:
        _send_ses(settings, to, rendered)
        return
    _send_smtp(settings, to, rendered)


def _deliver(template: str, to: str, variables: dict[str, Any]) -> None:
    """Send one email. Runs in a background task; never raises."""
    try:
        send_email(template, to, variables)
    except Exception as exc:  # noqa: BLE001 - delivery must never crash the request
        response = getattr(exc, "response", None)
        error_code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
        error_type = type(exc).__name__
        if isinstance(exc, UndefinedError):
            error_type = "UndefinedError"
        logger.error(
            "email send failed",
            extra={
                "template": template,
                "error_type": error_type,
                "ses_error_code": error_code,
                "recipient": mask_email(to),
            },
        )


def deliver_login_otp(to: str, code: str) -> None:
    _deliver(
        "login_otp",
        to,
        {
            "code": code,
            "expires_minutes": OTP_TTL_MINUTES,
            "sender_name": SENDER_NAME,
        },
    )


def deliver_password_reset(to: str, link: str) -> None:
    _deliver(
        "password_reset",
        to,
        {
            "reset_link": link,
            "expires_minutes": RESET_TTL_MINUTES,
            "sender_name": SENDER_NAME,
        },
    )


def deliver_invite(to: str, link: str) -> None:
    """Invitation email adapter contract for MVP-19 integration."""

    _deliver(
        "invite",
        to,
        {
            "invite_link": link,
            "expires_hours": INVITE_TTL_HOURS,
            "sender_name": SENDER_NAME,
        },
    )


def get_otp_sender() -> OtpSender:
    """FastAPI dependency; tests override it to capture codes."""
    return deliver_login_otp


def get_reset_sender() -> ResetSender:
    """FastAPI dependency; tests override it to capture reset links."""
    return deliver_password_reset


def get_invite_sender() -> InviteSender:
    """FastAPI dependency seam for future invitation-flow integration."""

    return deliver_invite

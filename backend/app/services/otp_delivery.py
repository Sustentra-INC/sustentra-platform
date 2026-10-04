"""Auth emails - interim delivery until EMAIL-001 (MVP-16).

The auth flows need exactly two messages, each behind one function the flow
depends on (FastAPI dependencies, so tests can capture what would be sent):

    deliver_login_otp(to, code)         # AUTH-005, via get_otp_sender()
    deliver_password_reset(to, link)    # AUTH-006, via get_reset_sender()

- local/test: plain SMTP to Mailpit (http://localhost:8025 shows the email)
- staging/prod: Amazon SES (SendEmail) from SES_FROM_ADDRESS

EMAIL-001 replaces the bodies with the proper `login_otp` / `password_reset`
templates (HTML + text) via send_email(template, to, variables); the call
sites and dependencies stay the same.

Failures are caught and logged (template name, error code, recipient masked
after '@') and never raise into the request. Codes and links are never logged.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from ..core.config import Settings, get_settings

logger = logging.getLogger("sustentra.email")

OTP_TTL_MINUTES = 10
RESET_TTL_MINUTES = 15

LOGIN_OTP_SUBJECT = "Your Sustentra sign-in code"
PASSWORD_RESET_SUBJECT = "Reset your Sustentra password"

OtpSender = Callable[[str, str], None]  # (to, code)
ResetSender = Callable[[str, str], None]  # (to, link)

_FOOTER = "\n\n- Sustentra"


def mask_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def login_otp_body(code: str) -> str:
    return (
        f"Your Sustentra sign-in code is: {code}\n\n"
        f"It expires in {OTP_TTL_MINUTES} minutes.\n\n"
        "Didn't try to sign in? You can ignore this email - your password is still required "
        "to use this code. If it keeps happening, contact your Sustentra administrator."
        + _FOOTER
    )


def password_reset_body(link: str) -> str:
    return (
        "We received a request to reset your Sustentra password.\n\n"
        f"Choose a new password here (the link expires in {RESET_TTL_MINUTES} minutes):\n{link}\n\n"
        "Didn't request this? You can ignore this email - your password won't change."
        + _FOOTER
    )


def _send_smtp(settings: Settings, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.ses_from_address or "no-reply@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


def _send_ses(settings: Settings, to: str, subject: str, body: str) -> None:
    import boto3  # imported lazily: not needed locally or in tests

    if not settings.ses_from_address:
        raise RuntimeError("SES_FROM_ADDRESS is not configured")
    boto3.client("sesv2").send_email(
        FromEmailAddress=settings.ses_from_address,
        Destination={"ToAddresses": [to]},
        Content={"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}}},
    )


def _deliver(template: str, to: str, subject: str, body: str) -> None:
    """Send one email. Runs in a background task; never raises."""
    settings = get_settings()
    try:
        if settings.is_production_like:
            _send_ses(settings, to, subject, body)
        else:
            _send_smtp(settings, to, subject, body)
    except Exception as exc:  # noqa: BLE001 - delivery must never crash the request
        response = getattr(exc, "response", None)
        error_code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
        logger.error(
            "email send failed",
            extra={
                "template": template,
                "error_type": type(exc).__name__,
                "ses_error_code": error_code,
                "recipient": mask_email(to),
            },
        )


def deliver_login_otp(to: str, code: str) -> None:
    _deliver("login_otp", to, LOGIN_OTP_SUBJECT, login_otp_body(code))


def deliver_password_reset(to: str, link: str) -> None:
    _deliver("password_reset", to, PASSWORD_RESET_SUBJECT, password_reset_body(link))


def get_otp_sender() -> OtpSender:
    """FastAPI dependency; tests override it to capture codes."""
    return deliver_login_otp


def get_reset_sender() -> ResetSender:
    """FastAPI dependency; tests override it to capture reset links."""
    return deliver_password_reset

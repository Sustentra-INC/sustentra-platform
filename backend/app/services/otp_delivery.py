"""Login OTP email delivery (interim, until EMAIL-001 / MVP-16).

AUTH-005 only needs "send this 6-digit code to this address". This module does
exactly that, behind one function the login flow depends on:

    deliver_login_otp(to, code)

- local/test: plain SMTP to Mailpit (http://localhost:8025 shows the email)
- staging/prod: Amazon SES (SendEmail) from SES_FROM_ADDRESS

EMAIL-001 replaces the body with the proper `login_otp` template (HTML + text)
via send_email(template, to, variables); the call site stays the same.

Failures are caught and logged (template name, error code, recipient masked
after '@') and never raise into the request. The code is never logged.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from ..core.config import Settings, get_settings

logger = logging.getLogger("sustentra.email")

SUBJECT = "Your Sustentra sign-in code"
OTP_TTL_MINUTES = 10

OtpSender = Callable[[str, str], None]


def mask_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _body(code: str) -> str:
    return (
        f"Your Sustentra sign-in code is: {code}\n\n"
        f"It expires in {OTP_TTL_MINUTES} minutes.\n\n"
        "Didn't try to sign in? You can ignore this email - your password is still required "
        "to use this code. If it keeps happening, contact your Sustentra administrator.\n\n"
        "- Sustentra"
    )


def _send_smtp(settings: Settings, to: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = settings.ses_from_address or "no-reply@localhost"
    message["To"] = to
    message["Subject"] = SUBJECT
    message.set_content(_body(code))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


def _send_ses(settings: Settings, to: str, code: str) -> None:
    import boto3  # imported lazily: not needed locally or in tests

    if not settings.ses_from_address:
        raise RuntimeError("SES_FROM_ADDRESS is not configured")
    boto3.client("sesv2").send_email(
        FromEmailAddress=settings.ses_from_address,
        Destination={"ToAddresses": [to]},
        Content={"Simple": {"Subject": {"Data": SUBJECT}, "Body": {"Text": {"Data": _body(code)}}}},
    )


def deliver_login_otp(to: str, code: str) -> None:
    """Send the login code. Runs in a background task; never raises."""
    settings = get_settings()
    try:
        if settings.is_production_like:
            _send_ses(settings, to, code)
        else:
            _send_smtp(settings, to, code)
    except Exception as exc:  # noqa: BLE001 - delivery must never crash the request
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
        logger.error(
            "email send failed",
            extra={
                "template": "login_otp",
                "error_type": type(exc).__name__,
                "ses_error_code": error_code,
                "recipient": mask_email(to),
            },
        )


def get_otp_sender() -> OtpSender:
    """FastAPI dependency; tests override it to capture codes."""
    return deliver_login_otp

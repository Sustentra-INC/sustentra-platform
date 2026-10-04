"""Interim auth email delivery: content, masking, failures never raise."""

import logging

import pytest

from backend.app.services import otp_delivery


def test_bodies_contain_code_or_link_and_the_didnt_request_line() -> None:
    otp = otp_delivery.login_otp_body("042917")
    assert "042917" in otp and "10 minutes" in otp and "Didn't" in otp
    reset = otp_delivery.password_reset_body("https://app.example/reset?token=abc")
    assert "https://app.example/reset?token=abc" in reset and "15 minutes" in reset and "Didn't" in reset


def test_mask_email() -> None:
    assert otp_delivery.mask_email("alice@acme.test") == "a***@acme.test"
    assert otp_delivery.mask_email("broken") == "***"


def test_send_failure_is_logged_without_secrets_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_: object) -> None:
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(otp_delivery, "_send_smtp", boom)
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery.deliver_login_otp("alice@acme.test", "042917")  # must not raise
    otp_delivery.deliver_password_reset("alice@acme.test", "https://x/reset?token=secret-token")

    records = [r for r in caplog.records if r.name == "sustentra.email"]
    assert [r.template for r in records] == ["login_otp", "password_reset"]  # type: ignore[attr-defined]
    for record in records:
        assert record.recipient == "a***@acme.test"  # type: ignore[attr-defined]
        rendered = record.getMessage() + str(record.__dict__)
        assert "042917" not in rendered and "secret-token" not in rendered

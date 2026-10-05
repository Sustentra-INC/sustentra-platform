"""EMAIL-001 unit tests: shared sender, template rendering, and adapter safety."""

from __future__ import annotations

import logging
import sys
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Any

import pytest
from botocore.exceptions import ClientError
from jinja2 import UndefinedError

from backend.app.core.config import Settings
from backend.app.services import otp_delivery


def _settings(environment: str = "test", from_address: str | None = "no-reply@sustentra.test") -> Settings:
    return Settings(
        environment=environment,
        ses_from_address=from_address,
        smtp_host="mailpit",
        smtp_port=1025,
    )


def _base_variables(template: str) -> dict[str, Any]:
    if template == "login_otp":
        return {
            "code": "004201",
            "expires_minutes": otp_delivery.OTP_TTL_MINUTES,
            "sender_name": "Sustentra QA",
        }
    if template == "invite":
        return {
            "invite_link": "https://app.example/invite?token=abc123&next=%2Forg%2Facme",
            "expires_hours": otp_delivery.INVITE_TTL_HOURS,
            "sender_name": "Sustentra QA",
        }
    if template == "password_reset":
        return {
            "reset_link": "https://app.example/reset?token=abc123&next=%2Forg%2Facme",
            "expires_minutes": otp_delivery.RESET_TTL_MINUTES,
            "sender_name": "Sustentra QA",
        }
    raise AssertionError(f"unsupported template in test: {template}")


def _missing_variable_cases() -> list[Any]:
    cases: list[Any] = []
    for template in ("login_otp", "invite", "password_reset"):
        variables = _base_variables(template)
        for missing_key in variables:
            cases.append(
                pytest.param(
                    template,
                    variables,
                    missing_key,
                    id=f"{template}-missing-{missing_key}",
                )
            )
    return cases


class _AnchorHrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value is not None:
                self.hrefs.append(value)


def _extract_anchor_hrefs(html_body: str) -> list[str]:
    parser = _AnchorHrefParser()
    parser.feed(html_body)
    parser.close()
    return parser.hrefs


def test_mask_email_masks_local_and_domain() -> None:
    assert otp_delivery.mask_email("alice@acme.test") == "a***@***"
    assert otp_delivery.mask_email("broken") == "***"


@pytest.mark.parametrize(
    (
        "template",
        "variables",
        "expected_subject",
        "expected_expiry_phrase",
        "required_variable_keys",
        "url_variable_key",
    ),
    [
        pytest.param(
            "login_otp",
            {
                "code": "004201",
                "expires_minutes": 10,
                "sender_name": "Sustentra QA",
            },
            "Your Sustentra sign-in code",
            "expires in 10 minutes",
            ("code", "sender_name"),
            None,
            id="login-otp-template-requirements",
        ),
        pytest.param(
            "password_reset",
            {
                "reset_link": "https://app.example/reset?token=abc123&next=%2Forg%2Facme",
                "expires_minutes": 15,
                "sender_name": "Sustentra QA",
            },
            "Reset your Sustentra password",
            "expires in 15 minutes",
            ("sender_name",),
            "reset_link",
            id="password-reset-template-requirements",
        ),
        pytest.param(
            "invite",
            {
                "invite_link": "https://app.example/invite?token=abc123&next=%2Forg%2Facme",
                "expires_hours": 24,
                "sender_name": "Sustentra QA",
            },
            "You are invited to Sustentra",
            "expires in 24 hours",
            ("sender_name",),
            "invite_link",
            id="invite-template-requirements",
        ),
    ],
)
def test_template_requirements_match_spec_expectations(
    template: str,
    variables: dict[str, Any],
    expected_subject: str,
    expected_expiry_phrase: str,
    required_variable_keys: tuple[str, ...],
    url_variable_key: str | None,
) -> None:
    rendered = otp_delivery.render_email(template, variables)

    assert rendered.subject == expected_subject
    assert expected_expiry_phrase in rendered.text_body.lower()
    assert expected_expiry_phrase in rendered.html_body.lower()

    for key in required_variable_keys:
        value = str(variables[key])
        assert value in rendered.text_body
        assert value in rendered.html_body

    if url_variable_key is None:
        return

    expected_url = str(variables[url_variable_key])
    assert expected_url in rendered.text_body
    assert expected_url in _extract_anchor_hrefs(rendered.html_body)


@pytest.mark.parametrize(
    ("template", "link_key", "input_url"),
    [
        pytest.param(
            "password_reset",
            "reset_link",
            "https://app.example/reset?token=abc123&next=%2Forg%2Facme&lang=en",
            id="reset-ordinary-query-separators",
        ),
        pytest.param(
            "password_reset",
            "reset_link",
            "https://app.example/reset?token=abc123&literal=%26amp%3B&glyph=%26%23x26%3B",
            id="reset-literal-entity-like-sequences",
        ),
        pytest.param(
            "password_reset",
            "reset_link",
            "https://app.example/reset?token=abc123&literal=&amp;&next=%2Forg%2Facme",
            id="reset-literal-amp-sequence",
        ),
        pytest.param(
            "password_reset",
            "reset_link",
            "https://app.example/reset?token=abc123&literal=&#38;&next=%2Forg%2Facme",
            id="reset-literal-decimal-entity-sequence",
        ),
        pytest.param(
            "password_reset",
            "reset_link",
            "https://app.example/reset?token=abc123&literal=&#x26;&next=%2Forg%2Facme",
            id="reset-literal-hex-entity-sequence",
        ),
        pytest.param(
            "invite",
            "invite_link",
            "https://app.example/invite?token=def456&next=%2Forg%2Facme&source=email",
            id="invite-ordinary-query-separators",
        ),
        pytest.param(
            "invite",
            "invite_link",
            "https://app.example/invite?token=def456&literal=%26amp%3B&glyph=%26%23x26%3B",
            id="invite-literal-entity-like-sequences",
        ),
        pytest.param(
            "invite",
            "invite_link",
            "https://app.example/invite?token=def456&literal=&amp;&next=%2Forg%2Facme",
            id="invite-literal-amp-sequence",
        ),
        pytest.param(
            "invite",
            "invite_link",
            "https://app.example/invite?token=def456&literal=&#38;&next=%2Forg%2Facme",
            id="invite-literal-decimal-entity-sequence",
        ),
        pytest.param(
            "invite",
            "invite_link",
            "https://app.example/invite?token=def456&literal=&#x26;&next=%2Forg%2Facme",
            id="invite-literal-hex-entity-sequence",
        ),
    ],
)
def test_rendered_anchor_href_preserves_original_url(
    template: str,
    link_key: str,
    input_url: str,
) -> None:
    variables = _base_variables(template)
    variables[link_key] = input_url

    rendered = otp_delivery.render_email(template, variables)
    hrefs = _extract_anchor_hrefs(rendered.html_body)

    assert hrefs == [input_url]
    assert input_url in rendered.text_body


@pytest.mark.parametrize(("template", "variables", "missing_key"), _missing_variable_cases())
def test_missing_required_variable_raises_undefined_and_skips_transport(
    template: str,
    variables: dict[str, Any],
    missing_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp_calls: list[Any] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="test"))
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))

    missing = {key: value for key, value in variables.items() if key != missing_key}
    with pytest.raises(UndefinedError):
        otp_delivery.send_email(template, "alice@acme.test", missing)

    assert smtp_calls == []


@pytest.mark.parametrize("template", ["nope", "../invite", "invite/../../reset", "..\\invite"])
def test_unknown_or_path_like_template_is_rejected_before_sending(
    template: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp_calls: list[Any] = []
    ses_calls: list[Any] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="test"))
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))
    monkeypatch.setattr(otp_delivery, "_send_ses", lambda *_: ses_calls.append(True))

    with pytest.raises(ValueError):
        otp_delivery.send_email(template, "alice@acme.test", {})

    assert smtp_calls == []
    assert ses_calls == []


@pytest.mark.parametrize(
    "raw_code",
    [
        pytest.param("000041", id="already-zero-padded"),
        pytest.param("42", id="short-numeric-not-padded"),
        pytest.param("  42  ", id="whitespace-not-stripped"),
        pytest.param("12A-β", id="non-numeric-kept-verbatim"),
        pytest.param("0000000", id="long-numeric-not-trimmed"),
    ],
)
def test_login_otp_adapter_passes_code_string_verbatim(raw_code: str) -> None:
    sent: list[dict[str, Any]] = []

    def capture(template: str, to: str, variables: dict[str, Any]) -> None:
        sent.append({"template": template, "to": to, "variables": dict(variables)})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(otp_delivery, "send_email", capture)
        otp_delivery.deliver_login_otp("alice@acme.test", raw_code)

    assert sent == [
        {
            "template": "login_otp",
            "to": "alice@acme.test",
            "variables": {
                "code": raw_code,
                "expires_minutes": otp_delivery.OTP_TTL_MINUTES,
                "sender_name": otp_delivery.SENDER_NAME,
            },
        }
    ]


def test_html_escaping_unicode_and_long_links(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[otp_delivery.RenderedEmail] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="test"))
    monkeypatch.setattr(
        otp_delivery,
        "_send_smtp",
        lambda _settings, _to, email: captured.append(email),
    )

    variables = _base_variables("password_reset")
    variables["sender_name"] = "Sustentra <Ops & QA> 東京"
    variables["reset_link"] = (
        "https://app.example/reset?token=this-token-is-very-long-"
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx&next=%2Forg%2Facme%2Fteams"
    )
    otp_delivery.send_email("password_reset", "alice@acme.test", variables)

    [email] = captured
    assert "Sustentra <Ops & QA> 東京" in email.text_body
    assert "Sustentra &lt;Ops &amp; QA&gt; 東京" in email.html_body
    assert "token=this-token-is-very-long" in email.text_body
    assert "token=this-token-is-very-long" in email.html_body
    assert "&amp;next=" in email.html_body


def test_send_email_uses_smtp_for_non_production(monkeypatch: pytest.MonkeyPatch) -> None:
    smtp_calls: list[Any] = []
    ses_calls: list[Any] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="local"))
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))
    monkeypatch.setattr(otp_delivery, "_send_ses", lambda *_: ses_calls.append(True))

    otp_delivery.send_email("login_otp", "alice@acme.test", _base_variables("login_otp"))
    assert smtp_calls == [True]
    assert ses_calls == []


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_send_email_uses_ses_for_production_like(environment: str, monkeypatch: pytest.MonkeyPatch) -> None:
    smtp_calls: list[Any] = []
    ses_calls: list[Any] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment=environment))
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))
    monkeypatch.setattr(otp_delivery, "_send_ses", lambda *_: ses_calls.append(True))

    otp_delivery.send_email("password_reset", "alice@acme.test", _base_variables("password_reset"))
    assert smtp_calls == []
    assert ses_calls == [True]


def test_send_smtp_message_structure_utf8_and_multipart(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class RecordingSMTP:
        def __enter__(self) -> RecordingSMTP:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
            return False

        def send_message(self, message: EmailMessage) -> None:
            captured["raw"] = message.as_bytes(policy=policy.SMTP)

    def smtp_factory(host: str, port: int, timeout: int) -> RecordingSMTP:
        captured["host"] = host
        captured["port"] = port
        captured["timeout"] = timeout
        return RecordingSMTP()

    monkeypatch.setattr(otp_delivery.smtplib, "SMTP", smtp_factory)
    settings = _settings(environment="test")
    expected_subject = "Reset your Sustentra password 東京"
    expected_text = "Plain text body with unicode 東京"
    expected_html = "<p>HTML body with unicode 東京</p>"
    email = otp_delivery.RenderedEmail(
        subject=expected_subject,
        text_body=expected_text,
        html_body=expected_html,
    )
    otp_delivery._send_smtp(settings, "alice@acme.test", email)

    parsed = BytesParser(policy=policy.default).parsebytes(captured["raw"])
    assert captured["host"] == "mailpit"
    assert captured["port"] == 1025
    assert captured["timeout"] == 10
    assert parsed["From"] == "Sustentra Team <no-reply@sustentra.test>"
    assert parsed["To"] == "alice@acme.test"
    assert parsed["Subject"] == expected_subject
    assert parsed.get_content_type() == "multipart/alternative"

    text_part = parsed.get_body(preferencelist=("plain",))
    html_part = parsed.get_body(preferencelist=("html",))
    assert text_part is not None
    assert html_part is not None
    assert text_part.get_content_type() == "text/plain"
    assert html_part.get_content_type() == "text/html"
    assert text_part.get_content_charset() == "utf-8"
    assert html_part.get_content_charset() == "utf-8"
    assert text_part.get_content().replace("\r\n", "\n").rstrip("\n") == expected_text
    assert html_part.get_content().replace("\r\n", "\n").rstrip("\n") == expected_html


def test_send_ses_uses_sesv2_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    requested_services: list[str] = []

    class FakeSesClient:
        def send_email(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    fake_client = FakeSesClient()

    def client_factory(name: str) -> FakeSesClient:
        requested_services.append(name)
        return fake_client

    fake_boto3 = type("FakeBoto3", (), {"client": staticmethod(client_factory)})
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    settings = _settings(environment="prod", from_address="no-reply@sustentra.example")
    email = otp_delivery.RenderedEmail(
        subject="Your Sustentra sign-in code",
        text_body="Text body",
        html_body="<p>HTML body</p>",
    )
    otp_delivery._send_ses(settings, "alice@acme.test", email)

    assert requested_services == ["sesv2"]
    [payload] = calls
    assert payload["FromEmailAddress"] == "no-reply@sustentra.example"
    assert payload["Destination"] == {"ToAddresses": ["alice@acme.test"]}
    assert payload["Content"]["Simple"]["Subject"] == {"Data": "Your Sustentra sign-in code", "Charset": "UTF-8"}
    assert payload["Content"]["Simple"]["Body"]["Text"] == {"Data": "Text body", "Charset": "UTF-8"}
    assert payload["Content"]["Simple"]["Body"]["Html"] == {"Data": "<p>HTML body</p>", "Charset": "UTF-8"}


def test_delivery_boundary_logs_smtp_failure_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="test"))
    monkeypatch.setattr(
        otp_delivery,
        "_send_smtp",
        lambda *_: (_ for _ in ()).throw(ConnectionRefusedError("OTP=042917 TOKEN=secret-token")),
    )
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery.deliver_login_otp("alice@acme.test", "042917")
    otp_delivery.deliver_password_reset("alice@acme.test", "https://x/reset?token=secret-token")

    records = [record for record in caplog.records if record.name == "sustentra.email"]
    assert [record.template for record in records] == ["login_otp", "password_reset"]  # type: ignore[attr-defined]
    for record in records:
        assert record.recipient == "a***@***"  # type: ignore[attr-defined]
        rendered = record.getMessage() + str(record.__dict__)
        assert "042917" not in rendered
        assert "secret-token" not in rendered


def test_delivery_boundary_logs_ses_client_error_code_without_leaking_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="prod"))
    error = ClientError(
        {
            "Error": {
                "Code": "ThrottlingException",
                "Message": "SENTINEL_TOKEN=top-secret",
            }
        },
        "SendEmail",
    )
    monkeypatch.setattr(otp_delivery, "_send_ses", lambda *_: (_ for _ in ()).throw(error))
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery.deliver_login_otp("alice@acme.test", "000001")

    [record] = [record for record in caplog.records if record.name == "sustentra.email"]
    assert record.ses_error_code == "ThrottlingException"  # type: ignore[attr-defined]
    assert "SENTINEL_TOKEN" not in (record.getMessage() + str(record.__dict__))


def test_missing_ses_sender_does_not_fallback_to_smtp(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    smtp_calls: list[Any] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="prod", from_address=None))
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery.deliver_password_reset("alice@acme.test", "https://x/reset?token=abc")

    assert smtp_calls == []
    [record] = [record for record in caplog.records if record.name == "sustentra.email"]
    assert record.error_type == "RuntimeError"  # type: ignore[attr-defined]


def test_deliver_real_renderer_missing_variable_does_not_raise_or_send_and_logs_safely(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    smtp_calls: list[Any] = []
    ses_calls: list[Any] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="test"))
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))
    monkeypatch.setattr(otp_delivery, "_send_ses", lambda *_: ses_calls.append(True))
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery._deliver(
        "password_reset",
        "alice+secret@acme.test",
        {
            "expires_minutes": 15,
            "sender_name": "Sustentra QA",
            "marker": "SENTINEL-MARKER",
        },
    )

    assert smtp_calls == []
    assert ses_calls == []

    [record] = [record for record in caplog.records if record.name == "sustentra.email"]
    assert record.template == "password_reset"  # type: ignore[attr-defined]
    assert record.error_type == "UndefinedError"  # type: ignore[attr-defined]
    assert record.recipient == "a***@***"  # type: ignore[attr-defined]

    rendered = record.getMessage() + str(record.__dict__)
    assert "SENTINEL-MARKER" not in rendered
    assert "alice+secret@acme.test" not in rendered


def test_deliver_handles_get_settings_error_without_transport_or_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    smtp_calls: list[Any] = []
    ses_calls: list[Any] = []

    def raise_config_error() -> Settings:
        raise RuntimeError("CONFIG_TOKEN=super-secret")

    monkeypatch.setattr(otp_delivery, "get_settings", raise_config_error)
    monkeypatch.setattr(otp_delivery, "_send_smtp", lambda *_: smtp_calls.append(True))
    monkeypatch.setattr(otp_delivery, "_send_ses", lambda *_: ses_calls.append(True))
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery.deliver_login_otp("alice@acme.test", "000001")

    assert smtp_calls == []
    assert ses_calls == []

    [record] = [record for record in caplog.records if record.name == "sustentra.email"]
    assert record.template == "login_otp"  # type: ignore[attr-defined]
    assert record.error_type == "RuntimeError"  # type: ignore[attr-defined]
    assert record.recipient == "a***@***"  # type: ignore[attr-defined]

    rendered = record.getMessage() + str(record.__dict__)
    assert "CONFIG_TOKEN" not in rendered
    assert "super-secret" not in rendered


def test_background_render_failure_does_not_raise_and_logs_safely(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        otp_delivery,
        "send_email",
        lambda *_: (_ for _ in ()).throw(UndefinedError("SENTINEL_LINK=https://x/reset?token=abc")),
    )
    caplog.set_level(logging.ERROR, logger="sustentra.email")

    otp_delivery.deliver_password_reset("alice@acme.test", "https://x/reset?token=abc")

    [record] = [record for record in caplog.records if record.name == "sustentra.email"]
    assert record.error_type == "UndefinedError"  # type: ignore[attr-defined]
    assert "SENTINEL_LINK" not in (record.getMessage() + str(record.__dict__))


def test_multiple_sends_keep_variables_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(otp_delivery, "get_settings", lambda: _settings(environment="test"))

    def capture_smtp(_settings: Settings, to: str, email: otp_delivery.RenderedEmail) -> None:
        captured.append({"to": to, "text": email.text_body, "html": email.html_body})

    monkeypatch.setattr(otp_delivery, "_send_smtp", capture_smtp)

    otp_delivery.send_email("login_otp", "alice@acme.test", _base_variables("login_otp") | {"code": "000001"})
    otp_delivery.send_email("login_otp", "bob@acme.test", _base_variables("login_otp") | {"code": "999999"})

    assert captured[0]["to"] == "alice@acme.test"
    assert captured[1]["to"] == "bob@acme.test"
    assert "000001" in captured[0]["text"]
    assert "999999" not in captured[0]["text"]
    assert "999999" in captured[1]["text"]
    assert "000001" not in captured[1]["text"]


def test_invite_adapter_contract_uses_shared_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def capture(template: str, to: str, variables: dict[str, Any]) -> None:
        calls.append({"template": template, "to": to, "variables": dict(variables)})

    monkeypatch.setattr(otp_delivery, "send_email", capture)

    otp_delivery.deliver_invite("invitee@acme.test", "https://app.example/invite?token=abc")
    sender = otp_delivery.get_invite_sender()
    sender("invitee-2@acme.test", "https://app.example/invite?token=xyz")

    assert calls == [
        {
            "template": "invite",
            "to": "invitee@acme.test",
            "variables": {
                "invite_link": "https://app.example/invite?token=abc",
                "expires_hours": otp_delivery.INVITE_TTL_HOURS,
                "sender_name": otp_delivery.SENDER_NAME,
            },
        },
        {
            "template": "invite",
            "to": "invitee-2@acme.test",
            "variables": {
                "invite_link": "https://app.example/invite?token=xyz",
                "expires_hours": otp_delivery.INVITE_TTL_HOURS,
                "sender_name": otp_delivery.SENDER_NAME,
            },
        },
    ]

"""Magic-link authentication behaviour, including the ways it must fail."""

from __future__ import annotations

import pytest

from intake.backend.services.auth_service import AuthError, AuthService, hash_token


def _token_from_mailbox(harness, email: str) -> str:
    message = harness.mailbox.last_to(email)
    assert message is not None
    return message.body.split("token=")[1].split()[0].strip()


def test_sign_in_round_trip(harness) -> None:
    harness.create_org()
    session_token = harness.sign_in()
    user = harness.auth_service.resolve_session(session_token)
    assert user.email == "owner@example.com"
    assert user.role == "client_owner"


def test_request_for_unknown_email_sends_nothing_but_looks_identical(harness) -> None:
    """No account enumeration: same response, no email."""
    harness.create_org()
    known = harness.auth_service.request_magic_link("owner@example.com")
    unknown = harness.auth_service.request_magic_link("stranger@example.com")

    assert known == unknown == {"status": "sent"}
    assert harness.mailbox.last_to("stranger@example.com") is None


def test_raw_token_is_never_persisted(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    raw = _token_from_mailbox(harness, "owner@example.com")

    stored = harness.tokens.list_records()
    assert stored, "a token record should exist"
    for record in stored:
        assert raw not in str(record)
        assert record["token_hash"] == hash_token(raw)


def test_token_is_single_use(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    raw = _token_from_mailbox(harness, "owner@example.com")

    harness.auth_service.verify_magic_link(raw)
    with pytest.raises(AuthError):
        harness.auth_service.verify_magic_link(raw)


def test_expired_token_is_rejected(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    raw = _token_from_mailbox(harness, "owner@example.com")

    harness.clock.advance(minutes=harness.settings.auth.magic_link_ttl_minutes + 1)
    with pytest.raises(AuthError):
        harness.auth_service.verify_magic_link(raw)


def test_token_valid_right_up_to_expiry(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    raw = _token_from_mailbox(harness, "owner@example.com")

    harness.clock.advance(minutes=harness.settings.auth.magic_link_ttl_minutes - 1)
    assert harness.auth_service.verify_magic_link(raw)["session_token"]


@pytest.mark.parametrize("bad", ["", "not-a-token", "x" * 60])
def test_garbage_tokens_are_rejected(harness, bad: str) -> None:
    harness.create_org()
    with pytest.raises(AuthError):
        harness.auth_service.verify_magic_link(bad)


def test_session_expires(harness) -> None:
    harness.create_org()
    session_token = harness.sign_in()

    harness.clock.advance(hours=harness.settings.auth.session_ttl_hours + 1)
    with pytest.raises(AuthError):
        harness.auth_service.resolve_session(session_token)


def test_session_can_be_revoked(harness) -> None:
    harness.create_org()
    session_token = harness.sign_in()

    harness.auth_service.revoke_session(session_token)
    with pytest.raises(AuthError):
        harness.auth_service.resolve_session(session_token)


def test_revoking_an_unknown_session_is_harmless(harness) -> None:
    assert harness.auth_service.revoke_session("nope") == {"status": "signed_out"}


def test_disabled_user_cannot_sign_in(harness) -> None:
    created = harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    raw = _token_from_mailbox(harness, "owner@example.com")

    disabled = dict(created["owner"])
    disabled["status"] = "disabled"
    harness.users.save(disabled)

    with pytest.raises(AuthError):
        harness.auth_service.verify_magic_link(raw)


def test_disabled_user_loses_an_existing_session(harness) -> None:
    created = harness.create_org()
    session_token = harness.sign_in()

    disabled = dict(created["owner"])
    disabled["status"] = "disabled"
    harness.users.save(disabled)

    with pytest.raises(AuthError):
        harness.auth_service.resolve_session(session_token)


def test_session_token_is_not_the_magic_link_token(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    raw = _token_from_mailbox(harness, "owner@example.com")
    result = harness.auth_service.verify_magic_link(raw)
    assert result["session_token"] != raw


def test_last_login_is_recorded(harness) -> None:
    harness.create_org()
    assert harness.users.get_by_email("owner@example.com")["last_login_at"] is None
    harness.sign_in()
    assert harness.users.get_by_email("owner@example.com")["last_login_at"] is not None


def test_email_is_case_insensitive_on_request(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("OWNER@Example.com")
    assert harness.mailbox.last_to("owner@example.com") is not None


def test_link_uses_the_configured_verify_url(harness) -> None:
    harness.create_org()
    harness.auth_service.request_magic_link("owner@example.com")
    body = harness.mailbox.last_to("owner@example.com").body
    assert harness.settings.auth.verify_url_template.split("{token}")[0] in body


def test_token_factory_length_follows_config(harness) -> None:
    """Tokens are generated with the configured entropy, not a hardcoded size."""
    captured: list[int] = []

    def factory(nbytes: int) -> str:
        captured.append(nbytes)
        return "deterministic-token"

    service = AuthService(
        token_repository=harness.tokens,
        session_repository=harness.sessions,
        user_repository=harness.users,
        email_service=harness.email_service,
        settings=harness.settings,
        clock=harness.clock,
        token_factory=factory,
    )
    harness.create_org()
    service.request_magic_link("owner@example.com")
    assert captured == [harness.settings.auth.token_bytes]

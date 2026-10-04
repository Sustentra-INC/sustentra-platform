"""AUTH-003 unit tests: passwords, policy, tokens, OTP."""

import hashlib
import re
import time

import pytest

from backend.app.core import security_primitives as sp

SECRET = "unit-test-otp-secret"


# --- passwords ---------------------------------------------------------------

def test_correct_password_verifies_and_wrong_does_not() -> None:
    hashed = sp.hash_password("correct horse battery staple")
    assert sp.verify_password("correct horse battery staple", hashed)
    assert not sp.verify_password("correct horse battery stapler", hashed)


def test_hash_is_bcrypt_cost_12_and_salted() -> None:
    first = sp.hash_password("same passphrase twelve+")
    second = sp.hash_password("same passphrase twelve+")
    assert first.startswith("$2b$12$")
    assert first != second  # unique salt per hash


def test_unknown_user_takes_comparable_time_and_fails() -> None:
    hashed = sp.hash_password("some real password here")
    sp.verify_password("warm-up", None)  # first call builds the dummy hash

    start = time.perf_counter()
    assert not sp.verify_password("guess one two three", None)
    unknown = time.perf_counter() - start

    start = time.perf_counter()
    assert not sp.verify_password("guess one two three", hashed)
    wrong = time.perf_counter() - start

    # Both run a full cost-12 bcrypt check; allow generous jitter.
    assert unknown > wrong * 0.5
    assert unknown < wrong * 2.0


def test_long_passwords_beyond_72_bytes_are_fully_significant() -> None:
    base = "x" * 100
    hashed = sp.hash_password(base + "A")
    assert sp.verify_password(base + "A", hashed)
    assert not sp.verify_password(base + "B", hashed)


def test_malformed_stored_hash_returns_false() -> None:
    assert not sp.verify_password("anything at all here", "not-a-bcrypt-hash")


# --- policy ------------------------------------------------------------------

def test_policy_rejects_short_password() -> None:
    assert sp.VIOLATION_TOO_SHORT in sp.validate_password("Short1!", "a@b.test")


def test_policy_rejects_too_long_password() -> None:
    assert sp.VIOLATION_TOO_LONG in sp.validate_password("a" * 129, "a@b.test")


@pytest.mark.parametrize("common", ["password", "Password123", "qwertyuiop", "123456789012"])
def test_policy_rejects_common_passwords(common: str) -> None:
    assert sp.VIOLATION_COMMON in sp.validate_password(common, "a@b.test")


def test_policy_rejects_password_equal_to_email() -> None:
    email = "jerome.long.address@sustentra.test"
    assert sp.VIOLATION_EQUALS_EMAIL in sp.validate_password(email.upper(), email)


def test_policy_accepts_long_passphrase() -> None:
    assert sp.validate_password("violet tractor sings at dawn", "a@b.test") == []


def test_policy_reports_every_violation_at_once() -> None:
    violations = sp.validate_password("password", "password")
    assert sp.VIOLATION_TOO_SHORT in violations
    assert sp.VIOLATION_COMMON in violations
    assert sp.VIOLATION_EQUALS_EMAIL in violations


def test_bundled_common_password_list_is_present() -> None:
    # backend/app/core/data/common_passwords.txt (SecLists 10k-most-common, MIT).
    assert sp.common_password_list_loaded(), "bundled top-10,000 common password list is missing"
    assert len(sp._common_passwords()) >= 9_000


# --- tokens --------------------------------------------------------------------

def test_tokens_are_unique_and_only_the_hash_is_stored() -> None:
    pairs = [sp.new_token() for _ in range(200)]
    tokens = {t for t, _ in pairs}
    assert len(tokens) == 200
    for token, digest in pairs:
        assert digest != token
        assert digest == hashlib.sha256(token.encode()).hexdigest()
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert len(token) >= 43  # 32 random bytes, base64url


def test_hash_token_matches_new_token_digest() -> None:
    token, digest = sp.new_token()
    assert sp.hash_token(token) == digest


# --- OTP -----------------------------------------------------------------------

def test_otp_is_always_six_digits() -> None:
    for _ in range(1000):
        code = sp.new_otp()
        assert re.fullmatch(r"\d{6}", code)


def test_otp_hmac_verifies_right_code_and_rejects_others() -> None:
    stored = sp.hash_otp("challenge-1", "042917", secret=SECRET)
    assert sp.verify_otp("challenge-1", "042917", stored, secret=SECRET)
    assert not sp.verify_otp("challenge-1", "042918", stored, secret=SECRET)


def test_otp_is_bound_to_its_challenge_and_secret() -> None:
    stored = sp.hash_otp("challenge-1", "042917", secret=SECRET)
    assert not sp.verify_otp("challenge-2", "042917", stored, secret=SECRET)
    assert not sp.verify_otp("challenge-1", "042917", stored, secret="another-secret")


def test_otp_hash_does_not_contain_the_code() -> None:
    assert "042917" not in sp.hash_otp("challenge-1", "042917", secret=SECRET)


def test_otp_secret_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core.config import get_settings

    monkeypatch.setenv("OTP_HMAC_SECRET", SECRET)
    get_settings.cache_clear()
    try:
        assert sp.hash_otp("c", "123456") == sp.hash_otp("c", "123456", secret=SECRET)
    finally:
        get_settings.cache_clear()


def test_missing_otp_secret_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core.config import get_settings

    monkeypatch.delenv("OTP_HMAC_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="OTP_HMAC_SECRET"):
            sp.hash_otp("c", "123456")
    finally:
        get_settings.cache_clear()

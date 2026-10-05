"""Security primitives shared by every auth flow (AUTH-003).

Passwords
    hash_password / verify_password - bcrypt, cost 12, constant-time verify.
    verify_password(plain, None) still runs a full bcrypt check against a dummy
    hash, so "unknown user" takes as long as "wrong password" (no user enumeration
    by timing).
    validate_password(plain, email) - policy check, returns a list of violations.

Tokens (sessions, password reset, invites)
    new_token() -> (token, sha256_hex). Store ONLY the hash; send the token.
    hash_token(token) -> sha256_hex, for looking a presented token up.

One-time passcodes (login OTP)
    new_otp() -> "042917" (6 digits).
    hash_otp(challenge_id, code) - HMAC-SHA256 keyed with otp_hmac_secret, bound
    to the challenge so a code can't be replayed against another challenge.
    verify_otp(...) compares with hmac.compare_digest.

Nothing in this module logs or returns plaintext secrets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache
from pathlib import Path

import bcrypt

from .config import get_settings

BCRYPT_COST = 12
# bcrypt only uses the first 72 bytes (bcrypt>=5 raises beyond that). Longer
# passwords (allowed up to 128 chars) are pre-hashed to a fixed 44-byte value.
_BCRYPT_MAX_BYTES = 72

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

OTP_DIGITS = 6

COMMON_PASSWORDS_FILE = Path(__file__).with_name("data") / "common_passwords.txt"

# Violation messages (stable strings; the API returns them in a 422 list).
VIOLATION_TOO_SHORT = f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
VIOLATION_TOO_LONG = f"Password must be at most {PASSWORD_MAX_LENGTH} characters long."
VIOLATION_COMMON = "Password is too common; choose something less predictable."
VIOLATION_EQUALS_EMAIL = "Password must not be the same as your email address."

# Always rejected, even if the bundled list is missing (defence in depth).
_BUILTIN_COMMON = frozenset(
    {
        "password", "password1", "password123", "passw0rd", "123456", "12345678",
        "123456789", "1234567890", "123456789012", "qwerty", "qwertyuiop", "qwerty123",
        "letmein", "welcome", "welcome123", "admin", "admin123", "iloveyou", "abc123",
        "111111", "000000", "changeme", "passwordpassword", "sustentra", "sustentra123",
    }
)


# --- passwords ---------------------------------------------------------------

def _bcrypt_input(plain: str) -> bytes:
    raw = plain.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return base64.b64encode(hashlib.sha256(raw).digest())
    return raw


def hash_password(plain: str) -> str:
    """bcrypt hash (cost 12), e.g. '$2b$12$...'."""
    return bcrypt.hashpw(_bcrypt_input(plain), bcrypt.gensalt(rounds=BCRYPT_COST)).decode("ascii")


@lru_cache(maxsize=1)
def _dummy_hash() -> bytes:
    # Same cost as real hashes so the timing matches; computed once per process.
    return hash_password(secrets.token_urlsafe(32)).encode("ascii")


def verify_password(plain: str, password_hash: str | None) -> bool:
    """Constant-time check. Pass password_hash=None when the user doesn't exist."""
    candidate = _bcrypt_input(plain)
    if not password_hash:
        bcrypt.checkpw(candidate, _dummy_hash())
        return False
    try:
        return bcrypt.checkpw(candidate, password_hash.encode("ascii"))
    except ValueError:  # malformed stored hash
        return False


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    words: set[str] = set(_BUILTIN_COMMON)
    if COMMON_PASSWORDS_FILE.is_file():
        with COMMON_PASSWORDS_FILE.open(encoding="utf-8", errors="ignore") as handle:
            words.update(line.strip().lower() for line in handle if line.strip())
    return frozenset(words)


def common_password_list_loaded() -> bool:
    """True when the bundled top-10,000 list is present (checked in tests/CI)."""
    return COMMON_PASSWORDS_FILE.is_file()


def validate_password(plain: str, email: str | None = None) -> list[str]:
    """Return every policy violation (empty list = acceptable)."""
    violations: list[str] = []
    if len(plain) < PASSWORD_MIN_LENGTH:
        violations.append(VIOLATION_TOO_SHORT)
    if len(plain) > PASSWORD_MAX_LENGTH:
        violations.append(VIOLATION_TOO_LONG)
    if plain.strip().lower() in _common_passwords():
        violations.append(VIOLATION_COMMON)
    if email and plain.strip().lower() == email.strip().lower():
        violations.append(VIOLATION_EQUALS_EMAIL)
    return violations


# --- opaque tokens -------------------------------------------------------------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """(token for the user, sha256 hex to store). 32 random bytes, URL-safe."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


# --- one-time passcodes ----------------------------------------------------------

def new_otp() -> str:
    return f"{secrets.randbelow(10**OTP_DIGITS):0{OTP_DIGITS}d}"


def _otp_key(secret: str | None) -> bytes:
    if secret is None:
        configured = get_settings().otp_hmac_secret
        if configured is None:
            raise RuntimeError("OTP_HMAC_SECRET is not configured")
        secret = configured.get_secret_value()
    if not secret:
        raise RuntimeError("OTP_HMAC_SECRET is empty")
    return secret.encode("utf-8")


def hash_otp(challenge_id: str, code: str, *, secret: str | None = None) -> str:
    """HMAC-SHA256(otp_hmac_secret, '<challenge_id>:<code>') as hex."""
    message = f"{challenge_id}:{code}".encode()
    return hmac.new(_otp_key(secret), message, hashlib.sha256).hexdigest()


def verify_otp(challenge_id: str, code: str, expected_hash: str, *, secret: str | None = None) -> bool:
    return hmac.compare_digest(hash_otp(challenge_id, code, secret=secret), expected_hash)

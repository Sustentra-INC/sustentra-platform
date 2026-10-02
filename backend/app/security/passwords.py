from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
HASH_BYTES = 32
MIN_PASSWORD_LENGTH = 8

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CLIENT_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")

# Used so missing-user logins still spend a hash cycle.
_DUMMY_SALT = os.urandom(SALT_BYTES)
_DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"not-a-real-password", _DUMMY_SALT, PBKDF2_ITERATIONS, dklen=HASH_BYTES
)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=HASH_BYTES,
    )
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=HASH_BYTES,
    )
    return hmac.compare_digest(actual, expected)


def dummy_verify(password: str) -> None:
    """Spend a hash cycle so unknown-user login timing is closer to a real check."""

    hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        _DUMMY_SALT,
        PBKDF2_ITERATIONS,
        dklen=HASH_BYTES,
    )
    hmac.compare_digest(_DUMMY_HASH, _DUMMY_HASH)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_recovery_code() -> str:
    return secrets.token_hex(5)


def validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError(
            "username must be 3-64 characters and use letters, numbers, dot, underscore, or hyphen."
        )
    return value.lower()


def validate_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not EMAIL_RE.fullmatch(value):
        raise ValueError("email is not valid.")
    return value


def validate_password(password: str) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


def validate_client_code(code: str) -> str:
    value = (code or "").strip()
    if not CLIENT_CODE_RE.fullmatch(value):
        raise ValueError(
            "client code must be 2-32 characters and start with a letter or number."
        )
    return value.lower()

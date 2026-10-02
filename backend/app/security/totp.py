from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_WINDOW = 1


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalize_secret(secret: str) -> bytes:
    padded = secret.strip().upper()
    padding = "=" * ((8 - len(padded) % 8) % 8)
    return base64.b32decode(padded + padding, casefold=True)


def hotp(secret: str, counter: int, digits: int = TOTP_DIGITS) -> str:
    key = _normalize_secret(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**digits)).zfill(digits)


def totp(
    secret: str,
    at: int | None = None,
    digits: int = TOTP_DIGITS,
    period: int = TOTP_PERIOD,
) -> str:
    timestamp = int(time.time() if at is None else at)
    counter = timestamp // period
    return hotp(secret, counter, digits=digits)


def verify_totp(
    secret: str,
    code: str,
    at: int | None = None,
    window: int = TOTP_WINDOW,
    period: int = TOTP_PERIOD,
) -> bool:
    candidate = (code or "").strip().replace(" ", "")
    if not candidate.isdigit() or len(candidate) != TOTP_DIGITS:
        return False
    timestamp = int(time.time() if at is None else at)
    counter = timestamp // period
    for offset in range(-window, window + 1):
        expected = hotp(secret, counter + offset)
        if hmac.compare_digest(expected, candidate):
            return True
    return False


def provisioning_uri(secret: str, account_name: str, issuer: str = "Sustentra") -> str:
    label = f"{issuer}:{account_name}"
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )

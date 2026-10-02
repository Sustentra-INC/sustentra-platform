from backend.app.security.totp import generate_secret, totp, verify_totp


def test_totp_round_trip():
    secret = generate_secret()
    at = 1_700_000_000
    code = totp(secret, at=at)
    assert len(code) == 6
    assert verify_totp(secret, code, at=at)
    assert verify_totp(secret, code, at=at + 29)
    assert not verify_totp(secret, "000000", at=at)

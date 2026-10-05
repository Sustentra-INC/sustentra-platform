"""Password + email-OTP login (AUTH-005).

Step 1  start_login(email, password, org_slug?)  -> challenge (OTP emailed)
Step 2  verify_login(challenge_id, code)         -> session (cookie)
        resend_code(challenge_id)                 -> new code, old one invalid

Security properties
- Every password-step failure (unknown org, unknown user, wrong password,
  inactive user/org, user without a password) returns the SAME 401 body and
  runs a full bcrypt check, so responses look and take alike.
- 5 consecutive failures lock the account for 15 minutes; a locked account
  gets 429 + Retry-After even with the correct password.
- OTP: 10-minute TTL, HMAC-stored, 3 wrong codes kill the challenge and count
  as one failed login; resend has a 60 s cooldown and a max of 3.
- No session cookie exists until the OTP step succeeds.
- Audit events never contain passwords or codes.

The caller's transaction must COMMIT on failures too (counters, audit), so the
API layer returns error responses instead of raising.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import set_provider, set_tenant
from ..core.security_primitives import hash_otp, new_otp, verify_otp, verify_password
from .audit_log import write_audit_event
from .sessions import SessionUser, create_session

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
OTP_TTL = timedelta(minutes=10)
MAX_OTP_ATTEMPTS = 3
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_RESENDS = 3

INVALID_CREDENTIALS = "Invalid credentials"
INVALID_CODE = "Invalid or expired code"


def utcnow() -> datetime:
    """Single clock for this module (tests monkeypatch it to move time)."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class RequestMeta:
    ip: str | None
    user_agent: str | None
    request_id: str | None


@dataclass
class LoginOutcome:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    # Set only on success:
    otp_email: str | None = None
    otp_code: str | None = None
    session_token: str | None = None


def _fail(detail: str = INVALID_CREDENTIALS) -> LoginOutcome:
    return LoginOutcome(401, {"detail": detail})


async def _audit(db: AsyncSession, event: str, meta: RequestMeta, *, org_id: uuid.UUID | None,
                 user_id: uuid.UUID | None = None, role: str | None = None, **metadata: Any) -> None:
    await write_audit_event(
        db, event, org_id=org_id, actor_user_id=user_id, actor_role=role,
        target_type="user" if user_id else None, target_id=str(user_id) if user_id else None,
        request_id=meta.request_id, ip_address=meta.ip, user_agent=meta.user_agent, metadata=metadata,
    )


async def _record_failure(db: AsyncSession, user: dict[str, Any], meta: RequestMeta, now: datetime,
                          reason: str) -> None:
    count = int(user["failed_login_count"]) + 1
    if count >= MAX_FAILED_LOGINS:
        await db.execute(
            text("UPDATE users SET failed_login_count = 0, locked_until = :until, updated_at = :now WHERE id = :id"),
            {"until": now + LOCKOUT, "now": now, "id": user["id"]},
        )
        await _audit(db, "login_fail", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"],
                     reason=reason)
        await _audit(db, "account_locked", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"],
                     locked_minutes=int(LOCKOUT.total_seconds() // 60))
    else:
        await db.execute(
            text("UPDATE users SET failed_login_count = :count, updated_at = :now WHERE id = :id"),
            {"count": count, "now": now, "id": user["id"]},
        )
        await _audit(db, "login_fail", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"],
                     reason=reason)


def _locked_response(locked_until: datetime, now: datetime) -> LoginOutcome:
    retry_after = max(1, math.ceil((locked_until - now).total_seconds()))
    return LoginOutcome(429, {"detail": "Too many failed attempts. Try again later."},
                        headers={"Retry-After": str(retry_after)})


# --- step 1: password -------------------------------------------------------------

async def start_login(db: AsyncSession, email: str, password: str, org_slug: str | None,
                      meta: RequestMeta) -> LoginOutcome:
    now = utcnow()
    email = email.strip().lower()

    # Resolve scope: org by slug (no RLS on organizations), or provider scope.
    org: dict[str, Any] | None = None
    if org_slug:
        org = dict((await db.execute(
            text("SELECT id, status FROM organizations WHERE slug = :slug"), {"slug": org_slug.strip().lower()}
        )).mappings().first() or {}) or None
        if org is None:
            verify_password(password, None)  # timing equalization
            await _audit(db, "login_fail", meta, org_id=None, reason="unknown_org")
            return _fail()
        await set_tenant(db, org["id"])
        user_sql = "SELECT * FROM users WHERE email = :email AND org_id = :org_id"
        params: dict[str, Any] = {"email": email, "org_id": org["id"]}
    else:
        await set_provider(db)
        user_sql = "SELECT * FROM users WHERE email = :email AND org_id IS NULL AND role = 'provider_admin'"
        params = {"email": email}

    user_row = (await db.execute(text(user_sql), params)).mappings().first()
    user = dict(user_row) if user_row else None

    if user is None:
        verify_password(password, None)
        await _audit(db, "login_fail", meta, org_id=org["id"] if org else None, reason="unknown_user")
        return _fail()

    if user["locked_until"] is not None and user["locked_until"] > now:
        return _locked_response(user["locked_until"], now)

    password_ok = verify_password(password, user["password_hash"])  # None hash -> dummy verify
    org_active = org is None or org["status"] == "active"
    if not (password_ok and user["status"] == "active" and org_active and user["password_hash"]):
        reason = (
            "no_password" if not user["password_hash"]
            else "wrong_password" if not password_ok
            else "inactive_user" if user["status"] != "active"
            else "inactive_org"
        )
        await _record_failure(db, user, meta, now, reason)
        return _fail()

    # Password OK -> new OTP challenge; earlier unused codes for this user die.
    await db.execute(
        text("UPDATE auth_tokens SET consumed_at = :now "
             "WHERE user_id = :uid AND type = 'login_otp' AND consumed_at IS NULL"),
        {"now": now, "uid": user["id"]},
    )
    challenge_id = uuid.uuid4()
    code = new_otp()
    await db.execute(
        text(
            """
            INSERT INTO auth_tokens (id, user_id, org_id, type, token_hash, created_at, expires_at, last_sent_at)
            VALUES (:id, :uid, :org_id, 'login_otp', :hash, :now, :expires, :now)
            """
        ),
        {"id": challenge_id, "uid": user["id"], "org_id": user["org_id"],
         "hash": hash_otp(str(challenge_id), code), "now": now, "expires": now + OTP_TTL},
    )
    await _audit(db, "login_password_ok", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"])
    return LoginOutcome(
        200,
        {"challenge_id": str(challenge_id), "expires_in": int(OTP_TTL.total_seconds())},
        otp_email=user["email"],
        otp_code=code,
    )


# --- challenge helpers -------------------------------------------------------------

async def _load_challenge(db: AsyncSession, challenge_id: str) -> dict[str, Any] | None:
    try:
        cid = uuid.UUID(str(challenge_id))
    except ValueError:
        return None
    row = (await db.execute(text("SELECT * FROM auth_resolve_challenge(:id)"), {"id": cid})).mappings().first()
    if row is None or row["type"] != "login_otp":
        return None
    challenge = dict(row)
    # Tenant context comes from the challenge's owner (set at the password step).
    if challenge["org_id"] is None:
        await set_provider(db)
    else:
        await set_tenant(db, challenge["org_id"])
    return challenge


def _usable(challenge: dict[str, Any], now: datetime) -> bool:
    return challenge["consumed_at"] is None and challenge["expires_at"] > now


async def _load_user_for_challenge(db: AsyncSession, challenge: dict[str, Any]) -> dict[str, Any] | None:
    row = (await db.execute(
        text("SELECT u.*, o.status AS org_status FROM users u LEFT JOIN organizations o ON o.id = u.org_id "
             "WHERE u.id = :id"),
        {"id": challenge["user_id"]},
    )).mappings().first()
    return dict(row) if row else None


# --- step 2: verify -----------------------------------------------------------------

async def verify_login(db: AsyncSession, challenge_id: str, code: str, meta: RequestMeta) -> LoginOutcome:
    now = utcnow()
    challenge = await _load_challenge(db, challenge_id)
    if challenge is None or not _usable(challenge, now):
        return _fail(INVALID_CODE)

    user = await _load_user_for_challenge(db, challenge)
    if user is None or user["status"] != "active" or (user["org_id"] and user["org_status"] != "active"):
        return _fail(INVALID_CODE)
    if user["locked_until"] is not None and user["locked_until"] > now:
        return _locked_response(user["locked_until"], now)

    if not verify_otp(str(challenge["challenge_id"]), code.strip(), challenge["token_hash"]):
        attempts = int(challenge["attempt_count"]) + 1
        if attempts >= MAX_OTP_ATTEMPTS:
            await db.execute(
                text("UPDATE auth_tokens SET attempt_count = :n, consumed_at = :now WHERE id = :id"),
                {"n": attempts, "now": now, "id": challenge["challenge_id"]},
            )
            await _audit(db, "otp_fail", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"],
                         challenge_invalidated=True)
            await _record_failure(db, user, meta, now, "otp_attempts_exhausted")
        else:
            await db.execute(
                text("UPDATE auth_tokens SET attempt_count = :n WHERE id = :id"),
                {"n": attempts, "id": challenge["challenge_id"]},
            )
            await _audit(db, "otp_fail", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"],
                         attempts=attempts)
        return _fail(INVALID_CODE)

    # Success.
    await db.execute(text("UPDATE auth_tokens SET consumed_at = :now WHERE id = :id"),
                     {"now": now, "id": challenge["challenge_id"]})
    await db.execute(
        text("UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = :now, "
             "updated_at = :now WHERE id = :id"),
        {"now": now, "id": user["id"]},
    )
    token = await create_session(db, SessionUser(id=user["id"], org_id=user["org_id"]), meta.ip, meta.user_agent)
    await db.execute(text("SELECT purge_expired_auth_rows()"))  # DB-002 opportunistic purge
    await _audit(db, "login_success", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"])
    return LoginOutcome(
        200,
        {"user_id": str(user["id"]), "org_id": str(user["org_id"]) if user["org_id"] else None, "role": user["role"]},
        session_token=token,
    )


# --- resend -------------------------------------------------------------------------

async def resend_code(db: AsyncSession, challenge_id: str, meta: RequestMeta) -> LoginOutcome:
    accepted = LoginOutcome(202, {"status": "accepted"})
    now = utcnow()
    challenge = await _load_challenge(db, challenge_id)
    if challenge is None or not _usable(challenge, now):
        return accepted  # unknown / expired / used: same answer, nothing revealed

    if challenge["resend_count"] >= MAX_RESENDS:
        return LoginOutcome(429, {"detail": "Too many codes requested. Sign in again."})
    last_sent = challenge["last_sent_at"]
    if last_sent is not None and now - last_sent < RESEND_COOLDOWN:
        wait = math.ceil((RESEND_COOLDOWN - (now - last_sent)).total_seconds())
        return LoginOutcome(429, {"detail": "Please wait before requesting another code."},
                            headers={"Retry-After": str(max(1, wait))})

    user = await _load_user_for_challenge(db, challenge)
    if user is None or user["status"] != "active":
        return accepted

    code = new_otp()
    # Replacing the stored HMAC invalidates the previous code for this challenge.
    await db.execute(
        text("UPDATE auth_tokens SET token_hash = :hash, resend_count = resend_count + 1, last_sent_at = :now, "
             "attempt_count = 0, expires_at = :expires WHERE id = :id"),
        {"hash": hash_otp(str(challenge["challenge_id"]), code), "now": now, "expires": now + OTP_TTL,
         "id": challenge["challenge_id"]},
    )
    await _audit(db, "otp_resent", meta, org_id=user["org_id"], user_id=user["id"], role=user["role"],
                 resend_count=int(challenge["resend_count"]) + 1)
    accepted.otp_email = user["email"]
    accepted.otp_code = code
    return accepted

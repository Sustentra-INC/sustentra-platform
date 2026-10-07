"""ORG-003 - invite and accept.

SKELETON ONLY. Every method raises NotImplementedError. Methods are async (MVP
runs SQLAlchemy async). The org-admin routes (create/resend) are guarded by
require_org_admin (currently 501); the public auth routes (validate/accept) follow
the AUTH-001 convention and answer 501 directly for now.

Invite tokens reuse the auth_tokens table (migration 0003), type='invite':
- The raw token is emailed; only its SHA-256 hash is stored (token_hash), matching
  how OTP/reset tokens are handled.
- TTL is 24h: expires_at = now() + 24h; `validate` and `accept` must treat an
  expired or already-consumed (consumed_at IS NOT NULL) token as invalid -> 400/410.
- `accept` sets consumed_at and the user's password_hash and marks the user active.
  It MUST NOT create a session - the user logs in normally afterwards (AUTH-005).

Other acceptance rules:
- create: the invited user is created up-front (status 'invited', DB-004) with the
  chosen role (org_admin|org_member) so the seat is reserved; 409 if the email already
  exists in the org; 422 if the org is at max_users.
- resend: issues a fresh token, invalidating prior unconsumed invite tokens for the user.
- validate: returns the invitee's names + the org name for the accept screen; it must
  not leak whether the email is otherwise registered.
"""

from __future__ import annotations

from typing import Any

# Invite token lifetime. TODO(AUTH-006/ORG-003): confirm against the shared auth-token policy.
INVITE_TTL_HOURS = 24


class InviteService:
    async def create_invite(
        self,
        *,
        org_id: str,
        email: str,
        role: str,
        first_name: str,
        last_name: str,
    ) -> dict[str, Any]:
        # TODO(DB): INSERT invited user (role, status) within max_users; 409 on duplicate email.
        # TODO(DB): INSERT auth_tokens row type='invite' storing SHA-256(token), expires_at=+24h.
        # TODO(EMAIL-001): send the invite email containing the raw token link.
        # TODO(DB-003): emit audit event 'user_invited'.
        raise NotImplementedError("ORG-003: create_invite")

    async def resend_invite(self, *, org_id: str, user_id: str) -> dict[str, Any]:
        # TODO(DB): verify the user is still in 'invited' state; 404 when missing/cross-org.
        # TODO(DB): invalidate prior unconsumed invite tokens, INSERT a fresh one (+24h).
        # TODO(EMAIL-001): resend the invite email.
        # TODO(DB-003): emit audit event 'user_invite_resent'.
        raise NotImplementedError("ORG-003: resend_invite")

    async def validate_token(self, *, token: str) -> dict[str, Any]:
        """Return {email, first_name, last_name, org_name} for a valid invite token."""
        # TODO(DB): look up auth_tokens by SHA-256(token), type='invite'; reject expired/consumed.
        # TODO(DB): join the invited user + organization for the display names.
        raise NotImplementedError("ORG-003: validate_token")

    async def accept_invite(self, *, token: str, password: str) -> dict[str, Any]:
        # TODO(DB): resolve + lock the invite token; reject expired/consumed -> 400/410.
        # TODO(AUTH-004): hash the password (same hasher as login) and set users.password_hash.
        # TODO(DB): mark the user active and set auth_tokens.consumed_at in one transaction.
        # NOTE: do NOT create a session here - the user authenticates via AUTH-005 afterwards.
        # TODO(DB-003): emit audit event 'invite_accepted'.
        raise NotImplementedError("ORG-003: accept_invite")


def get_invite_service() -> InviteService:
    """FastAPI dependency factory. TODO(AUTH-004/DB): inject the request's async session."""
    return InviteService()

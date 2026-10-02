from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActorType = Literal["sustentra_user", "client_user"]
AccountStatus = Literal["active", "disabled", "deleted"]
UserRole = Literal["admin", "operator"]
ClientStatus = Literal["active", "inactive", "deleted"]


class SustentraUser(BaseModel):
    """Internal Sustentra operator. Not a client and not stored with clients."""

    user_id: str
    username: str
    email: str
    password_salt: str
    password_hash: str
    role: UserRole = "operator"
    status: AccountStatus = "active"
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    mfa_recovery_hashes: list[str] = Field(default_factory=list)
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    last_login_at: str | None = None


class SustentraClient(BaseModel):
    """A company that uses the Sustentra app. Separate from Sustentra users."""

    client_id: str
    name: str
    code: str
    contact_email: str | None = None
    notes: str | None = None
    status: ClientStatus = "active"
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str


class ClientUser(BaseModel):
    """A person at a Sustentra client. Created by a Sustentra user."""

    client_user_id: str
    client_id: str
    username: str
    email: str
    password_salt: str
    password_hash: str
    status: AccountStatus = "active"
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    mfa_recovery_hashes: list[str] = Field(default_factory=list)
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    last_login_at: str | None = None


class AuditEvent(BaseModel):
    """Append-only record of identity and client administration actions."""

    audit_id: str
    occurred_at: str
    actor_id: str
    actor_type: ActorType | Literal["system"]
    action: str
    entity_type: str
    entity_id: str
    details: dict = Field(default_factory=dict)


class SessionRecord(BaseModel):
    session_id: str
    token: str
    actor_id: str
    actor_type: ActorType
    created_at: str
    expires_at: str
    revoked_at: str | None = None


class PasswordResetRecord(BaseModel):
    reset_id: str
    actor_id: str
    actor_type: ActorType
    token_hash: str
    created_at: str
    expires_at: str
    used_at: str | None = None


class MfaChallengeRecord(BaseModel):
    challenge_id: str
    actor_id: str
    actor_type: ActorType
    token: str
    created_at: str
    expires_at: str
    consumed_at: str | None = None

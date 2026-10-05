from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, cast
from uuid import uuid4

from backend.app.domain.identity import (
    AuditEvent,
    ClientUser,
    MfaChallengeRecord,
    PasswordResetRecord,
    SessionRecord,
    SustentraClient,
    SustentraUser,
)
from backend.app.repositories.identity_repository import IdentityRepository
from backend.app.security.passwords import (
    dummy_verify,
    hash_password,
    hash_token,
    new_recovery_code,
    new_token,
    validate_client_code,
    validate_email,
    validate_password,
    validate_username,
    verify_password,
)
from backend.app.security.totp import generate_secret, provisioning_uri, totp, verify_totp

SENSITIVE_FIELDS = {
    "password_salt",
    "password_hash",
    "mfa_secret",
    "mfa_recovery_hashes",
    "token",
    "token_hash",
}

SESSION_HOURS = 8
RESET_MINUTES = 30
MFA_CHALLENGE_MINUTES = 5
ISSUER = "Sustentra"


class IdentityError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def public_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {key: value for key, value in record.items() if key not in SENSITIVE_FIELDS}


class IdentityService:
    """Users, clients, login, MFA, reset, and audit without a database."""

    def __init__(
        self,
        repository: IdentityRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        totp_time: Callable[[], int] | None = None,
        return_dev_tokens: bool = True,
    ) -> None:
        self._repository = repository or IdentityRepository.in_memory()
        self._clock = clock or _now
        self._totp_time = totp_time
        self._return_dev_tokens = return_dev_tokens

    @property
    def persistence(self) -> str:
        from backend.app.repositories.identity_repository import JsonlRecordStore

        if isinstance(self._repository.users, JsonlRecordStore):
            return "jsonl"
        return "memory"

    def _stamp(self) -> str:
        return self._clock().isoformat()

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"

    def _audit(
        self,
        *,
        actor_id: str,
        actor_type: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = AuditEvent(
            audit_id=self._id("aud"),
            occurred_at=self._stamp(),
            actor_id=actor_id,
            actor_type=actor_type,  # type: ignore[arg-type]
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        ).model_dump()
        return self._repository.audit.save(record)

    def bootstrap_required(self) -> bool:
        return len(self._repository.users.list_active("user_id")) == 0

    def status(self) -> dict[str, Any]:
        return {
            "bootstrap_required": self.bootstrap_required(),
            "persistence": self.persistence,
            "sustentra_user_count": len(self._repository.users.list_active("user_id")),
            "client_count": len(self._repository.clients.list_active("client_id")),
        }

    def _require_unique_login(self, username: str, email: str, *, exclude_id: str | None = None) -> None:
        existing_user = self._find_login_record(username) or self._find_login_record(email)
        if existing_user and existing_user.get("user_id") != exclude_id and existing_user.get("client_user_id") != exclude_id:
            raise IdentityError("username or email is already in use.", 409)

    def _find_login_record(self, username_or_email: str) -> dict[str, Any] | None:
        needle = (username_or_email or "").strip().lower()
        if not needle:
            return None

        def user_match(record: dict[str, Any]) -> bool:
            return record.get("username") == needle or record.get("email") == needle

        user = self._repository.users.find_latest(user_match)
        if user:
            user = dict(user)
            user["actor_type"] = "sustentra_user"
            user["actor_id"] = user["user_id"]
            return user

        client_user = self._repository.client_users.find_latest(user_match)
        if client_user:
            client_user = dict(client_user)
            client_user["actor_type"] = "client_user"
            client_user["actor_id"] = client_user["client_user_id"]
            return client_user
        return None

    def create_sustentra_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        role: str = "operator",
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bootstrap = self.bootstrap_required()
        if not bootstrap:
            self._require_sustentra_user(actor)
        username = validate_username(username)
        email = validate_email(email)
        password = validate_password(password)
        if role not in {"admin", "operator"}:
            raise IdentityError("role must be admin or operator.")
        if bootstrap:
            role = "admin"
        self._require_unique_login(username, email)

        now = self._stamp()
        actor_id = (actor or {}).get("actor_id") or "system"
        salt, hashed = hash_password(password)
        record = SustentraUser(
            user_id=self._id("usr"),
            username=username,
            email=email,
            password_salt=salt,
            password_hash=hashed,
            role=role,  # type: ignore[arg-type]
            status="active",
            created_at=now,
            created_by=actor_id,
            updated_at=now,
            updated_by=actor_id,
        ).model_dump()
        saved = self._repository.users.save(record)
        self._audit(
            actor_id=actor_id,
            actor_type=(actor or {}).get("actor_type") or "system",
            action="user.create",
            entity_type="sustentra_user",
            entity_id=saved["user_id"],
            details={"username": username, "bootstrap": bootstrap, "role": role},
        )
        return public_record(saved)  # type: ignore[return-value]

    def list_sustentra_users(self, actor: dict[str, Any]) -> list[dict[str, Any]]:
        self._require_sustentra_user(actor)
        return [public_record(record) for record in self._repository.users.list_active("user_id")]  # type: ignore[misc]

    def get_sustentra_user(self, user_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        record = self._repository.users.get_by_id("user_id", user_id)
        if record is None:
            raise IdentityError("user not found.", 404)
        return public_record(record)  # type: ignore[return-value]

    def login(self, username_or_email: str, password: str) -> dict[str, Any]:
        record = self._find_login_record(username_or_email)
        if record is None:
            dummy_verify(password or "")
            self._audit(
                actor_id="anonymous",
                actor_type="system",
                action="auth.login_failed",
                entity_type="login",
                entity_id=username_or_email.strip().lower() or "unknown",
                details={"reason": "unknown_user"},
            )
            raise IdentityError("Invalid username or password.", 401)
        if record.get("status") != "active":
            dummy_verify(password or "")
            raise IdentityError("This account is disabled.", 403)
        if not verify_password(password, record["password_salt"], record["password_hash"]):
            self._audit(
                actor_id=record["actor_id"],
                actor_type=record["actor_type"],
                action="auth.login_failed",
                entity_type=record["actor_type"],
                entity_id=record["actor_id"],
                details={"reason": "bad_password"},
            )
            raise IdentityError("Invalid username or password.", 401)

        if record.get("mfa_enabled"):
            challenge = self._create_mfa_challenge(record)
            self._audit(
                actor_id=record["actor_id"],
                actor_type=record["actor_type"],
                action="auth.mfa_challenge",
                entity_type=record["actor_type"],
                entity_id=record["actor_id"],
            )
            return {
                "mfa_required": True,
                "mfa_token": challenge["token"],
                "expires_at": challenge["expires_at"],
                "actor_type": record["actor_type"],
            }

        return self._issue_session(record)

    def complete_mfa_login(self, mfa_token: str, code: str) -> dict[str, Any]:
        challenge = self._repository.challenges.find_latest(
            lambda record: record.get("token") == mfa_token,
            include_deleted=True,
        )
        if challenge is None or challenge.get("consumed_at"):
            raise IdentityError("MFA challenge is invalid or expired.", 401)
        if challenge["expires_at"] < self._stamp():
            raise IdentityError("MFA challenge is invalid or expired.", 401)

        record = self._actor_record(challenge["actor_id"], challenge["actor_type"])
        if record is None or not record.get("mfa_enabled"):
            raise IdentityError("MFA challenge is invalid or expired.", 401)

        accepted = False
        if record.get("mfa_secret") and verify_totp(
            record["mfa_secret"], code, at=self._totp_now()
        ):
            accepted = True
        elif self._match_recovery_code(record, code):
            accepted = True
            self._consume_recovery_code(record, code)

        if not accepted:
            self._audit(
                actor_id=record["actor_id"],
                actor_type=record["actor_type"],
                action="auth.mfa_failed",
                entity_type=record["actor_type"],
                entity_id=record["actor_id"],
            )
            raise IdentityError("Invalid MFA code.", 401)

        challenge["consumed_at"] = self._stamp()
        self._repository.challenges.save(challenge)
        return self._issue_session(record)

    def logout(self, token: str, actor: dict[str, Any] | None = None) -> dict[str, str]:
        session = self._repository.sessions.find_latest(
            lambda record: record.get("token") == token,
            include_deleted=True,
        )
        if session and not session.get("revoked_at"):
            session["revoked_at"] = self._stamp()
            self._repository.sessions.save(session)
            self._audit(
                actor_id=session["actor_id"],
                actor_type=session["actor_type"],
                action="auth.logout",
                entity_type=session["actor_type"],
                entity_id=session["actor_id"],
            )
        return {"status": "logged_out"}

    def resolve_session(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        session = self._repository.sessions.find_latest(
            lambda record: record.get("token") == token,
            include_deleted=True,
        )
        if session is None or session.get("revoked_at"):
            return None
        if session["expires_at"] < self._stamp():
            return None
        record = self._actor_record(session["actor_id"], session["actor_type"])
        if record is None or record.get("status") != "active":
            return None
        public = public_record(record)
        assert public is not None
        public["actor_id"] = record["actor_id"]
        public["actor_type"] = record["actor_type"]
        public["session_id"] = session["session_id"]
        return public

    def request_password_reset(self, email: str) -> dict[str, Any]:
        email = validate_email(email)
        record = self._find_login_record(email)
        response: dict[str, Any] = {
            "status": "accepted",
            "message": "If the email exists, a reset token has been issued.",
        }
        if record is None or record.get("status") != "active":
            return response

        raw_token = new_token()
        now = self._clock()
        reset = PasswordResetRecord(
            reset_id=self._id("rst"),
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            token_hash=hash_token(raw_token),
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=RESET_MINUTES)).isoformat(),
        ).model_dump()
        self._repository.resets.save(reset)
        self._audit(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            action="auth.password_reset_requested",
            entity_type=record["actor_type"],
            entity_id=record["actor_id"],
        )
        if self._return_dev_tokens:
            response["dev_reset_token"] = raw_token
            response["expires_at"] = reset["expires_at"]
        return response

    def confirm_password_reset(self, token: str, new_password: str) -> dict[str, Any]:
        new_password = validate_password(new_password)
        token_hash = hash_token(token)
        reset = self._repository.resets.find_latest(
            lambda record: record.get("token_hash") == token_hash,
            include_deleted=True,
        )
        if reset is None or reset.get("used_at"):
            raise IdentityError("Reset token is invalid or expired.", 400)
        if reset["expires_at"] < self._stamp():
            raise IdentityError("Reset token is invalid or expired.", 400)

        record = self._actor_record(reset["actor_id"], reset["actor_type"])
        if record is None:
            raise IdentityError("Reset token is invalid or expired.", 400)

        salt, hashed = hash_password(new_password)
        record["password_salt"] = salt
        record["password_hash"] = hashed
        record["updated_at"] = self._stamp()
        record["updated_by"] = record["actor_id"]
        self._save_actor(record)

        reset["used_at"] = self._stamp()
        self._repository.resets.save(reset)
        self._revoke_actor_sessions(record["actor_id"])
        self._audit(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            action="auth.password_reset_completed",
            entity_type=record["actor_type"],
            entity_id=record["actor_id"],
        )
        return {"status": "password_updated"}

    def setup_mfa(self, actor: dict[str, Any]) -> dict[str, Any]:
        record = self._require_active_actor(actor)
        if record.get("mfa_enabled"):
            raise IdentityError("MFA is already enabled.")
        secret = generate_secret()
        record["mfa_secret"] = secret
        record["updated_at"] = self._stamp()
        record["updated_by"] = record["actor_id"]
        self._save_actor(record)
        account_name = record["username"]
        self._audit(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            action="auth.mfa_setup_started",
            entity_type=record["actor_type"],
            entity_id=record["actor_id"],
        )
        return {
            "mfa_enabled": False,
            "secret": secret,
            "otpauth_uri": provisioning_uri(secret, account_name, ISSUER),
            "dev_current_code": totp(secret, at=self._totp_now()) if self._return_dev_tokens else None,
        }

    def confirm_mfa(self, actor: dict[str, Any], code: str) -> dict[str, Any]:
        record = self._require_active_actor(actor)
        secret = record.get("mfa_secret")
        if not secret:
            raise IdentityError("Start MFA setup first.")
        if not verify_totp(secret, code, at=self._totp_now()):
            raise IdentityError("Invalid MFA code.", 400)

        recovery_codes = [new_recovery_code() for _ in range(8)]
        record["mfa_enabled"] = True
        record["mfa_recovery_hashes"] = [hash_token(code) for code in recovery_codes]
        record["updated_at"] = self._stamp()
        record["updated_by"] = record["actor_id"]
        self._save_actor(record)
        self._audit(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            action="auth.mfa_enabled",
            entity_type=record["actor_type"],
            entity_id=record["actor_id"],
        )
        return {"mfa_enabled": True, "recovery_codes": recovery_codes}

    def disable_mfa(self, actor: dict[str, Any], password: str, code: str) -> dict[str, Any]:
        record = self._require_active_actor(actor)
        if not verify_password(password, record["password_salt"], record["password_hash"]):
            raise IdentityError("Invalid password.", 401)
        if record.get("mfa_enabled"):
            secret = record.get("mfa_secret")
            recovery_ok = self._match_recovery_code(record, code)
            totp_ok = isinstance(secret, str) and bool(secret) and verify_totp(secret, code, at=self._totp_now())
            if not totp_ok and not recovery_ok:
                raise IdentityError("Invalid MFA code.", 401)
        record["mfa_enabled"] = False
        record["mfa_secret"] = None
        record["mfa_recovery_hashes"] = []
        record["updated_at"] = self._stamp()
        record["updated_by"] = record["actor_id"]
        self._save_actor(record)
        self._audit(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            action="auth.mfa_disabled",
            entity_type=record["actor_type"],
            entity_id=record["actor_id"],
        )
        return {"mfa_enabled": False}

    def create_client(
        self,
        *,
        name: str,
        code: str,
        contact_email: str | None,
        notes: str | None,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        name = (name or "").strip()
        if not name:
            raise IdentityError("client name is required.")
        code = validate_client_code(code)
        contact = validate_email(contact_email) if contact_email else None
        existing = self._repository.clients.find_latest(
            lambda record: record.get("code") == code
        )
        if existing:
            raise IdentityError("client code is already in use.", 409)

        now = self._stamp()
        record = SustentraClient(
            client_id=self._id("cli"),
            name=name,
            code=code,
            contact_email=contact,
            notes=(notes or "").strip() or None,
            status="active",
            created_at=now,
            created_by=actor["actor_id"],
            updated_at=now,
            updated_by=actor["actor_id"],
        ).model_dump()
        saved = self._repository.clients.save(record)
        self._audit(
            actor_id=actor["actor_id"],
            actor_type=actor["actor_type"],
            action="client.create",
            entity_type="client",
            entity_id=saved["client_id"],
            details={"name": name, "code": code},
        )
        return saved

    def list_clients(self, actor: dict[str, Any]) -> list[dict[str, Any]]:
        if actor.get("actor_type") == "client_user":
            client = self._repository.clients.get_by_id("client_id", actor["client_id"])
            return [client] if client else []
        self._require_sustentra_user(actor)
        return self._repository.clients.list_active("client_id")

    def get_client(self, client_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        record = self._repository.clients.get_by_id("client_id", client_id)
        if record is None:
            raise IdentityError("client not found.", 404)
        if actor.get("actor_type") == "client_user" and actor.get("client_id") != client_id:
            raise IdentityError("not allowed.", 403)
        if actor.get("actor_type") != "client_user":
            self._require_sustentra_user(actor)
        return record

    def update_client(
        self,
        client_id: str,
        actor: dict[str, Any],
        *,
        name: str | None = None,
        code: str | None = None,
        contact_email: str | None = None,
        notes: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        record = self._repository.clients.get_by_id("client_id", client_id)
        if record is None:
            raise IdentityError("client not found.", 404)
        if name is not None:
            name = name.strip()
            if not name:
                raise IdentityError("client name is required.")
            record["name"] = name
        if code is not None:
            code = validate_client_code(code)
            existing = self._repository.clients.find_latest(
                lambda item: item.get("code") == code and item.get("client_id") != client_id
            )
            if existing:
                raise IdentityError("client code is already in use.", 409)
            record["code"] = code
        if contact_email is not None:
            record["contact_email"] = validate_email(contact_email) if contact_email else None
        if notes is not None:
            record["notes"] = notes.strip() or None
        if status is not None:
            if status not in {"active", "inactive"}:
                raise IdentityError("status must be active or inactive.")
            record["status"] = status
        record["updated_at"] = self._stamp()
        record["updated_by"] = actor["actor_id"]
        saved = self._repository.clients.save(SustentraClient(**record).model_dump())
        self._audit(
            actor_id=actor["actor_id"],
            actor_type=actor["actor_type"],
            action="client.update",
            entity_type="client",
            entity_id=client_id,
            details={"fields": [key for key in ("name", "code", "contact_email", "notes", "status") if locals()[key] is not None]},
        )
        return saved

    def delete_client(self, client_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        record = self._repository.clients.get_by_id("client_id", client_id)
        if record is None:
            raise IdentityError("client not found.", 404)
        record["status"] = "deleted"
        record["updated_at"] = self._stamp()
        record["updated_by"] = actor["actor_id"]
        self._repository.clients.save(record)
        for client_user in self._repository.client_users.list_active("client_user_id"):
            if client_user.get("client_id") == client_id:
                client_user["status"] = "deleted"
                client_user["updated_at"] = self._stamp()
                client_user["updated_by"] = actor["actor_id"]
                self._repository.client_users.save(client_user)
                self._revoke_actor_sessions(client_user["client_user_id"])
        self._audit(
            actor_id=actor["actor_id"],
            actor_type=actor["actor_type"],
            action="client.delete",
            entity_type="client",
            entity_id=client_id,
            details={"name": record.get("name"), "code": record.get("code")},
        )
        return {"client_id": client_id, "status": "deleted"}

    def create_client_user(
        self,
        *,
        client_id: str,
        username: str,
        email: str,
        password: str,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        client = self._repository.clients.get_by_id("client_id", client_id)
        if client is None or client.get("status") == "inactive":
            raise IdentityError("client not found.", 404)
        username = validate_username(username)
        email = validate_email(email)
        password = validate_password(password)
        self._require_unique_login(username, email)
        now = self._stamp()
        salt, hashed = hash_password(password)
        record = ClientUser(
            client_user_id=self._id("cu"),
            client_id=client_id,
            username=username,
            email=email,
            password_salt=salt,
            password_hash=hashed,
            status="active",
            created_at=now,
            created_by=actor["actor_id"],
            updated_at=now,
            updated_by=actor["actor_id"],
        ).model_dump()
        saved = self._repository.client_users.save(record)
        self._audit(
            actor_id=actor["actor_id"],
            actor_type=actor["actor_type"],
            action="client_user.create",
            entity_type="client_user",
            entity_id=saved["client_user_id"],
            details={"client_id": client_id, "username": username},
        )
        return public_record(saved)  # type: ignore[return-value]

    def list_client_users(self, client_id: str, actor: dict[str, Any]) -> list[dict[str, Any]]:
        self.get_client(client_id, actor)
        if actor.get("actor_type") == "client_user":
            own = self._repository.client_users.get_by_id("client_user_id", actor["actor_id"])
            return [cast(dict[str, Any], public_record(own))] if own else []
        return [
            cast(dict[str, Any], public_record(record))
            for record in self._repository.client_users.list_active("client_user_id")
            if record.get("client_id") == client_id
        ]

    def update_client_user(
        self,
        client_id: str,
        client_user_id: str,
        actor: dict[str, Any],
        *,
        email: str | None = None,
        status: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        record = self._repository.client_users.get_by_id("client_user_id", client_user_id)
        if record is None or record.get("client_id") != client_id:
            raise IdentityError("client user not found.", 404)
        if email is not None:
            email = validate_email(email)
            self._require_unique_login(record["username"], email, exclude_id=client_user_id)
            record["email"] = email
        if status is not None:
            if status not in {"active", "disabled"}:
                raise IdentityError("status must be active or disabled.")
            record["status"] = status
            if status == "disabled":
                self._revoke_actor_sessions(client_user_id)
        if password is not None:
            password = validate_password(password)
            salt, hashed = hash_password(password)
            record["password_salt"] = salt
            record["password_hash"] = hashed
            self._revoke_actor_sessions(client_user_id)
        record["updated_at"] = self._stamp()
        record["updated_by"] = actor["actor_id"]
        saved = self._repository.client_users.save(ClientUser(**record).model_dump())
        self._audit(
            actor_id=actor["actor_id"],
            actor_type=actor["actor_type"],
            action="client_user.update",
            entity_type="client_user",
            entity_id=client_user_id,
        )
        return public_record(saved)  # type: ignore[return-value]

    def delete_client_user(
        self, client_id: str, client_user_id: str, actor: dict[str, Any]
    ) -> dict[str, Any]:
        self._require_sustentra_user(actor)
        record = self._repository.client_users.get_by_id("client_user_id", client_user_id)
        if record is None or record.get("client_id") != client_id:
            raise IdentityError("client user not found.", 404)
        record["status"] = "deleted"
        record["updated_at"] = self._stamp()
        record["updated_by"] = actor["actor_id"]
        self._repository.client_users.save(record)
        self._revoke_actor_sessions(client_user_id)
        self._audit(
            actor_id=actor["actor_id"],
            actor_type=actor["actor_type"],
            action="client_user.delete",
            entity_type="client_user",
            entity_id=client_user_id,
        )
        return {"client_user_id": client_user_id, "status": "deleted"}

    def list_audit_events(
        self,
        actor: dict[str, Any],
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_sustentra_user(actor)
        events = self._repository.audit._versions()
        if entity_type:
            events = [event for event in events if event.get("entity_type") == entity_type]
        if entity_id:
            events = [event for event in events if event.get("entity_id") == entity_id]
        return list(reversed(events[-limit:]))

    def _totp_now(self) -> int:
        if self._totp_time is not None:
            return self._totp_time()
        return int(self._clock().timestamp())

    def _require_sustentra_user(self, actor: dict[str, Any] | None) -> dict[str, Any]:
        if not actor or actor.get("actor_type") != "sustentra_user":
            raise IdentityError("Sustentra user authentication is required.", 403)
        return actor

    def _require_active_actor(self, actor: dict[str, Any]) -> dict[str, Any]:
        record = self._actor_record(actor["actor_id"], actor["actor_type"])
        if record is None or record.get("status") != "active":
            raise IdentityError("Not authenticated.", 401)
        return record

    def _actor_record(self, actor_id: str, actor_type: str) -> dict[str, Any] | None:
        if actor_type == "sustentra_user":
            record = self._repository.users.get_by_id("user_id", actor_id)
            if record:
                record = dict(record)
                record["actor_type"] = "sustentra_user"
                record["actor_id"] = record["user_id"]
            return record
        record = self._repository.client_users.get_by_id("client_user_id", actor_id)
        if record:
            record = dict(record)
            record["actor_type"] = "client_user"
            record["actor_id"] = record["client_user_id"]
        return record

    def _save_actor(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.pop("actor_type", None)
        payload.pop("actor_id", None)
        if record["actor_type"] == "sustentra_user":
            return self._repository.users.save(SustentraUser(**payload).model_dump())
        return self._repository.client_users.save(ClientUser(**payload).model_dump())

    def _create_mfa_challenge(self, record: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        challenge = MfaChallengeRecord(
            challenge_id=self._id("mfa"),
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            token=new_token(24),
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=MFA_CHALLENGE_MINUTES)).isoformat(),
        ).model_dump()
        return self._repository.challenges.save(challenge)

    def _issue_session(self, record: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        session = SessionRecord(
            session_id=self._id("ses"),
            token=new_token(),
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=SESSION_HOURS)).isoformat(),
        ).model_dump()
        saved = self._repository.sessions.save(session)
        record["last_login_at"] = now.isoformat()
        record["updated_at"] = now.isoformat()
        self._save_actor(record)
        self._audit(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            action="auth.login",
            entity_type=record["actor_type"],
            entity_id=record["actor_id"],
        )
        public = public_record(record)
        assert public is not None
        public["actor_id"] = record["actor_id"]
        public["actor_type"] = record["actor_type"]
        return {
            "mfa_required": False,
            "token": saved["token"],
            "expires_at": saved["expires_at"],
            "actor_type": record["actor_type"],
            "actor": public,
        }

    def _revoke_actor_sessions(self, actor_id: str) -> None:
        now = self._stamp()
        seen: set[str] = set()
        for session in reversed(self._repository.sessions._versions()):
            if session.get("actor_id") != actor_id:
                continue
            if session["session_id"] in seen:
                continue
            seen.add(session["session_id"])
            session_id: str = session["session_id"]

            def _same_session(record: dict[str, Any], session_id: str = session_id) -> bool:
                return record.get("session_id") == session_id

            latest = self._repository.sessions.find_latest(_same_session, include_deleted=True)
            if latest and not latest.get("revoked_at"):
                latest["revoked_at"] = now
                self._repository.sessions.save(latest)

    def _match_recovery_code(self, record: dict[str, Any], code: str) -> bool:
        candidate = hash_token((code or "").strip().lower())
        return candidate in (record.get("mfa_recovery_hashes") or [])

    def _consume_recovery_code(self, record: dict[str, Any], code: str) -> None:
        candidate = hash_token((code or "").strip().lower())
        hashes = [item for item in record.get("mfa_recovery_hashes") or [] if item != candidate]
        record["mfa_recovery_hashes"] = hashes
        self._save_actor(record)

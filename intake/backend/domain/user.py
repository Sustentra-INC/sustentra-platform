"""User and role model (intake Stage 0).

Roles come from ``intake/SPEC.md`` section 3. A user belongs to exactly one org
in v1 (SPEC section 8: single org per user, no SSO, no password auth).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Role = Literal["client_owner", "client_member", "sustentra_reviewer"]
UserStatus = Literal["active", "disabled"]


class User(BaseModel):
    user_id: str
    org_id: str
    email: str
    name: str
    role: Role
    status: UserStatus = "active"
    created_at: str
    last_login_at: str | None = None

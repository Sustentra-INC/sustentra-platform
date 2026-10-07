"""One vocabulary for organizations and users, shared by the API and the database (DB-004).

The database stores exactly these values (migrations 0005 + 0009); there is no
translation layer between API and DB, so ORG-001/002/003 cannot disagree.

Organizations
    status     active | suspended          suspended orgs cannot log in (0005)
    max_users  seat limit, 1..10000, default 25 (0009)

Users
    role       provider_admin | org_admin | org_member
    status     invited | active | suspended | deleted
               invited   - created by an invite (ORG-003), cannot log in until accepted
               active    - the only status that can log in / hold a session
               suspended - turned off by an org or provider admin (ORG-002); was 'disabled'
               deleted   - erased (COMP-001); never counted against max_users
"""

from __future__ import annotations

from typing import Final, Literal

OrgStatus = Literal["active", "suspended"]
UserRole = Literal["provider_admin", "org_admin", "org_member"]
UserStatus = Literal["invited", "active", "suspended", "deleted"]

ORG_STATUSES: Final = ("active", "suspended")
USER_ROLES: Final = ("provider_admin", "org_admin", "org_member")
# Roles an org admin may assign; provider_admin is never assignable through the API.
ASSIGNABLE_ROLES: Final = ("org_admin", "org_member")
USER_STATUSES: Final = ("invited", "active", "suspended", "deleted")
# Statuses an org admin can see / filter on (deleted users are gone from the API).
LISTED_USER_STATUSES: Final = ("invited", "active", "suspended")
# Statuses that occupy a seat (invited users hold theirs until accepted or removed).
SEATED_USER_STATUSES: Final = ("invited", "active", "suspended")

DEFAULT_MAX_USERS: Final = 25
MAX_MAX_USERS: Final = 10_000

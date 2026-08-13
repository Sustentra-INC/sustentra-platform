"""Audit log entry.

Every change to a datapoint state is appended here: who, when, old value, new
value. intake/SPEC.md section 6 puts it plainly - for a verification company the
edit history is itself evidence - so entries are written for status changes,
value changes and escalation resolutions alike, and are never edited or deleted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

AuditAction = Literal[
    "state_created",
    "status_changed",
    "value_changed",
    "escalation_opened",
    "escalation_resolved",
    # Phase E: changes to the facts themselves, not just the answers. A moved
    # reporting period or a site switched from owned to leased changes what the
    # answers mean, so it belongs in the same history.
    "org_fact_changed",
    "site_created",
    "site_fact_changed",
]


class AuditLogEntry(BaseModel):
    audit_id: str
    org_id: str
    action: AuditAction
    entity_type: str
    entity_id: str
    datapoint_id: str | None = None
    scope_ref: str | None = None
    field: str | None = None
    old_value: object | None = None
    new_value: object | None = None
    actor_id: str
    actor_role: str | None = None
    reason: str | None = None
    at: str

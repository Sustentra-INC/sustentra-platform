"""Audit company and site facts (Phase E).

Phase C1's state machine audits every change to an *answer*. Nothing audited
changes to the *facts* - the reporting period, a site's name, whether a site is
owned or leased. A client could resubmit the seed form, move their reporting
period by a month, and leave no trace.

For a verification product that is a hole, not a nicety: the profile page claims
to be versioned, and the boundary answers downstream depend on facts like
ownership. This service closes it, using the same append-only audit log so there
is one history rather than two.

It records what changed, never why - the why lives in the seed-form submission
that caused it, which is stored separately and referenced by ``reason``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.domain.audit_log import AuditLogEntry
from intake.backend.repositories.audit_log_repository import AuditLogRepository

#: Fields worth a history entry. Timestamps and derived bookkeeping are not:
#: "updated_at changed" is noise that would bury the real changes.
ORG_FIELDS = (
    "legal_name",
    "reporting_year",
    "industry",
    "industry_overlay_id",
    "reporting_period_start",
    "reporting_period_end",
    "fiscal_year_basis",
    "responsible_party",
    "profile_status",
)

SITE_FIELDS = (
    "site_name",
    "address",
    "operational_status",
    "site_type",
    "ownership",
    "lease_type",
    "ownership_note",
    "period_in_scope_start",
    "period_in_scope_end",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileAuditService:
    def __init__(
        self,
        audit_repository: AuditLogRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._audit = audit_repository
        self._clock = clock

    def record_org_change(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        actor_id: str,
        actor_role: str | None = None,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._diff(
            before=before,
            after=after,
            fields=ORG_FIELDS,
            action="org_fact_changed",
            entity_type="org",
            entity_id=after["org_id"],
            org_id=after["org_id"],
            scope_ref=None,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
        )

    def record_site_change(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        actor_id: str,
        actor_role: str | None = None,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        """A new site is one 'site_created' entry, not nine field changes."""
        if before is None:
            return [
                self._write(
                    org_id=after["org_id"],
                    action="site_created",
                    entity_type="site",
                    entity_id=after["site_id"],
                    scope_ref=after["site_id"],
                    field=None,
                    old=None,
                    new=after.get("site_name"),
                    actor_id=actor_id,
                    actor_role=actor_role,
                    reason=reason,
                )
            ]

        return self._diff(
            before=before,
            after=after,
            fields=SITE_FIELDS,
            action="site_fact_changed",
            entity_type="site",
            entity_id=after["site_id"],
            org_id=after["org_id"],
            scope_ref=after["site_id"],
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
        )

    # -- internals ----------------------------------------------------------

    def _diff(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        fields: tuple[str, ...],
        action: str,
        entity_type: str,
        entity_id: str,
        org_id: str,
        scope_ref: str | None,
        actor_id: str,
        actor_role: str | None,
        reason: str | None,
    ) -> list[dict[str, Any]]:
        written = []
        for field in fields:
            old = (before or {}).get(field)
            new = after.get(field)
            if old == new:
                continue
            written.append(
                self._write(
                    org_id=org_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    scope_ref=scope_ref,
                    field=field,
                    old=old,
                    new=new,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    reason=reason,
                )
            )
        return written

    def _write(
        self,
        org_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        scope_ref: str | None,
        field: str | None,
        old: Any,
        new: Any,
        actor_id: str,
        actor_role: str | None,
        reason: str | None,
    ) -> dict[str, Any]:
        return self._audit.save(
            AuditLogEntry(
                audit_id=f"aud_{uuid.uuid4().hex[:12]}",
                org_id=org_id,
                action=action,  # type: ignore[arg-type]
                entity_type=entity_type,
                entity_id=entity_id,
                datapoint_id=None,
                scope_ref=scope_ref,
                field=field,
                old_value=old,
                new_value=new,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=reason,
                at=self._clock().isoformat(),
            )
        )

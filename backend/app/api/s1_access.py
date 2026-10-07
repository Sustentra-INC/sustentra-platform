"""SEC-001 - session + organization scoping for the S1 workpaper routes.

Every S1 route requires a valid session (401 otherwise):

* ``s1_reader`` - org_admin / org_member of the owning org, or provider_admin
  (support, read-only across orgs);
* ``s1_writer`` - org_admin / org_member only (upload, process, review, project);
  a provider_admin gets 403.

S1 records (documents, pipeline runs, review decisions, approved evidence) carry
the ``org_id`` of the caller who created them. A caller from another org gets 404,
never 403, so the existence of another org's data is not revealed. Records written
before SEC-001 have no ``org_id``: only a provider_admin can see them until they are
claimed for an org (``python -m backend.app.cli claim-s1-data``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException

from ..core.auth import CurrentUser, require_role

S1_READ_ROLES = ("org_admin", "org_member", "provider_admin")
S1_WRITE_ROLES = ("org_admin", "org_member")

s1_reader = require_role("org_admin", "org_member", "provider_admin")
s1_writer = require_role("org_admin", "org_member")


def org_of(user: CurrentUser) -> str:
    """The caller's org id as stored on S1 records (writers always have one)."""

    if user.org_id is None:  # pragma: no cover - s1_writer excludes provider_admin
        raise HTTPException(status_code=403, detail="Forbidden")
    return str(user.org_id)


def can_see(record: dict[str, Any] | None, user: CurrentUser) -> bool:
    if record is None:
        return False
    if user.is_provider:
        return True
    owner = record.get("org_id")
    return owner is not None and str(owner) == str(user.org_id)


def visible(records: Iterable[dict[str, Any]], user: CurrentUser) -> list[dict[str, Any]]:
    return [record for record in records if can_see(record, user)]


def require_visible(record: dict[str, Any] | None, user: CurrentUser, detail: str) -> dict[str, Any]:
    """The record, or 404 when it does not exist or belongs to another org."""

    if not can_see(record, user):
        raise HTTPException(status_code=404, detail=detail)
    assert record is not None
    return record


def evidence_records(evidence_id: str) -> list[dict[str, Any]]:
    """Every S1 record that references an evidence id: documents, pipeline runs,
    review decisions and approved evidence. Together they establish its owner."""

    from . import documents as documents_api
    from . import evidence as evidence_api
    from . import pipeline as pipeline_api
    from . import reviews as reviews_api

    if not evidence_id or not str(evidence_id).strip():
        return []
    return [
        *documents_api.current_upload_service().list_documents_by_evidence(evidence_id),
        *pipeline_api.current_service().list_runs_by_evidence(evidence_id),
        *reviews_api.current_service().list_by_evidence(evidence_id),
        *evidence_api.current_service().list_by_evidence(evidence_id),
    ]


def evidence_visible(evidence_id: str, user: CurrentUser) -> bool:
    """An evidence id is visible when every record referencing it is visible: one
    unowned or foreign record (e.g. a pre-SEC-001 review) hides it from org users."""

    records = evidence_records(evidence_id)
    return bool(records) and all(can_see(record, user) for record in records)


def require_evidence(evidence_id: str, user: CurrentUser, detail: str = "Evidence not found.") -> None:
    if not evidence_visible(evidence_id, user):
        raise HTTPException(status_code=404, detail=detail)


def evidence_free_or_own(evidence_id: str, user: CurrentUser) -> bool:
    """For writes that name an evidence id: unused, or already owned by the caller."""

    records = evidence_records(evidence_id)
    return not records or all(can_see(record, user) and record.get("org_id") is not None for record in records)


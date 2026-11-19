"""vehicle groups get a stable group_id (S1-BE-012).

A mobile line's anchor was ``vg-<slug of the group's label>``, numbered by order among groups whose
labels give the same slug, so removing or reordering a group renumbered the others and a document placed
by hand could land on another group's line. A group now carries a ``group_id`` the server made when the
group was created; lines anchor on it.

This data migration gives every existing group (``settings.recalculation.vehicle_groups``) the anchor it
has today as its id, in the same order the code numbers them. The id is opaque from now on. Nothing else
moves: every line key, user line, document placement (chains and parked documents included), reported
figure and recalculation reads exactly as before, because each key already contains that anchor.
A group that already has a ``group_id`` is left alone, so the migration can run twice.

The downgrade takes the ids out again (the older code rejects the key); the lines then number as they
did, by label and order.

Revision ID: 0021_vehicle_group_ids
Revises: 0020_audit_logs_target_index
Create Date: 2026-11-19
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0021_vehicle_group_ids"
down_revision: str | None = "0020_audit_logs_target_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _slug(text: Any) -> str:
    """The slug the line keys used (a frozen copy: this migration must not follow later changes)."""

    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:60].strip("-") or "none"


def _label(group: dict[str, Any]) -> str:
    return str(group.get("label") or f"{group.get('vehicle_type')} ({group.get('factor_fuel_type')})")


def _legacy_anchors(groups: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for group in groups:
        base = f"vg-{_slug(_label(group))}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return out


def _rewrite(change) -> int:  # noqa: ANN001 - a function from the settings to the new settings, or None
    bind = op.get_bind()
    # engagements has forced row level security: act as the provider scope for this statement's transaction
    bind.execute(sa.text("SELECT set_config('app.is_provider', 'true', true)"))
    rows = bind.execute(sa.text(
        "SELECT id, settings FROM engagements "
        "WHERE jsonb_typeof(settings #> '{recalculation,vehicle_groups}') = 'array' "
        "AND jsonb_array_length(settings #> '{recalculation,vehicle_groups}') > 0")).mappings().all()
    changed = 0
    for row in rows:
        settings = row["settings"]
        settings = json.loads(settings) if isinstance(settings, str) else settings
        groups = settings["recalculation"]["vehicle_groups"]
        if not all(isinstance(g, dict) for g in groups):
            continue  # not data this migration understands: left as it is
        new = change(groups)
        if new is None:
            continue
        settings["recalculation"]["vehicle_groups"] = new
        bind.execute(sa.text("UPDATE engagements SET settings = CAST(:settings AS jsonb) WHERE id = :id"),
                     {"settings": json.dumps(settings, ensure_ascii=False), "id": row["id"]})
        changed += 1
    return changed


def _add_ids(groups: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if all(isinstance(g.get("group_id"), str) for g in groups):
        return None
    anchors = _legacy_anchors(groups)
    taken = {g["group_id"] for g in groups if isinstance(g.get("group_id"), str)}
    out: list[dict[str, Any]] = []
    for group, anchor in zip(groups, anchors, strict=True):
        if isinstance(group.get("group_id"), str):
            out.append(group)
            continue
        candidate, n = anchor, 1
        while candidate in taken:  # only when an id already present uses the same anchor
            n += 1
            candidate = f"{anchor}-x{n}"
        taken.add(candidate)
        out.append({**group, "group_id": candidate})
    return out


def _remove_ids(groups: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not any("group_id" in g for g in groups):
        return None
    return [{k: v for k, v in g.items() if k != "group_id"} for g in groups]


def upgrade() -> None:
    _rewrite(_add_ids)


def downgrade() -> None:
    _rewrite(_remove_ids)

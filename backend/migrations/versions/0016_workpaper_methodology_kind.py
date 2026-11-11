"""workpaper_items: a new kind, ``methodology``, for the reviewer's decisions on the
Methodology review page (one row per decision field, keyed by its field id).

Only the kind CHECK changes. The downgrade deletes methodology rows first (as the table
owner, which may delete) so the narrower CHECK can be restored.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("ask", "finding", "examination", "document")
NEW_KINDS = (*OLD_KINDS, "methodology")


def _check(kinds: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_workpaper_items_kind", "workpaper_items", type_="check")
    op.create_check_constraint("ck_workpaper_items_kind", "workpaper_items", _check(NEW_KINDS))


def downgrade() -> None:
    op.execute("DELETE FROM workpaper_items WHERE kind = 'methodology'")
    op.drop_constraint("ck_workpaper_items_kind", "workpaper_items", type_="check")
    op.create_check_constraint("ck_workpaper_items_kind", "workpaper_items", _check(OLD_KINDS))

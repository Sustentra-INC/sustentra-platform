"""workpaper_items: a new kind, ``calc_line``, for the reviewer's decisions on calculation lines (a method choice,
or an input of a line's working), add-only like ``s1_review_decisions`` (0025).

A decision on a calculation line is evidence of what was reviewed and by whom, so no change of mind may rewrite
the one before it. Each decision is a NEW row: ``item_key`` is a hash of (line key, target) plus a sequence
number, and the payload holds the line key, the target, the sequence number and the field's whole record after
the move (suggestion, decision, history, value history). The latest sequence number of a target is its current
state. (A line key can be 200 characters, the whole item_key limit, so it cannot be part of the key itself.)

- The kind CHECK gains ``calc_line``.
- ``workpaper_items`` stays UPDATE-able for the other kinds (methodology fields are edited in place), and the
  app role has no DELETE on it (0012). For this kind a row trigger refuses UPDATE and DELETE for every role, the
  owner included, so the rows are add-only wherever the grants differ; TRUNCATE is not granted to the app role.
- A partial index on (engagement, line key) serves "the decisions on this line".

Deleting an engagement that has calc_line rows is refused by the trigger (the cascade would delete them), like
keeping audit history; the app archives engagements and never deletes them.

Deploy order is migrate, then swap containers: the previous app version never reads or writes this kind, so it
keeps working. The downgrade drops the trigger, deletes the calc_line rows (as the owner) and restores the
narrower CHECK.

Revision ID: 0028_workpaper_calc_line_kind
Revises: 0027_s1_parsed_texts
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028_workpaper_calc_line_kind"
down_revision: str | None = "0027_s1_parsed_texts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("ask", "finding", "examination", "document", "methodology")
NEW_KINDS = (*OLD_KINDS, "calc_line")
FUNCTION = "workpaper_items_calc_line_add_only"
INDEX = "ix_workpaper_items_calc_line_key"


def _check(kinds: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_workpaper_items_kind", "workpaper_items", type_="check")
    op.create_check_constraint("ck_workpaper_items_kind", "workpaper_items", _check(NEW_KINDS))
    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'calc_line decisions are add-only: % is not allowed', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER workpaper_items_calc_line_no_update
          BEFORE UPDATE ON workpaper_items FOR EACH ROW
          WHEN (OLD.kind = 'calc_line' OR NEW.kind = 'calc_line')
          EXECUTE FUNCTION {FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER workpaper_items_calc_line_no_delete
          BEFORE DELETE ON workpaper_items FOR EACH ROW
          WHEN (OLD.kind = 'calc_line')
          EXECUTE FUNCTION {FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE INDEX {INDEX} ON workpaper_items (engagement_id, (payload ->> 'line_key')) WHERE kind = 'calc_line'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    op.execute("DROP TRIGGER IF EXISTS workpaper_items_calc_line_no_delete ON workpaper_items")
    op.execute("DROP TRIGGER IF EXISTS workpaper_items_calc_line_no_update ON workpaper_items")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
    op.execute("DELETE FROM workpaper_items WHERE kind = 'calc_line'")
    op.drop_constraint("ck_workpaper_items_kind", "workpaper_items", type_="check")
    op.create_check_constraint("ck_workpaper_items_kind", "workpaper_items", _check(OLD_KINDS))

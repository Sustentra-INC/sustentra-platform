"""tasks: work one member of an organization asks another to do, with Row-Level Security.

- One row per task. ``assignee_user_id`` is who should do it, ``requested_by_user_id`` who asked
  (they may be the same person: a note to self). Both are members of ``org_id``; the API checks that,
  the foreign keys keep the users real.
- ``link`` is an in-app path (``/org/acme/...``) to the thing the task is about: a document, a data
  point line, a methodology row. Never a full URL, never document contents.
- ``engagement_id`` is optional: a task can be about the company as a whole. Engagements are never
  deleted (they are archived), so the foreign key is a safety net only.
- ``status`` open -> done | cancelled; ``completed_at`` / ``completed_by`` are set when it leaves open.
- RLS enabled and forced with the same predicate as ``engagements`` (an org's tenant context, or provider
  scope). No DELETE for the app: a task is cancelled, never removed.

Revision ID: 0022_tasks
Revises: 0021_vehicle_group_ids
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_tasks"
down_revision: str | None = "0021_vehicle_group_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("open", "done", "cancelled")

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name="fk_tasks_org_id"),
            nullable=False,
        ),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id", ondelete="SET NULL", name="fk_tasks_engagement_id"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column(
            "assignee_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_tasks_assignee_user_id"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_tasks_requested_by_user_id"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "completed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_tasks_completed_by"),
            nullable=True,
        ),
        sa.CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="ck_tasks_title_length"),
        sa.CheckConstraint("note IS NULL OR length(note) <= 2000", name="ck_tasks_note_length"),
        sa.CheckConstraint(
            "link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%' AND length(link) <= 500)",
            name="ck_tasks_link_is_app_path",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="ck_tasks_status"
        ),
        sa.CheckConstraint(
            "(status = 'open') = (completed_at IS NULL)", name="ck_tasks_completed_at_matches_status"
        ),
    )
    op.execute("CREATE INDEX ix_tasks_org_assignee_status ON tasks (org_id, assignee_user_id, status)")
    op.execute("CREATE INDEX ix_tasks_org_requester_status ON tasks (org_id, requested_by_user_id, status)")
    op.execute("CREATE INDEX ix_tasks_org_created_at ON tasks (org_id, created_at DESC)")
    op.execute("CREATE INDEX ix_tasks_engagement_id ON tasks (engagement_id) WHERE engagement_id IS NOT NULL")

    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tasks_tenant_isolation ON tasks
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON tasks TO app_user")
    op.execute("REVOKE DELETE ON tasks FROM app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tasks_tenant_isolation ON tasks")
    op.drop_table("tasks")

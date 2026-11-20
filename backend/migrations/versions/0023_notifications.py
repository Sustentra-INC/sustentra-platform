"""notifications: the in-app bell. One row per person told about a task, with Row-Level Security.

- ``kind``: task_assigned (to the assignee) | task_completed (to the requester and the org admins).
- ``title`` and ``link`` are copied from the task when the notification is made, so the bell reads the
  same even if the task changes. No document contents, ever.
- ``read_at`` NULL = unread. ``email_status`` records what happened to the matching email, which is sent
  after the transaction commits: pending (not tried yet) | sent | failed. A failed email never fails
  the action; this column is how an admin can see it did.
- RLS like ``tasks``; the API only ever shows a person their own rows (user_id), RLS keeps orgs apart.
  The app may update (read_at, email_status) but never delete.

Revision ID: 0023_notifications
Revises: 0022_tasks
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_notifications"
down_revision: str | None = "0022_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("task_assigned", "task_completed")
EMAIL_STATUSES = ("pending", "sent", "failed")

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name="fk_notifications_org_id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_notifications_user_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE", name="fk_notifications_task_id"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")", name="ck_notifications_kind"
        ),
        sa.CheckConstraint(
            "email_status IN (" + ", ".join(f"'{s}'" for s in EMAIL_STATUSES) + ")",
            name="ck_notifications_email_status",
        ),
        sa.CheckConstraint(
            "link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%' AND length(link) <= 500)",
            name="ck_notifications_link_is_app_path",
        ),
    )
    op.execute("CREATE INDEX ix_notifications_user_created_at ON notifications (org_id, user_id, created_at DESC)")
    op.execute(
        "CREATE INDEX ix_notifications_user_unread ON notifications (org_id, user_id) WHERE read_at IS NULL"
    )
    op.execute("CREATE INDEX ix_notifications_task_id ON notifications (task_id) WHERE task_id IS NOT NULL")

    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY notifications_tenant_isolation ON notifications
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON notifications TO app_user")
    op.execute("REVOKE DELETE ON notifications FROM app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS notifications_tenant_isolation ON notifications")
    op.drop_table("notifications")

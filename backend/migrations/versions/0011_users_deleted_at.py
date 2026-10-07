"""users.deleted_at (COMP-001 user erasure).

Erasure is a soft delete: the row stays (audit_logs and invited_by keep pointing at
it) but status becomes 'deleted', deleted_at is set and the personal data is
overwritten. Existing 'deleted' rows get deleted_at = updated_at.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    # FORCE RLS applies to the table owner too: provider scope, or the backfill touches nothing.
    op.execute("SELECT set_config('app.is_provider', 'true', true)")
    op.execute("UPDATE users SET deleted_at = updated_at WHERE status = 'deleted' AND deleted_at IS NULL")


def downgrade() -> None:
    op.drop_column("users", "deleted_at")

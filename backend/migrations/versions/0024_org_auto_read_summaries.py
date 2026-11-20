"""organizations.auto_read_summaries: whether Sustentra's AI reads a newly uploaded summary document by itself.

- ``true`` (the default, for every existing and new organization): when a company summary document
  (Block 1) finishes reading, the methodology prefill runs once for its engagement, in the background.
- ``false``: only the "Read the client's reports" button asks for the read.
- Organization admins change it at PATCH /api/v1/orgs/{org_id}/settings. No RLS change: organizations has none.

Revision ID: 0024_org_auto_read_summaries
Revises: 0023_notifications
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_org_auto_read_summaries"
down_revision: str | None = "0023_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("auto_read_summaries", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("organizations", "auto_read_summaries")

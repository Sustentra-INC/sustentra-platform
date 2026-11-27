"""ai_usage.document_id: the document a call read, so the cost of a whole-document read (the sum of its
parts' rows) is known per document (MVP-237).

- Nullable text, no foreign key: the ledger outlives the document, as ``textract_usage.document_id`` (0029).
  Rows written before this migration, and calls about no one document, have none.
- An index on (org_id, document_id) for the per-document sum.
- The table stays append only (SELECT and INSERT for app_user); adding a nullable column rewrites nothing.

Deploy order is migrate, then swap containers: the previous app version names its columns on insert, so it
keeps working against the new column.

Revision ID: 0030_ai_usage_document_id
Revises: 0029_textract_usage
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_ai_usage_document_id"
down_revision: str | None = "0029_textract_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_usage"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("document_id", sa.Text(), nullable=True))
    op.execute(f"CREATE INDEX ix_{TABLE}_org_document ON {TABLE} (org_id, document_id) WHERE document_id IS NOT NULL")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS ix_{TABLE}_org_document")
    op.drop_column(TABLE, "document_id")

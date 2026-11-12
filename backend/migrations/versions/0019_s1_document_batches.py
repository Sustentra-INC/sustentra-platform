"""s1 document batches: files uploaded together are one batch, with one progress view.

- ``s1_document_batches``: one row per batch (id, org_id, engagement_id, created_by, created_at,
  label). ``engagement_id`` is text with no foreign key, as the other s1 tables (0013): older
  records use ids that are not engagement UUIDs. RLS and grants as the s1 tables; the app never
  deletes a batch.
- ``s1_documents.batch_id``: nullable, the batch a document was uploaded in. Like the other filter
  columns of 0013 it must equal the record's own ``batch_id`` (a CHECK), so a query on the column
  and the record the API returns cannot disagree. Documents uploaded before this have none.

Revision ID: 0019_s1_document_batches
Revises: 0018_s1_document_chunks
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_s1_document_batches"
down_revision: str | None = "0018_s1_document_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "s1_document_batches"
DOCUMENTS = "s1_documents"

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{TABLE}_org_id"),
            nullable=False,
        ),
        sa.Column("engagement_id", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("id <> ''", name=f"ck_{TABLE}_id"),
        sa.CheckConstraint("engagement_id <> ''", name=f"ck_{TABLE}_engagement_id"),
    )
    op.execute(f"CREATE INDEX ix_{TABLE}_engagement ON {TABLE} (org_id, engagement_id)")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO app_user")
    op.execute(f"REVOKE UPDATE, DELETE ON {TABLE} FROM app_user")

    op.add_column(DOCUMENTS, sa.Column("batch_id", sa.Text(), nullable=True))
    op.create_check_constraint(
        f"ck_{DOCUMENTS}_batch_id_matches", DOCUMENTS, "batch_id IS NOT DISTINCT FROM (record->>'batch_id')"
    )
    op.execute(f"CREATE INDEX ix_{DOCUMENTS}_batch_id_seq ON {DOCUMENTS} (batch_id, seq) WHERE batch_id IS NOT NULL")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS ix_{DOCUMENTS}_batch_id_seq")
    op.drop_constraint(f"ck_{DOCUMENTS}_batch_id_matches", DOCUMENTS, type_="check")
    op.drop_column(DOCUMENTS, "batch_id")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)

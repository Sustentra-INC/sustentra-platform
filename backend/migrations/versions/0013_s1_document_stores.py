"""s1 document stores: uploads, pipeline runs, extraction results, review decisions and
approved evidence in Postgres with RLS, instead of JSONL files on one server's disk.

Each table keeps the exact record the JSONL repositories return today (``record``), plus
the columns queries filter on. The filter columns must equal the record's own values
(CHECK constraints), so RLS can never disagree with the ``org_id`` the API's ``can_see``
reads. ``seq`` replaces file order ("latest" = highest seq).

- ``org_id`` may be NULL for records made before uploads were owned (SEC-001): like
  ``can_see``, only provider scope sees those.
- ``engagement_id`` is text with no foreign key: older records use ids such as
  ``ENG-S1-2025`` that are not engagement UUIDs.
- ``legacy_key`` is set only by the one-time import from JSONL, so the import can be re-run.
- File bytes live in their own table, so no metadata query ever reads them.
- Nothing is deleted by the app (DELETE revoked); UPDATE stays for the document's status and
  for stamping ownership on legacy rows.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)

# table -> (filter columns taken from the record, indexes)
TABLES: dict[str, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
    "s1_documents": (("document_id", "engagement_id", "evidence_id", "processing_status"),
                     (("engagement_id", "seq"), ("evidence_id", "seq"))),
    "s1_pipeline_runs": (("pipeline_run_id", "engagement_id", "evidence_id", "document_id"),
                         (("pipeline_run_id", "seq"), ("evidence_id", "seq"), ("engagement_id", "seq"),
                          ("document_id", "seq"))),
    "s1_extraction_results": (("pipeline_run_id", "document_id", "evidence_id"),
                              (("document_id", "seq"), ("evidence_id", "seq"), ("pipeline_run_id", "seq"))),
    "s1_review_decisions": (("review_decision_id", "candidate_id", "evidence_id", "document_id", "field_name"),
                            (("evidence_id", "field_name", "seq"), ("document_id", "seq"), ("candidate_id", "seq"))),
    "s1_approved_evidence": (("approved_evidence_id", "engagement_id", "evidence_id", "document_id"),
                             (("approved_evidence_id", "seq"), ("evidence_id", "seq"), ("engagement_id", "seq"))),
}
ALL_TABLES = (*TABLES, "s1_document_files")


def _org_fk(table: str) -> sa.Column:
    return sa.Column(
        "org_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{table}_org_id"),
        nullable=True,
    )


def _record_table(table: str, columns: tuple[str, ...]) -> None:
    op.create_table(
        table,
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        _org_fk(table),
        # Only a document's id is always present; older records can lack the others.
        *(sa.Column(name, sa.Text(), nullable=not (table == "s1_documents" and name == "document_id"))
          for name in columns),
        sa.Column("record", postgresql.JSONB(), nullable=False),
        sa.Column("legacy_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("jsonb_typeof(record) = 'object'", name=f"ck_{table}_record_is_object"),
        sa.CheckConstraint("org_id IS NOT DISTINCT FROM NULLIF(record->>'org_id', '')::uuid",
                           name=f"ck_{table}_org_matches_record"),
        *(sa.CheckConstraint(f"{name} IS NOT DISTINCT FROM (record->>'{name}')", name=f"ck_{table}_{name}_matches")
          for name in columns),
        sa.UniqueConstraint("legacy_key", name=f"uq_{table}_legacy_key"),
    )


def _secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO app_user")
    op.execute(f"REVOKE DELETE ON {table} FROM app_user")


def upgrade() -> None:
    for table, (columns, indexes) in TABLES.items():
        _record_table(table, columns)
        for index in indexes:
            op.execute(f"CREATE INDEX ix_{table}_{'_'.join(index)} ON {table} ({', '.join(index)})")
    # One row per document: the latest version replaces the earlier ones.
    op.create_unique_constraint("uq_s1_documents_document_id", "s1_documents", ["document_id"])

    op.create_table(
        "s1_document_files",
        sa.Column("storage_uri", sa.Text(), primary_key=True),
        _org_fk("s1_document_files"),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("content", postgresql.BYTEA(), nullable=False),
        sa.Column("legacy_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes = octet_length(content)",
                           name="ck_s1_document_files_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_s1_document_files_sha256"),
        sa.UniqueConstraint("legacy_key", name="uq_s1_document_files_legacy_key"),
    )
    # Uploaded PDFs and images are already compressed: store them out of line, uncompressed.
    op.execute("ALTER TABLE s1_document_files ALTER COLUMN content SET STORAGE EXTERNAL")
    op.execute("CREATE INDEX ix_s1_document_files_document_id ON s1_document_files (document_id)")

    for table in ALL_TABLES:
        _secure(table)


def downgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    for table in reversed(ALL_TABLES):
        op.drop_table(table)

"""workpaper_copies and workpaper_downloads: the Excel workpaper as it was on the day it was served.

The Output page rebuilds the workpaper on every download, so nothing showed what the figures were on the
day a file was sent. From this release each download keeps the exact bytes it served:

- ``workpaper_copies``: one row per distinct workpaper (org, engagement, file name, size, SHA-256 of the
  bytes, a fingerprint of the content that ignores the time it was prepared, the app version, who prepared
  it, the request id) and the bytes themselves, in the row for now (as ``s1_document_files``; a later change
  can move them to S3 behind ``services/workpaper_copy_store.py``).
- ``workpaper_downloads``: one row per time someone downloaded a copy (a new workpaper, the same one again,
  or a kept copy fetched from the list): who, when, which request.

Both tables are add-only for ``app_user``, as ``audit_logs`` (0004) and ``s1_review_decisions`` (0025):
SELECT and INSERT only; UPDATE, DELETE and TRUNCATE are never granted, and there is one SELECT policy and
one INSERT policy (the same org predicate as every s1_* table), so a future grant of UPDATE or DELETE would
still match no row.

Foreign keys: ``org_id -> organizations``, ``engagement_id -> engagements`` and (downloads)
``copy_id -> workpaper_copies``, all ON DELETE RESTRICT, so nothing cascades into or out of these tables:
deleting an organization or an engagement that has copies is refused, like keeping audit history. (The app
archives engagements and never deletes them.) Users are plain ids and an email, with no foreign key, so
erasing a user (COMP-001) leaves the record of who prepared a copy.

Deploy order is migrate, then swap containers: the previous app version never touches these tables, so it
keeps working against this schema. Downgrading drops both tables and the copies in them.

Revision ID: 0026_workpaper_copies
Revises: 0025_review_decisions_add_only
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_workpaper_copies"
down_revision: str | None = "0025_review_decisions_add_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COPIES = "workpaper_copies"
DOWNLOADS = "workpaper_downloads"
TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _org_and_engagement(table: str) -> list[sa.Column]:
    return [
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{table}_org_id"), nullable=False),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("engagements.id", ondelete="RESTRICT", name=f"fk_{table}_engagement_id"),
                  nullable=False),
    ]


def _add_only(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({TENANT_PREDICATE})")
    op.execute(f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({TENANT_PREDICATE})")
    op.execute(f"REVOKE ALL ON {table} FROM app_user")
    op.execute(f"GRANT SELECT, INSERT ON {table} TO app_user")


def upgrade() -> None:
    op.create_table(
        COPIES,
        _id(),
        *_org_and_engagement(COPIES),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        # A hash of what the workbook says, without the time it was prepared (see workpaper_export_service).
        sa.Column("content_fingerprint", sa.Text(), nullable=False),
        sa.Column("app_version", sa.Text(), nullable=False),
        # Plain id and email, no foreign key: the record must survive user erasure.
        sa.Column("prepared_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prepared_by_email", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("content", postgresql.BYTEA(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes = octet_length(content)", name=f"ck_{COPIES}_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=f"ck_{COPIES}_sha256"),
        sa.CheckConstraint("content_fingerprint ~ '^[0-9a-f]{64}$'", name=f"ck_{COPIES}_fingerprint"),
    )
    # The workbook is already a compressed zip: keep it out of line, uncompressed.
    op.execute(f"ALTER TABLE {COPIES} ALTER COLUMN content SET STORAGE EXTERNAL")
    op.execute(f"CREATE INDEX ix_{COPIES}_engagement_id_created_at ON {COPIES} (engagement_id, created_at DESC, id DESC)")

    op.create_table(
        DOWNLOADS,
        _id(),
        *_org_and_engagement(DOWNLOADS),
        sa.Column("copy_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey(f"{COPIES}.id", ondelete="RESTRICT", name=f"fk_{DOWNLOADS}_copy_id"), nullable=False),
        # "prepared": the Output page's Download button; "saved": a kept copy fetched from the list.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("downloaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("downloaded_by_email", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('prepared', 'saved')", name=f"ck_{DOWNLOADS}_kind"),
    )
    op.execute(f"CREATE INDEX ix_{DOWNLOADS}_copy_id ON {DOWNLOADS} (copy_id)")

    for table in (COPIES, DOWNLOADS):
        _add_only(table)


def downgrade() -> None:
    op.drop_table(DOWNLOADS)
    op.drop_table(COPIES)

"""s1_parsed_texts: the text a reader made of a file, kept by the file's content hash.

A re-read after a type change, the methodology read and a re-run of the pipeline used to parse the file
again, and a scan was sent to Textract (billed per page) every time. From this release the parsed output
is kept per (organization, SHA-256 of the file's bytes, reader version, page range) and reused while the
hash and the reader version match.

- ``reader_version`` names the reader build and its OCR setting, so a new reader, or OCR switched on after
  a read without it, reads the file again instead of reusing the older text.
- ``page_from`` / ``page_to`` are 0 for the whole document, else the range of a chunk of a large PDF.
- ``parser_output`` is the whole normalized output (pages, text blocks, tables, key-values, source
  references): everything the pipeline uses, so a reuse skips Textract entirely.
- Never shared across organizations: ``org_id`` is part of the unique key, with the same RLS predicate as
  every s1_* table. ``org_id -> organizations`` ON DELETE RESTRICT, as 0018.
- app_user may SELECT, INSERT and UPDATE (a row that proved unusable is replaced), never DELETE.

Deploy order is migrate, then swap containers: the previous app version never touches the table.
Downgrading drops it; the next reads parse the files again.

Revision ID: 0027_s1_parsed_texts
Revises: 0026_workpaper_copies
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_s1_parsed_texts"
down_revision: str | None = "0026_workpaper_copies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "s1_parsed_texts"
TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{TABLE}_org_id"), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("reader_version", sa.Text(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("page_to", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("reader_name", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("parser_output", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=f"ck_{TABLE}_sha256"),
        sa.CheckConstraint("reader_version <> ''", name=f"ck_{TABLE}_reader_version"),
        sa.CheckConstraint("page_from >= 0 AND page_to >= page_from", name=f"ck_{TABLE}_pages"),
        sa.CheckConstraint("page_count >= 0", name=f"ck_{TABLE}_page_count"),
        sa.CheckConstraint("status IN ('parsed', 'partial', 'empty')", name=f"ck_{TABLE}_status"),
        sa.CheckConstraint("jsonb_typeof(parser_output) = 'object'", name=f"ck_{TABLE}_parser_output_is_object"),
        sa.UniqueConstraint("org_id", "sha256", "reader_version", "page_from", "page_to", name=f"uq_{TABLE}_key"),
    )
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
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {TABLE} TO app_user")
    op.execute(f"REVOKE DELETE ON {TABLE} FROM app_user")


def downgrade() -> None:
    op.drop_table(TABLE)

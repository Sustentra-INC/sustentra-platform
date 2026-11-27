"""textract_usage: the ledger of Textract calls, one row per call, so scans count toward the same
monthly limit as Sustentra's AI and the spend can be shown (MVP-245).

Mirrors ``ai_usage`` (0017):

- Append only: the app can SELECT and INSERT, never UPDATE or DELETE.
- RLS and grants as the other s1 tables: each organization sees only its own rows, provider scope sees all.
- ``document_id`` and ``sha256`` have no foreign key: the ledger outlives the document. Only ids, counts and
  cost are stored, never a file or its text.
- ``mode`` is the price used (forms_tables, tables, forms, detect_text); ``cost_microusd`` is pages times that
  price, 0 for a call that failed (AWS does not bill an error).

Deploy order is migrate, then swap containers: the previous app version never touches the table.

Revision ID: 0029_textract_usage
Revises: 0027_s1_parsed_texts
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_textract_usage"
# NOTE: this points at 0027 only because 0028 (0028_workpaper_calc_line_kind) is not on staging yet.
# Set it to "0028_workpaper_calc_line_kind" when that PR has landed.
down_revision: str | None = "0028_workpaper_calc_line_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "textract_usage"
MODES = ("forms_tables", "tables", "forms", "detect_text")
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
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("pages > 0", name=f"ck_{TABLE}_pages"),
        sa.CheckConstraint("cost_microusd >= 0", name=f"ck_{TABLE}_non_negative"),
        sa.CheckConstraint("mode IN (" + ", ".join(f"'{m}'" for m in MODES) + ")", name=f"ck_{TABLE}_mode"),
    )
    op.execute(f"CREATE INDEX ix_{TABLE}_org_month ON {TABLE} (org_id, created_at)")
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


def downgrade() -> None:
    op.execute(f"DROP TABLE {TABLE}")

"""s1_review_decisions: add-only for the application role, like audit_logs (0004).

A reviewer's decision on a value (accepted, edited, rejected, needs more evidence) is evidence of what
was reviewed and by whom. 0013 let ``app_user`` UPDATE these rows. Nothing in the app does: a changed
mind is a new row and the latest one wins (``seq``). So the privilege goes:

- ``app_user`` keeps SELECT and INSERT; UPDATE, DELETE and TRUNCATE are revoked.
- The one FOR ALL policy becomes a SELECT policy and an INSERT policy (same predicate), so even a
  future grant of UPDATE or DELETE would match no row, as on audit_logs.
- Foreign keys: the table's only one is ``org_id -> organizations ON DELETE RESTRICT``. Nothing
  cascades into it, and a referential action would run with the table owner's rights, which this
  migration does not touch (the owner is the migration role, never the app role).

Deploy order is migrate, then swap containers, so the previous app version runs against this schema for
a short time. It only INSERTs and SELECTs on this table (a plain INSERT, no ON CONFLICT DO UPDATE, no
SELECT ... FOR UPDATE), so it keeps working. The one-off ``import-s1-stores`` command did upsert
(``ON CONFLICT DO UPDATE``, which needs UPDATE even for a new row): this release's version no longer does
for this table; run the old version of the import against a migrated database and it fails.

Revision ID: 0025_review_decisions_add_only
Revises: 0024_org_auto_read_summaries
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_review_decisions_add_only"
down_revision: str | None = "0024_org_auto_read_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "s1_review_decisions"
# The predicate 0013 uses for every s1_* table.
TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)


def upgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.execute(f"CREATE POLICY {TABLE}_select ON {TABLE} FOR SELECT USING ({TENANT_PREDICATE})")
    op.execute(f"CREATE POLICY {TABLE}_insert ON {TABLE} FOR INSERT WITH CHECK ({TENANT_PREDICATE})")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {TABLE} FROM app_user")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO app_user")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_select ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_insert ON {TABLE}")
    op.execute(
        f"""
        CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
          FOR ALL
          USING ({TENANT_PREDICATE})
          WITH CHECK ({TENANT_PREDICATE})
        """
    )
    # As 0013 left it: SELECT, INSERT, UPDATE; never DELETE or TRUNCATE.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {TABLE} TO app_user")
    op.execute(f"REVOKE DELETE, TRUNCATE ON {TABLE} FROM app_user")

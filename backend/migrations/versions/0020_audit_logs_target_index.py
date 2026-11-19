"""audit_logs: an index for reading one engagement's events (the Evidence activity log).

``GET /v1/engagements/{id}/evidence-activity`` reads the events about one engagement, newest first,
by cursor: ``WHERE org_id AND target_type AND target_id ORDER BY created_at DESC, id DESC``. The
existing index covers (org_id, created_at) only, so every page would scan the org's whole log.

Revision ID: 0020_audit_logs_target_index
Revises: 0019_s1_document_batches
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_audit_logs_target_index"
down_revision: str | None = "0019_s1_document_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_audit_logs_target"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX {INDEX} ON audit_logs (org_id, target_type, target_id, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")

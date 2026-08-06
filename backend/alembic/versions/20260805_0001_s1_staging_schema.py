"""Create S1 staging persistence tables.

Revision ID: 20260805_0001
Revises:
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "s1_engagements",
        sa.Column("engagement_id", sa.String(), primary_key=True),
        sa.Column("engagement_name", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )

    op.create_table(
        "s1_documents",
        sa.Column("document_id", sa.String(), primary_key=True),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("storage_uri", sa.String(), nullable=False),
        sa.Column("document_role", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=True),
        sa.Column("uploaded_by", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.String(), nullable=False),
        sa.Column("processing_status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["engagement_id"], ["s1_engagements.engagement_id"]),
    )

    op.create_table(
        "s1_pipeline_runs",
        sa.Column("pipeline_run_id", sa.String(), primary_key=True),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["s1_documents.document_id"]),
    )

    op.create_table(
        "s1_extraction_results",
        sa.Column("pipeline_run_id", sa.String(), primary_key=True),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["s1_pipeline_runs.pipeline_run_id"]),
        sa.ForeignKeyConstraint(["document_id"], ["s1_documents.document_id"]),
    )

    op.create_table(
        "s1_review_decisions",
        sa.Column("review_decision_id", sa.String(), primary_key=True),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["s1_documents.document_id"]),
    )

    for table_name, columns in {
        "s1_documents": ["engagement_id", "evidence_id"],
        "s1_pipeline_runs": ["engagement_id", "evidence_id", "document_id", "created_at"],
        "s1_extraction_results": ["engagement_id", "evidence_id", "document_id", "created_at"],
        "s1_review_decisions": ["candidate_id", "evidence_id", "document_id", "field_name", "reviewed_at"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def downgrade() -> None:
    op.drop_table("s1_review_decisions")
    op.drop_table("s1_extraction_results")
    op.drop_table("s1_pipeline_runs")
    op.drop_table("s1_documents")
    op.drop_table("s1_engagements")

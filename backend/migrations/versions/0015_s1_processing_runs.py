"""s1 processing runs: the queue of document reads, so a long scan can be read outside the
upload request.

One row per request to read a document. The API inserts it (``queued``); whoever reads the
document claims it (``in_progress``, with a worker id and a lease), then records how it ended
(``completed`` with the pipeline run it produced, or ``failed`` with a message for the user).
The status values are those of contracts/processing_run.schema.json.

- One active run per document: a unique partial index over (org_id, document_id) for the
  queued and in_progress rows, so a second request for the same document finds the first
  (INSERT ... ON CONFLICT DO NOTHING) instead of starting another read.
- RLS and grants as the other s1_* tables (0013): each organization sees only its own runs,
  provider scope sees all, and nothing is deleted by the app. ``org_id`` is NOT NULL: runs
  are only ever requested by an organization's own users.
- ``engagement_id`` and ``document_id`` are text with no foreign key, like 0013.
- Two SECURITY DEFINER functions are the only cross-organization access, for the reader
  process, which serves every organization: ``claim_s1_processing_run`` takes the oldest
  queued run that is due, and ``requeue_expired_s1_processing_runs`` puts back runs whose
  reader stopped renewing its lease (or fails them once they have used every attempt). As in
  0003 (purge_expired_auth_rows) they switch app.is_provider on inside the body, because RDS
  refuses a custom GUC on the function definition, and restore the caller's value before
  returning; they touch only this table. Everything else about a run (including reading the
  document) happens in the run's own organization scope.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "s1_processing_runs"

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)

STATUSES = ("queued", "in_progress", "completed", "failed")
KINDS = ("process_document",)
ACTIVE = "status IN ('queued', 'in_progress')"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _timestamp(name: str, *, nullable: bool, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("now()") if default_now else None,
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{TABLE}_org_id"),
            nullable=False,
        ),
        sa.Column("engagement_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'process_document'")),
        # canonical_type_id_override, include_optional, include_deprecated (and persist_run)
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        _timestamp("run_after", nullable=False, default_now=True),
        _timestamp("lease_expires_at", nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("pipeline_run_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),  # the message the user sees
        sa.Column("requested_by", sa.Text(), nullable=False),  # email of the signed-in user
        _timestamp("created_at", nullable=False, default_now=True),
        _timestamp("started_at", nullable=True),
        _timestamp("completed_at", nullable=True),
        _timestamp("updated_at", nullable=False, default_now=True),
        sa.CheckConstraint("run_id <> ''", name=f"ck_{TABLE}_run_id"),
        sa.CheckConstraint("document_id <> ''", name=f"ck_{TABLE}_document_id"),
        sa.CheckConstraint(f"kind IN ({_in(KINDS)})", name=f"ck_{TABLE}_kind"),
        sa.CheckConstraint("jsonb_typeof(params) = 'object'", name=f"ck_{TABLE}_params_is_object"),
        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name=f"ck_{TABLE}_status"),
        sa.CheckConstraint("attempts >= 0", name=f"ck_{TABLE}_attempts"),
        sa.CheckConstraint("max_attempts >= 1", name=f"ck_{TABLE}_max_attempts"),
        sa.CheckConstraint(
            "status <> 'in_progress' OR (lease_expires_at IS NOT NULL AND worker_id IS NOT NULL)",
            name=f"ck_{TABLE}_in_progress_is_leased",
        ),
        sa.CheckConstraint("status <> 'failed' OR error IS NOT NULL", name=f"ck_{TABLE}_failed_has_error"),
        sa.CheckConstraint(
            "status <> 'completed' OR pipeline_run_id IS NOT NULL", name=f"ck_{TABLE}_completed_has_pipeline_run"
        ),
    )
    op.execute(f"CREATE UNIQUE INDEX uq_{TABLE}_active ON {TABLE} (org_id, document_id) WHERE {ACTIVE}")
    op.execute(f"CREATE INDEX ix_{TABLE}_claim ON {TABLE} (run_after, created_at) WHERE status = 'queued'")
    op.execute(f"CREATE INDEX ix_{TABLE}_lease ON {TABLE} (lease_expires_at) WHERE status = 'in_progress'")
    op.execute(f"CREATE INDEX ix_{TABLE}_engagement ON {TABLE} (engagement_id, document_id, created_at DESC)")

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

    # The oldest queued run that is due, across every organization, now leased to p_worker.
    # SKIP LOCKED: two readers claiming at once get different runs, never the same one.
    op.execute(
        f"""
        CREATE FUNCTION claim_s1_processing_run(p_worker text, p_lease_seconds integer)
          RETURNS SETOF {TABLE}
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        DECLARE
          prev_is_provider text := current_setting('app.is_provider', true);
        BEGIN
          IF coalesce(p_worker, '') = '' OR coalesce(p_lease_seconds, 0) < 1 THEN
            RAISE EXCEPTION 'claim_s1_processing_run needs a worker id and a lease of at least one second';
          END IF;
          -- RDS: only a superuser may attach a custom GUC (SET app.is_provider) to a
          -- function definition, so switch it on with set_config() inside the body and
          -- restore the caller's value before returning (as purge_expired_auth_rows, 0003).
          PERFORM set_config('app.is_provider', 'true', true);
          RETURN QUERY
            UPDATE {TABLE} AS r
               SET status = 'in_progress',
                   attempts = r.attempts + 1,
                   worker_id = p_worker,
                   started_at = coalesce(r.started_at, now()),
                   lease_expires_at = now() + make_interval(secs => p_lease_seconds),
                   updated_at = now()
             WHERE r.run_id = (
                     SELECT q.run_id FROM {TABLE} AS q
                      WHERE q.status = 'queued' AND q.run_after <= now()
                      ORDER BY q.run_after, q.created_at
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1)
            RETURNING r.*;
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
          RETURN;
        END
        $$
        """
    )
    # Runs whose reader stopped renewing the lease (it was killed, or hung): queued again
    # while attempts remain, failed with timed_out after the last one. Returns what changed,
    # so the caller can mark a failed run's document failed in that organization's scope.
    op.execute(
        f"""
        CREATE FUNCTION requeue_expired_s1_processing_runs()
          RETURNS TABLE(run_id text, org_id uuid, document_id text, status text)
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        DECLARE
          prev_is_provider text := current_setting('app.is_provider', true);
        BEGIN
          PERFORM set_config('app.is_provider', 'true', true);
          RETURN QUERY
            WITH expired AS (
              SELECT e.run_id FROM {TABLE} AS e
               WHERE e.status = 'in_progress' AND e.lease_expires_at < now()
               FOR UPDATE SKIP LOCKED
            )
            UPDATE {TABLE} AS r
               SET status = CASE WHEN r.attempts < r.max_attempts THEN 'queued' ELSE 'failed' END,
                   run_after = CASE WHEN r.attempts < r.max_attempts THEN now() ELSE r.run_after END,
                   worker_id = NULL,
                   lease_expires_at = NULL,
                   error_code = CASE WHEN r.attempts < r.max_attempts THEN r.error_code ELSE 'timed_out' END,
                   error = CASE
                     WHEN r.attempts < r.max_attempts THEN r.error
                     WHEN r.attempts <= 1 THEN
                       'Reading stopped before it finished. Try again later, or upload a smaller file.'
                     ELSE format('Reading stopped %s times before it finished. '
                                 'Try again later, or upload a smaller file.', r.attempts)
                   END,
                   completed_at = CASE WHEN r.attempts < r.max_attempts THEN NULL ELSE now() END,
                   updated_at = now()
              FROM expired
             WHERE r.run_id = expired.run_id
            RETURNING r.run_id, r.org_id, r.document_id, r.status;
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
          RETURN;
        END
        $$
        """
    )
    for signature in ("claim_s1_processing_run(text, integer)", "requeue_expired_s1_processing_runs()"):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS requeue_expired_s1_processing_runs()")
    op.execute("DROP FUNCTION IF EXISTS claim_s1_processing_run(text, integer)")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)

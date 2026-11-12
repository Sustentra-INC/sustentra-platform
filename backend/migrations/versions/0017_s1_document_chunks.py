"""s1 document chunks: a large PDF is read in page chunks on the same queue as the document.

When the reader claims a queued run for a PDF with more pages than S1_CHUNK_THRESHOLD_PAGES, it
inserts one row here per block of pages and parks the run in the new status
``waiting_on_chunks`` (it releases its lease). Readers then claim chunks before runs. Each chunk
parses only its own pages and stores the parser output. The chunk that ends the last unfinished
chunk (completed, or failed for good) puts the run back in ``queued`` so a reader assembles the
chunks and carries on with classification and extraction as for any document.

- ``s1_processing_runs.status`` gains ``waiting_on_chunks``. It is an active status: the unique
  "one active run per document" index now covers it too (dropped and rebuilt below).
- ``s1_document_chunks``: one row per (run, chunk_index). Status queued, in_progress, completed
  or failed, with attempts, a worker id, a lease and ``available_at`` (the retry backoff), as
  the runs. ``run_id`` has no foreign key, as the other s1 tables (0013, 0015) and so the run
  table can still be truncated by itself. RLS and grants as ``s1_processing_runs``.
- ``claim_s1_document_chunk`` and ``requeue_expired_s1_document_chunks`` are SECURITY DEFINER,
  like their run twins in 0015, for the reader that serves every organization.
- ``s1_wake_parent_run(run_id)`` is the one place a parked run is queued again: a single
  fenced UPDATE ... WHERE NOT EXISTS (an unfinished chunk). It first locks the run row, so two
  readers finishing the last two chunks at once cannot both see the other as unfinished (and
  neither wake the run), nor both wake it: the second one finds the run already queued.

Downgrade: parked runs go back to queued (they are read whole again) and the table goes.

Revision ID: 0017_s1_document_chunks
Revises: 0016
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_s1_document_chunks"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "s1_document_chunks"
RUNS = "s1_processing_runs"

TENANT_PREDICATE = (
    "org_id::text = current_setting('app.tenant_id', true) "
    "OR current_setting('app.is_provider', true) = 'true'"
)

OLD_RUN_STATUSES = ("queued", "in_progress", "completed", "failed")
NEW_RUN_STATUSES = (*OLD_RUN_STATUSES, "waiting_on_chunks")
CHUNK_STATUSES = ("queued", "in_progress", "completed", "failed")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _timestamp(name: str, *, nullable: bool, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("now()") if default_now else None,
    )


def _set_run_statuses(statuses: tuple[str, ...], active: tuple[str, ...]) -> None:
    op.drop_constraint(f"ck_{RUNS}_status", RUNS, type_="check")
    op.create_check_constraint(f"ck_{RUNS}_status", RUNS, f"status IN ({_in(statuses)})")
    op.execute(f"DROP INDEX uq_{RUNS}_active")
    op.execute(f"CREATE UNIQUE INDEX uq_{RUNS}_active ON {RUNS} (org_id, document_id) WHERE status IN ({_in(active)})")


def upgrade() -> None:
    _set_run_statuses(NEW_RUN_STATUSES, ("queued", "in_progress", "waiting_on_chunks"))

    op.create_table(
        TABLE,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT", name=f"fk_{TABLE}_org_id"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Text(), nullable=False),  # the parent processing run
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=False),  # 1-based, inclusive
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("worker_id", sa.Text(), nullable=True),
        _timestamp("lease_expires_at", nullable=True),
        _timestamp("available_at", nullable=False, default_now=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("parser_output", postgresql.JSONB(), nullable=True),
        _timestamp("created_at", nullable=False, default_now=True),
        _timestamp("updated_at", nullable=False, default_now=True),
        sa.CheckConstraint("id <> ''", name=f"ck_{TABLE}_id"),
        sa.CheckConstraint("run_id <> ''", name=f"ck_{TABLE}_run_id"),
        sa.CheckConstraint("chunk_index >= 0", name=f"ck_{TABLE}_chunk_index"),
        sa.CheckConstraint("page_from >= 1 AND page_to >= page_from", name=f"ck_{TABLE}_pages"),
        sa.CheckConstraint(f"status IN ({_in(CHUNK_STATUSES)})", name=f"ck_{TABLE}_status"),
        sa.CheckConstraint("attempts >= 0", name=f"ck_{TABLE}_attempts"),
        sa.CheckConstraint("max_attempts >= 1", name=f"ck_{TABLE}_max_attempts"),
        sa.CheckConstraint(
            "status <> 'in_progress' OR (lease_expires_at IS NOT NULL AND worker_id IS NOT NULL)",
            name=f"ck_{TABLE}_in_progress_is_leased",
        ),
        sa.CheckConstraint(
            "parser_output IS NULL OR jsonb_typeof(parser_output) = 'object'",
            name=f"ck_{TABLE}_parser_output_is_object",
        ),
        sa.UniqueConstraint("run_id", "chunk_index", name=f"uq_{TABLE}_run_chunk"),
    )
    op.execute(f"CREATE INDEX ix_{TABLE}_claim ON {TABLE} (available_at, created_at) WHERE status = 'queued'")
    op.execute(f"CREATE INDEX ix_{TABLE}_lease ON {TABLE} (lease_expires_at) WHERE status = 'in_progress'")

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

    # Queue the parked run again once none of its chunks is unfinished. SECURITY INVOKER: it
    # works in the caller's scope (a reader's tenant scope, or the provider scope the requeue
    # function below switches on). The row lock serializes the readers that finish the last
    # chunks; the UPDATE is fenced on the status, so the run is queued exactly once.
    op.execute(
        f"""
        CREATE FUNCTION s1_wake_parent_run(p_run_id text)
          RETURNS boolean
          LANGUAGE plpgsql
          SET search_path = public, pg_temp
        AS $$
        DECLARE
          woken integer;
        BEGIN
          PERFORM 1 FROM {RUNS} WHERE run_id = p_run_id FOR UPDATE;
          UPDATE {RUNS}
             SET status = 'queued', run_after = now(), worker_id = NULL, lease_expires_at = NULL,
                 updated_at = now()
           WHERE run_id = p_run_id AND status = 'waiting_on_chunks'
             AND NOT EXISTS (SELECT 1 FROM {TABLE} c
                              WHERE c.run_id = p_run_id AND c.status IN ('queued', 'in_progress'));
          GET DIAGNOSTICS woken = ROW_COUNT;
          RETURN woken > 0;
        END
        $$
        """
    )

    # The oldest queued chunk that is due, across every organization, leased to p_worker.
    op.execute(
        f"""
        CREATE FUNCTION claim_s1_document_chunk(p_worker text, p_lease_seconds integer)
          RETURNS SETOF {TABLE}
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        DECLARE
          prev_is_provider text := current_setting('app.is_provider', true);
        BEGIN
          IF coalesce(p_worker, '') = '' OR coalesce(p_lease_seconds, 0) < 1 THEN
            RAISE EXCEPTION 'claim_s1_document_chunk needs a worker id and a lease of at least one second';
          END IF;
          PERFORM set_config('app.is_provider', 'true', true);
          RETURN QUERY
            UPDATE {TABLE} AS c
               SET status = 'in_progress',
                   attempts = c.attempts + 1,
                   worker_id = p_worker,
                   lease_expires_at = now() + make_interval(secs => p_lease_seconds),
                   updated_at = now()
             WHERE c.id = (
                     SELECT q.id FROM {TABLE} AS q
                      WHERE q.status = 'queued' AND q.available_at <= now()
                      ORDER BY q.available_at, q.created_at, q.chunk_index
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1)
            RETURNING c.*;
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
          RETURN;
        END
        $$
        """
    )
    # Chunks whose reader stopped renewing the lease: queued again while attempts remain, failed
    # (timed_out) after the last one. A chunk that fails for good may have been the last
    # unfinished one, so every parked run with nothing left to wait for is woken here too (this
    # also heals a wake-up that was missed). Returns the chunks it changed.
    op.execute(
        f"""
        CREATE FUNCTION requeue_expired_s1_document_chunks()
          RETURNS TABLE(id text, run_id text, org_id uuid, document_id text, status text)
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = public, pg_temp
        AS $$
        DECLARE
          prev_is_provider text := current_setting('app.is_provider', true);
          parked text;
        BEGIN
          PERFORM set_config('app.is_provider', 'true', true);
          RETURN QUERY
            WITH expired AS (
              SELECT e.id FROM {TABLE} AS e
               WHERE e.status = 'in_progress' AND e.lease_expires_at < now()
               FOR UPDATE SKIP LOCKED
            )
            UPDATE {TABLE} AS c
               SET status = CASE WHEN c.attempts < c.max_attempts THEN 'queued' ELSE 'failed' END,
                   available_at = CASE WHEN c.attempts < c.max_attempts THEN now() ELSE c.available_at END,
                   worker_id = NULL,
                   lease_expires_at = NULL,
                   error_code = CASE WHEN c.attempts < c.max_attempts THEN c.error_code ELSE 'timed_out' END,
                   updated_at = now()
              FROM expired
             WHERE c.id = expired.id
            RETURNING c.id, c.run_id, c.org_id, c.document_id, c.status;
          FOR parked IN
            SELECT r.run_id FROM {RUNS} r
             WHERE r.status = 'waiting_on_chunks'
               AND NOT EXISTS (SELECT 1 FROM {TABLE} c
                                WHERE c.run_id = r.run_id AND c.status IN ('queued', 'in_progress'))
             ORDER BY r.run_id
          LOOP
            PERFORM s1_wake_parent_run(parked);
          END LOOP;
          PERFORM set_config('app.is_provider', coalesce(prev_is_provider, ''), true);
          RETURN;
        END
        $$
        """
    )
    for signature in (
        "claim_s1_document_chunk(text, integer)",
        "requeue_expired_s1_document_chunks()",
        "s1_wake_parent_run(text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO app_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS requeue_expired_s1_document_chunks()")
    op.execute("DROP FUNCTION IF EXISTS claim_s1_document_chunk(text, integer)")
    op.execute("DROP FUNCTION IF EXISTS s1_wake_parent_run(text)")
    op.execute(f"DROP POLICY IF EXISTS {TABLE}_tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
    # A parked run has no chunks any more: it is read whole again.
    op.execute(
        f"UPDATE {RUNS} SET status = 'queued', run_after = now(), worker_id = NULL, lease_expires_at = NULL "
        "WHERE status = 'waiting_on_chunks'"
    )
    _set_run_statuses(OLD_RUN_STATUSES, ("queued", "in_progress"))

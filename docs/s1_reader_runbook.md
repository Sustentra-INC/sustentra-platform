# Reading documents in the background (reader runbook)

Reading a document (parsing it, extracting values) can take a while, and a scanned bill takes
longest. With `S1_PROCESSING=queued` the app does not read inside the request: an upload, or
a request to read a document again, only queues a processing run and answers at once. A
separate process, the **reader**, picks the run up and reads the document. The Evidence
screen shows "Reading…" and fills in the values when the run ends, without a reload.

`S1_PROCESSING` (in `/opt/sustentra/.env`, passed to the containers by `deploy.sh`, like
`S1_STORE`) chooses how documents are read:

| `S1_PROCESSING` | what a read does |
|---|---|
| `inline` (default) | The request reads the document, as before, and records it as a processing run. |
| `queued` | The request queues a run and answers at once (`202` from `POST /processing-runs`). The reader reads it. Needs `S1_STORE=postgres` or `postgres+jsonl`. |

## What runs on the app host

`reader` is a service in `deploy/docker-compose.prod.yml`. It runs the api image with the
api's settings (`app.env`), and the command `python -m backend.app.workers.processing_reader`.

- **Active whenever `S1_STORE` is postgres-backed,** whatever `S1_PROCESSING` says. That
  way it reads runs left queued after a switch back to inline, and it reads a document whose
  inline request died during a deploy. Under `S1_STORE=jsonl` (prod today) it logs
  `reader_idle` and does nothing, and stays healthy.
- **One document at a time,** in one container (`mem_limit: 768m`). Several readers are safe
  (a run is claimed by one of them only), so scaling later is `--scale reader=2`.
- **Healthy** means its loop is running: the container's health check
  (`python -m backend.app.workers.reader_health`) passes while the process has touched its
  alive file in the last 90 seconds.
- **A hung read:** after `S1_READER_MAX_RUN_SECONDS` (900) the reader exits with code 75 and
  Docker restarts it. The run goes back to the queue when its 120-second lease runs out, and
  fails with `timed_out` after 3 attempts.
- **A stop** (`docker stop`, a deploy) gives a read `S1_READER_SHUTDOWN_GRACE_SECONDS` (45)
  to finish; otherwise the run is put back and read again. The container's
  `stop_grace_period` is 60 seconds, above that.
- **Logs** go to the api's CloudWatch group (`/sustentra/<env>/api`), with the container name
  as the stream. A group of its own would need a Terraform apply and an IAM change.

The reader's timing settings (`S1_READER_*` in `backend/app/core/config.py`) run on their
defaults: `deploy.sh` writes only the settings listed in `write_app_env` into `app.env`, so a
value in `/opt/sustentra/.env` does not reach the container. Changing one needs a line added
to `write_app_env`.

Log lines carry ids, codes, counts and durations, never a file name or document text:

| event | meaning |
|---|---|
| `reader_started` | the reader is up (`s1_store`, `s1_processing`) |
| `reader_idle` | `S1_STORE=jsonl`: nothing to do here |
| `processing_run_claimed`, `processing_run_finished` | a run was taken (`wait_ms` in the queue), and how it ended (`status`, `error_code`, `duration_ms`) |
| `processing_run_released` | a stop put an unfinished run back in the queue |
| `processing_runs_requeued` | runs whose lease had run out were queued again |
| `processing_run_overran`, `processing_run_crashed` | a read ran too long (the reader restarts), or failed unexpectedly |
| `reader_error` | one pass of its loop failed (for example the database was unreachable); it waits, then tries again |

## What a deploy does with it

`deploy.sh` (run on the host by the deploy workflow):

1. **Checks `S1_PROCESSING` first,** before it logs in to ECR, pulls or writes anything. It
   must be `inline` or `queued` (unset means `inline`), and `queued` needs a postgres-backed
   `S1_STORE`. Otherwise the deploy stops with a one-line message and exit code 1, and the
   running release stays up. The app refuses these settings at start, which would crash the new
   release and the rollback alike.
2. Writes `S1_PROCESSING` into `app.env`.
3. Releases `caddy`, `web`, `api` and `reader` with the new tag.
4. Waits for the release to be healthy: `GET /api/health` answers **and** the reader's
   container is `healthy`. It tries for about 150 seconds; the reader's first health check
   comes about 15 seconds after it starts.
5. If that fails, it prints the last 50 log lines of all four services and redeploys the
   previous tag, as before. That rollback only exists when the tag changed: it does not
   rewrite `app.env`, so it cannot undo a setting. A redeploy of the current tag (as in
   the switches below) has no earlier release: `deploy.sh` logs
   `nothing to roll back to; <tag> left running` and exits 1.

**A rollback to an image from before the reader existed** (the first failed deploy in an
environment after the reader was added): the previous image has no reader process, and the
compose file still starts one, so the reader restarts in a loop and cannot become healthy.
The deploy then ends with `ROLLBACK ALSO UNHEALTHY` even when the api is fine. Judge that
rollback by `curl -s https://<host>/api/health` and `dc ps api`, ignore the reader, and run
`dc stop reader` to quiet it. The exit code is 1 either way.

## Before you start

- The reader, queued uploads and "Reading…" on Evidence must be deployed to the environment.
- `curl -s https://staging.sustentra.com/api/health` shows `"status":"ok"`, with a `version`
  equal to a `staging` commit at or after the merge that added the reader
  (`git merge-base --is-ancestor <that merge> <version>`).

## Switch staging to queued

```bash
# From your machine: open a shell on the staging host
ID=$(aws ec2 describe-instances --region us-east-1 \
  --filters "Name=tag:Name,Values=sustentra-staging-app-host" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
aws ssm start-session --region us-east-1 --target "$ID"

# On the host
dc() { sudo docker compose -f /opt/sustentra/docker-compose.prod.yml --env-file /opt/sustentra/.env "$@"; }
sudo grep -E '^(S1_STORE|S1_PROCESSING|API_TAG)=' /opt/sustentra/.env   # S1_STORE=postgres+jsonl (or postgres); S1_PROCESSING absent or inline
dc ps reader                                                             # State: Up ... (healthy)
dc logs reader | grep reader_started                                     # a "reader_started" line

sudo sed -i 's/^S1_PROCESSING=.*/S1_PROCESSING=queued/' /opt/sustentra/.env
sudo grep -q '^S1_PROCESSING=' /opt/sustentra/.env || echo 'S1_PROCESSING=queued' | sudo tee -a /opt/sustentra/.env

# Redeploy the current tag: writes S1_PROCESSING into app.env, restarts api + reader, health-checks.
# The tag is unchanged, so a failure is NOT rolled back: follow "Roll back to inline" below.
cd /opt/sustentra && sudo ./deploy.sh staging "$(sudo grep '^API_TAG=' /opt/sustentra/.env | cut -d= -f2)"
#   (or from your machine: gh workflow run deploy.yml --repo Sustentra-INC/sustentra-platform --ref staging -f image_tag=<API_TAG>)

dc exec api python -m backend.app.cli show-settings | grep -E '"s1_(store|processing)"'   # "s1_processing": "queued"
```

**If `deploy.sh` exits 1 (the reader or the api is not healthy), the switch has not been
reverted.** Redeploying the current tag leaves nothing to roll back to: `deploy.sh` logs
`nothing to roll back to; <tag> left running` and stops, and it has already written
`S1_PROCESSING=queued` into `app.env`. Staging is then in queued mode, and uploads wait at
Reading… if the reader is down. Follow **Roll back to inline** below at once.

Staging stays on `S1_STORE=postgres+jsonl` for this switch, so that one thing changes at a
time. The JSONL mirror appends, and two containers appending lines over 8 KB at the same
moment could interleave one line. That only matters on a rollback to `jsonl`, and
`verify-s1-stores` shows it. Move staging to `S1_STORE=postgres` (`docs/s1_store_cutover.md`,
step 4) about a week after the queued switch.

## Check it works

1. In the browser, upload `s1-test-suite/stationary_combustion/documents/SC-08_scanned_bill_no_text_layer.pdf`
   and the photo of a bill.
   - The upload finishes at once.
   - The rows say Reading…, then show values without a reload.
   - Reloading during reading still shows Reading….
2. Follow the reader:
   - On the host: `dc logs -f reader | grep -E 'processing_run_(claimed|finished)'`.
   - In CloudWatch Logs Insights, on `/sustentra/staging/api`:
     `fields @timestamp, message, run_id, status, error_code, duration_ms | filter @logStream like /reader/ | sort @timestamp desc | limit 50`.
3. Restart the reader while a read is in flight: `dc restart -t 60 reader`. The read finishes
   within 45 s, or the log shows `processing_run_released` and it is read again.
4. Run steps 3–6 of `docs/staging_test_plan.md`.

## Roll back to inline

```bash
sudo sed -i 's/^S1_PROCESSING=.*/S1_PROCESSING=inline/' /opt/sustentra/.env
cd /opt/sustentra && sudo ./deploy.sh staging "$(sudo grep '^API_TAG=' /opt/sustentra/.env | cut -d= -f2)"
dc exec api python -m backend.app.cli show-settings | grep '"s1_processing"'   # "inline"
```

- Uploads read inline again. Runs that are still queued are read by the reader, which stays
  active while `S1_STORE` is postgres-backed.
- **If this redeploy also exits 1** because the reader is not healthy, inline is still in
  effect: `deploy.sh` writes `app.env` and restarts the containers before it health-checks.
  Confirm with the `show-settings` line, then deal with the reader as below.
- **If the reader itself misbehaves,** run `dc stop reader`. That lasts until the next deploy.
  A document left at Reading… is then read inline when its type is set again in Evidence.
- **To remove the reader completely,** revert the merge that added it on `staging` with a PR;
  the deploy that follows runs without the reader. Do this only after switching back to inline.

## Production

Prod runs `S1_STORE=jsonl` and `S1_PROCESSING` unset (inline). After the next promotion the
reader starts, logs `reader_idle`, and stays healthy, and nothing else changes. `queued` is
refused there (by `deploy.sh`, and by the app) until prod moves to a postgres-backed store.

# Moving the S1 stores to Postgres (cutover runbook)

The S1 records (documents, pipeline runs, extraction results, review decisions, approved
evidence) and the uploaded files live in JSONL files and a folder on the app host
(`/opt/sustentra/data`, `/app/local-data` in the api container). This moves them into
Postgres (RDS, backed up), where each organization's rows are isolated by RLS.

`S1_STORE` (in `/opt/sustentra/.env`, passed to the api container by `deploy.sh`) chooses the stores:

| `S1_STORE` | records | uploaded files |
|---|---|---|
| `jsonl` (default) | JSONL files | uploads folder |
| `postgres+jsonl` | Postgres, every write also to the files | Postgres, every upload also to the folder |
| `postgres` | Postgres | Postgres (copied to `/tmp` in the container when a parser or download needs the file) |

Needs, deployed: migrations 0013 and 0014, the Postgres stores, evidence owners (#116), the
`S1_STORE` switch (#118) and the `import-s1-stores` / `verify-s1-stores` commands.

On the app host, `dc` below stands for:

```bash
docker compose -f /opt/sustentra/docker-compose.prod.yml --env-file /opt/sustentra/.env
```

## 1. Back up

- An RDS snapshot (the deploy workflow takes one before every deploy; take one by hand if the last deploy was a while ago).
- The files: `sudo tar czf /opt/sustentra/s1-data-$(date +%F).tgz -C /opt/sustentra data`

## 2. Import while the app keeps running (S1_STORE=jsonl)

```bash
dc exec api python -m backend.app.cli import-s1-stores --dry-run
dc exec api python -m backend.app.cli import-s1-stores
dc exec api python -m backend.app.cli verify-s1-stores
```

The import is a sync and can be repeated: it adds lines written since the last run and
updates lines the ownership claim (`claim-s1-data`) rewrote. Run any claims you need first.
`verify-s1-stores` must end with "The files and Postgres agree." Documents whose file is
missing on disk are listed but are not a mismatch (they are missing today too).

Evidence whose records have no single owner (unowned legacy records, or two organizations)
stays visible to provider scope only, exactly as with the files.

## 3. Cut over (about a minute without the API)

```bash
dc stop api
dc run --rm api python -m backend.app.cli import-s1-stores     # catches up the last writes
dc run --rm api python -m backend.app.cli verify-s1-stores
sudo sed -i 's/^S1_STORE=.*/S1_STORE=postgres+jsonl/' /opt/sustentra/.env
grep -q '^S1_STORE=' /opt/sustentra/.env || echo 'S1_STORE=postgres+jsonl' | sudo tee -a /opt/sustentra/.env
```

Then redeploy the current tag (the deploy workflow, or `deploy.sh <env> <current tag>` on the
host), which writes `S1_STORE` into `app.env` and starts the api. Check by hand: sign in, open
Evidence, open and download a document, upload one and process it.

From here on the import refuses to run: the app writes Postgres itself.

## 4. Run on postgres+jsonl, then postgres

Leave it on `postgres+jsonl` for about a week; `verify-s1-stores` should keep agreeing. Then
set `S1_STORE=postgres` and redeploy. Keep `/opt/sustentra/data` and the tarball as a backup.

## Rolling back

- From `postgres+jsonl`: set `S1_STORE=jsonl` and redeploy. The files received every write.
- From `postgres`: the files lack everything written since. Go back to `postgres+jsonl` instead,
  or restore the RDS snapshot.

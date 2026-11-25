# Saved copies of the Excel workpaper

The Output page builds the workpaper again on every download, so nothing used to show what the figures were
on the day a file was sent. Every download now keeps the exact file it served (migration 0026).

## What is kept

- `workpaper_copies`: org, engagement, file name, size, SHA-256 of the bytes, a content fingerprint, the app
  version (`GIT_SHA`), who prepared it (id and email), the request id, when, and the bytes.
- `workpaper_downloads`: one row per download of a copy (`prepared`: the Download button, `saved`: a kept copy
  fetched from the list), with who, when and the request id.
- Both are add-only for `app_user` (SELECT and INSERT; one SELECT and one INSERT policy with the usual org
  predicate), like `audit_logs` and `s1_review_decisions`.
- Foreign keys are all RESTRICT, as for audit history: an organization or engagement that has copies cannot be
  deleted (the app only archives engagements). Users are a plain id and an email, so erasing a user keeps the
  record. Downgrading 0026 drops both tables and the copies in them.

## When two downloads are one copy

An .xlsx carries the time in its own properties, so its bytes differ on every build. The fingerprint
(`workpaper_export_service.content_fingerprint`) is a hash of every sheet name and cell value except the time in
the Summary's "Exported" row (it keeps who prepared it). If a download's fingerprint equals the engagement's
newest copy, no new copy is made: the kept copy's own bytes are served and the download is recorded against it.
So the file in an auditor's hands is always byte for byte a kept one, and its "Exported" time (and the date in
its file name) is when that copy was first prepared. A change in the figures, in who downloads, or in the app
version makes a new copy.

## Order and failure

Build, then in the request's own transaction: lock the engagement's copies (`pg_advisory_xact_lock`, so two
downloads at once keep one copy), save the copy, the download record and the audit event, and only then send
the bytes. If any of that fails the answer is 503 with `Retry-After`, plain words, and nothing is sent: a
workpaper that Sustentra has no record of must not exist, and a retry costs the auditor one click. A copy over
`WORKPAPER_COPY_MAX_MB` (default 50) is refused with 413 and a message; a 1,000-document workpaper is a few MB.
A kept copy that fails its SHA-256 or size check on the way out is never sent (500 and an error log); the live
download then keeps a fresh copy instead of reusing it.

## API

- `GET /v1/engagements/{id}/export`: the live download, as before, now kept.
- `GET /v1/engagements/{id}/workpaper-copies?limit=20&offset=0` (limit 1 to 100): newest first, with `total`.
- `GET /v1/engagements/{id}/workpaper-copies/{copy_id}/download`: one kept copy, checked against its SHA-256.

Same access as the live download (`s1_reader`; another organization gets 404). Audit events:
`workpaper_exported` ("Downloaded the workpaper") and `workpaper_copy_downloaded` ("Downloaded a saved
workpaper"), with ids, SHA-256 and size only. An archived engagement can still be downloaded.

## Storage

The bytes are in Postgres whatever `S1_STORE` is (the engagement and audit log are there regardless; there is no
file fallback). All reads and writes go through `services/workpaper_copy_store.py`, so moving the bytes to S3
means a new store class with the same methods.

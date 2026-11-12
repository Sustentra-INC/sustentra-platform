# Backend Service Skeleton

## API Routers

- engagements: engagement lifecycle operations.
- documents: document registration and lookup.
- processing_runs: extraction run lifecycle.
- evidence: evidence record retrieval.
- reviews: reviewer decisions per field.
- assistant: assistant endpoint shell.

## Service Layer Stubs

- ingestion_service: upload and metadata registration orchestration.
- processing_service: run lifecycle orchestration.
- classification_service: document role/type classification.
- extraction_service: candidate extraction normalization.
- review_service: decision persistence and audit metadata.
- approved_evidence_service: approved evidence projection.

## Adapter Layer Stubs

- parsers: textract/pdf/excel/image parser entry points.
- llm: Claude adapter (`llm/claude.py`) for AI suggestions; see below.
- storage: S3 read/write shell.
- persistence: SQLAlchemy session/bootstrap shell.

## Page chunks (large PDFs, queued mode)

A scanned PDF of hundreds of pages used to be parsed in one run (50 OCR pages at most, and one
failure lost everything). In queued mode a PDF with more than `S1_CHUNK_THRESHOLD_PAGES` pages
is now read as page chunks on the same queue as the document reads. Inline mode and smaller
documents are read as before, byte for byte.

1. The reader claims the run (`processing_reader`). `DocumentChunkService.step` counts the pages
   and, in one transaction (`DocumentChunkRepository.plan`), inserts one `s1_document_chunks` row per
   `S1_CHUNK_PAGES` (10) pages and parks the run in `waiting_on_chunks`: no worker, no lease,
   and the attempt is not spent.
2. One loop, chunks first: a reader claims the oldest due chunk
   (`claim_s1_document_chunk`, `SKIP LOCKED`), parses only its pages through
   `ParserService.parse_document(..., pages=(from, to))` and stores the parser output on the
   chunk. Page numbers in `pages`, `text_blocks` and `source_references` are the document's own.
   The 50-page OCR cap (`OCR_MAX_PAGES`) applies per chunk.
3. The chunk that ends the last unfinished chunk (completed, or failed for good) queues the run
   again with `s1_wake_parent_run`: a fenced `UPDATE ... WHERE NOT EXISTS (unfinished chunk)`
   taken under the run's row lock, so two readers ending the last two chunks together wake it
   exactly once, never zero times.
4. A reader claims the run again and assembles (`merge_chunk_outputs`): the chunks' text blocks,
   key-value pairs, tables, source references, pages and warnings are concatenated in page
   order into one parser output (an id that would collide gets a `c{index}:` prefix). Classify,
   target planning, extraction and persist then run on that one output as for any document, so
   the rule extractors see the whole document. The merged status is `parsed` when every chunk
   is, `empty` when none found text, `partial` otherwise.

Retries and leases are those of the runs: a chunk failure goes back to `queued` after
`RETRY_DELAYS_SECONDS` (30 s, then 120 s), and after `S1_CHUNK_MAX_ATTEMPTS` (3) the chunk is
`failed` (`error_code`, no text). A chunk whose Textract call failed on a page is also tried
again, and on its last attempt it is kept with what it read. A chunk whose reader died is
claimable again when its lease runs out (`requeue_expired_s1_document_chunks`, called by the
reader every 30 s with the runs'). Assembly goes on with the pages it has: the pipeline run is
`partial` with the warning `pages_unread: Pages 11-20 could not be read, ...`.

Over `S1_MAX_DOCUMENT_PAGES` (500) pages the document is not read: a `partial` pipeline run with
halt `document_too_long`.

| Setting | Default | |
|---|---|---|
| `S1_CHUNK_THRESHOLD_PAGES` | 20 | A PDF with more pages is chunked (at or under: read whole). |
| `S1_CHUNK_PAGES` | 10 | Pages per chunk. |
| `S1_CHUNK_MAX_ATTEMPTS` | 3 | Reads of one chunk before it is failed. |
| `S1_MAX_DOCUMENT_PAGES` | 500 | Over this, the run is partial with `document_too_long`. |

Like the `S1_READER_*` settings they are read from the container's own environment; a value in
`/opt/sustentra/.env` reaches it only once `write_app_env` in `deploy.sh` lists it.

`GET /v1/processing-runs/{run_id}` adds `chunks: {total, completed, failed, failed_pages}` for a
chunked run (see `api_contract.md`). Log lines for chunks carry the run id, chunk index, page
range, attempt, status and error code only (`chunks_planned`, `document_chunk_claimed`,
`chunk_finished`, `document_chunk_done`, `chunks_assembled`, `document_too_long`,
`document_chunks_requeued`).

## Document batches (migration 0019)

Files dropped together are one batch: `POST /v1/engagements/{id}/document-batches` makes it and uploads
carry its `batch_id`; `GET .../document-batches/{batch_id}` reports each document's status, chunk
progress, type, halt sentence and records found, with totals (`api/document_batches.py`, contract in
`api_contract.md`). `s1_document_batches` (id, org_id, engagement_id, created_by, created_at, label) has
RLS like the other s1 tables and is never updated or deleted by the app; `s1_documents.batch_id` is a
nullable filter column that must equal the record's own `batch_id`. The batch table lives in Postgres
whatever `S1_STORE` is, like the run queue. The view reads the latest run of each document, its chunk
summary and its pipeline run; it adds no new queue or state of its own.

## AI suggestions (Claude)

AI suggests a type or values for documents the system cannot read on its own; a person
accepts or corrects every suggestion. This part is the foundation only: no route calls
Claude yet, and the feature is off everywhere.

`backend/app/adapters/llm/claude.py`:

- `get_claude()` returns a `ClaudeClient`, or `None` when `AI_PROVIDER=anthropic` has no key.
- `ClaudeClient.structured()` sends one request whose reply must match a pydantic model
  (structured outputs). A refusal, a cut-off reply or a reply that does not match the model
  gives no output. On the Claude API, Claude Opus 5.5 and Claude Sonnet 5.5 requests carry
  `fallbacks: "default"` (server-side refusal fallback); Bedrock has no such fallback.
- `PRICES` and `cost_microusd()`: Anthropic's prices per million tokens. A model without a
  price is refused, so changing `AI_MODEL` means checking the
  [price list](https://platform.claude.com/docs/en/about-claude/pricing) first. On Bedrock
  the cost is an estimate; AWS bills at its own rates.
- The SDK is `anthropic` 2.x (API version `2026-10-21`). Tests fake the HTTP layer and never
  reach the network.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `AI_SUGGESTIONS_ENABLED` | `false` | The feature switch. |
| `AI_PROVIDER` | `anthropic` | `anthropic` (Claude API, needs the key) or `bedrock` (instance role, no key). |
| `ANTHROPIC_API_KEY` | none | Claude API key. A `SecretStr`: `show-settings` prints `**********`. |
| `AI_MODEL` | `claude-sonnet-5-5` | Claude API model id; on Bedrock the adapter adds `anthropic.`. |
| `AI_BEDROCK_MODEL_ID` | none | Bedrock only: full model id, sent as given. Unset, the adapter sends `anthropic.` + `AI_MODEL`. Prices stay keyed by `AI_MODEL`. |
| `AI_EFFORT` | `low` | `low`, `medium` or `high`. |
| `S1_AI_ROUTING_SHADOW` | `false` | Claude routing also reads documents the rules placed confidently, and may only add the warning `ai_type_disagrees`. One call per document; needs `AI_SUGGESTIONS_ENABLED`. |
| `AI_MONTHLY_CAP_USD` | `25` | Per-organization monthly cap (UTC calendar month; enforced before each call against the `ai_usage` ledger, which records every call; used by Methodology review prefill). |

### Claude routing (document type)

`services/ai_routing.py`, called by `PipelineOrchestrationService` right after the rule
classifier. Claude reads pages 1-2 (at most 200 lines and 12,000 characters, from
`ai_locator.document_lines`) and answers one `structured()` call:
`{canonical_type_id (the vocabulary's ids + "none"), quote, line, reason_code (title | header_terms | table_headers | other)}`.

- Runs when the classifier status is `unclassified` or `low_confidence` and the content-check
  accept path did not take the document. A type that has extraction targets is used with
  `canonical_type_source = "ai"` and `review_required`; the pipeline run carries
  `ai_routing` (quote, line, page from the parser, reason code). Extraction proceeds; the
  reviewer confirms or changes the type with the existing control.
- With `S1_AI_ROUTING_SHADOW` on, a confidently classified document is also read; a
  different answer only adds the warning `ai_type_disagrees` (both ids) and an `ai_routing`
  with `used: false`. The type never changes.
- A reviewer's override wins and Claude is not called.
- The quote must locate on the parser's lines (`locate_quote`). Otherwise the answer is
  ignored and counted: warning `ai_routing_ignored: <reason>` (`quote_not_on_document`,
  `unknown_line`, `ambiguous_quote`, `no_targets`). The page never comes from the model.
- Gate as prefill: `AI_SUGGESTIONS_ENABLED`, a client from `get_claude()`, and
  `ai_usage.cap_reached`. Every call that returns a reply is recorded in `ai_usage`
  (feature `routing`, no user) in its own short transaction after the call; no connection is
  held while Claude answers. A failed call (network, refusal, bad reply) adds the warning
  `ai_unavailable` and the run goes on as without AI. AI off: the run is byte-identical.
- The cap is checked without the per-org advisory lock: documents are read concurrently by
  several readers, and the lock is released before the call anyway, so it would only drop
  routing at random. A burst can overshoot the cap by a few calls of well under a cent each.

### How the key reaches the api container (staging)

1. The key lives only in SSM Parameter Store as the SecureString `/staging/anthropic_api_key`.
   It is created by hand, not in Terraform, so it never enters Terraform state.
2. On every deploy, `deploy/deploy.sh` (`write_app_env`) reads it with `get_optional_param`
   and appends `ANTHROPIC_API_KEY=...` to `/opt/sustentra/app.env` (mode 0600). When the
   parameter does not exist, as on prod, nothing is written and the deploy carries on. Any
   other SSM error fails the deploy. The value is never echoed or logged.
3. `deploy/docker-compose.prod.yml` gives `app.env` to the api container only (`env_file`);
   the web container never sees the key.
4. `Settings.anthropic_api_key` holds it as a `SecretStr`. The adapter keeps the SDK's
   logger at INFO, because at DEBUG the SDK logs whole request bodies.

The optional String parameters `/<env>/ai_suggestions_enabled`, `/<env>/ai_provider`,
`/<env>/ai_model`, `/<env>/ai_bedrock_model_id` and `/<env>/ai_monthly_cap_usd` are written to `app.env` the same way,
when they exist.

### Runbook

- **Put or rotate the key.** Paste it at a prompt so it stays out of shell history, then
  redeploy staging (`app.env` is refreshed only on deploy: re-run the deploy workflow):

  ```bash
  read -rs KEY && aws ssm put-parameter --region us-east-1 --overwrite \
    --name /staging/anthropic_api_key --type SecureString --value "$KEY"; unset KEY
  ```

- **Switch the feature on or off.** `aws ssm put-parameter --region us-east-1 --overwrite
  --name /staging/ai_suggestions_enabled --type String --value true` (or `false`), then redeploy.
- **Check.** On the host, in `/opt/sustentra`: `docker compose -f docker-compose.prod.yml
  --env-file .env exec api python -m backend.app.cli show-settings` shows
  `"anthropic_api_key": "**********"` when the key is set.
- **Remove the key.** `aws ssm delete-parameter --region us-east-1 --name
  /staging/anthropic_api_key`, then redeploy. Revoke it in the Anthropic Console too.
- **Bedrock instead.** Not yet tried live. The adapter uses the Bedrock Mantle endpoint
  (`bedrock-mantle.<region>.api.aws`, SigV4 service `bedrock-mantle`), which takes model ids
  like `anthropic.claude-sonnet-5-5` (no cross-region `us.` profile) and is authorized by
  `bedrock-mantle:CreateInference`, granted to the app-host role in `infra/iam_app_host.tf`
  (resource `*` until the model-ARN format is documented). See
  [Claude in Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock).
  No server-side refusal fallback on Bedrock.
  1. **First use (once per account).** An admin sends one message to the chosen Claude model
     in the Bedrock console playground in us-east-1. Anthropic models ask for a one-time
     use-case form on first invoke; the old model-access page is retired.
  2. **Apply the IAM change.** Run the terraform-apply workflow for staging.
  3. **Switch.** `aws ssm put-parameter --region us-east-1 --overwrite --name
     /staging/ai_provider --type String --value bedrock`; optionally set
     `/staging/ai_model` and `/staging/ai_bedrock_model_id`; then redeploy.
  4. **Smoke check.** On the host, in `/opt/sustentra`, one real call (a few tokens):

     ```bash
     docker compose -f docker-compose.prod.yml --env-file .env exec api python -c "
     from pydantic import BaseModel
     from backend.app.adapters.llm.claude import get_claude
     class Pong(BaseModel):
         word: str
     c = get_claude()
     r = c.structured(system='Reply with JSON.', content='Set word to pong.', output_type=Pong, max_tokens=200)
     print(c.provider, c.model, r.outcome, r.output, r.cost_microusd)"
     ```

     Expect `bedrock ... ok word='pong'`. `AccessDeniedException` means step 1 or 2 is missing.
- Prod has no AI parameters, so AI stays off there.

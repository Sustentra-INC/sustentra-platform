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
| `AI_WINDOW_PAGES` | `5` | Claude reading: pages per window (one page of overlap between windows). |
| `AI_MAX_WINDOWS` | `10` | Claude reading: windows per document; the pages left out are the warning `ai_pages_skipped`. |
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

### Claude reading (extraction assist)

`services/ai_extraction.py`, called by `PipelineOrchestrationService` after
`ExtractionService.extract` and before the result is persisted (not when the extraction halted).
Claude reads the document in windows and suggests values the rule extractors missed. Claude
only suggests.

- **Windows.** The parser's lines (`ai_locator.document_lines`) are split by page into windows
  of `AI_WINDOW_PAGES` pages with a one-page overlap (a workbook or CSV has no pages: its lines
  are cut into parts of 100), at most `AI_MAX_WINDOWS`, read in sequence. Every window's prompt
  starts with a header: canonical type, file name and the account number, period and supplier
  the rules already read, so context crosses the window borders. Pages left out: warning
  `ai_pages_skipped: pages 10-12 ...`. The run stops early at 80% of
  `S1_READER_MAX_RUN_SECONDS` (counted from the start of the document's run): warning
  `ai_time_budget` with the pages not read.
- **What is asked.** Fields whose document-level candidate is empty (`normalized_value` and
  `raw_value` null), each as an enum value with its label and allowed units, plus the known-gap
  fields of the type (extraction-config rows with `ai_only: true`: `heat_content`,
  `meter_number`, `vehicle_type`, `model_year`, `distance`; optional, not consumed by the
  calculation, never planned for the rule extractors: `get_targets_for_canonical_type` leaves
  them out unless `include_ai_only=True`). When a call is made anyway, the rule-read
  document-level fields are included as read-only cross-checks. Candidates of a layout
  extractor's records (`record_index`) are not filled and no record is created. Nothing is asked
  when nothing is missing and the type has no known-gap field.
- **Verify.** `ai_locator.locate` (quote on the cited parser line, value printed in the quote as
  a whole token), the value must be a bare number for numeric fields, and the unit must be in
  the field's allowed list (for `activity_unit`, the value is the unit). Dropped and counted by
  reason: `empty_value`, `unknown_line`, `quote_not_on_document`, `ambiguous_quote`,
  `value_not_in_quote`, `invalid_value`, `unit_not_allowed`.
- **Merge.** A verified value fills the empty candidate (same `candidate_id`; raw, normalized,
  unit; `source_reference` is the parser's reference of the quoted line; `confidence` =
  min(0.6, the line's parser confidence); flags: `field_not_found` removed, `ai_suggested`
  added). A known-gap field is added as a new candidate. The same field at the same parser
  reference counts once (windows overlap); the same value twice counts once; two different
  values for one field are two candidates (`...::ai2`) flagged `ai_conflict`. A rule-extracted
  value is never changed: when Claude read a different value there, the candidate gets the flag
  `ai_disagrees` and `ai_alternative {value, unit, source_reference}`.
- **The calculation never reads a suggestion.** `reviewed_evidence.group_reviewed_records` hides
  the value and unit of an `ai_suggested` candidate that has no accepted or edited decision, so
  neither the recalculation, the evidence tree nor the Coverage page can read it until a
  reviewer accepts or corrects it (an accept records the candidate's value as the reviewed
  value, as for any value).
- **Gate, ledger, warnings.** As routing: `AI_SUGGESTIONS_ENABLED`, a client, `cap_reached`
  (checked before each window against the month's spend plus what this run has spent). One
  `ai_usage` row per call, feature `extraction`, no user; a call that raises has no row. Any
  failure is the warning `ai_unavailable` and the run goes on. A summary warning carries counts
  only: `ai_extraction: ai_suggested n, ai_disagrees n, ai_conflict n, dropped n (reason n, ...),
  cost $x, windows k of m`. Logs carry ids, counts, cost and duration, never text. AI off: the
  pipeline output is byte-identical.

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

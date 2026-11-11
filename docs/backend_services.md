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
| `AI_MONTHLY_CAP_USD` | `25` | Per-organization monthly cap (enforced by the usage ledger, a later PR). |

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

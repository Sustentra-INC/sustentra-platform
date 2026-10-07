# Sustentra infrastructure (Terraform)

AWS account `012751249540`, region `us-east-1`, environment `prod`.
Every resource is named `sustentra-<environment>-<thing>` (e.g. `sustentra-prod-api`).

| Path | What it manages | How it is applied |
|---|---|---|
| `infra/bootstrap/` | S3 state bucket `sustentra-tfstate-012751249540` | From a laptop / the client admin (rare; see OPS-002) |
| `infra/` | GitHub OIDC provider, `deploy` + `terraform` roles, ECR repos (and later: network, EC2, RDS, SES, monitoring) | First apply from a laptop, then CI only |

State: S3 with versioning + AES-256, public access blocked, locking via
`use_lockfile = true` (S3 lock file, no DynamoDB). Requires Terraform >= 1.10.

No AWS access keys are stored anywhere in CI: GitHub Actions gets short-lived
credentials through OIDC, and only for `Sustentra-INC/sustentra-platform` on
the `main` branch or the `production` environment.

---

## One-time bootstrap (MVP-1)

Run in PowerShell. `allowed_account_ids` makes Terraform refuse to run if the
active credentials belong to any other account, so your other AWS setup is safe.

```powershell
$env:AWS_PROFILE = "sustentra"
aws sts get-caller-identity   # must show 012751249540
cd E:\Task\Vivian\Sustentra\sustentra-platform\infra
terraform fmt -recursive
```

### 1. Create the state bucket (local state)

```powershell
cd bootstrap
terraform init
terraform apply
```

### 2. Move the bootstrap's own state into that bucket

```powershell
Rename-Item backend.tf.disabled backend.tf
terraform init -migrate-state      # answer "yes"
Remove-Item terraform.tfstate, terraform.tfstate.backup -ErrorAction SilentlyContinue
cd ..
```

### 3. Create OIDC provider, CI roles and ECR repositories

```powershell
terraform init -backend-config="environments/prod.s3.tfbackend"
terraform providers lock -platform=windows_amd64 -platform=linux_amd64
terraform plan  -var-file="environments/prod.tfvars"
terraform apply -var-file="environments/prod.tfvars"
```

Commit `.terraform.lock.hcl` (both in `infra/` and `infra/bootstrap/`).
From here on, changes to `infra/` go through the `terraform` GitHub workflow.

### 4. GitHub setup

1. Repo **Settings → Environments → New environment** → `production`.
   Add yourself as a required reviewer so applies need approval.
2. Push the branch, open a PR (runs fmt + validate), merge to `main` (runs plan).
3. **Actions → ecr-oidc-smoke-test → Run workflow** — should push
   `sustentra-prod-api:oidc-smoke-<run id>` using the deploy role.

### 5. Clean up laptop credentials

If you used an IAM access key for the bootstrap, deactivate or delete it
afterwards (IAM → Users → your user → Security credentials), and ask the admin
to remove the temporary bootstrap permissions.

---

## Roles

| Role | Used by | Can do |
|---|---|---|
| `sustentra-prod-deploy` | app deploy workflow | push to the two ECR repos, `ssm:SendCommand` to EC2 instances tagged `Project=sustentra, Environment=prod`, snapshot RDS instances named `sustentra-prod-*` |
| `sustentra-prod-terraform` | `terraform` workflow | `PowerUserAccess` + IAM limited to `sustentra-prod-*` + the state bucket |

ECR repositories `sustentra-prod-api` and `sustentra-prod-web`: scan on push,
untagged images expire after 1 day, only the last 10 images are kept, and a
repository policy denies pushes from anyone except the deploy role.

## Environments and domains

| Env | Domain | Config | State key | CI roles trust |
|---|---|---|---|---|
| prod | `app.sustentra.com` | `environments/prod.*` | `prod/terraform.tfstate` | GitHub env `production` + `main` |
| staging | `staging.sustentra.com` | `environments/staging.*` | `staging/terraform.tfstate` | GitHub env `staging` + `main` |

DNS for `sustentra.com` is on Cloudflare. After each environment's first apply,
add an `A` record (`app` or `staging`) pointing to its `app_host_public_ip`,
proxy status **DNS only** (grey cloud).

### Creating staging (one-time, from a laptop)

Staging's own `sustentra-staging-terraform` role does not exist until staging is
applied once, so its first apply is manual (same permissions as the prod bootstrap,
plus EC2/VPC/CloudWatch/SSM read+write):

```powershell
$env:AWS_PROFILE = "sustentra"
cd infra
terraform init -reconfigure -backend-config="environments/staging.s3.tfbackend"
terraform apply -var-file="environments/staging.tfvars"
terraform init -reconfigure -backend-config="environments/prod.s3.tfbackend"   # switch back
```

Then create the GitHub environment `staging`. After that, use
Actions -> terraform -> Run workflow -> environment: staging.

### Branches and deploys

| Branch | Deploys to | Approval | Pre-deploy RDS snapshot |
|---|---|---|---|
| `staging` | `staging.sustentra.com` | GitHub env `staging` (none by default) | no |
| `main` | `app.sustentra.com` | GitHub env `production` (required reviewers) | yes |

Flow: feature branch -> PR into `staging` -> test on staging -> PR `staging` -> `main`.
`deploy.yml` picks the environment from the branch name; a manual *Run workflow*
deploys the branch you select (anything other than `staging` = prod).
Staging's CI roles trust the `staging` branch (`github_branch` in `staging.tfvars`).

### Running Terraform from a laptop

Always pass the matching backend **and** var file - without `-var-file` Terraform
prompts for every variable and falls back to defaults (e.g. the wrong DB class):

```powershell
terraform init -reconfigure -backend-config="environments/prod.s3.tfbackend"
terraform plan  -var-file="environments/prod.tfvars"
```

Never mix staging vars with prod state (or the reverse). A healthy plan for an
existing environment shows `0 to destroy`.

Notes:
- Both environments use `db_instance_class = "db.t3.micro"`: `db.t4g.micro` had no
  capacity in us-east-1 when they were created. Changing the class later needs
  capacity in the DB's current AZ.
- SES identities are account-wide: never list the same address in
  `ses_sandbox_recipients` of both `prod.tfvars` and `staging.tfvars`.

## RDS and application secrets (MVP-3)

- PostgreSQL 16 (`sustentra-<env>-db`), private subnets only, encrypted, 7-day
  backups, deletion protection, `rds.force_ssl = 1`, `row_security = on`.
- Port 5432 accepts connections only from the app host security group.
- SSM SecureString parameters (generated by Terraform):
  `/<env>/db_migration_url`, `/<env>/db_app_url`, `/<env>/otp_hmac_secret`.
  The app host can read only `/<env>/*`.
- Because generated secrets live in Terraform state, set
  `state_bucket_engineer_arns` in `infra/bootstrap/terraform.tfvars` and re-apply
  the bootstrap to lock the state bucket down.

### Tests (from the app host via `aws ssm start-session`)

```bash
URL=$(aws ssm get-parameter --with-decryption --name /prod/db_migration_url --query Parameter.Value --output text)
PG="sudo docker run --rm postgres:16-alpine psql"

$PG "$URL" -c "SELECT version();"                  # SSL connection works
$PG "${URL/sslmode=require/sslmode=disable}" -c "SELECT 1;"   # must FAIL: no pg_hba.conf entry ... no encryption
$PG "$URL" -c "SHOW row_security;"                 # on
```

From your laptop (outside the VPC), port 5432 must be unreachable:
`Test-NetConnection <db_endpoint> -Port 5432` -> `TcpTestSucceeded : False`.

## Email: Amazon SES (MVP-4)

- Sending domain = `app_domain` (prod `app.sustentra.com`, staging `staging.sustentra.com`),
  From address `no-reply@<domain>`. Using the subdomain keeps the Microsoft 365
  email records on `sustentra.com` untouched.
- Easy DKIM (2048-bit), custom MAIL FROM `bounce.<domain>` (SPF), DMARC `p=quarantine`.
- Configuration set `sustentra-<env>-default` (TLS required, account suppression list)
  sends BOUNCE and COMPLAINT events to SNS topic `sustentra-<env>-ses-events`, which
  emails everyone in `alert_emails`.
- CloudWatch alarms: bounce rate >= 2%, complaint rate >= 0.05% (AWS reviews at 5% / 0.1%).
- The app host may send only as `no-reply@<domain>` through that configuration set.

### After apply

1. `terraform output ses_dns_records` -> add every record in Cloudflare
   (3 DKIM CNAMEs, 1 MX + 1 TXT on `bounce.<domain>`, 1 TXT `_dmarc.<domain>`),
   proxy status **DNS only**. SES shows the domain as *Verified* within ~1 hour.
2. Confirm the "AWS Notification - Subscription Confirmation" email for each
   address in `alert_emails`.
3. Request production access (one per AWS account/region; takes up to 24h):
   ```powershell
   aws sesv2 put-account-details --region us-east-1 --profile sustentra `
     --production-access-enabled --mail-type TRANSACTIONAL `
     --website-url https://app.sustentra.com --contact-language EN `
     --use-case-description "Transactional email for the Sustentra platform: sign-in one-time passcodes and account notifications to registered users only. No marketing. Bounces and complaints are handled via SNS and the SES suppression list." `
     --additional-contact-email-addresses ops@sustentra.com
   ```
   (Needs `ses:PutAccountDetails`; otherwise an admin can submit the same in the
   SES console -> Account dashboard -> Request production access.)

### Sandbox fallback (until production access is approved)

SES only delivers to verified addresses. Add developer inboxes to
`ses_sandbox_recipients` in the env tfvars, apply, and click the verification
link AWS emails to each one. Remove them once production access is granted.

### Tests (from the app host via `aws ssm start-session`)

```bash
# Delivered; in the recipient's "Show original": SPF=PASS, DKIM=PASS, DMARC=PASS
aws sesv2 send-email --region us-east-1 \
  --from-email-address no-reply@app.sustentra.com \
  --destination ToAddresses=you@example.com \
  --content '{"Simple":{"Subject":{"Data":"SES test"},"Body":{"Text":{"Data":"Hello from Sustentra"}}}}'

# Simulated bounce -> an SNS notification email arrives at alert_emails
aws sesv2 send-email --region us-east-1 \
  --from-email-address no-reply@app.sustentra.com \
  --destination ToAddresses=bounce@simulator.amazonses.com \
  --content '{"Simple":{"Subject":{"Data":"Bounce test"},"Body":{"Text":{"Data":"bounce"}}}}'
```

## First provider admin (ORG-000)

There is no sign-up for provider admins: create the first one from the running `api`
container. The command uses the API's own database connection (`app_user`, provider RLS
scope), is idempotent on the email (a second run changes nothing and exits 0), and writes
a `provider_admin_created` audit event. The password is never a command-line argument.

```bash
aws ssm start-session --target <instance-id>      # staging or prod app host

sudo docker compose -f /opt/sustentra/docker-compose.prod.yml --env-file /opt/sustentra/.env \
  exec api python -m backend.app.cli create-provider-admin \
  --email ops@sustentra.com --first-name Ada --last-name Lovelace
# Password: / Confirm password:   (hidden; >= 12 chars, not a common password, not the email)
```

No one at the keyboard who should know the password? Add `--reset-link`: the account is
created without a password and the command prints a one-time
`https://<domain>/provider-admin/reset-password?token=...` link (valid 1 hour) to hand
over. If it expires, use *Forgot password* on `/provider-admin/login`.

Then sign in at `https://<domain>/provider-admin/login` with password + email OTP.
While SES is in the sandbox, the admin's email must be in `ses_sandbox_recipients`
(see above) or the OTP is never delivered.

## S1 data ownership (SEC-001)

Every S1 workpaper endpoint under `/api/v1` needs a signed-in session, and data is
scoped to the caller's organization: `org_admin` / `org_member` read and write their own
org's documents, pipeline runs, reviews and approved evidence; a `provider_admin` can read
every org's data (support) but not upload, process or review. Another org's records
answer 404.

S1 records written before SEC-001 have no owner, so only a provider admin sees them. To
hand one engagement's records (and its uploaded files) to an organization:

```bash
sudo docker compose -f /opt/sustentra/docker-compose.prod.yml --env-file /opt/sustentra/.env \
  exec api python -m backend.app.cli claim-s1-data --engagement-id ENG-123 --org-slug acme --dry-run
# then the same without --dry-run
```

It only stamps records that have no owner (records owned by another org are reported and
left alone), moves the uploaded files into the org's folder, and keeps a
`<file>.bak-<timestamp>` copy of each JSONL file it rewrites.

## Security headers and document previews (S1-BE-001)

`deploy/Caddyfile` sets the security headers on every response. `X-Frame-Options`
and `Content-Security-Policy` are set as defaults (`?`): a response that already has
them keeps its own. Only the API's document routes do that:

- `/api/v1/documents/{id}/preview` - `X-Frame-Options: SAMEORIGIN`, `frame-ancestors 'self'`
  (plus `default-src 'none'; sandbox` for images), so the workpaper can frame it;
- `/api/v1/documents/{id}/download` - `X-Frame-Options: DENY` and a `sandbox` CSP.

Everything else gets the proxy's `DENY` / `frame-ancestors 'none'` as before.

## Upload size limit (INFRA-007)

S1 document uploads may be up to **25 MB** (`MAX_UPLOAD_MB` in the API's `app.env`,
default 25). Every other request stays capped at 1 MB by Caddy.

| Layer | Where | Limit |
|---|---|---|
| Caddy | `deploy/Caddyfile` (`@document_upload`) | 26 MiB body on `/api/v1/engagements/*/documents/upload`; a larger declared `Content-Length` gets 413 straight away |
| API | `UploadSizeLimitMiddleware` + the upload route | 413 `File is too large. The maximum upload size is 25 MB.` |
| Frontend | `features/s1/constants/uploads.ts` | checks the file before sending; any 413 shows the same message |
| Next dev proxy | `next.config.ts` `proxyClientMaxBodySize` | 26 MB (local dev only) |

To change it, update all four together.

The API image links `/app/local-data` to the `/app/data` volume: the S1 JSONL stores
and uploads write to `./local-data`, and the root filesystem is read-only.

## Hand-over to CI: remove laptop credentials (OPS-002)

Infra was bootstrapped from a laptop (IAM user `Jerome`, profile `sustentra`).
After this hand-over, GitHub Actions (OIDC roles) is the only way to change
infrastructure and nobody keeps a long-lived access key.

Check progress at any point (read-only; Git Bash or WSL on Windows):

```bash
bash infra/scripts/ops002-check.sh           # report
bash infra/scripts/ops002-check.sh --final   # exit 1 until everything is done
```

Do the steps **in this order**. Step 2 must happen before step 4, or nobody but
the account root can reach the Terraform state (it holds the DB passwords).

1. **CI applies cleanly.** Actions → terraform-apply → Run workflow (from `main`)
   for `staging`, then `prod`. Each plan must show no changes, or only ones you
   expect. Fix any drift through a PR, not from the laptop.
2. **Give the client admin state access.** Ask the client admin for their ARN
   (`aws sts get-caller-identity --query Arn`), add it to
   `state_bucket_engineer_arns` in `infra/bootstrap/terraform.tfvars` (PR), then
   re-apply the bootstrap once more from the laptop:
   ```powershell
   $env:AWS_PROFILE = "sustentra"
   cd infra\bootstrap
   terraform init
   terraform apply
   ```
   The check script should now list the client admin under "allowed".
3. **Client removes the temporary bootstrap permissions** from IAM user `Jerome`
   (attached policies, inline policies, groups). From here the laptop key can no
   longer change anything.
4. **Retire the laptop key.** IAM → Users → Jerome → Security credentials:
   *Deactivate* the access key, wait a day to be sure nothing still uses it (the
   check script prints when it was last used), then *Delete* it. Remove the
   `sustentra` profile from `~/.aws/credentials` on the laptop.
5. Run `bash infra/scripts/ops002-check.sh --final` as the client admin: all
   checks pass. `user/Jerome` may stay in `state_bucket_engineer_arns`; with no
   key and no permissions it grants nothing, and the next bootstrap change can
   drop it.

Re-applying the bootstrap later (rare: only the state bucket lives there) is
done by the client admin with their own credentials.

## Branch protection and deploy approval (OPS-003)

`infra/github/branch-protection.sh` sets everything up with the GitHub CLI
(run it as a repository admin; it is idempotent):

```bash
gh auth login
bash infra/github/branch-protection.sh --check   # what is in place now (read-only)
bash infra/github/branch-protection.sh --apply   # create / update
```

| Target | Rules |
|---|---|
| `main` (ruleset `protect-main`) | PR required; checks `backend`, `frontend`, `validate`, `plan-pr` must pass; no force-push, no deletion |
| `staging` (ruleset `protect-staging`) | PR required; checks `backend`, `frontend` must pass; no force-push, no deletion |
| environment `production` | required reviewers (default: whoever runs the script; `REVIEWERS=a,b` to set); deploys from `main` only |

- Checks must come from the GitHub Actions app, so nothing else can fake a green status.
- `APPROVALS=1` makes PRs need an approving review (default 0: a PR is required but you may merge your own).
- `validate` and `plan-pr` only matter for infra changes. `terraform.yml` therefore
  runs on every PR and skips them when nothing under `infra/` changed — a skipped
  check counts as passed. **Merge that workflow change before running `--apply`**,
  or PRs to `main` that don't touch `infra/` would wait forever for those checks.
- Emergency: a repo admin can temporarily set a ruleset's enforcement to
  *Disabled* (Settings → Rules → Rulesets) instead of deleting it.

## CI/CD (MVP-5)

| Workflow | Trigger | What it does | AWS role |
|---|---|---|---|
| `ci` | every PR + push to main | ruff, mypy, pytest (**80% coverage gate**), eslint, tsc, vitest, next build | none |
| `terraform` | PR / push touching `infra/` | fmt + validate; PR: `terraform plan` posted as a PR comment; main: plan | `*-terraform-plan` (PR, read-only), `*-terraform` (main) |
| `terraform-apply` | manual, from main | plan + apply for prod or staging, **approval required** | `*-terraform` |
| `deploy` | push to main touching app code, or manual | build `api` + `web` images tagged with the commit SHA -> ECR -> **approval** -> RDS snapshot -> `alembic upgrade head` -> `compose pull && up -d` -> poll `/api/health` -> auto-rollback to the previous tag on failure | `*-deploy` |

No AWS keys are stored in GitHub; every job uses OIDC.

### One-time GitHub settings (repo admin)

1. **Settings -> Environments -> `production`**: *Required reviewers* = you (+ a teammate).
   This is the manual approval for both `deploy` and `terraform-apply`.
2. **Settings -> Branches -> main -> Branch protection**: require a PR and the status
   checks `backend`, `frontend`, `validate`, `plan-pr` - so a failed coverage gate blocks the merge.

### Tests

- Valid PR -> all checks green, plan comment appears.
- Drop coverage below 80% (e.g. add an untested module) -> `backend` fails -> merge blocked.
- Deploy a commit whose `/health` returns 500 -> `deploy` fails, log shows
  "rolling back to <previous sha>", the site keeps serving the previous version.
- Start `deploy` -> it waits on "Waiting for review" until a reviewer approves.

## Monitoring and alarms (MVP-6)

- Log groups `/sustentra/<env>/{caddy,api,web}`, 30-day retention. Each container
  logs to its own group (awslogs driver, `deploy/docker-compose.prod.yml`).
- API logs are JSON (`backend/app/observability.py`): one line per request with
  `request_id`, `method`, `path` (no query string), `status`, `duration_ms`,
  `user_id`, `org_id`. Bodies, headers, passwords, OTP codes and tokens are never logged.
  Caddy passes the same `X-Request-ID` to the API and returns it to the client.
- SNS topic `sustentra-<env>-alerts` -> every address in `alert_emails` (confirm the email).
- Alarms: EC2 `StatusCheckFailed`; RDS `FreeStorageSpace` < 2 GB, `CPUUtilization` > 80%
  for 10 min, `DatabaseConnections` > 80% of `db_max_connections` (verify with `SHOW max_connections;`).
- Uptime: Route 53 health check on `https://<app_domain>/api/health` from AWS checkers
  outside the VPC (every 30s, 3 failures) -> alarm -> email, typically within ~3 minutes.

### Tests

```powershell
# 1. Alarm email arrives
aws cloudwatch set-alarm-state --profile sustentra --alarm-name sustentra-prod-rds-cpu-high `
  --state-value ALARM --state-reason "test"

# 2. Uptime alert within 5 minutes: on the server (SSM session)
#    sudo docker compose -f /opt/sustentra/docker-compose.prod.yml --env-file /opt/sustentra/.env stop api
#    ...wait for the email, then: ... start api

# 3. Login request in the API logs with its request ID and no secrets
aws logs filter-log-events --profile sustentra --log-group-name /sustentra/prod/api `
  --filter-pattern '{ $.path = "/v1/auth/login" }' --max-items 5
```

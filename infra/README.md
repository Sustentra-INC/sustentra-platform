# Sustentra infrastructure (Terraform)

AWS account `012751249540`, region `us-east-1`, environment `prod`.
Every resource is named `sustentra-<environment>-<thing>` (e.g. `sustentra-prod-api`).

| Path | What it manages | How it is applied |
|---|---|---|
| `infra/bootstrap/` | S3 state bucket `sustentra-tfstate-012751249540` | Once, from a laptop |
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

## Adding a staging environment later

Copy `environments/prod.*` to `environments/staging.*`, change `environment`
and the state `key`, and set `create_github_oidc_provider = false` (the OIDC
provider is account-wide and already exists).

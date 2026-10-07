#!/usr/bin/env bash
# OPS-003 - protect main and staging, and gate production deploys, with the GitHub CLI.
#
#   bash infra/github/branch-protection.sh --check   # read-only: show what is in place
#   bash infra/github/branch-protection.sh --apply   # create / update (idempotent)
#
# Needs `gh` logged in as a repository ADMIN (gh auth login). Safe to re-run:
# rulesets are matched by name and updated in place.
#
#   main     PR required; checks backend, frontend, validate, plan-pr must pass;
#            no force-push, no deletion
#   staging  PR required; checks backend, frontend must pass; no force-push, no deletion
#   production environment
#            required reviewers (REVIEWERS, default: you); deploys only from main
#
# validate / plan-pr come from .github/workflows/terraform.yml, which runs on every
# PR and SKIPS them when infra/ is untouched (a skipped check counts as passed).
# Without that, PRs to main that don't touch infra/ could never be merged.

set -euo pipefail

REPO="${REPO:-Sustentra-INC/sustentra-platform}"
REVIEWERS="${REVIEWERS:-}"          # comma-separated GitHub logins; default: the gh user
APPROVALS="${APPROVALS:-0}"         # PR approvals required (0 = PR required, self-merge ok)
ACTIONS_APP_ID=15368                # "GitHub Actions" app: only it may report these checks
MODE="${1:---check}"

die() { echo "error: $*" >&2; exit 1; }
command -v gh >/dev/null || die "install the GitHub CLI (https://cli.github.com) and run: gh auth login"
gh auth status >/dev/null 2>&1 || die "not logged in: gh auth login"

ruleset_json() { # name, branch, checks...
  local name="$1" branch="$2"; shift 2
  local checks="" sep=""
  for c in "$@"; do checks+="${sep}{\"context\":\"${c}\",\"integration_id\":${ACTIONS_APP_ID}}"; sep=","; done
  cat <<JSON
{
  "name": "${name}",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["refs/heads/${branch}"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": ${APPROVALS},
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [${checks}]
    }}
  ]
}
JSON
}

ruleset_id() { gh api "repos/${REPO}/rulesets" --jq ".[] | select(.name == \"$1\") | .id" 2>/dev/null | head -1; }

show() {
  echo "Repository: ${REPO}  (you: $(gh api user --jq .login))"
  echo "Admin: $(gh api "repos/${REPO}" --jq .permissions.admin)"
  for name in protect-main protect-staging; do
    local id; id=$(ruleset_id "$name")
    if [[ -z "$id" ]]; then echo "  [todo] ruleset ${name} missing"; continue; fi
    gh api "repos/${REPO}/rulesets/${id}" --jq \
      '"  [ok]   ruleset \(.name) (\(.enforcement)): " + ([.rules[].type] | join(", ")) +
       "; checks: " + ([.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context] | join(", "))'
  done
  local env
  env=$(gh api "repos/${REPO}/environments/production" 2>/dev/null || true)
  if [[ -z "$env" ]]; then
    echo "  [todo] environment production missing"
  else
    gh api "repos/${REPO}/environments/production" --jq \
      '"  [" + (if ([.protection_rules[]? | select(.type=="required_reviewers")] | length) > 0 then "ok]  " else "todo]" end) +
       " environment production: reviewers " +
       ([.protection_rules[]? | select(.type=="required_reviewers") | .reviewers[].reviewer.login] | join(", ")) +
       "; branch policy: " + ((.deployment_branch_policy // {}) | tostring)'
  fi
}

apply() {
  [[ "$(gh api "repos/${REPO}" --jq .permissions.admin)" == "true" ]] || die "you need admin rights on ${REPO}"

  upsert() { # name, json
    local id; id=$(ruleset_id "$1")
    if [[ -n "$id" ]]; then
      gh api -X PUT "repos/${REPO}/rulesets/${id}" --input - <<<"$2" >/dev/null && echo "updated ruleset $1"
    else
      gh api -X POST "repos/${REPO}/rulesets" --input - <<<"$2" >/dev/null && echo "created ruleset $1"
    fi
  }
  upsert protect-main "$(ruleset_json protect-main main backend frontend validate plan-pr)"
  upsert protect-staging "$(ruleset_json protect-staging staging backend frontend)"

  # production: required reviewers, deploys from main only.
  local logins ids="" sep=""
  logins="${REVIEWERS:-$(gh api user --jq .login)}"
  IFS=',' read -ra arr <<<"$logins"
  for login in "${arr[@]}"; do
    ids+="${sep}{\"type\":\"User\",\"id\":$(gh api "users/${login// /}" --jq .id)}"; sep=","
  done
  gh api -X PUT "repos/${REPO}/environments/production" --input - >/dev/null <<JSON
{"reviewers": [${ids}], "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
  if ! gh api "repos/${REPO}/environments/production/deployment-branch-policies" \
       --jq '.branch_policies[].name' | grep -qx main; then
    gh api -X POST "repos/${REPO}/environments/production/deployment-branch-policies" \
      -f name=main -f type=branch >/dev/null
  fi
  echo "environment production: reviewers ${logins}; deploys from main only"
  echo
  show
}

case "$MODE" in
  --check) show ;;
  --apply) apply ;;
  *) die "usage: $0 --check | --apply" ;;
esac

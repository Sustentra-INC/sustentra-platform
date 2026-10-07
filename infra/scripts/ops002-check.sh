#!/usr/bin/env bash
# OPS-002 - check the hand-over of infrastructure to CI. READ-ONLY: it never
# changes anything in AWS. Run it before and after each manual step:
#
#   bash infra/scripts/ops002-check.sh            # progress report, exit 0
#   bash infra/scripts/ops002-check.sh --final    # exit 1 unless every check passes
#
# Needs the AWS CLI v2 and credentials that may read IAM and the state bucket
# policy (the client admin, or the laptop key while it still exists).
# Override the defaults with env vars: AWS_ACCOUNT_ID, LAPTOP_USER, STATE_BUCKET.

set -uo pipefail

ACCOUNT="${AWS_ACCOUNT_ID:-012751249540}"
LAPTOP_USER="${LAPTOP_USER:-Jerome}"
BUCKET="${STATE_BUCKET:-sustentra-tfstate-${ACCOUNT}}"
PROJECT=sustentra
FINAL=0
[[ "${1:-}" == "--final" ]] && FINAL=1

failures=0
pass() { printf '  [ok]   %s\n' "$*"; }
fail() { printf '  [todo] %s\n' "$*"; failures=$((failures + 1)); }
info() { printf '         %s\n' "$*"; }

echo "Caller: $(aws sts get-caller-identity --query Arn --output text 2>/dev/null || echo 'no AWS credentials')"
echo

echo "1. CI can manage both environments"
if aws iam get-open-id-connect-provider \
     --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com" \
     >/dev/null 2>&1; then
  pass "GitHub OIDC provider exists"
else
  fail "GitHub OIDC provider not found"
fi
for env in staging prod; do
  for role in terraform terraform-plan deploy; do
    name="${PROJECT}-${env}-${role}"
    if aws iam get-role --role-name "$name" >/dev/null 2>&1; then
      pass "role ${name}"
    else
      fail "role ${name} is missing"
    fi
  done
done
info "Then run Actions -> terraform-apply for staging and prod (from main): the plan step"
info "must show 'No changes' (or only changes you expect) before you remove the laptop key."
echo

echo "2. State bucket policy lists the right engineers (${BUCKET})"
policy=$(aws s3api get-bucket-policy --bucket "$BUCKET" --query Policy --output text 2>/dev/null)
if [[ -z "$policy" ]]; then
  fail "cannot read the bucket policy (no access, or the bucket name is wrong)"
else
  # Named principals only: skip the CI role wildcard (role/sustentra-*-terraform*).
  mapfile -t engineers < <(printf '%s' "$policy" | grep -oE 'arn:aws:iam::[0-9]+:(user|role)/[A-Za-z0-9+=,.@_/*-]+' \
    | grep -v '\*' | sort -u)
  if ((${#engineers[@]} == 0)); then
    fail "no named engineers: only root and the CI terraform roles can reach the state"
  else
    for arn in "${engineers[@]}"; do info "allowed: ${arn}"; done
    others=$(printf '%s\n' "${engineers[@]}" | grep -cv ":user/${LAPTOP_USER}$")
    if ((others > 0)); then
      pass "${others} engineer(s) besides ${LAPTOP_USER} can still reach the state"
    else
      fail "only ${LAPTOP_USER} is listed: add the client admin to state_bucket_engineer_arns and re-apply the bootstrap BEFORE removing the laptop key"
    fi
  fi
fi
echo

echo "3. Temporary bootstrap permissions removed from IAM user ${LAPTOP_USER}"
if ! aws iam get-user --user-name "$LAPTOP_USER" >/dev/null 2>&1; then
  pass "user ${LAPTOP_USER} does not exist (or is not visible to this caller)"
else
  attached=$(aws iam list-attached-user-policies --user-name "$LAPTOP_USER" --query 'AttachedPolicies[].PolicyName' --output text 2>/dev/null)
  inline=$(aws iam list-user-policies --user-name "$LAPTOP_USER" --query 'PolicyNames' --output text 2>/dev/null)
  groups=$(aws iam list-groups-for-user --user-name "$LAPTOP_USER" --query 'Groups[].GroupName' --output text 2>/dev/null)
  if [[ -z "$attached$inline$groups" ]]; then
    pass "no policies or groups attached"
  else
    fail "still has permissions - attached: [${attached}] inline: [${inline}] groups: [${groups}]"
  fi
fi
echo

echo "4. No long-lived access keys for ${LAPTOP_USER}"
keys=$(aws iam list-access-keys --user-name "$LAPTOP_USER" --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output text 2>/dev/null)
if [[ -z "$keys" ]]; then
  pass "no access keys"
else
  while read -r id status; do
    [[ -z "$id" ]] && continue
    last=$(aws iam get-access-key-last-used --access-key-id "$id" --query 'AccessKeyLastUsed.LastUsedDate' --output text 2>/dev/null)
    fail "key ${id:0:8}... is ${status} (last used: ${last:-never}) - deactivate, wait a day, then delete"
  done <<< "$keys"
fi
echo

if ((failures == 0)); then
  echo "OPS-002: all checks pass."
else
  echo "OPS-002: ${failures} item(s) still to do."
fi
((FINAL == 1 && failures > 0)) && exit 1
exit 0

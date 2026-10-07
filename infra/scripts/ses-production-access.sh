#!/usr/bin/env bash
# OPS-001 - move Amazon SES (us-east-1) out of the sandbox.
#
#   bash infra/scripts/ses-production-access.sh --check     # read-only status (default)
#   bash infra/scripts/ses-production-access.sh --request   # submit the production access request
#
# Needs the AWS CLI v2. --check needs ses:GetAccount / ses:GetEmailIdentity;
# --request needs ses:PutAccountDetails (or submit the same text in the SES console:
# Account dashboard -> Request production access). Pass --profile via AWS_PROFILE.
# AWS answers within ~24h by email to the account's contacts.

set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
DOMAINS=(app.sustentra.com staging.sustentra.com)
CONTACT="${SES_CONTACT:-dev.sustentra@gmail.com}"
MODE="${1:---check}"

USE_CASE="Sustentra is a B2B web platform for verifying greenhouse-gas emissions data. We send transactional email only, from no-reply@app.sustentra.com (production) and no-reply@staging.sustentra.com (staging): one-time sign-in passcodes, password-reset links and account invitations, each triggered by an action of a registered user of an organization that has a contract with us. No marketing, newsletters or purchased lists, and every recipient is a known user of a client organization. Expected volume: under 2,000 emails per month (pilot), peaks of a few hundred per day. Both domains are verified with Easy DKIM (2048-bit), a custom MAIL FROM (SPF) and DMARC p=quarantine. Every message goes through a configuration set that publishes bounces and complaints to SNS (alerted to our operations inbox); the account-level suppression list is enabled, and CloudWatch alarms fire at a 2% bounce or 0.05% complaint rate, well below the review thresholds."

check() {
  echo "SES account in ${REGION}"
  aws sesv2 get-account --region "$REGION" --output text --query \
    '[ProductionAccessEnabled, SendingEnabled, SendQuota.Max24HourSend, SendQuota.MaxSendRate, Details.ReviewDetails.Status, Details.ReviewDetails.CaseId]' \
    2>/dev/null | {
      read -r prod sending max24 rate review case || { echo "  cannot read the SES account (credentials / permissions?)"; return; }
      echo "  production access: ${prod}   sending enabled: ${sending}"
      echo "  quota: ${max24} per 24h, ${rate}/s   (sandbox = 200 per 24h, 1/s)"
      echo "  review: ${review:-none}   case: ${case:-none}"
      if [[ "$prod" == "True" ]]; then
        echo "  -> out of the sandbox: merge the 'remove sandbox recipients' PR and apply both environments"
      fi
    }
  echo
  for domain in "${DOMAINS[@]}"; do
    # Keep AWS's own error: "not found" and "not allowed to look" need different fixes.
    local out
    if out=$(aws sesv2 get-email-identity --region "$REGION" --email-identity "$domain" --output text --query \
      '[VerifiedForSendingStatus, DkimAttributes.Status, MailFromAttributes.MailFromDomainStatus]' 2>&1); then
      read -r verified dkim mailfrom <<<"$out"
      echo "  ${domain}: verified=${verified} dkim=${dkim} mail-from=${mailfrom}"
    elif grep -q NotFoundException <<<"$out"; then
      echo "  ${domain}: NOT FOUND in ${REGION} - the SES domain identity is missing (terraform apply for that environment)"
    elif grep -qE "AccessDenied|not authorized" <<<"$out"; then
      echo "  ${domain}: cannot check - these credentials lack ses:GetEmailIdentity (try the client admin / CI role)"
    else
      echo "  ${domain}: cannot check - $(head -1 <<<"$out")"
    fi
  done
}

request() {
  echo "Submitting the production access request (${REGION}), contact ${CONTACT}:"
  echo
  echo "$USE_CASE" | fold -s -w 100 | sed 's/^/  /'
  echo
  read -r -p "Submit? [y/N] " answer
  [[ "$answer" == [yY] ]] || { echo "Cancelled."; exit 0; }
  aws sesv2 put-account-details --region "$REGION" \
    --production-access-enabled \
    --mail-type TRANSACTIONAL \
    --website-url https://app.sustentra.com \
    --contact-language EN \
    --use-case-description "$USE_CASE" \
    --additional-contact-email-addresses "$CONTACT" \
    && echo "Submitted. AWS replies by email (usually within 24h); re-run with --check."
}

case "$MODE" in
  --check) check ;;
  --request) request ;;
  *) echo "usage: $0 --check | --request" >&2; exit 2 ;;
esac

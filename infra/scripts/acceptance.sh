#!/usr/bin/env bash
# TEST-003 - infra acceptance tests for one environment. Writes a Markdown report
# (paste it into the Linear ticket as the per-environment comment).
#
#   bash infra/scripts/acceptance.sh staging --email you@example.com
#   bash infra/scripts/acceptance.sh prod    --email you@example.com
#   bash infra/scripts/acceptance.sh staging --email you@example.com --disruptive
#
# Automated:  RDS SSL / non-SSL / row_security (on the app host via SSM), RDS port
#             closed from here, API log line for a login request (request ID, no secrets)
# Triggered, you confirm by email/inbox: SES test email (SPF/DKIM/DMARC), simulated
#             bounce -> SNS email, alarm email (set-alarm-state)
# --disruptive: stops the API for up to 6 minutes to prove the uptime alarm fires
#             (asks for confirmation; never use on prod during working hours)
# Manual (listed in the report): deploy rollback on failed health check, prod
#             deploy approval
#
# Needs the AWS CLI v2 and curl; credentials that can use SSM send-command on the app
# host, read RDS / CloudWatch / logs, and set alarm state. Region us-east-1.

set -uo pipefail

ENV="${1:-}"
[[ "$ENV" == "staging" || "$ENV" == "prod" ]] || { echo "usage: $0 staging|prod --email you@example.com [--disruptive]" >&2; exit 2; }
shift
EMAIL=""
DISRUPTIVE=0
while (($#)); do
  case "$1" in
    --email) EMAIL="${2:-}"; shift 2 ;;
    --disruptive) DISRUPTIVE=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

export AWS_REGION="${AWS_REGION:-us-east-1}"
P="sustentra-${ENV}"
DOMAIN=$([[ "$ENV" == "prod" ]] && echo app.sustentra.com || echo staging.sustentra.com)
REPORT="acceptance-${ENV}-$(date +%Y%m%d-%H%M).md"
COMPOSE="sudo docker compose -f /opt/sustentra/docker-compose.prod.yml --env-file /opt/sustentra/.env"

declare -a ROWS=()
row() { # check, result, details (one line, no pipes, so the Markdown table stays intact)
  local details; details=$(printf '%s' "$3" | tr '\n|' ' /' | cut -c1-240)
  ROWS+=("| $1 | $2 | ${details} |"); printf '  %-8s %s - %s\n' "$2" "$1" "$details"
}

# Run a shell script on the app host through SSM; prints its stdout, returns its exit code.
on_host() {
  local cid status out
  cid=$(aws ssm send-command --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
        --parameters "$(printf '{"commands":[%s]}' "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')")" \
        --query Command.CommandId --output text 2>/dev/null) || return 99
  for _ in $(seq 1 60); do
    sleep 3
    status=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$INSTANCE" --query Status --output text 2>/dev/null)
    [[ "$status" == "InProgress" || "$status" == "Pending" || "$status" == "Delayed" || -z "$status" ]] || break
  done
  out=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$INSTANCE" --query StandardOutputContent --output text 2>/dev/null)
  printf '%s' "$out"
  [[ "$status" == "Success" ]]
}

echo "Acceptance tests: ${ENV} (${DOMAIN}) as $(aws sts get-caller-identity --query Arn --output text 2>/dev/null || echo '?')"

INSTANCE=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=${P}-app-host" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null)
[[ "$INSTANCE" == i-* ]] || { echo "app host ${P}-app-host not found / not running" >&2; exit 1; }
DB_HOST=$(aws rds describe-db-instances --db-instance-identifier "${P}-db" --query 'DBInstances[0].Endpoint.Address' --output text 2>/dev/null)
echo "  app host ${INSTANCE}, db ${DB_HOST}"
echo

# ---------------------------------------------------------------- RDS
PSQL="URL=\$(aws ssm get-parameter --region ${AWS_REGION} --with-decryption --name /${ENV}/db_migration_url --query Parameter.Value --output text)
PG='sudo docker run --rm postgres:16-alpine psql'"
if out=$(on_host "${PSQL}
\$PG \"\$URL\" -Atc 'SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()'"); then
  if [[ "$(tr -d '[:space:]' <<<"$out")" == "t" ]]; then
    row "RDS: SSL connection" PASS "connected, pg_stat_ssl.ssl = t"
  else
    row "RDS: SSL connection" FAIL "connected but not encrypted: ${out}"
  fi
else
  row "RDS: SSL connection" FAIL "could not connect: ${out:0:200}"
fi
if out=$(on_host "${PSQL}
\$PG \"\${URL/sslmode=require/sslmode=disable}\" -Atc 'SELECT 1' 2>&1; echo \"exit=\$?\""); then
  if [[ "$out" == *"exit=0"* ]]; then
    row "RDS: non-SSL rejected" FAIL "a non-SSL connection succeeded"
  else
    row "RDS: non-SSL rejected" PASS "server refused it: $(grep -m1 -i 'error' <<<"$out" || echo rejected)"
  fi
else
  row "RDS: non-SSL rejected" FAIL "SSM command failed: ${out:0:200}"
fi
if out=$(on_host "${PSQL}
\$PG \"\$URL\" -Atc 'SHOW row_security'"); then
  if [[ "$(tr -d '[:space:]' <<<"$out")" == "on" ]]; then
    row "RDS: row_security" PASS "on"
  else
    row "RDS: row_security" FAIL "got: ${out}"
  fi
else
  row "RDS: row_security" FAIL "SSM command failed: ${out:0:200}"
fi
if timeout 6 bash -c "exec 3<>/dev/tcp/${DB_HOST}/5432" 2>/dev/null; then
  row "RDS: port 5432 from outside the VPC" FAIL "connected to ${DB_HOST}:5432 from here"
else
  row "RDS: port 5432 from outside the VPC" PASS "no connection within 6 s"
fi

# ---------------------------------------------------------------- Logs
password="acceptance-$(date +%s)-not-a-real-password"
hdrs=$(curl -s -o /dev/null -D - -X POST "https://${DOMAIN}/api/v1/auth/login" \
  -H "Origin: https://${DOMAIN}" -H "Content-Type: application/json" \
  -d "{\"email\":\"acceptance-test@example.com\",\"password\":\"${password}\"}" 2>/dev/null)
rid=$(grep -i '^x-request-id:' <<<"$hdrs" | awk '{print $2}' | tr -d '\r')
if [[ -z "$rid" ]]; then
  row "Logs: login request logged" FAIL "no X-Request-ID returned by https://${DOMAIN}/api/v1/auth/login"
else
  found=""
  for _ in $(seq 1 12); do
    sleep 10
    found=$(aws logs filter-log-events --log-group-name "/sustentra/${ENV}/api" --start-time $((($(date +%s) - 900) * 1000)) \
      --filter-pattern "\"${rid}\"" --query 'events[].message' --output text 2>/dev/null)
    [[ -n "$found" ]] && break
  done
  leaked=$(aws logs filter-log-events --log-group-name "/sustentra/${ENV}/api" --start-time $((($(date +%s) - 900) * 1000)) \
    --filter-pattern "\"${password}\"" --query 'length(events)' --output text 2>/dev/null)
  if [[ -z "$found" ]]; then
    row "Logs: login request logged" FAIL "request ${rid} not found in /sustentra/${ENV}/api after 2 min"
  elif [[ "${leaked:-0}" != "0" ]]; then
    row "Logs: login request logged" FAIL "request found, but the password appears in the logs (${leaked} events)"
  elif [[ "$found" != *"/api/v1/auth/login"* ]]; then
    row "Logs: login request logged" FAIL "request ${rid} found without its path"
  else
    row "Logs: login request logged" PASS "request_id ${rid} with path and status; password not in the logs"
  fi
fi

# ---------------------------------------------------------------- SES
if [[ -z "$EMAIL" ]]; then
  row "SES: test email SPF/DKIM/DMARC" SKIPPED "run with --email you@example.com"
else
  if out=$(on_host "aws sesv2 send-email --region ${AWS_REGION} --from-email-address no-reply@${DOMAIN} \
      --configuration-set-name ${P}-default --destination ToAddresses=${EMAIL} \
      --content '{\"Simple\":{\"Subject\":{\"Data\":\"Sustentra ${ENV} acceptance test\"},\"Body\":{\"Text\":{\"Data\":\"TEST-003\"}}}}' \
      --query MessageId --output text"); then
    row "SES: test email SPF/DKIM/DMARC" CONFIRM "sent to ${EMAIL} (MessageId ${out}); open it -> Show original: SPF, DKIM, DMARC = PASS"
  else
    row "SES: test email SPF/DKIM/DMARC" FAIL "send failed (sandbox? unverified recipient?): ${out:0:200}"
  fi
fi
if out=$(on_host "aws sesv2 send-email --region ${AWS_REGION} --from-email-address no-reply@${DOMAIN} \
    --configuration-set-name ${P}-default --destination ToAddresses=bounce@simulator.amazonses.com \
    --content '{\"Simple\":{\"Subject\":{\"Data\":\"Bounce test\"},\"Body\":{\"Text\":{\"Data\":\"bounce\"}}}}' \
    --query MessageId --output text"); then
  row "SES: simulated bounce -> SNS email" CONFIRM "sent (MessageId ${out}); an SNS bounce notification should reach the alert inbox"
else
  row "SES: simulated bounce -> SNS email" FAIL "send failed: ${out:0:200}"
fi

# ---------------------------------------------------------------- Alarms
if aws cloudwatch set-alarm-state --alarm-name "${P}-rds-cpu-high" --state-value ALARM \
     --state-reason "TEST-003 acceptance test" 2>/dev/null; then
  row "Alarms: alarm email" CONFIRM "${P}-rds-cpu-high set to ALARM; an email should arrive (it returns to OK on its next evaluation)"
else
  row "Alarms: alarm email" FAIL "set-alarm-state failed (permissions?)"
fi

if ((DISRUPTIVE == 0)); then
  row "Alarms: uptime alarm when the API stops" SKIPPED "run with --disruptive (stops the API for up to 6 min)"
else
  read -r -p "Stop the API on ${ENV} for up to 6 minutes? Type the environment name to confirm: " ok
  if [[ "$ok" != "$ENV" ]]; then
    row "Alarms: uptime alarm when the API stops" SKIPPED "not confirmed"
  else
    on_host "${COMPOSE} stop api" >/dev/null
    start=$(date +%s); state=""
    for _ in $(seq 1 24); do
      sleep 15
      state=$(aws cloudwatch describe-alarms --alarm-names "${P}-uptime-api-health" --query 'MetricAlarms[0].StateValue' --output text 2>/dev/null)
      [[ "$state" == "ALARM" ]] && break
    done
    on_host "${COMPOSE} start api" >/dev/null
    took=$(( $(date +%s) - start ))
    if [[ "$state" == "ALARM" ]]; then
      row "Alarms: uptime alarm when the API stops" PASS "ALARM after ${took}s (API restarted); confirm the email"
    else
      row "Alarms: uptime alarm when the API stops" FAIL "still ${state:-unknown} after ${took}s (API restarted)"
    fi
  fi
fi

# ---------------------------------------------------------------- Deploy (manual)
row "Deploy: failed /api/health rolls back" MANUAL "deploy an image whose /api/health fails (Actions -> deploy -> image_tag); the job must roll back to the previous tag"
if [[ "$ENV" == "prod" ]]; then
  row "Deploy: prod waits for approval" MANUAL "a push to main pauses the deploy job at the production environment until a reviewer approves (OPS-003)"
fi

{
  echo "### TEST-003 - ${ENV} ($(date -u +%Y-%m-%dT%H:%MZ))"
  echo
  echo "| Check | Result | Details |"
  echo "|---|---|---|"
  printf '%s\n' "${ROWS[@]}"
  echo
  echo "CONFIRM = triggered by the script, confirm in the inbox; MANUAL = steps listed, done by hand."
} > "$REPORT"
echo
echo "Report: ${REPORT}"
grep -q "| FAIL |" "$REPORT" && exit 1
exit 0

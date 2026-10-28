#!/bin/bash
# Runs ON THE APP HOST via SSM Run Command (see .github/workflows/deploy.yml).
#
#   deploy.sh <env> <image-tag>
#
# 0. check:    S1_PROCESSING in .env is valid, before anything is pulled or written
# 1. migrate:  alembic upgrade head in a one-off api container (db_migration_url)
# 2. release:  docker compose pull && up -d with the new tag. The release is caddy, web,
#              api and reader (the process that reads queued documents; same image as api)
# 3. verify:   poll GET https://<APP_DOMAIN>/api/health and wait for the reader's container
#              health check
# 4. rollback: on failure, redeploy the previous tag and exit non-zero
#
# The RDS snapshot is taken by the workflow (deploy role) before this runs.
set -euo pipefail

ENV_NAME="${1:?usage: deploy.sh <env> <image-tag>}"
NEW_TAG="${2:?usage: deploy.sh <env> <image-tag>}"

APP_DIR=/opt/sustentra
COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml" --env-file "$APP_DIR/.env")
HEALTH_ATTEMPTS=30
HEALTH_DELAY=5

cd "$APP_DIR"
# shellcheck disable=SC1091
source "$APP_DIR/.env"

log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }

# S1_PROCESSING (in .env, like S1_STORE) must be inline or queued, and queued needs Postgres
# stores. Checked before the deploy changes anything: the app refuses these settings at start,
# which would crash the new release and the rollback alike, so a bad value stops here while
# the running release stays up.
check_processing_mode() {
  case "${S1_PROCESSING:-inline}" in
    inline) ;;
    queued)
      if [ "${S1_STORE:-jsonl}" = jsonl ]; then
        log "S1_PROCESSING=queued needs S1_STORE=postgres or postgres+jsonl in $APP_DIR/.env" >&2; return 1
      fi ;;
    *) log "S1_PROCESSING must be inline or queued, not '${S1_PROCESSING}'" >&2; return 1 ;;
  esac
}

# A required parameter: prints its value, or fails when it cannot be read or is empty.
# Capture it with a plain assignment (`value=$(get_param name)`) so `set -e` stops the
# deploy: a substitution inside a heredoc or another command's arguments ignores the
# failure and would write an empty value (DATABASE_URL=). Never log the value.
get_param() {
  local value
  value=$(aws ssm get-parameter --region "$AWS_REGION" --with-decryption \
      --name "/${ENV_NAME}/$1" --query Parameter.Value --output text) || {
    log "reading /${ENV_NAME}/$1 from Parameter Store failed" >&2
    return 1
  }
  if [ -z "$value" ]; then
    log "/${ENV_NAME}/$1 is empty in Parameter Store" >&2
    return 1
  fi
  printf '%s' "$value"
}

# Like get_param, but a parameter that does not exist prints nothing instead of failing
# (prod has no AI parameters). Any other error (AccessDenied, throttling) still fails the
# deploy. The value goes to stdout only, for the caller to capture: never log it.
get_optional_param() {
  local value err_file
  err_file=$(mktemp)
  if value=$(aws ssm get-parameter --region "$AWS_REGION" --with-decryption \
      --name "/${ENV_NAME}/$1" --query Parameter.Value --output text 2>"$err_file"); then
    rm -f "$err_file"
    printf '%s' "$value"
    return 0
  fi
  if grep -q 'ParameterNotFound' "$err_file"; then
    rm -f "$err_file"
    return 0
  fi
  # stderr: stdout is the caller's captured value.
  log "reading /${ENV_NAME}/$1 from Parameter Store failed:" >&2
  cat "$err_file" >&2
  rm -f "$err_file"
  return 1
}

set_tags() {
  sed -i -e "s/^API_TAG=.*/API_TAG=$1/" -e "s/^WEB_TAG=.*/WEB_TAG=$1/" "$APP_DIR/.env"
}

write_app_env() {
  # Runtime secrets for the api container, refreshed from Parameter Store on every deploy.
  # Read before writing: a failed read stops the deploy with the previous app.env in place.
  local db_app_url otp_hmac_secret
  db_app_url=$(get_param db_app_url)
  otp_hmac_secret=$(get_param otp_hmac_secret)
  umask 077
  cat > "$APP_DIR/app.env" <<EOF
ENVIRONMENT=${ENV_NAME}
ALLOWED_ORIGINS=https://${APP_DOMAIN}
PUBLIC_BASE_URL=https://${APP_DOMAIN}
DATABASE_URL=${db_app_url}
OTP_HMAC_SECRET=${otp_hmac_secret}
SES_FROM_ADDRESS=no-reply@${APP_DOMAIN}
S1_STORE=${S1_STORE:-jsonl}
TEXTRACT_ENABLED=${TEXTRACT_ENABLED:-false}
S1_PROCESSING=${S1_PROCESSING:-inline}
EOF

  # AI suggestions (docs/backend_services.md). Each line is written only when its
  # parameter exists; otherwise the app default applies (AI off, no key). The key is a
  # SecureString: it goes from the variable straight into app.env (0600, umask above),
  # never to the log. Do not add `set -x` to this script.
  local pair value
  for pair in ANTHROPIC_API_KEY=anthropic_api_key AI_SUGGESTIONS_ENABLED=ai_suggestions_enabled \
      AI_PROVIDER=ai_provider AI_MODEL=ai_model AI_MONTHLY_CAP_USD=ai_monthly_cap_usd; do
    value=$(get_optional_param "${pair#*=}")
    if [ -n "$value" ]; then
      printf '%s=%s\n' "${pair%%=*}" "$value" >> "$APP_DIR/app.env"
    fi
  done
}

release() {
  local tag="$1"
  set_tags "$tag"
  "${COMPOSE[@]}" pull --quiet
  "${COMPOSE[@]}" up -d --remove-orphans
}

# True when the reader container's own health check (compose: reader_health) says healthy:
# its loop is running. That check's first pass comes about 15 s after the start, well inside
# the attempts in healthy().
reader_healthy() {
  local id status
  id=$("${COMPOSE[@]}" ps -q reader) || return 1
  [ -n "$id" ] || return 1
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id") || return 1
  [ "$status" = healthy ]
}

healthy() {
  local i
  for ((i = 1; i <= HEALTH_ATTEMPTS; i++)); do
    # --resolve: hit Caddy on this host while still validating the real certificate.
    # An attempt passes when the api answers and the reader is healthy.
    if curl -fsS --max-time 5 --resolve "${APP_DOMAIN}:443:127.0.0.1" \
        "https://${APP_DOMAIN}/api/health" >/dev/null && reader_healthy; then
      log "health check passed (attempt $i)"
      return 0
    fi
    sleep "$HEALTH_DELAY"
  done
  return 1
}

# After the functions, so log() exists; before anything is pulled, written or restarted.
check_processing_mode

PREV_TAG="${API_TAG:-latest}"
log "env=$ENV_NAME new=$NEW_TAG previous=$PREV_TAG"

log "ECR login"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null

write_app_env
grep -q "^LOG_GROUP_PREFIX=" "$APP_DIR/.env" || echo "LOG_GROUP_PREFIX=/sustentra/${ENV_NAME}" >> "$APP_DIR/.env"
# Writable data dir for the api container (uid 10001); hosts built before MVP-5 lack it.
install -d -m 0750 -o 10001 -g 10001 "$APP_DIR/data"

log "migrations"
# Plain assignments, so a failed read stops the deploy (see get_param).
DB_MIGRATION_URL=$(get_param db_migration_url)
DB_APP_URL=$(get_param db_app_url)
docker pull --quiet "${API_IMAGE}:${NEW_TAG}" >/dev/null
docker run --rm --read-only --tmpfs /tmp \
  --log-driver none \
  -e DATABASE_URL="$DB_MIGRATION_URL" \
  -e APP_DATABASE_URL="$DB_APP_URL" \
  -w /app/backend \
  "${API_IMAGE}:${NEW_TAG}" \
  sh -c 'if [ -f alembic.ini ]; then alembic upgrade head; else echo "no alembic.ini yet - skipping migrations"; fi'

log "release $NEW_TAG"
release "$NEW_TAG"

if healthy; then
  log "deploy OK: $NEW_TAG"
  docker image prune -af --filter "until=168h" >/dev/null || true
  exit 0
fi

log "HEALTH CHECK FAILED - rolling back to $PREV_TAG"
"${COMPOSE[@]}" ps -a || true
"${COMPOSE[@]}" logs --tail 50 caddy api web reader || true
# First deploy: there is no earlier release to go back to. Leave the new one running
# so it can be inspected (docker compose logs caddy) instead of failing on a missing image.
if [ "$PREV_TAG" = "$NEW_TAG" ] || ! docker pull --quiet "${API_IMAGE}:${PREV_TAG}" >/dev/null 2>&1; then
  log "no previous release image ($PREV_TAG) - nothing to roll back to; $NEW_TAG left running"
  exit 1
fi
release "$PREV_TAG"
# healthy() also needs the reader. A previous image from before the reader existed has none
# (the first rollback after it was added), so this can report unhealthy while the api is
# fine: see docs/s1_reader_runbook.md.
if healthy; then
  log "rollback to $PREV_TAG succeeded"
else
  log "ROLLBACK ALSO UNHEALTHY - manual intervention needed"
fi
exit 1

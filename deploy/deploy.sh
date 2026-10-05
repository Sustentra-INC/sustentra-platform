#!/bin/bash
# Runs ON THE APP HOST via SSM Run Command (see .github/workflows/deploy.yml).
#
#   deploy.sh <env> <image-tag>
#
# 1. migrate:  alembic upgrade head in a one-off api container (db_migration_url)
# 2. release:  docker compose pull && up -d with the new tag
# 3. verify:   poll GET https://<APP_DOMAIN>/api/health
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

get_param() {
  aws ssm get-parameter --region "$AWS_REGION" --with-decryption \
    --name "/${ENV_NAME}/$1" --query Parameter.Value --output text
}

set_tags() {
  sed -i -e "s/^API_TAG=.*/API_TAG=$1/" -e "s/^WEB_TAG=.*/WEB_TAG=$1/" "$APP_DIR/.env"
}

write_app_env() {
  # Runtime secrets for the api container, refreshed from Parameter Store on every deploy.
  umask 077
  cat > "$APP_DIR/app.env" <<EOF
ENVIRONMENT=${ENV_NAME}
ALLOWED_ORIGINS=https://${APP_DOMAIN}
PUBLIC_BASE_URL=https://${APP_DOMAIN}
DATABASE_URL=$(get_param db_app_url)
OTP_HMAC_SECRET=$(get_param otp_hmac_secret)
SES_FROM_ADDRESS=no-reply@${APP_DOMAIN}
EOF
}

release() {
  local tag="$1"
  set_tags "$tag"
  "${COMPOSE[@]}" pull --quiet
  "${COMPOSE[@]}" up -d --remove-orphans
}

healthy() {
  local i
  for ((i = 1; i <= HEALTH_ATTEMPTS; i++)); do
    # --resolve: hit Caddy on this host while still validating the real certificate.
    if curl -fsS --max-time 5 --resolve "${APP_DOMAIN}:443:127.0.0.1" \
        "https://${APP_DOMAIN}/api/health" >/dev/null; then
      log "health check passed (attempt $i)"
      return 0
    fi
    sleep "$HEALTH_DELAY"
  done
  return 1
}

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
docker pull --quiet "${API_IMAGE}:${NEW_TAG}" >/dev/null
docker run --rm --read-only --tmpfs /tmp \
  --log-driver none \
  -e DATABASE_URL="$(get_param db_migration_url)" \
  -e APP_DATABASE_URL="$(get_param db_app_url)" \
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
"${COMPOSE[@]}" logs --tail 50 caddy api web || true
# First deploy: there is no earlier release to go back to. Leave the new one running
# so it can be inspected (docker compose logs caddy) instead of failing on a missing image.
if [ "$PREV_TAG" = "$NEW_TAG" ] || ! docker pull --quiet "${API_IMAGE}:${PREV_TAG}" >/dev/null 2>&1; then
  log "no previous release image ($PREV_TAG) - nothing to roll back to; $NEW_TAG left running"
  exit 1
fi
release "$PREV_TAG"
if healthy; then
  log "rollback to $PREV_TAG succeeded"
else
  log "ROLLBACK ALSO UNHEALTHY - manual intervention needed"
fi
exit 1

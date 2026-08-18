#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/recovery_restore/compose.yml"
PROJECT="zebra-pg-recovery-restore-test"
PG_PORT="${ZEBRA_PG_RECOVERY_RESTORE_POSTGRES_PORT:-25463}"
REDIS_PORT="${ZEBRA_PG_RECOVERY_RESTORE_REDIS_PORT:-16382}"
MINIO_PORT="${ZEBRA_PG_RECOVERY_RESTORE_MINIO_PORT:-19002}"
export ZEBRA_PG_RECOVERY_RESTORE_POSTGRES_PORT="$PG_PORT"
export ZEBRA_PG_RECOVERY_RESTORE_REDIS_PORT="$REDIS_PORT"
export ZEBRA_PG_RECOVERY_RESTORE_MINIO_PORT="$MINIO_PORT"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")
TEMP_DIR=$(mktemp -d)
DUMP_FILE="$TEMP_DIR/zebra.dump"
EXPECTED_FILE="$TEMP_DIR/expected.json"
ARTIFACT_FILE="$TEMP_DIR/artifact.bin"

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

run_verifier() {
  local mode="$1"
  (
    cd "$ROOT_DIR"
    uv run --package agent-storage python tests/compose/recovery_restore/verify_restore.py \
      --mode "$mode" \
      --dsn "postgresql://zebra:zebra-test-password@127.0.0.1:${PG_PORT}/$2" \
      --redis-url "redis://127.0.0.1:${REDIS_PORT}/0" \
      --s3-endpoint "http://127.0.0.1:${MINIO_PORT}" \
      --s3-access-key zebra-recovery \
      --s3-secret-key zebra-recovery-test-secret \
      --expected "$EXPECTED_FILE" \
      --artifact-payload "$ARTIFACT_FILE"
  )
}

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres redis minio
"${COMPOSE[@]}" run --rm minio-init

run_verifier seed zebra

"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password postgres \
  pg_dump -U zebra -d zebra --format=custom --no-owner --no-privileges > "$DUMP_FILE"
test -s "$DUMP_FILE"
DUMP_SHA=$(sha256_file "$DUMP_FILE")
printf 'RECOVERY_RESTORE_ARCHIVE=PASS sha256=%s bytes=%s\n' \
  "$DUMP_SHA" "$(wc -c < "$DUMP_FILE" | tr -d '[:space:]')"

run_verifier clear zebra

"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password postgres \
  createdb -U zebra --template=template0 zebra_restore
"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password postgres \
  pg_restore --exit-on-error --no-owner --no-privileges -U zebra -d zebra_restore < "$DUMP_FILE"

run_verifier verify zebra_restore
echo "ZEBRA_PG_RECOVERY_RESTORE_TEST_RESULT=PASS"

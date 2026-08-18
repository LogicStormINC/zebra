#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/recovery_s3/compose.yml"
PROJECT="zebra-s3-recovery-test"
POSTGRES_PORT="${ZEBRA_S3_RECOVERY_POSTGRES_PORT:-25467}"
MINIO_PORT="${ZEBRA_S3_RECOVERY_MINIO_PORT:-19003}"
export ZEBRA_S3_RECOVERY_POSTGRES_PORT="$POSTGRES_PORT"
export ZEBRA_S3_RECOVERY_MINIO_PORT="$MINIO_PORT"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")
TEMP_DIR=$(mktemp -d)
EXPECTED_FILE="$TEMP_DIR/expected.json"
REPORT_FILE="$TEMP_DIR/s3-recovery-report.json"
EVIDENCE_DIR="${ZEBRA_S3_RECOVERY_EVIDENCE_DIR:-}"
DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${POSTGRES_PORT}/zebra"
ENDPOINT="http://127.0.0.1:${MINIO_PORT}"
ACCESS_KEY="zebra-recovery"
SECRET_KEY="zebra-recovery-test-secret"

run_verifier() {
  local mode="$1"
  shift
  (
    cd "$ROOT_DIR"
    uv run --package agent-storage python tests/compose/recovery_s3/verify_s3_recovery.py \
      --mode "$mode" \
      --dsn "$DSN" \
      --endpoint "$ENDPOINT" \
      --access-key "$ACCESS_KEY" \
      --secret-key "$SECRET_KEY" \
      --expected "$EXPECTED_FILE" \
      "$@"
  )
}

cleanup() {
  local status=$?
  set +e
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1
  if [[ -f "$REPORT_FILE" ]]; then
    local finalize_args=(--mode finalize --report "$REPORT_FILE")
    if [[ -n "$EVIDENCE_DIR" ]]; then
      finalize_args+=(--evidence-dir "$EVIDENCE_DIR")
    fi
    (
      cd "$ROOT_DIR"
      uv run --package agent-storage python tests/compose/recovery_s3/verify_s3_recovery.py \
        "${finalize_args[@]}"
    ) || status=1
  fi
  rm -rf "$TEMP_DIR"
  exit "$status"
}
trap cleanup EXIT

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres minio
"${COMPOSE[@]}" run --rm minio-init >/dev/null

run_verifier seed
run_verifier clear
run_verifier verify --report "$REPORT_FILE"
echo "ZEBRA_S3_RECOVERY_TEST_RESULT=PASS"

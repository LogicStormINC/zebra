#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/recovery_pitr/compose.yml"
PROJECT="zebra-pg-recovery-pitr-test"
PRIMARY_PORT="${ZEBRA_PG_RECOVERY_PITR_PRIMARY_PORT:-25465}"
RESTORE_PORT="${ZEBRA_PG_RECOVERY_PITR_RESTORE_PORT:-25466}"
TARGET_NAME="${ZEBRA_PG_PITR_TARGET_NAME:-zebra_pitr_target_v1}"
export ZEBRA_PG_RECOVERY_PITR_PRIMARY_PORT="$PRIMARY_PORT"
export ZEBRA_PG_RECOVERY_PITR_RESTORE_PORT="$RESTORE_PORT"
export ZEBRA_PG_PITR_TARGET_NAME="$TARGET_NAME"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")
TEMP_DIR=$(mktemp -d)
EXPECTED_FILE="$TEMP_DIR/expected.json"
REPORT_FILE="$TEMP_DIR/pitr-report.json"
EVIDENCE_DIR="${ZEBRA_PG_PITR_EVIDENCE_DIR:-}"
SOURCE_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${PRIMARY_PORT}/zebra"
RESTORE_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${RESTORE_PORT}/zebra"

now_ns() {
  python -c 'import time; print(time.time_ns())'
}

run_verifier() {
  local mode="$1"
  local dsn="$2"
  shift 2
  (
    cd "$ROOT_DIR"
    uv run --package agent-storage python tests/compose/recovery_pitr/verify_pitr.py \
      --mode "$mode" \
      --dsn "$dsn" \
      --expected "$EXPECTED_FILE" \
      "$@"
  )
}

wait_for_archive() {
  local archived_count
  for _ in $(seq 1 30); do
    archived_count=$("${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password primary \
      psql -U zebra -d zebra -Atqc "SELECT archived_count FROM pg_stat_archiver" \
      | tr -d '\r[:space:]')
    if [[ "$archived_count" =~ ^[0-9]+$ ]] && (( archived_count >= 1 )); then
      printf '%s\n' "$archived_count"
      return 0
    fi
    sleep 1
  done
  echo "WAL archive did not advance" >&2
  return 1
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
      uv run --package agent-storage python tests/compose/recovery_pitr/verify_pitr.py \
        "${finalize_args[@]}"
    ) || status=1
  fi
  rm -rf "$TEMP_DIR"
  exit "$status"
}
trap cleanup EXIT

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait primary

run_verifier seed "$SOURCE_DSN"

"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password primary sh -ec \
  'rm -rf /backup/base && mkdir -p /backup/base && pg_basebackup -h 127.0.0.1 -U zebra -D /backup/base -Fp -X none -P'
BASE_BACKUP_SHA256=$("${COMPOSE[@]}" exec -T primary sh -ec \
  'tar -C /backup/base -cf - . | sha256sum | cut -d " " -f 1' | tr -d '\r[:space:]')
if [[ ! "$BASE_BACKUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "physical base backup digest is invalid: $BASE_BACKUP_SHA256" >&2
  exit 1
fi

run_verifier target "$SOURCE_DSN" --target-name "$TARGET_NAME"
"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password primary \
  psql -U zebra -d zebra -Atqc "SELECT pg_switch_wal()" >/dev/null
ARCHIVED_WAL_COUNT=$(wait_for_archive)
"${COMPOSE[@]}" stop primary >/dev/null

RESTORE_STARTED_NS=$(now_ns)
"${COMPOSE[@]}" run --rm restore-init >/dev/null
"${COMPOSE[@]}" up --detach --wait restore
RESTORE_COMPLETED_NS=$(now_ns)
RTO_SECONDS=$(python - "$RESTORE_STARTED_NS" "$RESTORE_COMPLETED_NS" <<'PY'
import sys

started, completed = (int(value) for value in sys.argv[1:])
print(max(0.0, (completed - started) / 1_000_000_000))
PY
)

run_verifier verify "$RESTORE_DSN" \
  --report "$REPORT_FILE" \
  --base-backup-id "${PROJECT}:base-backup" \
  --base-backup-sha256 "$BASE_BACKUP_SHA256" \
  --archived-wal-count "$ARCHIVED_WAL_COUNT" \
  --rto-seconds "$RTO_SECONDS"
echo "ZEBRA_PG_RECOVERY_PITR_TEST_RESULT=PASS"

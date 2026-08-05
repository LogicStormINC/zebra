#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/recovery_drill/compose.yml"
PROJECT="zebra-pg-recovery-drill-test"
PORT="${ZEBRA_PG_RECOVERY_DRILL_POSTGRES_PORT:-25464}"
export ZEBRA_PG_RECOVERY_DRILL_POSTGRES_PORT="$PORT"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")
TEMP_DIR=$(mktemp -d)
REPORT_FILE="$TEMP_DIR/recovery-drill-report.json"

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres

(
  cd "$ROOT_DIR"
  uv run --package agent-storage python tests/compose/recovery_drill/verify_drill.py \
    --dsn "postgresql://zebra:zebra-test-password@127.0.0.1:${PORT}/zebra" \
    --report "$REPORT_FILE"
)

test -s "$REPORT_FILE"
cat "$REPORT_FILE"
echo "ZEBRA_PG_RECOVERY_DRILL_TEST_RESULT=PASS"

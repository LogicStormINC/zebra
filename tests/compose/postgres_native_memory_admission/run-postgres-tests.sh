#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/postgres_native_memory_admission/compose.yml"
PROJECT="zebra-pg-native-memory-admission-test"
PORT="${ZEBRA_PG_NATIVE_POSTGRES_PORT:-25443}"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres

set +e
(
  cd "$ROOT_DIR"
  ZEBRA_TEST_POSTGRES_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${PORT}/zebra" \
    uv run pytest -q tests/agent_storage/test_postgres_native_memory_admission.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS"
  echo "ZEBRA_PG_NATIVE_MEMORY_TEST_RESULT=PASS"
else
  echo "ZEBRA_PG_NATIVE_ADMISSION_VERDICT=FAIL"
  echo "ZEBRA_PG_NATIVE_MEMORY_TEST_RESULT=FAIL"
fi
exit "$status"

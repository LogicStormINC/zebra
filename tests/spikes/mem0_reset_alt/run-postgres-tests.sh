#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker/compose.mem0-reset-alt.test.yml"
PROJECT="zebra-mem0-reset-alt-test"
PORT="${ZEBRA_MEM0_RESET_ALT_POSTGRES_PORT:-25441}"
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
    uv run pytest -q tests/spikes/mem0_reset_alt/test_logical_reset.py
)
result_code=$?
set -e

if [[ "$result_code" -eq 0 ]]; then
  echo "ZEBRA_MEM0_RESET_ALT_TEST_RESULT=PASS"
  echo "ZEBRA_MEM0_RESET_ALT_VERDICT=B"
else
  echo "ZEBRA_MEM0_RESET_ALT_TEST_RESULT=FAIL"
fi
exit "$result_code"

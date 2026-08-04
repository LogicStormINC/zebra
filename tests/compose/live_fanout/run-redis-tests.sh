#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/live_fanout/compose.yml"
PROJECT="zebra-live-fanout-test"
PORT="${ZEBRA_LIVE_REDIS_PORT:-16381}"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait redis

set +e
(
  cd "$ROOT_DIR"
  ZEBRA_LIVE_REDIS_URL="redis://127.0.0.1:${PORT}/0" \
    uv run --package agent-integrations --with pytest pytest -q \
      tests/compose/live_fanout/test_redis_live_fanout.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_LIVE_FANOUT_REDIS_TEST_RESULT=PASS"
else
  echo "ZEBRA_LIVE_FANOUT_REDIS_TEST_RESULT=FAIL"
fi
exit "$status"

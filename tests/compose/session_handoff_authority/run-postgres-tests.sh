#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/session_handoff_authority/compose.yml"
PROJECT="zebra-session-handoff-authority-test"
PORT="${ZEBRA_HANDOFF_AUTH_POSTGRES_PORT:-25452}"
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
    uv run pytest -q \
      tests/agent_storage/test_postgres_session_handoffs.py \
      tests/agent_storage/test_postgres_session_handoff_authority.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=PASS"
else
  echo "ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=FAIL"
fi
exit "$status"

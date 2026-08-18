#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/control_plane/compose.yml"
PROJECT="zebra-control-plane-test"
PORT="${ZEBRA_CONTROL_PLANE_POSTGRES_PORT:-25448}"
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
      tests/agent_storage/test_postgres_control_plane_composition.py \
      tests/agent_storage/test_postgres_migrations.py \
      tests/agent_storage/test_postgres_model_tool_projections.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_CONTROL_PLANE_POSTGRES_TEST_RESULT=PASS"
else
  echo "ZEBRA_CONTROL_PLANE_POSTGRES_TEST_RESULT=FAIL"
fi
exit "$status"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/workspace_task/compose.yml"
PROJECT="zebra-workspace-task-test"
PORT="${ZEBRA_WORKSPACE_TASK_POSTGRES_PORT:-25456}"
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
  PYTHONPATH="$ROOT_DIR/packages/agent-context/src${PYTHONPATH:+:$PYTHONPATH}" \
  ZEBRA_TEST_POSTGRES_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${PORT}/zebra" \
    uv run --package zebra-agent-worker --with pytest pytest -q \
      tests/agent_storage/test_postgres_workspaces.py \
      tests/agent_storage/test_postgres_agent_tasks.py \
      tests/agent_storage/test_postgres_migrations.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_WORKSPACE_TASK_POSTGRES_TEST_RESULT=PASS"
else
  echo "ZEBRA_WORKSPACE_TASK_POSTGRES_TEST_RESULT=FAIL"
fi
exit "$status"

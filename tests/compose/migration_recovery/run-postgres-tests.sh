#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/migration_recovery/compose.yml"
PROJECT="zebra-pg-migration-test"
PORT="${ZEBRA_PG_MIGRATION_POSTGRES_PORT:-25457}"
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
    uv run --package agent-storage --with pytest pytest -q \
      tests/agent_storage/test_postgres_migration_recovery.py \
      tests/agent_storage/test_postgres_migration_handoff.py \
      tests/agent_storage/test_postgres_migration_idempotency.py \
      tests/agent_storage/test_postgres_migration_memory.py \
      tests/agent_storage/test_postgres_migration_delivery_audit.py \
      tests/agent_storage/test_postgres_migrations.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_PG_MIGRATION_TEST_RESULT=PASS"
else
  echo "ZEBRA_PG_MIGRATION_TEST_RESULT=FAIL"
fi
exit "$status"

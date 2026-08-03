#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/delivery_transaction/compose.yml"
PROJECT="zebra-delivery-transaction-test"
PORT="${ZEBRA_DELIVERY_TRANSACTION_POSTGRES_PORT:-25449}"
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
      tests/agent_storage/test_postgres_delivery_transaction.py \
      tests/agent_storage/test_postgres_migrations.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=PASS"
else
  echo "ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=FAIL"
fi
exit "$status"

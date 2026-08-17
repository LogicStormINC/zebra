#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/cloud_effect_composition/compose.yml"
PROJECT="zebra-cloud-effect-composition-test"
POSTGRES_PORT="${ZEBRA_CLOUD_EFFECT_POSTGRES_PORT:-25463}"
MINIO_PORT="${ZEBRA_CLOUD_EFFECT_MINIO_PORT:-29100}"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres minio
"${COMPOSE[@]}" run --rm minio-init

set +e
(
  cd "$ROOT_DIR"
  ZEBRA_TEST_POSTGRES_DSN="postgresql://zebra:zebra-cloud-effect-test-password@127.0.0.1:${POSTGRES_PORT}/zebra" \
  ZEBRA_TEST_S3_ENDPOINT="http://127.0.0.1:${MINIO_PORT}" \
  ZEBRA_TEST_S3_BUCKET="zebra-artifacts" \
  ZEBRA_TEST_S3_ACCESS_KEY="zebra-cloud-effect" \
  ZEBRA_TEST_S3_SECRET_KEY="zebra-cloud-effect-test-secret" \
    uv run --package agent-storage --with pytest pytest -q \
      tests/agent_storage/test_postgres_effect_payload_transactions.py \
      tests/agent_storage/test_postgres_governed_memories.py
)
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "ZEBRA_CLOUD_EFFECT_COMPOSITION_TEST_RESULT=PASS"
else
  echo "ZEBRA_CLOUD_EFFECT_COMPOSITION_TEST_RESULT=FAIL"
fi
exit "$status"

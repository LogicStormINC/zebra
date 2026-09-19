#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/cloud_faults/compose.yml"
PROJECT="zebra-cloud-faults"
PORT="${ZEBRA_CLOUD_FAULTS_POSTGRES_PORT:-25499}"
EVIDENCE_DIR="${ZEBRA_CLOUD_FAULTS_EVIDENCE_DIR:?set evidence directory}"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

mkdir -p "$EVIDENCE_DIR"
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres

cd "$ROOT_DIR"
ZEBRA_TEST_POSTGRES_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${PORT}/zebra" \
  uv run pytest -q --junitxml="$EVIDENCE_DIR/cloud-faults.xml" \
    tests/agent_storage/test_postgres_effect_faults.py \
    tests/agent_storage/test_postgres_lease_clock.py \
    tests/agent_storage/test_postgres_leases.py \
    tests/agent_storage/test_postgres_task_lease_lock.py

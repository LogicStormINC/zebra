#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
BASE_COMPOSE_FILE="$ROOT_DIR/tests/compose/application/dependencies.yml"
APP_COMPOSE_FILE="$ROOT_DIR/docker/compose.application.yml"
PROJECT="zebra-application-test"
API_PORT="${ZEBRA_APPLICATION_TEST_API_PORT:-18081}"
BASE_COMPOSE=(docker compose --project-name "$PROJECT-dependencies" --file "$BASE_COMPOSE_FILE")
APP_COMPOSE=(docker compose --project-name "$PROJECT" --file "$APP_COMPOSE_FILE")

export ZEBRA_APPLICATION_NETWORK=zebra-application-test-dependencies
export ZEBRA_PROFILE=cloud
export ZEBRA_DATABASE_URL=postgresql://zebra:zebra-application-test-password@postgres:5432/zebra
export ZEBRA_RUNTIME_CLASS=gvisor
export ZEBRA_RUNTIME_IMAGE=zebra/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA=true
export ZEBRA_DEPLOYMENT_NAMESPACE=application-compose-test
export ZEBRA_AUTHORITY_ISSUER=application-compose-test-authority
export ZEBRA_HISTORY_SCOPE_NAMESPACE=application-compose-test-history
export ZEBRA_CONTINUATION_SCOPE_NAMESPACE=application-compose-test-continuation
export ZEBRA_MEMORY_CURSOR_SIGNING_KEY=application-compose-test-memory-cursor-key-32-bytes
export ZEBRA_S3_ENDPOINT=http://minio:9000
export ZEBRA_S3_BUCKET=zebra-artifacts
export ZEBRA_S3_ACCESS_KEY=zebra-application
export ZEBRA_S3_SECRET_KEY=zebra-application-test-secret
export ZEBRA_S3_REGION=us-east-1
export ZEBRA_API_PORT="$API_PORT"
export ZEBRA_WORKER_ID=application-compose-test-worker

cleanup() {
  "${APP_COMPOSE[@]}" down --volumes --remove-orphans
  "${BASE_COMPOSE[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${BASE_COMPOSE[@]}" config --quiet
"${APP_COMPOSE[@]}" config --quiet
"${BASE_COMPOSE[@]}" up --detach --wait postgres minio
"${BASE_COMPOSE[@]}" run --rm minio-init
"${APP_COMPOSE[@]}" up --detach --build zebra-migrate
"${APP_COMPOSE[@]}" wait zebra-migrate
"${APP_COMPOSE[@]}" up --detach --build --wait zebra-api zebra-worker

curl --fail --silent --show-error "http://127.0.0.1:${API_PORT}/health" >/dev/null
"${APP_COMPOSE[@]}" exec -T zebra-api python -c \
  'from zebra_agent_api import create_app; from zebra_agent_config import load_settings; s = load_settings(); api = create_app(settings=s); assert s.profile == "cloud"; assert s.database_url.startswith("postgresql://"); assert type(api.stores).__name__ == "PostgresControlPlaneStores"'
"${APP_COMPOSE[@]}" ps --status running zebra-api zebra-worker
echo "ZEBRA_APPLICATION_COMPOSE_TEST_RESULT=PASS"

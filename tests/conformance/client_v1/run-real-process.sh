#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/zebra-client-conformance.XXXXXX")
PG_CONTAINER="zebra-client-conformance-pg-$$"
REDIS_CONTAINER="zebra-client-conformance-redis-$$"
API_PORT="${ZEBRA_CLIENT_CONFORMANCE_API_PORT:-18082}"
API_PID=""
NODE_BIN="${ZEBRA_NODE_BIN:-/Users/lukeding/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node}"
SEED_FILE="$RUN_DIR/seed.json"

stop_api() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID"
    wait "$API_PID" 2>/dev/null || true
  fi
  API_PID=""
}

cleanup() {
  stop_api
  docker rm -f "$REDIS_CONTAINER" "$PG_CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$RUN_DIR"
}
trap cleanup EXIT

docker run --detach --rm --name "$PG_CONTAINER" \
  -e POSTGRES_DB=zebra \
  -e POSTGRES_USER=zebra \
  -e POSTGRES_PASSWORD=zebra-client-conformance \
  -p 127.0.0.1::5432 \
  postgres:17.5-alpine3.21 >/dev/null
docker run --detach --rm --name "$REDIS_CONTAINER" \
  -p 127.0.0.1::6379 redis:7-alpine >/dev/null

for _ in $(seq 1 40); do
  if docker exec "$PG_CONTAINER" pg_isready -U zebra -d zebra >/dev/null 2>&1; then break; fi
  sleep 0.25
done
docker exec "$PG_CONTAINER" pg_isready -U zebra -d zebra >/dev/null
PG_PORT=$(docker port "$PG_CONTAINER" 5432/tcp | awk -F: '{print $NF}')
export ZEBRA_TEST_POSTGRES_DSN="postgresql://zebra:zebra-client-conformance@127.0.0.1:${PG_PORT}/zebra"
export ZEBRA_TEST_NAMESPACE="client-conformance-$$"
export ZEBRA_TEST_API_PORT="$API_PORT"
export ZEBRA_TEST_LOCAL_DB="$RUN_DIR/api.sqlite"
export ZEBRA_TEST_BROWSER_PROFILE="$RUN_DIR/browser-profile"

cd "$ROOT_DIR"
uv run python tests/conformance/client_v1/real_process_probe.py seed "$SEED_FILE"
uv run python tests/conformance/client_v1/real_process_probe.py \
  worker-recover "$SEED_FILE" --expected waiting

start_api() {
  local reject_receipts="$1"
  ZEBRA_TEST_REJECT_RECEIPTS="$reject_receipts" \
    uv run python tests/conformance/client_v1/http_process.py \
    >"$RUN_DIR/api-$reject_receipts.log" 2>&1 &
  API_PID=$!
  for _ in $(seq 1 60); do
    if curl --fail --silent "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then return; fi
    sleep 0.2
  done
  cat "$RUN_DIR/api-$reject_receipts.log"
  return 1
}

start_api 1
PATH="$(dirname "$NODE_BIN"):/opt/homebrew/bin:$PATH" \
  "$NODE_BIN" /opt/homebrew/bin/pnpm --dir sdks/typescript build >/dev/null
"$NODE_BIN" sdks/typescript/conformance/browser-reconnect/run.mjs first "$SEED_FILE"
stop_api

docker exec "$REDIS_CONTAINER" redis-cli SET zebra:client:volatile marker >/dev/null
docker exec "$REDIS_CONTAINER" redis-cli FLUSHALL >/dev/null
test "$(docker exec "$REDIS_CONTAINER" redis-cli DBSIZE | tr -d '\r')" = "0"

start_api 0
"$NODE_BIN" sdks/typescript/conformance/browser-reconnect/run.mjs replay "$SEED_FILE"

EFFECT_ID=$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["effect_id"])' "$SEED_FILE")
CREDENTIAL=$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["session_credential"])' "$SEED_FILE")
FENCE=$(uv run python -c 'import json,sys; print(json.load(open(sys.argv[1]))["fence_token"])' "$SEED_FILE")
STATUS=$(curl --fail --silent \
  -H "X-Zebra-Client-Session: $CREDENTIAL" \
  "http://127.0.0.1:${API_PORT}/v1/client-effects/${EFFECT_ID}" \
  | uv run python -c 'import json,sys; print(json.load(sys.stdin)["status"])')
test "$STATUS" = "succeeded"

RECEIPT_ID=$(uv run python -c 'import uuid; print(uuid.uuid4())')
REPLAYED=$(curl --fail --silent \
  -X POST \
  -H 'Content-Type: application/json' \
  -H "X-Zebra-Client-Session: $CREDENTIAL" \
  -H "X-Zebra-Client-Fence: $FENCE" \
  -H "Idempotency-Key: sdk-receipt:${EFFECT_ID}" \
  --data "{\"receipt_id\":\"${RECEIPT_ID}\",\"status\":\"succeeded\",\"result\":{\"opened\":true},\"received_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
  "http://127.0.0.1:${API_PORT}/v1/client-effects/${EFFECT_ID}/receipts" \
  | uv run python -c 'import json,sys; print(str(json.load(sys.stdin)["replayed"]).lower())')
test "$REPLAYED" = "true"
stop_api

uv run python tests/conformance/client_v1/real_process_probe.py \
  worker-recover "$SEED_FILE" --expected resumed

echo "ZEBRA_CLIENT_REAL_PROCESS_CONFORMANCE=PASS"

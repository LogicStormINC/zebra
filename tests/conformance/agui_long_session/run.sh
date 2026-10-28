#!/usr/bin/env bash
# Native Cloud + public SDK protocol checks; no business Host checkout required.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
ZPY=${ZEBRA_PYTHON:-$ROOT/.venv/bin/python}
NODE=${ZEBRA_NODE_BIN:-node}
OUT=${AGUI_EVIDENCE_DIR:-$ROOT/.artifacts/agui-long-session-gate-$(date +%Y%m%d-%H%M%S)}
[[ -x "$ZPY" && -f "$ROOT/sdks/typescript/node_modules/tsx/dist/cli.mjs" ]]
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
PG="zebra-agui-long-pg-$$"
REDIS="zebra-agui-long-redis-$$"
trap 'docker rm -fv "$REDIS" "$PG" >/dev/null 2>&1 || true' EXIT
# No pulls or arbitrary cleanup; image availability is a gate prerequisite.
docker image inspect postgres:17-alpine redis:8.2.1-alpine >/dev/null
docker run -d --name "$PG" --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_PASSWORD=isolated-agui -e POSTGRES_DB=zebra_agui_conformance \
  -p 127.0.0.1::5432 postgres:17-alpine -c shared_preload_libraries=pg_stat_statements >/dev/null
docker run -d --name "$REDIS" -p 127.0.0.1::6379 redis:8.2.1-alpine \
  redis-server --save '' --appendonly no >/dev/null
for _ in $(seq 1 80); do
  if docker exec "$PG" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then break; fi
  sleep 0.1
done
docker exec "$PG" pg_isready -h 127.0.0.1 -U postgres >/dev/null
docker exec "$PG" createdb -U postgres header_scratch
PP=$(docker port "$PG" 5432/tcp | awk -F: '{print $NF}')
RP=$(docker port "$REDIS" 6379/tcp | awk -F: '{print $NF}')
export ZEBRA_TEST_POSTGRES_DSN="postgresql://postgres:isolated-agui@127.0.0.1:$PP/zebra_agui_conformance"
export ZEBRA_HEADER_SCRATCH_DSN="postgresql://postgres:isolated-agui@127.0.0.1:$PP/header_scratch"
export ZEBRA_STREAM_TEST_POSTGRES_DSN="$ZEBRA_TEST_POSTGRES_DSN"
export ZEBRA_STREAM_TEST_REDIS_URL="redis://127.0.0.1:$RP/0"
export ZEBRA_LONG_WIRE_OUTPUT="$OUT/wire.json"
export ZEBRA_LONG_WIRE_FILE="$OUT/wire.json"
cd "$ROOT"
"$ZPY" -m pytest -q -o junit_family=legacy --junitxml="$OUT/cloud.xml" \
  tests/api/test_agui_long_session_wire.py tests/api/test_stream_v2_cursor.py \
  tests/api/test_stream_v2_http.py tests/api/test_stream_v2_native.py \
  tests/api/test_stream_v2_observation_failure_native.py tests/api/test_stream_v2_proof_batch_native.py \
  tests/api/test_task_approval.py tests/api/test_task_approval_expiry.py tests/agent_storage/test_task_approval.py \
  tests/agent_storage/test_worker_commit_confirmation.py tests/agent_storage/test_task_projection_work.py \
  tests/api/test_task_message_receipts.py tests/api/test_task_message_coordinates.py \
  | tee "$OUT/cloud.txt"
cd "$ROOT/sdks/typescript"
"$NODE" node_modules/tsx/dist/cli.mjs --test \
  packages/client-core/src/conversation_stream.test.ts \
  packages/client-core/tests/agui-native-wire.test.ts | tee "$OUT/sdk.txt"
# A conditional skip cannot certify the native release gate.
"$ZPY" - "$OUT/cloud.xml" <<'CHECK'
import sys
from xml.etree import ElementTree
root = ElementTree.parse(sys.argv[1]).getroot()
assert not root.findall(".//skipped"), "native gate skipped required checks"
CHECK
printf 'AGUI_LONG_SESSION_GATE=PASS evidence=%s\n' "$OUT"

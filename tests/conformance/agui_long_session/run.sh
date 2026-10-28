#!/usr/bin/env bash
# Existing real encoder, HTTP, SQL and browser checks; disposable resources only.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
TRN=${TRENCH_REPO:?set TRENCH_REPO to the paired Trench checkout}
ZPY=${ZEBRA_PYTHON:-$ROOT/.venv/bin/python}
TPY=${TRENCH_PYTHON:-$TRN/.venv/bin/python}
NODE=${ZEBRA_NODE_BIN:-node}
OUT=${AGUI_EVIDENCE_DIR:-$ROOT/.artifacts/agui-long-session-gate-$(date +%Y%m%d-%H%M%S)}
[[ -x "$ZPY" && -x "$TPY" && -d "$TRN/toc-frontend/node_modules" ]]
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
PG="zebra-agui-long-pg-$$"
REDIS="zebra-agui-long-redis-$$"
trap 'docker rm -fv "$REDIS" "$PG" >/dev/null 2>&1 || true' EXIT
# No pulls or arbitrary cleanup; image availability is a gate prerequisite.
docker image inspect postgres:17-alpine redis:8.2.1-alpine >/dev/null
docker run -d --name "$PG" --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_PASSWORD=isolated-agui -e POSTGRES_DB=trench_freshness_scratch_agui \
  -p 127.0.0.1::5432 postgres:17-alpine -c shared_preload_libraries=pg_stat_statements >/dev/null
docker run -d --name "$REDIS" -p 127.0.0.1::6379 redis:8.2.1-alpine \
  redis-server --save '' --appendonly no >/dev/null
for _ in $(seq 1 80); do
  if docker exec "$PG" pg_isready -U postgres >/dev/null 2>&1; then break; fi
  sleep 0.1
done
docker exec "$PG" pg_isready -U postgres >/dev/null
PP=$(docker port "$PG" 5432/tcp | awk -F: '{print $NF}')
RP=$(docker port "$REDIS" 6379/tcp | awk -F: '{print $NF}')
export ZEBRA_TEST_POSTGRES_DSN="postgresql://postgres:isolated-agui@127.0.0.1:$PP/trench_freshness_scratch_agui"
export ZEBRA_STREAM_TEST_POSTGRES_DSN="$ZEBRA_TEST_POSTGRES_DSN"
export ZEBRA_STREAM_TEST_REDIS_URL="redis://127.0.0.1:$RP/0"
export TRENCH_FRESHNESS_TEST_PG_DSN="postgresql+asyncpg://postgres:isolated-agui@127.0.0.1:$PP/trench_freshness_scratch_agui"
export TRENCH_CURSOR_TEST_DATABASE_URL="$TRENCH_FRESHNESS_TEST_PG_DSN"
export ZEBRA_LONG_WIRE_OUTPUT="$OUT/wire.json"
export ZEBRA_LONG_WIRE_FILE="$OUT/wire.json"
cd "$ROOT"
"$ZPY" -m pytest -q -o junit_family=legacy --junitxml="$OUT/cloud.xml" \
  tests/api/test_agui_long_session_wire.py tests/api/test_stream_v2_cursor.py \
  tests/api/test_stream_v2_http.py tests/api/test_stream_v2_native.py \
  tests/api/test_stream_v2_observation_failure_native.py tests/api/test_stream_v2_proof_batch_native.py \
  tests/api/test_task_approval.py tests/api/test_task_approval_expiry.py tests/agent_storage/test_task_approval.py \
  | tee "$OUT/cloud.txt"
cd "$TRN"
export PYTHONPATH=.:packages/models/src:packages/core/src:services/api/src:services/state_derive/src:services/rss_ingest/src:services/scraper/src:services/normalize/src:services/archive/src
"$TPY" -m pytest -q -o junit_family=legacy --junitxml="$OUT/host.xml" \
  tests/api/test_trench_ai_long_session*.py tests/api/test_trench_ai_approval.py \
  tests/api/test_trench_ai_approval_replay.py tests/api/test_trench_ai_cursor_migration.py \
  tests/api/test_trench_ai_turn_history.py tests/api/test_trench_ai_turn_observation.py \
  tests/api/test_trench_ai_turn_suggestions.py tests/api/test_trench_ai_snapshot_purity.py \
  | tee "$OUT/host.txt"
cd "$TRN/toc-frontend"
PATH="$(dirname "$(command -v "$NODE")"):$PATH" "$NODE" node_modules/vitest/vitest.mjs run \
  src/hooks/use-strategy-history.test.tsx src/hooks/use-strategy-turn.test.tsx \
  src/hooks/use-strategy-suggestions.test.tsx src/hooks/use-strategy-answer-body.test.tsx \
  src/components/product/strategy-history-window.test.tsx src/components/product/strategy-approval.test.tsx \
  src/components/product/strategy-actions.test.tsx src/lib/strategy-stream.test.ts \
  src/lib/strategy-conversation-turns.test.ts src/lib/strategy-snapshot-freshness.test.ts \
  src/lib/strategy-coverage-report.test.ts src/components/product/strategy-coverage-report.test.tsx \
  | tee "$OUT/frontend.txt"
# This existing browser fixture proves rendering/retention, not live provider work.
PATH="$(dirname "$(command -v "$NODE")"):$PATH" "$NODE" scripts/strategy-history-browser.mjs | tee "$OUT/browser.txt"
printf 'AGUI_LONG_SESSION_GATE=PASS evidence=%s\n' "$OUT"

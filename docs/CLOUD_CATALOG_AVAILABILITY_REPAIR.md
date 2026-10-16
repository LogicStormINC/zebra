# Cloud catalog admission availability repair

Task: `CATALOG-ADMISSION-AVAILABILITY-01`; owner Luke Ding, executor Codex.
Branch `codex/catalog-admission-availability-01`, base `4b151251`.
Scope: local `cloud-agent-trench` integration and API/Worker activation only.

## Incident and measured root cause

Conversation `conv_1792079945299_240d12`, Run
`3b49833c-1f3e-417c-987b-9dacb4f7e9f7`, failed with
`skill_catalog_unavailable` before a Cloud Session or model request was created.
The UI rendered “Zebra Cloud Agent is temporarily unavailable.”

The API returned 503 on `GET /v1/extensions/skill-installations?limit=100`.
Both startup key warmup and request authentication logged `TimeoutError`.
Actual API-container read-only probes measured:

| Stage | Measured duration |
| --- | --- |
| Fresh Host registry lookup | 31–212 ms |
| Cold pinned public-key retrieval, existing 5 s dependency budget | 1648–4091 ms |
| Child module imports in two separate staged samples | 832–1236 ms |
| TLS/open in those staged samples | 129–327 ms |
| Body read in those staged samples | 0.21–1.35 ms |

The catalog HTTP and authorizer caps were both 2 s; optional public-key warmup
also had only 2 s. They could reject a valid cold key fetch before the existing
5 s dependency timeout. Through the configured Trench workload authority and
Broker, three fresh signed catalog reads reproduced 503 at 2123.9, 2077.7 and
2062.2 ms. No model or command was dispatched by these probes.

Separately, bounded read-only legacy command candidate discovery raised
`TimeoutError`/PostgreSQL operational errors outside the consumer's guards.
These errors escaped the Worker loop and caused container restarts.

## Minimal implementation and guarantees

- One shared route budget selector gives extension **GET** authentication 5 s.
  Execution, writes and all other routes retain 2 s. A supplied shorter deadline
  still wins in both HTTP and the concrete authorizer.
- Optional public-key warmup receives the same cumulative 5 s bound. It still
  uses the existing bounded 32-keyset resolver and creates no background service.
- Per-connection TaskIO operations remain capped at 2 s. No pool, cache, SQL,
  schema, dependency, provider or model-policy change is introduced.
- Registry, target, namespace, scope, expiry and atomic nonce consumption remain
  fresh. Existing key TTL, rotation and child termination/reaping remain intact.
  Unknown grant-consumption outcomes are never retried.
- Only candidate/event **reads before execution** catch transient timeout or
  PostgreSQL operational failures. The consumer defers to the next normal poll,
  preserving the durable intent and scan cursor. Logs expose stage/class only.
  Execution and write timeouts continue to escape; they are never treated as
  retryable discovery failures.

This is an availability correction, not a claim that cold key retrieval became
faster. A cold catalog request may now take longer than 2 s before succeeding;
the already warm common path and previous performance changes are preserved.

## Validation

- Red first: 8 relevant failures, 3 existing-safe behaviors passed.
- Final focused API/Host/Worker suite: **44 passed**, including caller deadlines,
  fresh registry and consumption, denial/expiry, unknown consumption outcome,
  read failure/recovery with exactly one execution, and execution-timeout escape.
- Existing native stalled TLS child termination/reaping: **1 passed** isolated.
  In the first mixed run its 300 ms handshake-start timing assertion failed
  under load; no source or fixture was changed for it.
- First mixed suite: 69 passed, four failures. One new assertion needed a 100 ms
  scheduling tolerance; the native timing test passed isolated. Two unrelated
  Redis-composition fixture failures reproduce unchanged on `cloud-agent-trench`
  at the base; these were not repaired or counted as passing.
- Source Ruff and mypy (1283 source files), file-size gate (3088 files), existing
  deterministic eval (30 cases) pass. Full repository suite is not claimed.

Private reproducible evidence/scripts are under
`.artifacts/catalog-admission-20261016/`; credentials stay in memory and are not
included in safe reports. Live catalog/service verification is recorded below
after activation. An authenticated read is distinct from model/page acceptance.

## Activation results

Normal API and Worker were replaced with source-only images, using the original
six Compose files, entrypoints, commands and byte-equivalent environment. The
restart guard confirmed zero queued/running/processing Trench turns first.

| Identical real signed read | Before | After |
| --- | --- | --- |
| Skill installations | 503 / 2123.9 ms | 200 / 593.2 ms |
| MCP connections | 503 / 2077.7 ms | 200 / 233.3 ms |
| Skill installations, new grant | 503 / 2062.2 ms | 200 / 107.8 ms |

All three responses had the expected `items`/`next_cursor` structure and one
scoped item. Reusing each already consumed grant returned **403**, as required.
These numbers describe restored directory availability with startup-warmed keys;
they are not a controlled latency or model first-body performance comparison.

The running API image is `50810e64`; Worker is `017aae18`. Both are healthy with
zero restarts at verification. **63 running source identities** were checked,
including the previously accepted 62 and the Worker consumer. Existing search
image/config/proxy and v2/service configuration were retained. No trace launcher,
DB migration, old Run replay, new model request, push, npm publication or remote
deployment was performed. Original failed Run remains failed and unbound.

## Read-only follow-up, 2026-10-16

The initial three successful reads were a bounded acceptance result, not proof
that every later request would succeed. A later user Run
`9e3549d1-d5a2-4c32-9988-ad0b6e6237e8` failed `upstream_timeout` without a Cloud
binding or model request. Its wall-clock lifetime was 103.769 s:

| Local time, UTC+08 | Recorded fact |
| --- | --- |
| 00:25:21–00:27:21 | 17 Worker candidate reads deferred on `TimeoutError` |
| 00:25:29.916 | User Turn created |
| 00:26:57 | OrbStack VM manager logged `sleep` |
| 00:27:03.552 | First recorded successful Broker `/exchange` response |
| 00:27:09.351 | API Host authentication timeout; skill catalog returned 503 |
| 00:27:13.685 | Host Turn marked failed, no Cloud Task binding |
| 00:27:26 | macOS recorded entry into clamshell sleep |

Both PostgreSQL services logged canceled statements/client disconnects in that
window. These facts support a shared runtime/dependency disturbance; they do
**not** isolate CPU, disk, a database lock, sleep preparation, or Host queueing as
the cause. In particular, 93.636 s elapsed before the first recorded Broker
success, whose access log records completion rather than arrival. Historical
logs cannot split that span further. A checkpoint duration by itself is not
evidence of a stall, since PostgreSQL deliberately paces checkpoint writes.

Current follow-up checks, with no restart or production source change:

- API/Worker remain the accepted images, healthy with zero restarts after more
  than 11 hours. Worker has 18 total read deferrals, 17 in the above window;
  no traceback or additional authentication failure was recorded at this check.
- Three fresh signed catalog reads: 200 at 301.8/35.9/27.8 ms; all three consumed
  grants still reject reuse with 403. The first occurs after the original key
  TTL expired, so the result is not limited to the initial startup warmup.
- The actual consumer `_read_task_skills` flow, including active principal
  validation, Broker exchange, catalog parse and selection: 261.57/72.57/47.95 ms.
  Three corresponding normal-budget `/capabilities/runtime` calls also return
  200 at 20.62/28.83/30.21 ms. No Task or Run was created by the probes.
- Eight separate cold pinned-key fetches succeed. A diagnostic `-S` comparison
  gives overlapping timings (ordinary 182–232 ms; diagnostic 182–204 ms), so no
  further child-launch change is justified from this sample.
- Canonical model-request count since activation remains zero. Failed Runs are
  not replayed and runtime configuration/performance source overlays are intact.

The initially inspected Chrome DevTools session was a separate unauthenticated
browser. The existing user Chrome extension session was subsequently found
already authenticated as the expected account; no fresh login was needed.

The actual conversation page was opened there without sending a message. It
displays exactly the two durable failed turns above, an enabled composer, Flash
with high thinking, and the no-model-data indicator. The empty composer explains
why Send is disabled. There is no active turn or automatic retry. Screenshot:
`.artifacts/catalog-admission-20261016/page-readonly.jpg`. This completes
**read-only page inspection**, not new-message generation or first-body timing
acceptance. The isolated historical timeout is not described as fully explained
or fixed by an additional patch.

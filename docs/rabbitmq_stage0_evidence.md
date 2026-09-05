# RabbitMQ stage 0: contract and baseline evidence

Date: 2026-09-04. Task: RABBIT-FOUNDATION-01. Owner: Luke Ding; executor: Codex.
Scope: approved isolated Zebra/Trench worktrees, no production activation.

## 1. Versions and limits

- Zebra base: 230caeb1; Trench base: 84e9946 plus the preserved source snapshot.
- Trench tracked baseline diff SHA-256:
  `918bc8a6307051b39eec9439bea3b5c8c84ecc230851b32b1848d7a331e1fbc3`.
  This hash excludes untracked files; import paths were separately verified to
  resolve to the isolated Trench source, not the original editable checkout.
- Database: PostgreSQL 17.5, Docker on local macOS, temporary container
  `zebra-rabbitmq-baseline-20260904`; localhost ephemeral port, tmpfs data.
- Only synthetic fixtures in `rabbitmq_baseline`; no original database access,
  browser credentials, network tools or model calls. Loopback trust auth is for
  this disposable test instance only, not deployment configuration.
- Production Trench currently uses a different PostgreSQL major version. These
  measurements prove the local baseline and scanner behavior, not production SLOs.
- Contract code is not wired to admission or Worker paths. No Rabbit server was
  deployed by this stage. Benchmark assertions are not concurrent lease tests.

## 2. Pre-change regression

- Trench: test_trench_ai_turn_store.py + test_trench_ai_turn_dispatcher.py:
  **7 passed** (SQLite existing tests; not PG concurrency acceptance).
- Zebra: test_session_command_contract.py + test_command_consumer.py:
  **18 passed** (existing local contract/consumer regression).

## 3. Trench real store/dispatcher baseline

Runner: sibling Trench `scripts/benchmark_turn_pickup.py`.
Uses actual ORM tables, create_turn, claim_next, dispatcher loop, durable result
projection. Runtime is an immediate synthetic `done` event; no external Agent.
Each scenario creates 100 distinct conversations and admits one Turn per conversation,
with executor concurrency 8. Arrivals are serial submissions, not 100 parallel clients.
Paced intervals use a seeded jitter; interval 0 is back-to-back admission, not saturation.
All 100 Turns reached database `completed` in each run; no duplicate claim observed.

| Scenario | Store admission p95 / p99 | Commit-ack→claim p50 / p95 / p99 |
|---|---|---|
| 20ms nominal inter-arrival | 13.177 / 19.307ms | 132.750 / 242.036 / 248.284ms |
| Back-to-back admission | 15.367 / 16.615ms | 126.985 / 256.928 / 260.493ms |
| Paced repeat, same settings | 12.112 / 17.868ms | 140.671 / 247.089 / 253.512ms |

Each two-second idle window issued 8 claim SQL statements (~4/sec per dispatcher).
Full runs issued 119, 110 and 119 claim statements respectively, including empty polls.
Timings use monotonic perf_counter; commit observation is the client's commit
acknowledgement, not a PostgreSQL server timestamp. Store admission excludes HTTP,
authentication and reverse proxy work. Do not label it API p95 or model response time.
The 250ms loop sleep explains the observed pickup distribution; no Rabbit speedup
has been measured yet. Percentiles are nearest-rank with only 100 samples.

## 4. Zebra real PostgreSQL adapter/consumer baseline

Runner: `scripts/benchmark_command_scan.py`. Applies actual migrations only to the
dedicated DB, seeds canonical bootstrap Events and Session projections. One pending
RUN exists on the oldest Session. Actual PostgresEventStore/PostgresProjectionStore
and SessionCommandConsumer are used, with batch_size=1 and 30 repeated scans.
Only execute_session is a recording substitute: this measures discovery, not execution.

| Sessions | SQL / connections per scan | Scan p50 / p95 / p99 | Old pending command found |
|---:|---:|---|---|
| 10 | 9 / 9 | 51.058 / 66.297 / 67.544ms | 0 of 30 |
| 100 | 9 / 9 | 55.178 / 80.259 / 88.076ms | 0 of 30 |
| 1000 | 9 / 9 | 59.051 / 72.846 / 80.229ms | 0 of 30 |

Each scenario issued 270 explicit SQL statements and opened 270 connections.
Counts exclude driver-internal BEGIN/COMMIT wire commands. The constant query count
is not proof of scalable correctness: only the eight most recent Sessions are read.
Positive control expands the scan window and finds the *same* pending command in all
three scenarios without altering its identity or Event. This confirms a discovery gap.
Latency comparisons were not a statistically controlled capacity test; migrations,
cached pages and some overlapping local test work affect absolute timings.

## 5. Command producer inventory and identity boundaries

Search: `rg -n 'SESSION_COMMAND_ACCEPTED|submit_session_command' apps packages -g '*.py'`.

| Producer | Persistence seam that must participate in reliable wake-up |
|---|---|
| HTTP run/message/control + AG-UI commands | api_command_mixin / command_submission → stores.events.append |
| Approval-granted resume | api_approval_control_mixin → submit_session_command |
| Parent wake-up after child completion | worker/child_wakeup → append_event_in_transaction |
| Client-effect receipt resume | postgres/client_effects → _append_client_event → shared event transaction |
| Future or indirect Event append callers | shared PostgreSQL append transaction must enforce accepted-command hook |

The core decide_session_command function creates decisions, not durable writes.
The shared transaction hook must use the canonical accepted Event after idempotency
resolution, never the caller's fresh random command_id. API admission does not update
the projection's command-processed cursor today; do not assume generic projection
sequence advancement is a command receipt. Stage 3 must explicitly distinguish them.

Trench principal fields come from owned Turn/user/workspace rows, not queue input.
Host grant minting binds sub=viewer.user_id, workspace_ref, configured namespace_id,
principal/thread/run resources. Host namespace_id and deployment_namespace are
different concepts; they must not be silently equated. Zebra scope must be loaded from
the existing authenticated session/workspace authority binding at actual integration.
Mapping to exact opaque tenant IDs, lengths and private source credential bindings is
still an integration gate; the envelope parser alone grants no authorization.

## 6. Reproduction

Create a dedicated temporary PostgreSQL container using a locally available pinned
image, tmpfs data and `-p 127.0.0.1::5432`. Read its assigned port with docker port.
Never reuse the Trench/Zebra service database. Both runners reject non-localhost
hosts and database names other than rabbitmq_baseline; they intentionally leave
synthetic rows until the disposable database/container is removed.

Zebra, from its isolated worktree:

```sh
uv sync --all-packages --frozen
export RABBITMQ_BASELINE_DSN='postgresql://postgres@127.0.0.1:PORT/rabbitmq_baseline'
.venv/bin/python scripts/benchmark_command_scan.py --sizes 10,100,1000 --repeats 30
```

Trench, from its isolated worktree (use a Python environment with its locked dependencies):

```sh
export PYTHONPATH='packages/models/src:packages/core/src:services/api/src:services/state_derive/src'
export RABBITMQ_BASELINE_DSN='postgresql+asyncpg://postgres@127.0.0.1:PORT/rabbitmq_baseline'
python scripts/benchmark_turn_pickup.py --samples 100 --interval 0.02
python scripts/benchmark_turn_pickup.py --samples 100 --interval 0
```

Replace PORT with the assigned disposable port. Runs write only synthetic fixture
data; they do not send messages to the actual application or consume its subscriptions.

## 7. Local acceptance budget and remaining gates

For the same local fixtures, subsequent Rabbit integration must demonstrate:

- No missing or duplicate synthetic operations; old pending Sessions discoverable
  independently of recency. Every previously accepted operation retains recovery.
- At least 30% lower pickup p95 versus a same-run DB-poll control; target ≤150ms p95
  and ≤300ms p99, assessed with ≥1000 samples and controlled load per route.
- No continuously polling idle recent-session scans on the normal Rabbit path;
  bounded low-frequency recovery remains observable and proven complete.
- No >10% store admission p95 regression in repeated same-environment runs;
  >20% sustained regression, missing work, cross-scope behavior or duplicate effect
  blocks rollout and triggers verified fallback. These are gates, not achieved SLOs.

Schema and negative fixture gates are delivered with the contract code. Production
concurrency/arrival budgets, HTTP baseline, grant/identity composition, end-to-end
streaming, external effects and recovery TTL/scanner RTO still need real integration
evidence. This stage must not be reported as all v1.1 stages complete.

## 8. Contract delivery and review

- Both repositories now contain standalone identical Pydantic envelope models,
  bounded byte decoders, generated schema and shared positive/negative examples.
  Each envelope suite passes **84 tests**, including malformed identity/ref/version,
  UTF-8, size/depth, duplicate keys, strict integer and sensitive error cases.
- Zebra core suite: **637 passed**. Targeted Zebra contract+benchmark safety:
  **90 passed**; command contract/consumer baseline separately passed 18.
- Trench envelope+benchmark safety+existing Turn tests: **97 passed**.
- Zebra `make check` passes: Ruff, Mypy (790 source files), existing file-size gate,
  and release eval 10/10. New untracked Python files were separately measured
  against source/test limits because the existing size gate only enumerates tracked paths.
- Spec review independently passed envelope requirements. It found connection
  target override weaknesses in the benchmark DSN checks; those were fixed and
  regression-tested before the review passed. Libpq hostaddr is explicitly pinned,
  SQLAlchemy query overrides rejected, and explicit local ports required.
- Both benchmarks were rerun against the same disposable PostgreSQL after the
  guard fixes. No runtime application file was modified by these measurements.
- JSON Schema describes structure only; raw limits, duplicate keys and cross-field
  identity consistency also require the decoder. Neither proves database authority.
- Source is left uncommitted for review; no existing Trench baseline was staged.
- Final independent quality review passed without actionable findings and reran
  90 targeted tests in each repository. That review verifies code quality, not a
  second independent measurement of the reported PostgreSQL timings.

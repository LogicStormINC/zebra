# Cloud native web tool thread Task I/O reuse

Task CLOUD-TOOL-THREAD-IO-01, 2026-10-17. Source implemented in
`codex/cloud-tool-thread-io-01`; not integrated/activated in cloud-agent-trench.
The existing enabled egress and normal running services remain unchanged.

## Minimal change and boundaries

Cloud composition sets `WorkerToolGateway.reuse_task_io_connections` in all four
construction paths. The gateway opens the existing
`postgres_connection_scope(task_io=True)` only for a local native web read tool
with no existing scope owned by its executing thread. An already scoped sequential
call retains its original Run scope. Copied parent-thread scopes are rejected by
the existing thread guard; each concurrent tool obtains its own sockets. The
scope closes at call exit, including failure. No new pool, dependency or abstraction.

The wrapper is after management/client/Host route selection, so those routes and
local defaults retain their previous behavior. No infrastructure import enters
agent-core. Every existing fresh status/fence/cancellation callback, per-operation
deadline, transaction reset and idle-liveness check remains. No successful authority
result, query result, transaction or socket crosses tool threads. The native
50ms cancellation loop, DoH/target DNS/SSRF/TLS and egress routing are unchanged.
This is socket-lifecycle reuse, not an authorization cache or fewer checks.

## Safety validation

Resolved focused regression set:130 passed,2 skipped. The first run reported one
missing fixture import in this new test file; importing the existing fixture by
its normal alias fixed it. The five-test file then passed, including the real
PostgreSQL STOP case. No old fixture was changed. Coverage includes:

- separate thread owners, unchanged local/non-web/management routes, same-thread
  Run reuse, and socket closure on errors;
- original native Task I/O fresh transactions, independent commits, shortened
  budgets, older-libpq fallback, unknown-commit non-replay and reset failures;
- a Cloud gateway call reuses one physical PostgreSQL socket, sees an independent
  transaction change running→cancelled, raises, and closes that socket;
- native network cancellation, DNS/SSRF, egress, MCP lifecycle and Host/client routing.

Two existing real-PG lease-takeover tests fail their expected error-cause assertion
on both baseline and candidate: the old Worker stops with a Task-I/O timeout cause
rather than the expected LeaseLostError cause. This is retained as a baseline
limitation, not counted as a pass or repaired in this slice. Initial attempts with
the old scratch container's stale password failed before execution; a new uniquely
owned temporary scratch login allowed the isolated tests to run without changing
existing credentials. Its databases/schemas/grants/role and generated credential
file were removed afterwards. No Agent/Trench production data was mutated.

Ruff for the four changed Python files, Mypy for both changed Worker source files,
file-size gate and diff whitespace check pass. This is not a full repository suite.

## Actual native tool pairs: latency gate not met

The normal Cloud Worker executes a separate diagnostic process with candidate
modules under an owned temporary path. Its installed source/server process is not
changed. Same Linux Worker, prebuilt enabled egress, native children and two parallel
tools in both arms. A disables only the new thread scope; B enables it. Each arm
runs two searches followed by two official fetches, with new gateway/child state.
The agent/model is not invoked. Fixed four alternating A/B pairs, all32 tool results
executed (16search,16fetch); no favorable fifth pair or replacement.

Each callback freshly reads a controlled running row through the original
PostgresProjectionStore.get_session_status in isolated header_scratch schema.
This exercises fresh database status reads, not complete signed Host authorization;
production authority logic is unchanged and separately regression-tested. Check
counts vary with operation duration, since the original polling loop remains live.
No tool-selection restriction is added to the Agent.

| Pair | A total ms | B total ms | A physical opens | B physical opens |
|---|---:|---:|---:|---:|
| 1 |4797.1|2699.1|164|4|
| 2 |3446.1|3042.8|114|4|
| 3 |3191.8|3197.9|110|4|
| 4 |2769.7|3076.5|97|4|
| Median |3319.0|3059.6| | |

Physical opens fall to one per tool, but total median improves only7.8% and only
2of4 pairs improve. Pair3/4 regressions are retained. Much of connection work
occurs while upstream requests are already running. The predeclared latency gate
requires >=5% median improvement AND >=3of4 wins, zero failures and safety checks.
It therefore fails. This proves a connection-resource benefit, not stable wall-time
or page improvement. Total SQL calls were not captured; reset/liveness queries can
increase, so no SQL-reduction claim follows from fewer physical opens.

The measured parallel candidate precedes the final same-thread-existing-scope
preservation guard. In these concurrent tool threads the original thread guard
returns None in either version, so that final guard does not change the measured
parallel branch; its sequential behavior is covered by a separate regression.
The exact measured module snapshots remain with the cohort. A failed initial
module-overlay bootstrap occurred before tool execution and was retained; it is
not a performance sample. All actual completed samples above are retained.

## Delivery decision and next boundary

Do not invoke high/Flash/v2 page models or activate this candidate on the basis of
these samples. Code is committed for review on the isolated branch; primary normal
Worker image9953a04d/APIeb4f695b/Search245b675f,12source hashes,healthy0restart and
global-proxy digest remain verified unchanged. Temporary Worker overlay and owned
scratch resources were removed. No Trench source/config, global proxy, push or
remote deployment changes.

If resource pressure makes the connection reduction independently valuable, treat
that as a separate acceptance goal rather than claiming a first-body improvement.
For latency, the next diagnostic boundary is the remaining inter-stage canonical
append/progress work (about1.75s in retained page runs). Do not repeat the external
cohort until a concrete code change or new bottleneck evidence justifies it.

Evidence: private `.artifacts/cloud-tool-thread-io/` contains cohort.json, gate.json,
exact measured source snapshots, baseline/candidate test logs, normal-source
verification and cleanup proof. Reproduce only against an owned scratch database:

```sh
# Cloud Worker environment; operator supplies isolated DSN without printing secrets.
TOOL_THREAD_TRACE=/fresh/output/cohort.json python scripts/check_cloud_tool_thread_io.py
pytest tests/worker/test_tool_thread_connections.py -q
```

The runner refuses to overwrite an existing completed output and requires
header_scratch. It creates/removes only its own unique schema and requires the
already-ready explicitly configured Cloud egress. It does not create model tasks.

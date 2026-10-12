# Cloud stream full runtime acceptance plan

Readonly preparation2026-10-13. No edits to runtime, tests or services for the
source audit. Existing frozen baseline54cells is storage/recorder evidence,
with23terminal failures and no tools workload; it cannot establish full Worker,
signed HTTP, checkpoint consumer or SDK performance. New acceptance remains
Locked after CLIENT, proof performance and reliability integration.

## Actual chain and reuse

Create a new runtime harness; preserve frozen native_runner/native_baseline.
Reuse tests/stream_storage native_environment for owned database/namespace/prefix
and targeted cleanup only, not seed's manual ready/resolve/publish checkpoint.
Reuse telemetry for execute/executemany, commit/rollback and checkout/socket
counts. Use generated RS256 public keys and real PostgresHostAuthorityStore plus
PostgresHostGrantRequestAuthorizer; every HTTP request has an independent JTI.
Fixed VerifiedHostGrant injection is insufficient signed-entry evidence.

Compose actual build_worker_loop_service/SessionExecutionService, cloud
admission/claim/progress/recorder/finalize/release and actual
AgUiProjectionWorkService/AgUiCheckpointConsumer. Launch FastAPI on an owned
loopback port with real network SSE; ASGITransport is not slow-network evidence.
Use installed Node22/SDK/Playwright to consume and render. Existing UI fixture
react-browser-matrix is separate UI evidence, not backend integration.

Provide a free deterministic loopback OpenAI-compatible SSE provider through
existing model gateway decoding. Same UTF-8 answer, steps and duration with10
and100 provider frames; duration crosses100ms coalescing and report actual
callbacks/coalesced/published counts. Do not call transient Ports directly or
fabricate full durable response. Tool workload executes real files.read on an
isolated workspace then completes another model call, verifying proposal,
receipt/result and final answer. Include different draft/final body, pre-tool
text, private reasoning and coverage/private prohibition cases.

## Measurement boundary

Start at first real HTTP admission; stop after specified clients observe
ANSWER_COMMITTED, terminal and identical final body plus projection convergence.
Report bootstrap/admission, initial replay, execution/authorization renewal,
steady, final convergence, reconnect/receipt, background consumer and full total.
Registry/migrations/fixture setup are separate, but exclusions must also have an
inclusive total. Count SQL in every process; current monkeypatch is process-local.
Server pg_stat_statements track=all delta and observer exclusion are explicit.
WAL is cluster-global diagnostics, not isolated namespace SQL attribution.

Latency: accepted→provider request, provider request→first byte, actual callback
→SDK receive→React paint, accepted→first paint, last callback→committed paint.
The measured0.3-0.4s pre-callback activation must remain in full first-token time.
Do not subtract browser and Python clocks directly; calibrate with error bounds
or report separately mapped local clock milestones.

## Paired workload and capacity matrix

Run the SAME new harness against frozen v1 and accepted v2 source. Three routes
Session/Task/AG-UI each run1/10/100 independent Runs with identical issuance,
body/tool work, grants, slots, sockets and host infrastructure. Record offered,
accepted, started, active peak, completed, correctly committed, client-converged
and timed-out counts. Lower completion must fail, never become SQL savings.
Retain failed v1 cells. Calculate80% reduction only for comparable completed work.
100 accepted commands processed serially are not100 concurrent executing Runs.

Async XREAD avoids32default-executor resident waits, but current Redis pool128
is still finite. Run per-route100 cells first; mixed100×3routes may exceed pools.
Record Redis/PG actual sockets, exhaustion, executor active/queued/wait/threads,
Worker slots, RSS, owned Redis memory, API/SDK queue bounds. Browser100 requires
100 actually consuming/rendering runtimes; hidden99 or only Node reduction does
not prove100-Run rendering. Report actual sample count for p95 first token.

## Fault and compatibility cases

- Outer durable rollback; commit/publish gap; publish/ACK gap; checkpoint retry.
- Redis outage via owned proxy/instance, lost control hints, own-key trim/delete,
  expiration, duplicates/reorder/offset gaps. Never restart shared Redis.
- First-byte Worker exit/takeover; response-committed exit avoids model replay.
- STOP acceptance/closure, full fence takeover, Grant expiry/crossnamespace cursor.
- Slow consumer, same-instance partial resume, cold refresh, completed historical
  effect receipt never executes twice; next Turn/handoff and oldv1/newv2/local.
- Inject one-shot faults at actual transaction/publish/ACK boundaries. Exception
  injection and process kill/restart are distinct evidence; neither substitutes.

Proposed future exact owned paths at claim: tests/stream_storage runtime_environment,
runtime_workload, runtime_runner, runtime_report, runtime_faults and focused
report/native smoke tests; SDK scripts/stream-runtime-browser.mjs; focused runtime
acceptance evidence and governance. Real source defects require explicit repair
path transfer, not harness shortcuts. No business data, paid model, push/deploy.

## Duration and budget boundaries

Harness70-120k tokens/5-8 effective hours; faults/matrix/analysis50-90k/4-7h,
subject to uncovered defects. The2modes×3routes×3sizes×2framecounts×3repeats×60s
matrix has108minutes pure observation windows, excluding tools/setup/convergence.
Ten-minute idle2modes×3routes×3sizes needs180minutes per round,540minutes for3.
Start with complete one-round idle matrix and explicitly repeat marginal/failing
cells unless full3round stability is required. No silent shortened windows.
Runner saves per-cell JSON/JUnit and resumes after interruption. Component tests
and one-Run smoke do not replace these full-runtime acceptance boundaries.

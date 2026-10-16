# Progress source-read optimization and timeout-risk reduction

Task `PROGRESS-SOURCE-REUSE-01`; owner Luke Ding, executor Codex.
Branch `codex/progress-source-reuse-01`, base `f7395685`.
Earlier failure-boundary fixes are already active. This slice reduces duplicate
I/O in that path rather than changing authority or suppressing further errors.

## Measured redundant operation

After committing MODEL_RESPONSE_RECEIVED, progress catch-up reads a bounded
canonical page and advances its checkpoint. Commentary repair then point-reads
the same response before publishing its exact public chunks. Both reads consume
the same two-second publication/Task I/O budget. The second read can independently
fail even though the identical source was just verified by native advancement.

A native baseline with a real lease/fenced append executes61 explicit SQL calls,
10 TaskIO connections and three event-page reads (limits256/1/256) for one model
response plus its public commentary. No model or business tool is invoked.

## Minimal change

Only two Worker modules change:

- `WorkerProgressRecovery.catch_up` may return the pending source from a page
  successfully verified by native `advance_worker_progress` during this call.
- `repair_commentary` reuses that exact source, checking task, position, event
  type and deterministic chunk/output identities as before. Otherwise it retains
  the original bounded point-read fallback.

No value survives the current invocation. A cold recovery with no fresh page,
CAS loss, or a pending source absent from the successful page uses the fallback.
CAS loss explicitly clears any earlier candidate before reading the winning
checkpoint. Invalid source identity remains an error. Each publication still
checks fresh ownership and uses the fenced recorder; STOP, cancellation and
privacy decisions are unchanged. All callers of catch_up were inspected; callers
outside commentary repair ignore the additional optional result.

No new Port, cache, dependency, schema, retry, queue, pool or longer deadline.
This reuses work already done by existing storage verification.

## Native paired result

One disposable PostgreSQL server; four A and four B cases in ABBA/ABBA order.
A uses the original two functions from f7395685; B uses the candidate. Each case
gets an independent namespace/epoch and equivalent fresh source/lease state.
Only the response/commentary operation is measured, excluding setup/migration.
Cursor instrumentation counts explicit SQL without recording text/parameters.

| Median per operation | Original A | Candidate B |
| --- | ---: | ---: |
| Explicit SQL calls | 61 | 57 |
| TaskIO connection calls | 10 | 9 |
| Event-page reads | 3 | 2 |
| Elapsed native time | 264.40 ms | 233.47 ms |

All eight ordinary cases complete with exactly one public commentary and no
pending gap. Four fewer SQL calls are6.6% of this operation; one fewer connection
call is10%. These are not whole-Run/startup SQL percentages, text-frame savings,
page latency or an SLA. Native wall time is a small load-sensitive sample.

A separate fault control delays only the redundant limit1 read using native
pg_sleep(3). Original A stops at1819.04ms with a confirmed-source checkpoint
timeout and no commentary output. Candidate B does not issue that duplicate
read and completes at205.99ms with one output. The original2s budget is retained;
this proves avoidance of that specific failure opportunity, not immunity to
slow required reads or a sustained database outage.

## Regression and rollout

The existing default-gate script now checks hot source reuse, cold fallback,
foreign-task rejection and fresh ownership calls, in addition to its six prior
risk boundaries. No extra framework or fixture is introduced.

- Existing functional commentary/progress/public-output/composition:84passed.
- Existing native unknown-commit/lease/publication:4passed.
- Existing deadline/shutdown:7passed,2skipped,3deselected.
- Clean tracked-source `make check` passes, including whole-source Ruff,
  mypy1283, file-size3094, eval30 and both standalone fault checks.
- No historical fixture/account repair or full test-suite claim.

Build a source-only Worker overlay from the previous accepted normal image;
keep API/search/config unchanged. Require zero active Host intents for activation,
then verify retained source/config fingerprints and current source bytes. Only
local cloud-agent-trench integration is authorized. No model/page acceptance,
old Run replay, business-data write, schema migration, push or remote deployment.

Final normal Worker `bdd9972b` is healthy with zero restarts. Verified78 retained
source identities and original six Compose/environment/commands/search checks;
all overlay digests match current source bytes. API907fcc00 retains its original
image and exact start timestamp, confirming only Worker was replaced.

Private safe counts, native pair/fault logs, regressions and rollout receipts are
under `.artifacts/progress-source-20261016/`.

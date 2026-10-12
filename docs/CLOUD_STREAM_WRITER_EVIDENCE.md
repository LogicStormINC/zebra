# CLOUD-STREAM-WRITER-01 component evidence — 2026-10-12

Base: local cloud-agent-trench `3a3e5902`; isolated `codex/cloud-stream-writer-01`.
Implementation is a bounded adapter and optional Worker callback slice.
Production composition remains dormant. No push, deployment or full Writer GO.

## Implemented boundary

- `RedisTransientOutput` activates only through an injected trusted resolver.
  The Worker resolver recognizes its exact process-local issued handle and checks
  fresh durable admission, source-qualified ordinary privacy/current Run, native
  full lease epoch/token/owner and fresh Grant expiry. Windows are at most30s,
  clipped to actual lease/Grant expiration; no PG lookup occurs per frame.
- Gate source proof uses a bounded suffix from the captured committed model
  request: at most256 Events/1MiB and a2s cumulative PG deadline. Exact call,
  Attempt, Segment and main-call purpose must agree. Completed or reused calls
  cannot be reconstructed for activation, including after owned Redis keys vanish.
  A later Attempt or terminal Session also invalidates an unfinished old call
  under the same Run/full fence.
- `HarnessModelStep` invokes the public-call hook after its durable request sink
  returns. Provider public text alone reaches this hook/coalescer; private
  reasoning/tool arguments and `PublicExpression.complete` do not use it.
  Payload category/mode booleans do not admit a callback. Coalescer reset pins
  the current callback identity; stale callbacks cannot enter the next model call.
  The sink also drops known retired v2 calls, retaining at most256 identities.
- Worker composition wraps `WorkerProgressRecovery.persist_with` before
  `ProgressiveEventSink`. Source-confirmed ordinary v2 callback deltas bypass
  that durable sink; its in-memory progress observation still runs. Full request,
  response, public commentary and `ANSWER_COMMITTED` paths keep existing gates.
  Explicit legacy/absent admission and known coverage keep the original sink.
  Admission lookup errors, unknown privacy and source header failures suppress
  uncertain drafts; they never negotiate v1 fallback. Trusted mode selection is
  separate from source eligibility and remains pinned for this Run sink.
- Transport faults after ordinary v2 selection close the provisional generation
  and suppress further draft frames. They never persist partial deltas as a v1
  fallback or prevent the full business response from being recorded.
- Canonical events never wait for the transient lock. Provisional operations
  use75% of the existing publication deadline, reserving the remainder for facts
  and cleanup; cumulative native PG budgets never reset. Native Redis pool
  connections clip socket connect/send/read timeouts and disable automatic
  retries. Deadline failure retains failed references for a later bounded close
  and preserves the full-response path. DNS/TLS topology and service-scale
  deadline acceptance remain outside the native loopback/socket probes.
- Lua atomically checks full fence, current generation, Redis time, contiguous
  coalesced offset, exact content dedupe/mismatch, row/encoded-byte quotas, append
  and fixed expiry. Decimal fence comparison remains exact above2^53; a freshly
  resolved new epoch fences its predecessor. Retired generations cannot reopen.
  Activation snapshots a random lane revision before the fresh resolver and
  atomically compares it afterwards, without retries. Another activation or
  closure, expiry or Redis state loss rejects the delayed activation. An absent
  lane gets a revision-only reservation (no authority, fixed at most1h TTL),
  preventing absent-state ABA; reads/publishes never change that revision.
- Each encoded JSON frame, including every identity and escaping, fits16KiB.
  Unicode and whitespace are preserved. Resume returns at most100frames/256KiB;
  scope/cursor/generation gaps or loss require resync. Reads require trusted
  scope authority, recheck the deadline after hydration and never renew TTL.

## Validation

Configured disposable PG17.5/Redis8.2 scratch dependencies and header scratch:
**179passed, no skips,17.91s** across transient/core model/public-output/expression,
Worker progress/entry/deadline and cloud composition regression selection.
The existing publication fixture permits the configured loopback DSN only when
it exactly equals the private owned stream-test DSN, otherwise retaining its
legacy port32768 constraint. Both native statement/commit deadline cases ran.

Independent spec review found P1: an initial v2 eligibility lookup error could
silently persist subsequent deltas as v1. The mode/eligibility split, Run mode
pin, unknown/timeout suppression and actual callback/full-response/native PG
regressions repair that path. Publication timer facts complete while the visual
lock is held; separate close and socket blackhole probes respect the short
publication budget and keep the full response.

Independent quality review then found P1: a resolver validated the old fence,
paused, and activated after another adapter changed epoch/current call. The
revision CAS repair rejects delayed activation in native coordinated cases for
new epoch, higher token, same-fence new call, closure, loss and initially absent
lane; the winning generation still publishes. These race tests use native Redis
and a deterministic authoritative-fence fixture, not signed Host negotiation.
Renewed independent SPEC GO:42checks/no skips6.75s; QUALITY GO:54checks/no
skips11.26s, including independent reproduction of the former epoch/same-fence
race. Parent native Redis rerun16pass1.37s. The bounded component is accepted
for local integration; full activation, paired runtime and aggregate GC stay open.

Native actual `HarnessModelStep` → streaming provider public callback → Worker
progress wrapper → Redis test measures **0 client SQL statements for10frames and
0 for100frames** after activation, including configuration/checkout SQL. Full
model request/response persist, transient deltas do not, progress recovery retains
model-spoke state. Fresh native lease release/fence mismatch and Grant expiry,
completed-call reconstruction after Redis loss, dedupe/mismatch/offset gaps,
quotas, expiry/no-renew, exact high fences/new epochs, wrong scopes/gaps and an
uncertain append reply are exercised. Native admission/Grant loaders read a
synthetic scratch table; this does not prove signed Host negotiation/verification.

Re-run with the private native/header environment already exported, including
`ZEBRA_PUBLICATION_SCRATCH_DSN` set to the exact owned stream-test DSN:

```sh
uv run pytest -q --tb=short \
  tests/agent_core/test_stream_deltas.py tests/agent_core/test_transient_output_contract.py \
  tests/agent_core/test_harness_model_step.py tests/agent_core/test_public_output.py \
  tests/agent_core/test_public_expression.py \
  tests/agent_integrations/test_redis_transient_output.py \
  tests/worker/test_transient_output_runtime.py tests/worker/test_transient_output_native.py \
  tests/worker/test_worker_progress_recovery.py tests/worker/test_execution_progress_entry.py \
  tests/worker/test_public_output_deadline.py tests/worker/test_cloud_composition.py
make check
```

`make check`: file-size GO2991files; Ruff GO; mypy GO1254files; eval30/30.
`git diff --check` GO. No full-suite or paired-runtime performance claim.

## Remaining activation and acceptance

CLIENT or a separately claimed admission prerequisite must supply immutable
server-negotiated Run metadata, trusted Turn identity/Grant/admission loaders,
actual Worker factory wiring and authenticated v2 cursor/HTTP/SDK handling.
`compose_cloud_worker` leaves its optional factory `None`; Worker service has an
injection seam, but production loop wiring/config is not enabled by this slice.
Resume readers must bind their trusted request Grant/scope deadline; the supplied
read-authority callback is not permission to add PG work for every text frame.

Encoded payload cap is8MiB/8192rows per generation,256generations per lane,
4096simultaneous local handles per adapter, fixed retention no greater than1h.
Failed cleanup can retain a bounded local handle until a later close; this slice
claims bounded bookkeeping, not aggregate/global GC acceptance.
Redis object overhead and aggregate Run/deployment budgets, GC/restart/socket
load, STOP integration and wider reliability proofs remain successor work.
Source metadata may scan history at activation/renew; the2s budget fails closed.
A source-call suffix exceeding256 Events/1MiB also fails closed.
Fresh authority is checked at activation/renew rather than each delta; revocation
is bounded by the short authority deadline. No100-subscriber/paired reader+writer,
80–95% total-SQL,0.2SQL/subscriber/s, real Host/browser or deployment GO is inferred.

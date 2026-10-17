# Cloud event/progress boundary: fresh bound-Run metadata

CLOUD-PROGRESS-BOUNDARY-IO-01, 2026-10-17. Branch
`codex/cloud-progress-boundary-io-01` starts at49559417, the accepted egress source.
It excludes the preceding unaccepted tool-thread connection-reuse implementation.
Source is prepared for review, not activated in the normal Worker.

## What the remaining1.75s includes

Retained real high/Flash/transient_v2 B1/B2 page traces show four gaps between
model/tool phases,1603/1900ms (mean1751ms). Canonical append spans cover562/629ms,
progress spans560/637ms, preparation132/280ms and public-call setup95/103ms.
These inclusive spans overlap; do not sum them or call the entire1.75s database
execution. Rendering's separate500/623ms tail also includes generating the measured
16-character final-answer prefix, not a demonstrated fixed500ms delay.

Source audit rejected unsafe deletions:

- Model/tool index adapters already filter event types; both indexer calls do not
  imply two projection writes for every event.
- The progress adapter rereads a submitted page inside its write transaction to
  validate canonical content/membership/byte bounds. That read cannot be dropped
  simply because the caller already supplied the page.
- Progress CAS/frontier writes and pre/post canonical-append qualification remain.
  An unknown commit must never be replayed as a guessed failed append.
- Main-thread Task-I/O connection reuse already exists; it is not rebuilt here.

A synthetic no-model native-PG progress flow (two model-request/response facts,
with ordinary commentary, no Provider call) measured216ms,155 driver SQL calls and
only two physical opens (about16ms). Twelve latest-Run and ten explicit-Run metadata
queries consumed72.9ms,47.0% of observed SQL wall time. EXPLAIN trials put planning
around1.5–1.8ms and execution0.3ms for these tiny-source queries. This identifies
repeated Run discovery/planning, not a missing connection pool, as fixed overhead.
It is a diagnostic subset, not a recreation of all1751ms of a fenced live Worker.

## Minimal change

Initial `recover_worker_progress` still discovers and qualifies the latest Run.
A `WorkerProgressRecovery` already owns its immutable scope/run ID. Each subsequent
`catch_up` now calls the existing `read_run_header(task_id, scope.run_id)` instead
of rediscovering a latest Run ID and then qualifying its metadata. The existing
explicit-Run query also finds a subsequent executable boundary; `run.stop` now
rejects that superseded Run before advancing, alongside the original anchor check.

The stored ID is only a query parameter. Header, highwater, source readiness,
membership, privacy and successor boundary are read fresh on every side of a
canonical append. No authority/header/result cache, new Port, schema, migration,
dependency, batching or transaction-boundary change. All canonical/projection writes,
DNS/SSRF/cancel paths, original deadlines and model/tool decisions are unchanged.
The change removes repeated identity-discovery work inside a query; it does not
remove one whole SQL statement per catch-up or prove fewer SQL calls.

## Regression evidence

- Focused Worker progress/entry/composition/recorder/index-routing group:98passed.
- Native PG progress plus Worker recovery group:20passed, including overlapping
  local cases;11special scalar-header tests skipped because their separate
  `ZEBRA_HEADER_SCRATCH_DSN` was not configured. Do not present this as full-suite proof.
- The updated freshness regression observes the explicit Run reader on both sides
  of canonical append and fails if a bound recovery rediscovers latest identity.
  Supersession before catch-up and during append both reject old-Run advancement.
- Existing canonical-conflict, stale-frontier, lease-loss, commentary repair,
  unknown-commit and exact-once repair checks remain green.
- Mypy for the changed Worker source, Ruff for changed Python files, size and
  whitespace gates pass. Storage/SQL implementations and old fixtures are unchanged.

## Actual native-tool pair: acceptance gate closed

A separate process in the existing normal Linux Worker loads candidate recovery
source from an owned temporary directory. Baseline and candidate catch_up methods
bind to otherwise identical recovery objects. Both use the accepted prebuilt egress
and original tool-thread behavior. Each arm executes two real searches, two official
fetches and the same synthetic canonical model-response/tool-result facts through
ProgressiveEventSink/WorkerProgressRecovery. No model or new Agent task is invoked.

The fixture owns its isolated migrated PG schema and status source. Canonical
append uses the native Event Store, not the complete signed Host/fenced Worker
recorder; lease/signature checks are not benchmarked by this fixture. Its purpose
is to measure the changed progress boundary with real tool traffic. Source behavior
is separately regression-tested. Normal Agent/Trench production data is untouched.

Four alternating A/B pairs were declared. Recorded results:

| Arm | Progress boundary ms | Tool+boundary total ms | Observed SQL | Physical opens |
|---|---:|---:|---:|---:|
| A1 baseline |578.6|4149.8|534|119|
| B1 candidate |515.9|5082.6|549|134|
| B2 candidate |511.4|3676.8|462|112|
| A2 baseline |incomplete|search failed after5626.1ms|incomplete|incomplete|

Both A2 searches failed; the fixed cohort stopped. The same-time SearXNG logs show
two Yahoo engine timeouts. No progress callback exception appears. This supports an
upstream search failure, but per-tool failure metadata was not retained, so do not
claim a finer error classification. No search-engine/timeout/retry repair was added.

The only complete pair shows about62.7ms lower progress time (10.8%), while overall
wall time increases22.5%. One pair is not stable performance evidence. SQL counts
include reset/liveness statements and duration-dependent fresh polling; differing
website waits explain why connection/SQL totals cannot isolate this query change.
No SQL-count reduction, whole-page gain or1.75s removal is accepted.

Gate required zero failures, >=5% median boundary improvement, >=3of4 wins, >=100ms
median boundary saving and no median whole-replay regression. It is not met.
No high/Flash/v2 page models are called and normal Worker is not switched.
The adverse samples are retained, with no favorable replacement cohort.

An initial runner trial reused an epoch namespace and failed before the first B
sample. That trial's A timing was not persisted and is unavailable; retain its log
and reject the entire trial. The runner now uses unique namespaces and checkpoints
each completed arm; all three completed arms plus the failing baseline search above
are retained. This is a diagnostic runner fix, not a production/fixture repair.

## State and handoff

Normal Worker9953a04d/APIeb4f695b/Search245b675f,12normal source hashes,health with
zero restarts and global-proxy digest remain unchanged. No Trench/model/thinking/v2
configuration edits, service restart, source integration, push or remote deployment.
The previous unaccepted tool-thread candidate is also not activated.

Source and evidence stay on the isolated branch. Investigate the known search
availability separately before spending further page-model calls; do not rerun the
performance cohort to select favorable upstream timings. This slice offers a small
fixed-query simplification, not an established end-to-end latency improvement.

Private evidence is in `.artifacts/cloud-progress-boundary-io/`: initial profile,
query-planning trials, complete-arm partial data, failed-arm gate record, matching
search-timeout logs, exact measured sources, regression logs and normal-source
verification. The owned scratch login/schemas/databases/generated credential and
Worker overlay are cleaned after probes.

Reproduction needs an already ready explicit Cloud egress, owned header_scratch
DSN, a saved baseline progress_recovery.py and a fresh output path:

```sh
PROGRESS_BASELINE_SOURCE=/absolute/path/baseline_progress_recovery.py \
PROGRESS_BOUNDARY_TRACE=/fresh/output/cohort.json \
python scripts/check_cloud_progress_boundary.py
```

The runner refuses to overwrite completed output and writes `.partial.json` after
each completed arm. It imports no test fixtures and invokes no model Provider.

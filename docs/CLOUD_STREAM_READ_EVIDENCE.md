# Cloud stream bounded-read component evidence

Date: 2026-10-12. Task: CLOUD-STREAM-READ-BOUNDS-01.
Owner: Luke Ding; executor: Codex. Branch: codex/cloud-stream-read-bounds-01.
Base: READ slice4a79a270 plus locally accepted CONTRACTd8e85614.
State: component review; full READ acceptance and v2 activation remain open.

## Implemented boundary

Cloud Session replay reuses SessionEventPage and source-owned UTF8 byte bounds.
A page admits at most256 Events and1MiB before payload transfer; native metadata
rejects oversized Chinese/emoji bodies before SessionEvent hydration. PostgreSQL
uses read-only repeatable-read page transactions. SQLite has the same bounded
page contract; unprepared standalone stores fail closed while legacy reads remain.
Post-commit publication wrappers only forward read methods.

Cloud HTTP admission bypasses legacy routes that materialized full JSON history.
It retains upstream verified Host Grant target/opaque scope validation and the
same tenant/principal authorization guard. Native namespace and root Session
status reads use scalar SQL. Future Task/Session cursors receive HTTP400.
Exact raw routes are /sessions/{id}/stream and /tasks/{id}/stream, GET only;
unknown prefixes and malformed component counts never become Session routes.
AG-UI's separate route matcher remains unchanged.

Opt-in Task headers qualify membership, root/active Segment, lineage, source
highwater, canonical/index coordinate equality and cardinality, Segment order,
header readiness, byte metadata and durable handoff root/parent/integer stage.
All metadata queries share one read-only REPEATABLE READ snapshot and2s TaskIO
budget. Ordinary callers retain the old header behavior; privacy defaults to
UNKNOWN(None). Strict coverage is read from the existing canonical source view,
backed by source marker presence, including malformed admission values.

Privacy qualification occurs at startup and again after each admitted replay
page before raw or AG-UI delivery. Late predecessor coverage suppresses child
output. Missing membership, source/index coverage or headers fail closed; GET
never backfills, adopts, repairs, modifies recorder state or advances recovery.

## Validation evidence

- Broad targeted suite:85passed,11header-scratch environment skips,58.70s.
- Separate configured header-scratch native suite:12passed,9.09s; narrow Run
  header seek/no-payload-column privilege behavior remains unchanged.
- Static gates:2,988files, mypy1,250files, eval30/30; all passed.
- Independent quality review found a P1 unknown-prefix SSE admission bypass.
  The shared exact raw-route predicate, helper404 and malformed normalization
  rejection repair it. Initial repair/API/Host preflight target:50passed,12.82s.
- Complete configured native/API/Host/header rerun after the P1 repair:
  **107passed, no skips,65.90s**. Independent spec/quality reviews GO for this component; final P1 reproduction
  returns404 for GET/POST/HEAD without SSE.

Regressions cover native PG/SQLite pages/resume, oversized UTF8 source admission,
large-history preflight with SessionEvent hydration forbidden, malformed late
coverage and predecessor privacy, missing headers/index/no read repair, incomplete
source cursors, unknown membership, scalar namespace authorization, deadline
expiry, future HTTP cursors before legacy source/body access, and concurrent
append between metadata reads retaining a consistent repeatable-read snapshot.
Routing repair cases include unknown prefixes, nested/duplicate components and
GET/POST/HEAD unknown routes with a real unrelated verified Host Grant; victim
source reads and frames are forbidden. Separate signed target-binding tests
remain part of the focused Host preflight suite.

## Explicit ceilings

Source integrity is still O(history) metadata SQL per page; legacy delta replay
can total O(history*pages), approaching quadratic work. The2s deadline bounds
operations by cancellation/fail-closed behavior, not by constant SQL work.
At most256 Segment metadata rows are admitted. A governed source prefix proof
could remove repeated scans in a future owned task; frontier/cache assertions
cannot replace the current canonical integrity checks.

Durable handoff root/parent/stage validation extracts scalar JSON in PostgreSQL.
It requires SELECT on the payload column even when no handoff matches. Python
startup hydrates zero historical Event bodies; this is distinct from a database
role with no payload-column privilege. No migration or new authority was added.

An oversized raw replay page can be rejected after HTTP200 headers, before any
frame, by the current raw-tail exception path. It does not provide a structured
raw observation notice yet. Native byte admission prevents oversized body
hydration; this does not claim polished transport error presentation.

No SQL reduction, capacity,100subscriber/default-executor, paired workload,
Host/BFF/browser, full Worker, v2 writer/client or production Gate is inferred.
V2 must still prove no per-frame PG content/projection writes and the paired SQL
budget. No commit, integration, push, deployment or service activation is claimed
by this component evidence alone. Frozen baseline code/dependencies stay untouched.

## Frozen v1 native SQL measurement handoff

BASELINE scope extended before recording this completed measurement. Frozen
profiler/runtime build f16d8324: 1/10/100 readers, Session/Task/AG-UI, idle/stream,
60-second windows, three repeats;54/54 cells completed, harness_unchanged=true.
Report: baseline worktree .artifacts/native-steady.json and XML. Runtime
conformance failed with23 terminal failures, zero content/tool failures; exit1
is preserved. These are baseline defects, not failed measurement collection.

| Single reader, idle | Median SQL in60s | SQL/s |
| --- | ---: | ---: |
| Session | 213 | 3.55 |
| Task | 3479 | 57.98 |
| AG-UI | 2739 | 45.65 |

Across27 stream cells, the durable delta recorder measured20SQL calls per delta.
This excludes full Worker progress, HTTP Grant/provider/browser paths; synthetic
checkpoint maintenance is counted separately. It is not the complete production
write cost. Initial replay, steady reads and final replay are separate counters.
The100-reader lower per-reader rates reflect saturation of the default32-thread
executor and degraded throughput; they do not certify efficiency or capacity.
WAL is cluster-global diagnostic data and may include other scratch tests.

The80–95percent total SQL reduction remains a target until paired v1/v2 runs
include actual Worker, checkpoint-ready publication and signed HTTP readers.
Frozen artifacts and runtime remain untouched; no production load was applied.

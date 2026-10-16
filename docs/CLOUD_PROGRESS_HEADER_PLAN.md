# Single-statement Run metadata snapshots

Task PROGRESS-HEADER-PLAN-01; human owner Luke Ding; executor Codex; base14f88588.
Local cloud-agent-trench only. No model call or historical Run replay.

## Measured scope and decision

The retained actual-page A1/A2 exclusive Worker residual is12.655/10.997s.
Progress catch-up accounts for3.756/3.502s and canonical append3.768/3.629s.
Within catch-up, latest Run SQL executes110/139times for879/1052ms total;
these are nested costs, not additional time to add to the residual.

Fresh isolated PostgreSQL18 EXPLAIN again identifies planning as dominant:
planning about1.5–2.1ms versus execution0.24–0.4ms on the small native source.
The previous RUN-HEADER-PLAN-01 had already rejected SQL rewrites; this slice's
additional materialization/flattening/singleton-join probes likewise do not
justify a query-body change. Two private probe variants initially had syntax/
forward-reference mistakes; they never touched normal services or production
source. An initial counter patched only ClientCursor and saw no bounded Cursor
queries; corrected to count both with nesting protection before relying on it.

A separate fixed ABBA test keeps all documented DISCARD reset actions except
plan invalidation in an isolated database only. Two-projector operation median
129.095→128.700ms is no meaningful benefit, while reset utility statements
increase9→72. Reject this experiment: existing DISCARD ALL remains unchanged.
No plan-cache cause or connection-reset speedup is claimed.

The retained change is smaller: latest and explicit Run adapters issue a
separate REPEATABLE READ READ ONLY SET even though each metadata reader already
uses exactly one SELECT statement. Remove that one setup round trip in both
shared adapter entry points. PostgreSQL provides a consistent snapshot within
[a single ordinary SELECT](https://www.postgresql.org/docs/18/transaction-iso.html).
The canonical query, row validators and return types are byte-identical.

The SQLite branch retains its existing transaction. Multi-query progress/page
and checkpoint reads retain their repeatable snapshots. Caller-owned snapshots
and every canonical namespace/Run/anchor/source/highwater check, lease/STOP
poll, deadline, independent commit/reset, Flash/high and v2 remain intact.
All metadata callers and RUN_HEADER_BODY consumers were inspected; no query
builder, schema, migration, dependency, Port, cache or retry is introduced.

## Paired operation result

One disposable PostgreSQL server, current v102 on both sides, fixed ABBAABBA
order, four samples per variant for each enabled-projector configuration.
Fresh namespace per sample, same canonical model response and commentary,
exact one output, final progress head and queue frontiers asserted.

| Operation | Original median | Candidate median |
| --- | ---: | ---: |
| Two enabled projectors, elapsed |127.975ms|121.865ms|
| Four enabled projectors, elapsed |126.525ms|122.530ms|
| Explicit application SQL, either configuration |59|56|
| Physical connections, either configuration |1|1|

SQL decreases5.1% in this operation; measured medians decrease4.8% and3.2%.
This is a small fixed-sample local result, not a real-page speedup, total Run
reduction or proof that the11–13s residual has been removed. Server-internal
statements and independent API/consumer work are outside these counts.
The change also removes one setup statement per explicit Run adapter read;
no extrapolation of whole-page counts is used as acceptance.

## Validation and activation boundary

The standalone native no-write check fails against old source (two statements)
and passes after the fix (one each, latest/explicit missing-source rejection).
Run on an already migrated disposable database with:

```
ZEBRA_TEST_POSTGRES_DSN=... uv run python scripts/check_run_header_statement_snapshot.py
```

Existing focused tests pass:22native latest/Worker progress/commentary cases,
including replacement/cancellation, snapshot consistency, invalid identities,
namespace/unready-source rejection, first-head races and expired publication
fence;34SQLite/header/core cases pass with7optional-native skips. An initial
Ruff line-length finding in the new check is corrected; no old fixture changes.
Clean tracked-source make check passes: Ruff, mypy1285, size3101 and eval30,
plus both existing standalone progress fault gates. Normal API7eb869c9 and
Worker120509bc are activated after zero-active-intent guard, healthy/zero restarts.
All89prior fingerprints are retained or explicitly updated;92current fingerprints
match after including both changed storage modules on both services. Original
six Compose files, environment, commands, entrypoints and search config match.
The actual API and Worker each pass the no-write one-statement source check.
Both services intentionally restarted for source activation; no migration occurs.
Local integration preserves27unrelated primary dirty entries; no push/publication
or remote deployment. Private receipts: .artifacts/progress-header-plan-20261016/.

Overall SQL80%, real-page first-substantive-body, STOP/revocation/takeover,
Redis faults, capacity/GC and multiworker acceptance remain OPEN. Bigger gains
require measuring repeated complete publication work and external model/tool
waiting; these micro-optimizations cannot substantiate a seconds-level promise.

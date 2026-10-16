# Projection repair failure cleanup

Task PROJECTION-REPAIR-CLEANUP-01; base `650235d1`.

## Root cause and minimum repair

The PostgreSQL maintenance path repairs scalar headers for at most 100ms per
iteration, within the original cumulative 2s Task I/O budget. At expiry it tries
to recover the current header's savepoint. The inherited statement timeout can
also cancel that rollback. The unconditional RELEASE in `finally` then executes
against the failed transaction and replaces the original failure with
`InFailedSqlTransaction`. A source integrity exception can be masked the same way.

Only the shared `PostgresTaskProjectionWorkStore.repair_projection_work` changes:

- Release a savepoint after a successful header, rather than in `finally`.
- If savepoint rollback fails, rethrow the original `CheckpointNotReady` with the
  cleanup failure as its cause. Transaction exit aborts the unconfirmed page.
- A recoverable header cancellation still rolls back just that header and commits
  the completed prefix. A failed recovery never acknowledges that prefix.
- Break paths end the transaction, which clears remaining savepoints normally.

No dependency, Port, retry, pool, schema, source-event rewrite or authority cache
is added. No 100ms/2s budget, lease/STOP/freshness, projector selection, normal SQL,
connection reuse, v2 or thinking setting changes. The existing consumer retries
from canonical scalar metadata on a later bounded maintenance tick; no model or
historical Run executes. To obey the repository's near-limit rule, the existing
private `_WorkConnection` class moves unchanged to `projection_work_io.py`; its
original import alias remains available. No new adapter or abstraction is added.

## Validation

`scripts/check_projection_repair_cleanup.py` is a runnable no-framework assertion
check. Six forced query/source/socket/rollback/release/commit cases exercise the
actual shared method. Four fail against the original source; all six pass after
the change. It validates failure identity and cleanup ordering, not native I/O.

Four separate isolated PostgreSQL cases exercise actual transactions and statement
cancellation. A delayed second-header closure is canceled within the unchanged
repair budget. Successful rollback retains the first header and rolls back its
partial closure. Injected secondary rollback failure, source failure after a real
routing write, and RELEASE failure abort the unconfirmed page. Fresh stores then
finish all four cases, with exact anchors/frontiers, unchanged three canonical
Events and zero fabricated problem attempts. No committed-prefix claim is made
when rollback itself fails.

Final clean tracked-source `make check` passes: Ruff, mypy (1285 files), size checks
(3099 files), 30 eval cases and both existing progress fault checks. Eight native
response/commentary operations (four each with two/four enabled projectors) retain
59 application SQL executions and one physical connection each. Their current
medians are 103.775/106.580ms, a retention check rather than a new paired speedup.
The bounded existing queue/I/O/repair-consumer run passed 47 cases, with 5 cases
explicitly deselected. An earlier expanded run was interrupted after 102 passes
and 5 deselections: an existing orphan-ledger case did not exit. That stalled case
is unclassified, not claimed as a proved inherited defect; no fixture is repaired.
One additional native invocation failed during disposable-server setup before
any case ran (server closed during startup); retained as setup failure evidence.
The final source passes the four native cases after the class-only move, and AST
comparison confirms the moved adapter body is identical to the original.
The old
single-call completion and 1.5–2.4s repair-tick assertions are explicitly excluded
from this focused run: they conflict with the existing 100ms sub-budget. They are
not changed to manufacture a full-suite pass. The previous whole-suite evidence
remains distinct; this slice does not establish whole-Run/page or 80% SQL gains.

## Local activation

Worker-only source overlay `b24807f5` is active after the zero-active-intent guard;
Worker and API are healthy with zero restarts. API `cfc1dcf8` and its exact start
time are unchanged. Verification covers 89 source fingerprints, the unchanged
v102 migration sources, original six Compose files, environment, commands,
entrypoints and search settings. The actual Worker passes all six cleanup checks
and the libpq18 two-transaction/one-socket/reset/close probe. No database migration
or event rewrite occurs in this slice. Local integration targets
`cloud-agent-trench`, preserving unrelated primary changes. No push, npm publication,
remote deployment, app data repair or provider call.

Private evidence is under `.artifacts/projection-repair-cleanup-20261016/`.

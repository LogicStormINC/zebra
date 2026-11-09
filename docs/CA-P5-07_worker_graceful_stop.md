# CA-P5-07 — Graceful CLI Worker stop

Status: producer Review; final full gates passed. Downstream source-pinned S1 remains OD-P5-07C-R.

OD-P5-07C-R reached actual same-Task approval/UI/Native execution completion, but
its original fixed-instance SIGTERM stop remained unknown/running. The container
uses the fallback CLI loop: unlike CommandWorkerProcess, it did not own SIGTERM.
A real CLI subprocess regression reproduced signal exit -15 rather than an
orderly Worker summary. Linux PID1 additionally cannot rely on default signal
termination. Neither observation authorizes force-killing active work.

## Implementation and boundary

- CLI composes a scoped stdlib SIGTERM/SIGINT stop request before Worker startup.
  Existing handlers are restored even on failure; an embedded non-main thread
  never acquires process signal ownership. No signal/global handler in core.
- Existing fallback polling stops further command/session pickup and new memory
  work after a request; the current execution and existing drain complete normally.
  The new callback defaults to false for existing non-CLI callers.
- A pre-start stop does not enter the migrated consumer. Once running, the migrated
  command consumer retains its own established async signal/shutdown behavior.
- Stop reason is signal, not a new quiescence or non-commit state. No cancellation,
  lease deletion, forced kill, authority refresh, automatic retry or new receipt.
  Native gate/owner/current-fleet proof remains required before lifecycle stop.
- No schema, stored snapshot/Event/Effect/receipt or Coverage rewrite. Graceful
  exit may still be delayed by current work; unknown remains original GET only.

## Checks

The real idle CLI signal check fails against the old source (-15), then passes
with normal signal summary. Handler restoration/failure, embedded thread, current
execution completion without next ready-session pickup, pre-start migrated
consumer refusal, and existing loop/CLI checks plus real command-process CLI adapter checks total31 passes.

Full make test/check are required before the producer is published and new exact
images are built. Old positive-v14/v15 stop originals stay retained; future test
intents use independent namespaces and UUIDs. Physical cleanup does not reconcile
the original logical stop. No deployment or production migration is authorized.


The first complete suite found one shared CLI adapter incompatibility (new stop
callback keyword,11229 passed/3080 skipped). CommandWorkerProcess now accepts the
same optional callback while keeping async signal ownership and real drain. Its
pre-start stop refuses consumer/transport creation. Existing deterministic cadence
validation moved to worker_polling to respect the process module size ceiling;
validation/cleanup order is preserved. Full gates are rerun after this correction.

Global Docker reconciliation saw10 new anonymous volumes during that first suite.
Six retained event mount/destruction chains identify an independent opt-in runtime
cleanup acceptance; that module was skipped in this run and its image was a
PostgreSQL image. Four older chains are outside Docker's256-event buffer. None is
attributed to this task or removed; existing23 unproven volumes also remain. No
container/network identity delta. The next suite records a complete event stream.


## Final producer evidence

- Corrected shared adapters:31 focused checks passed. Final make test11231 passed,
  3080 conditional skips; make check passed:1448 typed sources,30/30 eval,0 file-size
  violations/Ruff errors. Source blob hashes did not change during the final suite.
- Full event audit: global deltas are4 Jazz-owned containers/4 Jazz named volumes
  and8 independently marked opt-in cleanup volumes. These are external, untouched.
  No confirmed task-owned leftovers. Four first-run volume chains remain unproven;
  retained alongside the earlier23, never pruned or treated as empty business data.
- Final test runner/event collector exited. No S1 services or quotas were running
  concurrently. Downstream owns actual container PID1/upgrade/rollback evidence;
  a host CLI check alone cannot close that acceptance.

[Machine receipt](evidence/ca-p5-07/acceptance.json). No schema/data/receipt/Coverage
rewrite, mainline merge, deployment or production migration.

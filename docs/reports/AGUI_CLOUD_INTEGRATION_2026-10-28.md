# AGUI-CLOUD-INTEGRATION-20261028

## Scope and ownership

Luke Ding authorized local integration into `cloud-agent` and removal of Trench
coupling. Base: `0a50892d`; repair branch: `f8cd5d22`. The integration preserves
both histories, existing P3/P4 contracts, and uncommitted primary-checkout work.
No deployment, model/search call, approval decision, original Run change, or
Search/MCP restart is part of this task.

The Cloud Runtime owns canonical events, atomic approval/continuation, worker
commit confirmation, execution fences and bounded public streams. The existing
TypeScript SDK owns generic decoding/recovery and message reduction. Business
Turn tables, report/feedback UI and product-specific media/history projections
remain in the external Host adapter; they are not Cloud dependencies. The paired
Trench implementation remains a compatibility consumer, not a library imported
by Cloud or a prerequisite for its release gate.

## Integration decisions

- Merge the accepted event persistence budget, exact lost-ACK confirmation,
  service-tool sandbox avoidance, runtime readiness, approval API and native
  recovery regression work into the current Cloud baseline.
- Preserve both `/tasks/{id}/messages/receipt` and exact-Run approval routes.
  New P3 message recovery and existing approval operation contracts remain.
- Reuse mainline migration **113** (`approval_resume_replay_headers`). Its
  internal approval continuation SQL is equivalent to the repair branch's
  unintegrated **108**. Do not register a second migration with that version,
  edit issued mainline migrations, or change the P4 v114 catalog.
- The old production branch's v108 is **not** a drop-in migration history for
  the current Cloud baseline. A future deployment must inspect the ledger and
  reconcile that branch explicitly; this local merge does not alter production
  schemas or certify an in-place upgrade of that deployment.
- `tests/conformance/agui_long_session/run.sh` now requires only this repository,
  its existing Python/TypeScript dependencies and disposable PostgreSQL/Redis.
  No Trench path, virtualenv, frontend, database name or environment variable is
  required. Earlier paired browser acceptance remains historical evidence in
  `AGUI_LONG_SESSION_2026-10-28.md`, not a mandatory Cloud gate.

## Two generic defects exposed by the independent gate

### Replacement chunk identity

The real Cloud encoder emits an empty replacement at chunk 0, followed by the
answer replacement also beginning at chunk 0. The generic SDK previously keyed
its unacknowledged replay slot only by message/name/chunk index. Adjacent distinct
records could collide, reject the new prefix and leave later chunks with a gap.
The SSE decoder now attaches the validated opaque `streamCursor` to draft and
replacement observations; the existing reducer includes it in the replay key.
Exact replay remains idempotent and changed data at the same replay identity is
rejected. No new wire protocol, package, dependency, business identifier or
unbounded deduplication map is introduced.

### Checkpoint ahead of queue bootstrap

A pre-existing checkpoint may be ahead of a bounded, partially reconstructed
open projection-work target. Rejecting that scalar observation aborted the whole
pending read before routing repair could catch up. Open work now permits this
observation. Both stores still require the exact target, revision and current
checkpoint to ACK; a stale target cannot finish, advance or erase evidence.
Closed-target invariants remain strict. A shared SQLite/PostgreSQL regression
reproduces the old failure, checks failed premature ACK, then exact completion
after the existing repair catches up.

## Acceptance

Run the standalone gate:

```sh
ZEBRA_NODE_BIN=/path/to/node tests/conformance/agui_long_session/run.sh
```

The Python stage creates wire with the real `canonical_wire` encoder and signed
v2 cursor codec. The SDK stage serves that saved wire over loopback HTTP and uses
native `fetch` plus the existing consumer/reducer. It checks cold startup with a
persisted suffix cursor, 1,020,000-byte answer SHA, large tool result, provisional
resets during canonical assembly, complete and partial outcomes, and a chunked
terminal. Each sample makes one GET with `recovery=full`, executes no historical
Client Effect and retains the original Run identity. No intercepted HTTP response
or model output is used. This is protocol acceptance, not a product browser or
live model performance claim.

Native database checks cover approval identity/expiry, same-Run continuation,
checkpoint recovery, lost commit ACK, queue bootstrap and the existing message
receipt route. Conditional skips fail the standalone gate.

Validation: standalone native gate **152 passed / 0 skipped**, stream SDK gate
**32 passed / 0 skipped**, complete SDK suite **174 passed / 0 skipped**,
SDK build/typecheck and `make check` passed. Native gate applies the full current
migration catalog through v114 to an isolated database; the equivalent v113
approval SQL was also compared directly with the previous branch definition.
Full `make test`: **11,216 passed / 3,082 conditional skips / 0 failed**
(1,346.59 seconds). These external-environment skips are not native acceptance;
the standalone database/stream gate above explicitly requires zero skips.
Accepted for local fast-forward integration into `cloud-agent`; no push/deployment.

Historical compatibility is intentionally preserved: existing `trench_compat`
adapters, v1 coverage decoding constants and the opt-in Trench E2E target are not
removed or reinterpreted. They preserve old signed records and original Runs;
they are not dependencies of the default Runtime composition or this standalone
gate. The existing repository-wide product-boundary checker continues to reject
Trench implementation imports and product defaults in normal deployment files.

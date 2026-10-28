# APPROVAL-BRIDGE-20261028

## Root cause and scope

The original production Run `cf81d38f-d88f-4b71-bd4f-f94b296e2003`, Task
`24e4c24f-70c3-4be7-be2b-8286d9f499df`, correctly stopped at approval event
`71bc22cd-719d-458f-8ac1-306218dca996`, sequence 85. The policy deliberately
requires approval for shell metacharacters. Trench rendered the interrupt as
ordinary waiting input without a decision interface. This was an incomplete
approval transport, not a failed model or permission to bypass policy.

The legacy approval endpoint also did not atomically couple the decision and
wakeup or bind a decision to an exact displayed approval. The new Cloud-only
Task/Run endpoint uses the existing authorization guard, domain decision service,
canonical event appender and command outbox. Local/legacy surfaces are unchanged.

## Guarantees

- Revalidate signed Host authorization and Task/Run binding on every request.
- Display canonical tool name, reason and complete argv. Client submits identity
  and approve/reject only, never replacement arguments or operator authority.
- Lock canonical stream before Task; compare active segment, latest Run,
  approval event/revision, tool call and fingerprint; refuse active Worker lease.
- Commit decision, Session/Workspace projection and one internal resume wakeup
  atomically. Reject commits no wakeup. Keep the 1 MiB canonical event guard.
- Deterministic decision identity rejects conflicting decisions and deduplicates
  concurrent/response-loss submissions. GET can retrieve the committed receipt.
- Internal `approval-resume:` inherits the unique original Run anchor and active
  Turn extension snapshot; it does not introduce another Run or another snapshot.
  v108 adds this key family to the existing canonical replay-header trigger;
  original v66 migration is immutable. Full-event replay recognizes the same key.
- Trench pins intent before mutation, binds to the latest owned Turn and original
  accepted Run. Lost responses reconcile with GET; no automatic mutation retry.
- Confirmed approval rearms only the original observer/cursor using running/GET
  resume, not a new model Run POST. Repeated receipts do not requeue observation.
- Confirmed rejection marks the Turn blocked. Same-Turn resumed history replaces
  its waiting projection when later results arrive. Live UI preserves approval
  waiting rather than declaring completion.

## Verification

- Native PostgreSQL + API contract + existing Worker consumer: 23 passed.
- Trench approval + Turn store + dispatcher: 34 passed.
- Frontend approval controls + existing Turn observer: 43 passed; TypeScript clean.
- Native cases include concurrent decisions, conflict/stale identities, atomic
  rollback on wakeup failure, native handoff, lease/cancellation rejection and
  unchanged original Run replay binding. No provider/search calls.
- Trench cases include owned Turn checks, original Run/request/cursor preservation,
  idempotent receipt handling, reject-without-wakeup and lost POST response followed
  by GET reconciliation. UI covers explicit actions, locked double click, stale
  Run and no mutation retry.

## Deployment boundary

Use exact running image overlays; preserve previous Worker commit confirmation
and Trench source summary repairs. Production is on v105: apply only v108 to the
production catalog, leaving unrelated source-branch v106/v107 changes deferred.
Update Zebra API/Worker and Trench API/frontend; preserve environment, mounts,
security, Search/MCP processes and cooldown. Record private inspection/rollback
material under `/home/ubuntu/releases/20261028-approval-bridge`.

Production acceptance is read-only on the original pending Run. No approval or
rejection is submitted on behalf of the user; no original Run replay, model or
search call. User approval followed by real execution is deliberately outside
this acceptance boundary. The isolated tests prove decision/queue behavior;
production checks prove canonical pending identity and visible controls only.

## Production acceptance

Deployed and verified on 2026-10-28. Real logged-in Chrome page reads canonical
approval, displays complete arguments and both explicit decisions; reload retains
the same pending approval. No responses intercepted and neither button clicked.
Original 86 events, 4 pre-existing model calls, 1 pre-existing search and 0 approval
decisions are unchanged. All persisted Turn requests/status/answers/cursors are
unchanged. Search, MCP, their TLS/egress and grant broker processes are unchanged.
Final frontend image: `trench-frontend:approval-details-20261028`; other changed
services use `*:approval-bridge-20261028`.

During acceptance, an independent production TLS blocker was discovered: the
acceptance CA and leaf both expired at 2026-10-28 04:13:46 UTC. They were issued
with only 30-day lifetimes. Renewed with existing private keys/public identities,
identical subjects and SANs, through 2027-10-28 04:51:25 UTC; retained all other
bundle roots and hot-reloaded the existing acceptance TLS process. Verified both
Cloud and broker HTTPS with certificate validation enabled. No Search/MCP restart.
Certificate renewal remains an operational requirement before that expiry; this
change does not install an automatic renewal scheduler.

Deployment's first verification compared environment arrays by order and caused
an automatic rollback. Values were identical; changed verification to key/value
comparison, then redeployed successfully. No business events or decisions were
written in either rollout. Private backup, rollback and evidence material stays
under the release directory; no credentials/keys are committed.

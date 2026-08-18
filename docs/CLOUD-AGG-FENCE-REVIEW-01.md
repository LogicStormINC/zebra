# CLOUD-AGG-FENCE-REVIEW-01

## Aggregate Fencing Gate Evidence Review

- Status: `Done` / review result `PASS`
- Date: `2026-08-04`
- Base: `zebra-cloud-trench@7a13f7a3`
- Branch: `codex/cloud-agg-fence-review-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-review-01/zebra-agent`
- Owner: `codex`
- Parent gate: `CLOUD-AGG-FENCE-01`

## Decision boundary

This review reconciles the path-bounded aggregate evidence. It may move the
parent gate from `Locked` to `Review` for maintainer review, but it does not
authorize Runtime/API/Worker profile selection, application Compose, Redis live
fan-out, Provider HTTP, Mem0, Desktop or production rollout.

## Evidence matrix

| Aggregate / lane | Evidence | Result | Boundary |
| --- | --- | --- | --- |
| Context lifecycle | focused PostgreSQL `18/18`; administrative CAS and semantic zero-write regressions | PASS | Worker lifecycle + management CAS |
| Handoff reserve/abort | PostgreSQL `15/15` | PASS | Worker authority, source CAS, Workspace/Task binding |
| Handoff dispatch | PostgreSQL `14/14` | PASS | operation, stream/pointer revision, claim token and replay |
| Workspace/Task | repository runner `36/36` | PASS | Task rollover, Workspace/Task projections and concurrency |
| Model/Tool projections | PostgreSQL `8/8`; Control Plane `11/11` | PASS | Event-derived projection revision fencing |
| Provider continuation | PostgreSQL `4/4` | PASS | v13 payload lifecycle, soft-delete stream CAS and scope |
| Artifact payload | PostgreSQL `13/13` | PASS | v9 reserve/object/finalize/compensate/prune lifecycle |
| Effect → Artifact | PostgreSQL `7/7` | PASS | intent Event, Artifact finalize and outbox atomicity |
| Delivery command lane | PostgreSQL `12/12` | PASS | command claim/receipt/audit; not a Worker Lease aggregate |
| Session history/read composition | PostgreSQL `3/3` and Context materialization `4/4` | PASS | read-only namespace/allowed-session scope |

Every listed runner uses PostgreSQL `17.5-alpine3.21` (or the recorded pinned
equivalent), emits its PASS sentinel and removes its container, volume and
network. The Delivery row is intentionally included as a boundary check, not
as evidence that API commands consume Worker Lease fences.

## Cross-cutting checks

- Worker mutations carry deployment namespace, Session identity and the complete
  `LeaseFence`; stale epoch/token/owner and foreign namespace paths fail before
  business writes.
- Expected stream or projection revision is checked under a transaction-local
  row lock/CAS. Same-identity replay is canonical; same key with different
  content fails closed.
- Injected failures prove transaction rollback for Context, Handoff/dispatch,
  Model/Tool, Provider, Artifact, Effect/Artifact and Delivery paths.
- PostgreSQL composition and migration ownership remain serialized; the v13/v15
  schema sequence is unchanged by this review. Cloud composition remains
  explicit and fail-closed rather than silently falling back to SQLite.

## Remaining gates

The aggregate evidence is complete enough for a `Review` transition, but the
parent gate is not a production-readiness gate. The following remain separate:

1. maintainer approval of the parent review and any explicit runtime activation;
2. API/Worker application profile selection and `docker/compose.application.yml`;
3. Redis replay-plus-tail live fan-out and event routing;
4. migration backup/PITR/restore/rollback and multi-Worker failure drills;
5. Provider HTTP, Host/AG-UI/Trench and later frontend/product slices.

## Review result

`PASS`: all registered path-bounded aggregate evidence cards are `Done`, with
real PostgreSQL PASS sentinels and deterministic cleanup. The parent
`CLOUD-AGG-FENCE-01` moved from `Locked` to `Review`; implementation and
successor activation remain unauthorized until the maintainer explicitly
approves the next gate.

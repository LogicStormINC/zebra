# Zebra Agent Project Status

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Current Mainline Snapshot

- Snapshot date: `2026-07-18`
- Verified implementation baseline: `f950402` (PR `#156`)
- Product posture: `feature-complete local Beta / single-host production candidate`
- Active implementation task: `ARCH-RT-A1-OS-01` is in Review
- Desktop browser task: `QA-DESKTOP-E2E-01` is in Review on
  `codex/qa-desktop-e2e-01`
- Runtime blueprint: `ARCH-RT-BP-01` is complete on its local task branch
- Locked architecture tasks: ACP entry and optional code intelligence
- Open product issue: none; `#148` closed with PR `#156`

## Current Capability

### Durable execution

- Event Store and projections are the durable source of truth.
- Harness and Worker execution is bounded, stoppable, resumable, and recoverable.
- SQLite leases, idempotency, tool/effect ledgers, snapshots, artifacts, and
  delivery audit cover the local execution lifecycle.
- Stage Session handoff is disabled by default and can be enabled explicitly at
  a safe boundary with lineage, authority, workspace, and no-replay checks.

### Runtime and security

- Runtime classes are `trusted-local`, `oci-rootless`, and `gvisor`.
- Production mode requires gVisor and a digest-pinned image and fails closed on
  missing runtime capability or authority drift.
- Hard runtime modes use a read-only root, non-root identity, dropped
  capabilities, no-new-privileges, default no-network, resource limits, and
  session-labelled cleanup.
- Policy, HITL, network profiles, MCP/Web gates, credential boundaries, and
  audit remain independent of model output.

### Context and model integration

- Every provider request crosses a model-aware context-window hard gate.
- Large tool outputs retain complete Artifact payloads while the model receives
  bounded, checksummed projections.
- Transparent Context Capsules support compaction, inspection, recovery, and
  deterministic provider-continuation fallback.
- DeepSeek stable Flash/Pro profiles, streaming/cache/TTFT/error telemetry, and
  default-off Beta capabilities are implemented without exposing private reasoning.
- Explicit in-process DeepSeek thinking tool loops preserve and replay private
  `reasoning_content`; default executor profiles remain non-thinking, and missing
  continuation state fails before HTTP.

### Product surfaces

- API, CLI, Worker, and Desktop read and mutate the same durable state.
- Desktop consumes replay-plus-tail SSE, renders truthful partial output, and
  supports approval, clarification, task plans, context, artifacts, and handoff.
- Real Chromium exercises the live Desktop/API/Worker/SQLite/SSE chain for long
  streams, reload recovery, cancellation, and terminal-session follow-up.
- Typed local tools cover bounded file, command, patch, tests, Git, Web, Skill,
  MCP, and read-only Research paths according to the task profile.

## Latest Validation Baseline

Validated on the `QA-148-MDL-01` branch merged as `origin/main@f950402` on 2026-07-18:

- `make sync`: passed
- `make test`: `1452 passed, 4 skipped`
- file-size gate: `868` files, zero violations
- Ruff: passed
- strict Mypy: `403` source files, zero errors
- release Eval: `8/8`, `pass_rate=1.00`
- latest `main` Quality workflow: Backend, Desktop, and real Linux gVisor passed
- Desktop: all `19` deterministic checks and production build passed
- current main JavaScript chunk: about `1.47 MB` (`458 KB` gzip), Vite warning remains

The four skips are three opt-in real-provider smokes and the macOS-gated gVisor
test. Linux CI runs the real gVisor smoke instead of treating that skip as proof.

On `codex/qa-desktop-e2e-01`, Desktop passed all `19` deterministic checks, the
production build, and `4/4` real Chromium streaming regressions. Repository
validation passed `1452` tests with `4` opt-in/platform skips, the `870`-file
size gate, Ruff, strict Mypy over `403` source files, and release Eval `8/8`.

The DeepSeek credentials-enabled focused run also passed all `39` contracts,
including a real thinking tool round trip.

## Governance State

- The Phase 0-8 implementation baseline is complete and historical.
- `docs/AGENT_TASKS.md` is the only executable task registry.
- All eight stale `Review` cards verified as merged are closed as `Done` by
  `QA-GOV-02` / PR `#144`.
- `QA-148-MDL-01` is `Done`; `ARCH-RT-A1-OS-01` is Ready and
  `QA-DESKTOP-E2E-01` is in Review.
- `ARCH-129-ACP-01` and `ARCH-129-CTX-01` remain `Locked` until explicitly activated.

## Known Follow-Ups

1. Use `docs/单机与云平台Runtime目标架构方案_v1.0.md` to decide whether the next
   milestone remains single-host product hardening or activates the private-cloud
   foundation.
2. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
3. Add packaged Tauri, migration/backup, capacity, and fault-injection release evidence.
4. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
5. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, tenant isolation, and Kubernetes in dependency order.

## Runtime Blueprint

`ARCH-RT-BP-01` is complete on `codex/arch-runtime-deployment-blueprint` and
records the shared Runtime contract and the separate single-host and cloud
deployment profiles. It does not activate implementation or change the status
of locked architecture cards.

The maintainer activated single-host Phase A on 2026-07-18. Work is split into
`ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01`; A1 is in Review and later tasks
remain locked. Phase B and Phase C remain deferred until every Phase A exit
criterion is evidenced.

A1 now implements macOS Seatbelt and Linux bubblewrap `os-sandbox` with
capability probes, sanitized process environments, network denial, whole-process
boundaries, immutable authority, snapshots, and fail-closed platform selection.
A2 remains locked until A1 merges and both real-platform CI smokes pass.

## Explicitly Deferred

- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- PostgreSQL/object-storage production control plane
- multi-tenant RBAC, quota, billing, and organization policy
- centralized Vault/KMS-backed credentials and production Egress
- ecosystem marketplace, cross-organization A2A, and autonomous production release

## Document Responsibilities

| Document | Responsibility |
|---|---|
| `README.md` | stable product entry, setup, capability summary, boundaries |
| `PROGRESS.md` | concise current mainline snapshot and next decisions |
| `docs/AGENT_TASKS.md` | executable task status, owner, branch, paths, acceptance |
| `task_plan.md` | current task checklist only |
| `WORKLOG.md` | session-level execution history and handoff evidence |
| final architecture | target architecture and invariants |
| Phase 0-8 implementation document | historical dependency and acceptance baseline |

## Required Reading

1. `README.md`
2. `PROGRESS.md`
3. `docs/AGENT_TASKS.md`
4. `AGENTS.md`

Before architecture changes, also read the source-of-truth documents in the
precedence order defined by `AGENTS.md`.

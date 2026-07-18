# Zebra Agent Project Status

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Current Mainline Snapshot

- Snapshot date: `2026-07-18`
- Verified implementation baseline: `d586a8f` (PR `#165`)
- Product posture: `embeddable Agent Runtime / feature-complete local Beta / single-host Phase A complete`
- Active implementation task: `UI-LOBE-01` is in review on
  `codex/ui-lobe-01-component-library`
- Architecture boundary: `ARCH-SVC-BOUNDARY-01` is Done via PR `#166`
- Desktop browser task: `QA-DESKTOP-E2E-01` is Done via PR `#161`
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

- Runtime classes are `trusted-local`, `os-sandbox`, `oci-rootless`, and `gvisor`.
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

- Zebra owns Agent execution state and can run as an independent microservice;
  Desktop and CLI are optional operator surfaces over the same Runtime.
- Authelia/external identity owns authentication. Calling business systems own
  users, organizations, membership, business authorization, subscriptions, and billing.
- Zebra accepts signed Agent authority, opaque namespace, and technical limits;
  internal Policy may only preserve or narrow that authority.
- API, CLI, Worker, and Desktop read and mutate the same durable state.
- Desktop consumes replay-plus-tail SSE, renders truthful partial output, and
  supports approval, clarification, task plans, context, artifacts, and handoff.
- Real Chromium exercises the live Desktop/API/Worker/SQLite/SSE chain for long
  streams, reload recovery, cancellation, and terminal-session follow-up.
- Desktop composes Lobe UI `ThemeProvider` with Ant Design X and Zebra's durable
  event projection; Lobe UI does not replace session or chat state.
- Typed local tools cover bounded file, command, patch, tests, Git, Web, Skill,
  MCP, and read-only Research paths according to the task profile.

## Latest Validation Baseline

Validated on `ARCH-RT-A4-E2E-01`, merged as `origin/main@d586a8f` / PR `#165`
on 2026-07-18:

- `make test`: `1484 passed, 7 skipped`
- file-size gate: `889` files, zero violations
- Ruff: passed
- strict Mypy: `412` source files, zero errors
- release Eval: `8/8`, `pass_rate=1.00`
- Desktop: deterministic checks, production build, and `7/7` real Chromium
  Runtime/streaming regressions passed
- Quality run `29645045918`: all seven jobs passed, including the packaged Ubuntu
  `.deb` WebDriver chain, real Linux gVisor, Workspace exhaustion, and real OS
  sandbox smoke on Ubuntu and macOS
- packaged evidence records `passed=true`, `runtime_class=os-sandbox`,
  `fallback_allowed=false`, cancellation, approval with real tool execution,
  failure visibility, and restart-durable-recovery; final screenshot shows the
  recovered failed session and Runtime Inspector value
- current main JavaScript chunk: about `1.47 MB` (`458 KB` gzip), Vite warning remains

The seven skips are opt-in real-provider/platform smokes. Linux CI runs the real
gVisor and native sandbox jobs instead of treating local skips as proof.

`UI-LOBE-01` validation additionally passes all Desktop checks, TypeScript,
Vite production build, and a real browser smoke without console warnings.

The DeepSeek credentials-enabled focused run also passed all `39` contracts,
including a real thinking tool round trip.

## Governance State

- The Phase 0-8 implementation baseline is complete and historical.
- `docs/AGENT_TASKS.md` is the only executable task registry.
- All eight stale `Review` cards verified as merged are closed as `Done` by
  `QA-GOV-02` / PR `#144`.
- `QA-148-MDL-01`, `QA-DESKTOP-E2E-01`, and all Phase A Runtime tasks
  `ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01` are `Done`.
- `ARCH-SVC-BOUNDARY-01` is `Done` via PR `#166`; `UI-LOBE-01` is the only
  current `Review` task.
- `ARCH-129-ACP-01` and `ARCH-129-CTX-01` remain `Locked` until explicitly activated.

## Known Follow-Ups

1. Decide explicitly whether to activate Phase B private-cloud single-tenant work;
   its database migration and recovery-model reviews remain required entry gates.
2. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
3. Add migration/backup evidence before any Phase B activation.
4. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
5. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, external-namespace isolation, and Kubernetes in
   dependency order.

## Runtime Blueprint

`ARCH-RT-BP-01` is complete on `codex/arch-runtime-deployment-blueprint` and
records the shared Runtime contract and the separate single-host and cloud
deployment profiles. It does not activate implementation or change the status
of locked architecture cards.

The maintainer activated single-host Phase A on 2026-07-18. Work is split into
`ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01`; all four tasks are merged and
every Phase A exit criterion is evidenced. Phase B and Phase C remain deferred
pending explicit activation; Phase B additionally requires database migration
and recovery-model review.

A1 now implements macOS Seatbelt and Linux bubblewrap `os-sandbox` with
capability probes, sanitized process environments, network denial, whole-process
boundaries, immutable authority, snapshots, and fail-closed platform selection.
A1 merged through PR `#160` after Ubuntu bubblewrap, macOS Seatbelt, gVisor,
Backend, and Desktop CI passed. A2 now owns Setup/Agent isolation.

A2 now implements exact external HTTPS GET egress, SHA-256 cache reuse, temporary
Credential revocation before Sandbox startup, no-network Setup execution,
lockfile verification, SPDX Setup Artifact, verified Snapshot handoff, and a new
no-network Agent handle. It reuses existing Artifact/Snapshot storage and adds no
durable state model. A2 merged through PR `#163` after all five Quality jobs
passed. A3 now enforces a dedicated capacity-limited Workspace mount in
production, kills timed-out process groups, normalizes runtime failures, and adds
real `ENOSPC`, 20-cycle native soak, long-stream, and gVisor machine-readable CI
evidence. Local validation passed `1483` tests plus all static/release gates; PR
`#164` merged after all six Quality jobs passed. A4 then delivered the final
packaged Tauri/Desktop Runtime E2E exit gate through PR `#165` / merge commit
`d586a8f`. Quality run `29645045918` passed all seven jobs. The Ubuntu `.deb`
artifact was driven through the real API, Worker, and `os-sandbox`; its retained
JSON and screenshot evidence cover no-fallback identity, cancellation, approval,
real tool execution, failure visibility, API restart, and durable recovery.

## Explicitly Deferred

- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- PostgreSQL/object-storage production control plane
- external authority adapter and namespace-isolated cloud control plane
- centralized Vault/KMS-backed credentials and production Egress
- ecosystem marketplace, cross-organization A2A, and autonomous production release

## Permanently External Business Responsibilities

- user registration, login credentials, MFA and identity lifecycle
- organization, membership, invitation, join/leave and account-disable workflows
- business RBAC, subscriptions, plans, billing, invoices and commercial quota

Authelia is the selected authentication provider. Zebra verifies external Agent
authority and enforces technical execution limits, but does not duplicate these
business domains. The durable decision is `ADR-012`.

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

# Zebra Agent Project Status

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Current Mainline Snapshot

- Snapshot date: `2026-07-28`
- Review task: `CTX-MEM-01` is in PR `#198` and closes the valid parts of GitHub issue `#197` with
  an exact three-user-turn tail, complete tool groups, one strict retry from
  original history, recoverable context suspension, evidence-gated memory
  promotion, and repo-scoped SQLite FTS recall under a token budget. Local
  validation: `63` focused tests, changed-file Ruff, Mypy over `158` source
  files, and release eval `10/10` pass. Full suite: `1747 passed, 8 skipped`;
  the same nine failures reproduce on untouched `main`. `make check` is blocked
  only by two inherited file-size violations outside this task. PR CI run
  `30332213200` did not execute any step because GitHub reported an account
  payment/spending-limit gate.
- Verified implementation baseline: `f1e4965` (PR `#174`)
- Product posture: `embeddable Agent Runtime / feature-complete local Beta / single-host Phase A complete`
- Review task: `CTX-SEG-01` has delivered the stable Task, internal Segment,
  unified stream/routing, automatic safe rollover, and SQLite migration slice.
- Active repair task: `CTX-SEG-02` preserves the latest bounded conversation
  checkpoint across terminal follow-up Segments, removes implicit low call
  ceilings, and converts explicit hard-budget exhaustion into recoverable pause.
- Review task: `SUBAGENT-UX-01` makes Subagent use a model-native tool decision;
  simple work remains in the parent and every valid delegation records its reason.
- Active architecture task: ADR-013 replaces user-visible child Sessions with a
  stable Task boundary and backend-internal execution Segments.
- Desktop browser task: `QA-DESKTOP-E2E-01` is Done via PR `#161`
- Runtime blueprint: `ARCH-RT-BP-01` is complete on its local task branch
- Review Embedded architecture task: `EMB-PLAN-01` on `zebra-cloud-trench`
  replaces the conflicting draft with one CopilotKit/AG-UI target, ADR-015, and
  a dependency-ordered task roadmap. It is documentation-only and does not
  activate Phase B or any Trench implementation card.
- Compatibility task in Review: `EMB-AGUI-SPIKE-01` is explicitly activated on
  `codex/emb-agui-spike-01`. It is a test-only official Python SDK spike stacked
  on the architecture branch; it adds no production API/Worker wiring and cannot
  merge before `EMB-PLAN-01` reaches `main`.
- Storage task in Review: `CLOUD-STO-SEAM-01` on `codex/cloud-sto-seam-01` is the
  first Zebra-foundation task after the maintainer reprioritized durable storage
  and memory ahead of further Trench work. It injects existing control-plane Store
  Ports while preserving the local SQLite profile and adds no cloud dependency.
- Authoritative storage task in Review: `CLOUD-STO-AUTH-01` on
  `codex/cloud-sto-auth-01` extends that same flat bundle across every durable
  API/Worker collaborator that advances Session state, gates effects or governs
  memory. A/B regressions prove the legacy path is not created; no cloud backend,
  migration or Mem0 integration is selected by this task.
- Memory contract task in Review: `MEM-GW-CON-01` on `codex/mem-gw-con-01` defines
  provider-neutral confirmed-memory publish, search and delete outcomes. Remote
  hits contain only a Zebra `MemoryId` for mandatory Store revalidation; no Mem0
  adapter, credential, Docker or runtime wiring is part of this slice.
- Dependency-container task in Review: `CLOUD-COMPOSE-INFRA-01` on
  `codex/cloud-compose-infra-01` creates the base Docker Compose dependency stack
  and a separate optional Mem0 boot-smoke overlay. Its pinned image, migrations,
  health and anonymous-request rejection are verified locally. Mem0 remains
  derived and replaceable; Zebra application containers stay locked until real
  cloud adapters exist.
- PostgreSQL tasks in Review: `CLOUD-PG-01` implements isolated Event/Projection
  Adapters, while `CLOUD-LEASE-PG-01` implements epoch-scoped, database-clock
  Lease fencing. Both have real PostgreSQL evidence but neither is runtime-selected.
- Effect Outbox task in Review: `CLOUD-EFFECT-OUTBOX-01` now has typed Core
  dispatch states and a PostgreSQL aggregate for fenced schedule, `SKIP LOCKED`
  claim, terminal commit, uncertain reconciliation and explicit retry. Its isolated
  Docker Compose PostgreSQL 17.5 matrix passes `49/49`, including fault rollback,
  concurrency, restore epoch, namespace and response-loss cases. It is not runtime-
  selected; Worker integration and any cloud-readiness claim remain locked.
- Effect consumer task in Review: `CLOUD-EFFECT-CONSUMER-01` runs Lease heartbeat
  on a background thread before recovery, checks ownership at Event and external
  Effect boundaries, and releases through one fenced lifecycle exit. Explicitly
  injected cloud runtimes can now schedule, claim and terminalize durable Effect
  intents; expired claims become `uncertain` for reconciliation and never auto-
  replay. The local SQLite profile still uses its existing ledger, and no backend
  selector or production cutover is included. Its isolated Docker Compose
  PostgreSQL 17.5 consumer matrix passes `58/58`, including heartbeat, stale-fence,
  crash, response-loss and reconciliation cases; dedicated containers, volumes and
  network were removed after the run. Deterministic and full-suite gates retain
  only the confirmed inherited failures.
- Business-baseline recovery is active before cloud-stack integration. Exact replay
  on `zebra-cloud-trench@375dca92` reproduces all `9/9` remaining failures. Five
  path-bounded cards own provider expectations, SCM credential fixtures, Worker
  cancellation convergence, Desktop style extraction and Core Event contract
  extraction. `BASE-MDL-EXPECT-01` is in Review after reducing the full suite from
  nine to seven failures. `BASE-SCM-CRED-01` is also in Review after removing all
  five expired-fixture failures; `BASE-WKR-CANCEL-01` is the only active card and
  the full suite now retains two failures.
- Agent Definition architecture task in Review: `AGENT-DEF-ADR-01` records accepted
  Definition control-plane decisions and updates the final architecture. It
  separates Task-level Definition configuration from Attempt-level execution
  authority and preserves ADR-012's opaque external namespace. Code audit also
  confirmed that external Attempt authority snapshots and immutable Skill content
  snapshots are not yet implemented; dedicated locked tasks now own those gaps.
  This integration records the decision only; implementation remains governed by
  the registered dependency DAG and explicit task activation.
  The implementation order is `CON -> STO -> {PG,DRAFT}`, `CON -> AUTH`, then
  `{DRAFT,AUTH} -> BIND -> MEM -> TRUST -> EVAL -> PUB`.
- Locked architecture tasks: ACP entry and optional code intelligence
- Open product issue: none; `#148` closed with PR `#156`
- Review task: `WEB-UX-01` makes explicit `local + trusted-local` execution
  non-interactive across Desktop/API/CLI/Worker, including existing Tasks, while
  retaining fail-closed non-local defaults and hard Gateway/Runtime boundaries.
- Active extension task: `EXT-0` registers the Skill/MCP/Plugin extension
  control-plane contract (`ADR-014`, merged via PR `#180`); the **EXT-1 Skill v2
  epic is complete** — `EXT-SKILL-01..05` are `Done` (metadata v2,
  scope/namespace/digest, task-level skill-component snapshot +
  handoff/authority/recovery/API threading, the bounded admin surface with
  SQLite enable/disable state, and `skills.read` provenance + release-eval
  cases). **`EXT-MCP-01` is `Done`** — bounded protocol-version negotiation
  (`SUPPORTED_PROTOCOL_VERSIONS` with server-version validation) and a
  Streamable HTTP transport (`mcp_http.py`) with bearer-token-via-env,
  module-level SSRF guard, https enforcement, and stdio/http routing in the
  harness. **`EXT-MCP-02` is `Done`** — `McpSessionPool` with
  healthy/degraded/quarantined health classification, bounded backoff, and
  acquire/release/health/close wrapping `McpProxyTransport` (shared by stdio +
  http); `SessionState` dataclass exposed from `mcp_protocol`. **`EXT-MCP-06`
  is `Done`** — elicitation mapped onto the durable Clarification flow:
  `ClarificationContext`/`ClarificationRequestedPayload` gain optional
  `response_schema` + `elicitation_source` (existing flow byte-identical),
  `McpElicitationBridge` converts `elicitation/create` → ClarificationContext,
  and `ZEBRA_MCP_ELICITATION` gates it (default on). **This completes the EXT
  Phase A scope** (EXT-0 + SKILL-01..05 + MCP-01/02/06).
  Plugin/Hook/Marketplace remain `Locked` pending private-cloud GA. Elicitation
  is reconciled to durable HITL; sampling stays a hard non-goal.
- Active harness task: `HAR-TOOL-RECOVERY-01` enforces the durable contract
  that a single `ToolCallStatus.FAILED` (HTTP 4xx, missing file, timeout) must
  surface as a structured observation for model-selected correction rather than
  directly producing `session_failed`. Changes: repeated tool calls become
  observations with a threshold-gated `loop_guard_exhausted` hard stop (default
  3), sequential batches continue executing remaining tools after a mid-batch
  failure (matching concurrent-batch semantics), and a provider protocol
  firewall (`protocol_invariants.py`) validates tool-call/tool-result pairing
  before every model request to prevent `invalid_request` leakage.
- Model-response acceptance is now a separate provider-neutral boundary:
  malformed body/SSE/tool-call output becomes `ModelResponseRejectedError`,
  tool-capable stream deltas are committed only after validation, one bounded
  repair is allowed within the model-call budget, and exhaustion produces a
  recoverable `SESSION_SUSPENDED` rather than `session_failed`. Provider
  transport retries and semantic repairs have separate trace counters. The
  implementation and regression cases are present in the working tree; runtime
  validation has not been executed in this session.

## Current Capability

### Durable execution

- Event Store and projections are the durable source of truth.
- Harness and Worker execution is bounded, stoppable, resumable, and recoverable.
- SQLite leases, idempotency, tool/effect ledgers, snapshots, artifacts, and
  delivery audit cover the local execution lifecycle.
- Existing Session handoff safety contracts now back internal Segment rollover
  while the legacy ordinary-user mutation remains disabled by default.
- Stable Task persistence aggregates root and child Segments behind one identity,
  one monotonic event cursor, and active-Segment message/control routing.
- Completed-Task follow-up and cancelled/failed-Task recovery create internal Segments
  automatically; unsafe lifecycle boundaries pause or fail closed.
- Immediate terminal follow-ups inherit the previous user/Assistant checkpoint;
  internal rollover no longer drops the subject needed by short replies.

### Runtime and security

- Runtime classes are `trusted-local`, `os-sandbox`, `oci-rootless`, and `gvisor`.
- Production mode requires gVisor and a digest-pinned image and fails closed on
  missing runtime capability or authority drift.
- Hard runtime modes use a read-only root, non-root identity, dropped
  capabilities, no-new-privileges, default no-network, resource limits, and
  session-labelled cleanup.
- Policy, HITL, network profiles, MCP/Web gates, credential boundaries, and
  audit remain independent of model output.
- Explicit `local + trusted-local` mode uses effective `full-trusted-local`
  authority across Desktop/API/CLI/Worker, so new and existing Tasks execute model
  tools without per-call approval. One Agent Security resolver is the authority
  source for every execution entry point. System HTTPS proxies are honored for
  local Web execution; direct connections retain public-address DNS preflight.
  Core and non-local deployments remain default-deny and approval-gated.

### Context and model integration

- Every provider request crosses a model-aware context-window hard gate.
- Large tool outputs retain complete Artifact payloads while the model receives
  bounded, checksummed projections.
- Transparent Context Capsules support compaction, inspection, recovery, and
  deterministic provider-continuation fallback.
- DeepSeek stable Flash/Pro profiles, streaming/cache/TTFT/error telemetry, and
  default-off Beta capabilities are implemented without exposing private reasoning.
- Malformed provider JSON and Tool Call arguments are rejected before execution;
  one bounded model repair is attempted, then execution suspends recoverably.
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
  supports approval, clarification, task plans, context, and artifacts without
  exposing internal child-Session or handoff controls.
- Real Chromium exercises the live Desktop/API/Worker/SQLite/SSE chain for long
  streams, reload recovery, cancellation, and invisible cross-Segment follow-up.
- Desktop composes Lobe UI `ThemeProvider` with Ant Design X and Zebra's durable
  event projection; Lobe UI does not replace session or chat state.
- The compact Ant Design X composer is merged; it does not change conversation
  or task-launch contracts.
- Typed local tools cover bounded file, command, patch, tests, Git, Web, Skill,
  MCP, and read-only Research paths according to the task profile.
- Failed tools return structured observations for model-selected correction or
  fallback, including bounded failure reason and detail when output is empty,
  while Policy, approval, protocol, effect, and budget stops remain hard.
- API and Harness model/tool call limits are optional and default to unlimited;
  an explicit caller ceiling remains strict. A batch that cannot fit starts no
  tools and suspends recoverably instead of becoming a generic Task failure.

## Latest Validation Baseline

Validated on `codex/ctx-seg-02-followup-recovery` on 2026-07-20:

- focused API/Core/Worker regression: `74 passed`
- `make test`: `1519 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `419` source files,
  and all `8/8` release Eval cases passed
- all `22` deterministic Desktop checks and the production Vite build passed;
  Tauri validation was intentionally omitted per explicit scope waiver

Validated on `codex/web-ux-01-trusted-local-auto-web` on 2026-07-19:

- final focused authority, failure-observation, proxy, API, Worker and runtime:
  `101 passed`
- `make test`: `1515 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `418` source files, and
  `8/8` release Eval cases passed
- every deterministic Desktop `check:*` script and production build passed
- real Chromium: `8/8`, covering the trusted-local launch default, automatic
  command execution, streaming, reload, cancellation, Segment and failure paths
- the original old Task completed a real OpenAI `web.fetch` via the configured
  macOS HTTPS proxy without approval or `private_network_blocked`
- real Zhipu Task `91fbddb3-d608-4e7c-a15b-694d6e55c9ae` recorded Policy
  `allow`, recovered from the site's expired TLS certificate, and gave the model
  the exact failure detail instead of a false allowlist explanation

Validated on `codex/subagent-delegation-model-native` on 2026-07-19:

- focused delegation and recovery regression: `39 passed`
- `make test`: `1509 passed, 5 skipped`
- `make check`: file-size `898`, Ruff, strict Mypy over `417` source files, and
  `8/8` release Eval cases passed
- isolated real-model API check answered `1+1` directly with `2`; trace and
  durable events contained no tool or Subagent activity

Validated on `codex/ctx-seg-01-task-runtime` on 2026-07-19:

- `make test`: `1501 passed, 7 skipped`
- `make check`: file-size, Ruff, strict Mypy over `417` source files, and `8/8`
  release Eval cases passed
- Desktop: every deterministic `check:*` script and production build passed
- real Chromium: `7/7` long-stream, reload, stop, invisible Segment follow-up,
  approval, and failure regressions passed
- terminal control state and approval identity now project through the stable Task
  boundary even while an internal Segment execution request is settling
- inherited workspace revision is fail-closed before the first Segment attempt;
  later approval continuations use current runtime authority instead of replaying
  the immutable creation-time revision check

Previous packaged mainline baseline:

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

`UI-COMPOSER-01` additionally passes all `21` Desktop checks, TypeScript/Vite
build, and real Chromium desktop/mobile visual checks. The thread composer is
`117px` high instead of `183px`; the new-task and `390px` mobile variants are
`145px` and `113px`, with no horizontal overflow or browser console warnings.

The DeepSeek credentials-enabled focused run also passed all `39` contracts,
including a real thinking tool round trip.

## Governance State

- The Phase 0-8 implementation baseline is complete and historical.
- `docs/AGENT_TASKS.md` is the only executable task registry.
- All eight stale `Review` cards verified as merged are closed as `Done` by
  `QA-GOV-02` / PR `#144`.
- `QA-148-MDL-01`, `QA-DESKTOP-E2E-01`, and all Phase A Runtime tasks
  `ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01` are `Done`.
- `QA-HANDOFF-CLK-01`, `QA-PKG-E2E-02`, `QA-PKG-E2E-03`, and `UI-LOBE-01`
  are `Done` via PRs `#170`, `#171`, `#172`, and `#168`.
- `UI-COMPOSER-01` is `Done` via PR `#174`.
- `ARCH-129-ACP-01` and `ARCH-129-CTX-01` remain `Locked` until explicitly activated.
- `EMB-PLAN-01`, `EMB-AGUI-SPIKE-01`, `CLOUD-STO-SEAM-01`, and
  `CLOUD-STO-AUTH-01`, `CLOUD-COMPOSE-INFRA-01`, `MEM-GW-CON-01`,
  `MEM-MEM0-SPIKE-01`, `MEM-MEM0-ADP-01`, `CLOUD-PG-PLAN-01`, `CLOUD-PG-01`,
  `CLOUD-LEASE-PLAN-01`, `CLOUD-LEASE-CON-01`, and `CLOUD-LEASE-PG-01` are in
  Review. Mem0 remains a derived, degraded-safe index; PostgreSQL Event/Projection
  and epoch/Lease Adapters have real-service restore and concurrency evidence.
  The local CI-billing waiver does not satisfy merge, runtime composition, release
  or production gates. Effect Outbox/consumer, full aggregate fencing, Redis,
  object storage, production AG-UI, Trench, analysis, writeback, Memory delivery and runtime wiring, and GA cards remain `Locked` pending their explicit gates.

## Known Follow-Ups

1. Review and merge `EMB-PLAN-01`; keep the completed AG-UI and Trench Spikes
   parked while the storage branches follow their recorded merge order.
2. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
3. Preserve merge order from `CLOUD-STO-SEAM-01` through `CLOUD-STO-AUTH-01`,
   `CLOUD-PG-PLAN-01`, `CLOUD-PG-01`, and the Lease contract/Adapter chain; do not
   select PostgreSQL until every authoritative Store can move as one profile.
4. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
5. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, external-namespace isolation, and Kubernetes in
   dependency order.
6. Review the dependency Compose baseline and Mem0 contract/Adapter chain. Preserve
   its duplicate, expired-search, timeout and error-classification findings; do not
   claim real-provider compatibility or make Mem0 authoritative.
7. Preserve the PostgreSQL/Lease order: `CLOUD-PG-PLAN-01 -> CLOUD-PG-01 ->
   CLOUD-LEASE-PLAN-01 -> CLOUD-LEASE-CON-01 -> CLOUD-LEASE-PG-01`; only then may
   fenced Effect Outbox and Worker consumer cards be activated.
8. Activate Object Storage, Redis live state, recovery and Memory delivery/runtime
   wiring one path-bounded card at a time; no production claim precedes complete
   composition, migration, restore and failover evidence.

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

- Zebra AG-UI production adapter and HostSessionGrant verifier
- Trench CopilotKit Runtime/BFF, read-only panel, frontend tools and writeback
- Memory delivery ledger and runtime wiring (Mem0 contract, Spike and Adapter are in Review)
- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- complete PostgreSQL runtime composition and object-storage adapters
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
| `docs/Zebra Embedded 生产级目标架构.md` | Embedded/Trench target and invariant boundaries |
| `docs/Zebra Embedded与Trench实施任务拆解_v1.0.md` | dependency, ownership and phase gates for Embedded delivery |
| Phase 0-8 implementation document | historical dependency and acceptance baseline |

## Required Reading

1. `README.md`
2. `PROGRESS.md`
3. `docs/AGENT_TASKS.md`
4. `AGENTS.md`

Before architecture changes, also read the source-of-truth documents in the
precedence order defined by `AGENTS.md`.

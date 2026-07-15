![Zebra Agent](./assets/logo.png)

# Zebra Agent

Zebra Agent is a local-first runtime and workspace for general-purpose executing agents.

It borrows durable sessions, typed tools, sandboxing, recovery, and HITL patterns
from products such as Claude Code and Codex. Coding and Git delivery remain
optional tool domains; they are not the default product goal or desktop flow.

The current repository direction is:

- monorepo
- `uv` workspace
- `src/` layout in each member package
- modular monolith for phase 1
- explicit service boundaries only where security or runtime isolation requires them

Provider-backed local runs advertise the executable registry as typed JSON Schema
tools. The OpenAI-compatible adapter keeps internal dotted names while using
provider-safe function aliases on the wire. One attempt can execute bounded
sequential model turns and consume every tool call in one provider response as an
ordered batch. Each result returns under the original assistant batch identity
before the next model request. Model and tool budgets reserve a final-answer turn,
and denied, repeated, or over-budget batch members stop before later calls execute.
Calls requiring human approval preserve the exact pending call, completed results,
and unconsumed batch tail; a grant resumes without replaying prior tools. Complete
batches run concurrently only when every tool contract is explicitly parallel-safe,
with policy, duplicate, and budget preflight before the bounded pool starts. Results
and events retain provider order. Mixed, unknown, write-capable, and approval batches
stay sequential. Before follow-up provider calls, completed older exchanges may be
deterministically compacted to a configured conversation budget. The stable system
prefix, original goal, latest working exchange, complete assistant/tool pairs, and
pending approval evidence remain canonical; compaction events contain only estimates,
counts, and provenance.

When consequential information is missing, the parent agent may call the typed
`agent.clarify` tool. Zebra persists the bounded question and optional choices,
transitions the session to `waiting_input`, and releases the worker instead of
blocking a process thread. A response must carry the active clarification ID;
the worker then restores the original assistant/tool conversation and continues
the same session once. Clarification does not approve another tool or grant file,
command, network, credential, or write authority, and fixed Research children do
not receive it.

The parent agent can delegate up to three independent workspace investigations in
one provider batch through `agent.research`. Local children run concurrently through
the existing safe-batch executor, while results and lifecycle evidence return in
provider order. Each child reuses the same Harness but receives only `files.read`,
`files.search`, and `git.status` under a read-only policy, cannot recursively
delegate, and returns
a structured summary with sources and confidence. Policy, duplicate, parent tool
budget, and aggregate child capacity are checked before fan-out; child count, depth,
concurrency, model, and tool ceilings remain fixed, and parent teardown cancels and
joins unfinished local children. Lifecycle metadata aggregates identities, status,
usage, sources, confidence, and provenance without raw findings. Automatic call
reordering, dependency graphs, write-capable subagents, reviewer roles, separate
child worktrees, and distributed workflow scheduling remain later boundaries.

## Desktop UI Workspace

The repository now includes an isolated frontend workspace at `UI/desktop`.

The desktop defaults to task, context, execution, and result surfaces. Human
controls appear only for a concrete backend approval or clarification request;
dormant Commit or Pull Request forms do not belong in the normal task timeline.

- stack: `Tauri + React + Tailwind CSS + TanStack Query + Ant Design + Ant Design X`
- runtime: `Node 22.17.0` pinned via `volta`, `pnpm 10.28.2`
- install: `cd UI/desktop && ~/.volta/bin/pnpm install`
- web build check: `cd UI/desktop && ~/.volta/bin/pnpm build`
- rust shell check: `cd UI/desktop && ~/.volta/bin/pnpm tauri:check`
- desktop shell dev: `cd UI/desktop && ~/.volta/bin/pnpm tauri:dev`
- current live reads: `/health`, `/approvals`, `/approvals/{id}`, `/sessions/{id}`, `/sessions/{id}/stream`, `/sessions/{id}/diff`, `/sessions/{id}/memory`, `/sessions/{id}/memory/queue-summary`, `/users/{id}/memory`, `/users/{id}/memory/queue-summary`, `/tenants/{id}/memory`, `/tenants/{id}/memory/queue-summary`, `/sessions/{id}/memory-overview`, `/sessions/{id}/memory-governance`, `/sessions/{id}/memory-action-hints`, `/sessions/{id}/memory-pressure`, `/sessions/{id}/memory-escalations`, `/sessions/{id}/memory-follow-up-windows`, `/sessions/{id}/memory-overdue-flags`, `/sessions/{id}/memory-overdue-age-buckets`, `/sessions/{id}/memory-overdue-types`, `/sessions/{id}/memory-overdue-visibility`, `/sessions/{id}/memory-overdue-trends`, `/sessions/{id}/memory-overdue-interventions`, `/sessions/{id}/memory-overdue-escalation-lanes`, `/sessions/{id}/memory-overdue-recovery-paths`, `/sessions/{id}/memory-overdue-resolution-checkpoints`, `/sessions/{id}/memory-overdue-resolution-outcomes`, `/sessions/{id}/memory-overdue-closure-decisions`, `/sessions/{id}/memory-overdue-archive-recommendations`, `/sessions/{id}/memory-overdue-retention-guidance`, `/sessions/{id}/memory-overdue-retention-windows`, `/sessions/{id}/artifacts*`, `/sessions/{id}/delivery-audit`
- current live writes: `POST /sessions`, `POST /sessions/{id}/messages`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`, `POST /sessions/{id}/suspend`, `POST /sessions/{id}/resume`, `POST /sessions/{id}/cancel`, `POST /sessions/{id}/commit`, `POST /sessions/{id}/pull-request`, `POST /sessions/{id}/memory/{memory_id}/confirm`, `POST /sessions/{id}/memory/{memory_id}/expire`, `POST /sessions/{id}/memory/review-queue-preview`, `POST /sessions/{id}/memory/review-queue`, `POST /sessions/{id}/memory/bulk-review`, `POST /users/{id}/memory/review-queue-preview`, `POST /users/{id}/memory/review-queue`, `POST /users/{id}/memory/bulk-review`, `POST /tenants/{id}/memory/review-queue-preview`, `POST /tenants/{id}/memory/review-queue`, `POST /tenants/{id}/memory/bulk-review`, `POST /sessions/{id}/artifacts/{artifact_id}/prune`

This workspace is intentionally kept outside `apps/` and `packages/` so frontend tooling stays isolated from the Python runtime path. Tauri scripts pin `CARGO_HOME` to `UI/desktop/.cargo-home` so Rust artifacts for the desktop shell stay local to the UI workspace.
If your shell still resolves `pnpm` or `node` to Homebrew or another global install, either prepend `~/.volta/bin` to `PATH` or use the explicit `~/.volta/bin/pnpm ...` form above.

### Provider-backed local run

1. Create ignored `.env.local` values for `DEEPSEEK_API_KEY`,
   `DEEPSEEK_BASE_URL=https://api.deepseek.com`, and
   `DEEPSEEK_MODEL=deepseek-v4-flash`.
2. Start the API with `make api-serve`.
3. Start the desktop web shell with `make ui-dev`, or use `make ui-tauri-check`
   before `pnpm tauri:dev` when validating the native shell.

New tasks use the `general` tool profile by default. It advertises Research,
command, bounded file-search, file-read, patch, and bounded Web-fetch capabilities
without
coding-specific Git status or test-run tools. Select `coding` explicitly in the
desktop launch controls or pass `--tool-profile coding` in the CLI when those
additional tools are required.
Tool profile selection changes model-visible tools only; `policy_profile` remains
the independent authority and approval boundary.

Parent sessions can also use `agent.plan` to read or replace one durable ordered
task plan. The plan is limited to 12 steps, supports `pending`, `in_progress`,
`completed`, and `cancelled` states, and permits at most one active step. It is
session state, not execution authority: it cannot grant tools, filesystem,
network, credential, or approval access, and fixed Research children do not
receive it. API, CLI, and desktop surfaces read the same SQLite projection; the
desktop hides the plan surface for legacy or empty plans and does not expose
manual editing.

`files.search` provides literal content and filename discovery under a
workspace-relative root, with optional glob filtering and explicit pagination.
It skips hidden, symlinked, binary, and oversized files and enforces fixed scan,
result, line, and output-byte ceilings before content reaches the model.

Task tool egress also defaults independently to `network_profile=none`. Use the
CLI `--network-profile` option or the desktop launch control to select a broader
existing network profile explicitly; `domain-allowlist` additionally requires
one or more `--network-allowlist` bare hostnames. This setting does not add tools
or approve external actions by itself, and Research children remain offline.
`web.fetch` accepts one credential-free HTTPS URL, requires an exact durable
allowlist match plus HITL approval, and executes through the Web Gateway contract.
The local adapter blocks redirects, explicit ports, IP targets, non-public DNS
answers, non-text responses, and payloads above 256 KiB. It is a local-first
bounded adapter, not a production distributed egress proxy or DNS-pinning claim.

Provider credentials are read by the local API only. They must not be placed in
frontend storage, request payloads, API responses, tracked environment files, or logs.

## Current Status

Phase 101 is now closed and documented, and scoped queue-sweep filtered preview controls are complete. The repository now has a complete local delivery surface plus guarded GitHub pull-request execution, SCM proxy routing, concrete MCP proxy gateway execution, proxy-aware approval events, durable approval projections, projection-backed approval reads, trace normalization behind explicit provider, dry-run, network-profile, credential, and policy gates, a real local snapshot backend for workspace-backed runtime handles, snapshot-backed suspend or resume control wiring across CLI, API, and worker execution, manifest-aware snapshot compatibility checks, explicit retained-snapshot cleanup, durable artifact storage, worker-side artifact capture for supported text outputs, artifact detail plus content retrieval over the local API, CLI artifact list, inspect, and read surfaces, audit-backed artifact read tracing, lifecycle-aware artifact payload metadata, deterministic policy-driven artifact retention defaults, storage-side expiry sweep primitives for retained local payloads, lifecycle readback for payload-backed artifacts, deterministic artifact access classification, manual artifact prune controls over both API and CLI, access-class enforcement plus audit parity for artifact actions, additive access explainability metadata across operator read surfaces, consolidated Phase 34 API and CLI access projection helpers, a cross-surface contract matrix for allowed, denied, missing, and pruned artifact access paths, explicit `status=\"ok\"` envelopes for successful API artifact detail and content reads, CLI inspect envelopes that now include `preview_state`, `lifecycle`, and pruned-payload unavailable semantics aligned with API behavior, a shared `agent-storage` artifact projection serializer for payload lookup, lifecycle, retrieval, and base envelope assembly, both API and CLI artifact adapters adopted onto that shared projection path, a shared `agent-security` artifact access projection helper for explainability payload assembly and policy-rank evaluation, both API and CLI artifact access adapters adopted onto that shared security projection path, a shared `agent-security` artifact access audit metadata helper reused by API read and prune audit paths, shared API-side denial or unavailable response helpers for artifact read adapters, shared CLI-side denial or unavailable response helpers for artifact read adapters, shared prune denied or unavailable response helpers for both API and CLI artifact control adapters, shared prune success response helpers for both API and CLI artifact control adapters, a shared artifact control audit metadata helper in `agent-security`, a converged lower-level artifact audit metadata builder behind the read-side and control-side wrappers, explicit delivery-audit endpoint regression coverage that preserves current artifact read and prune metadata semantics, a local CLI delivery-audit read surface for session-level operator inspection, a local CLI diff read surface for session-level workspace inspection, a local CLI stream read surface for session-level event replay inspection, a local CLI commit delivery surface for session-level code delivery, a local CLI pull-request delivery surface for session-level SCM delivery, a local CLI approval queue/detail read surface for operator triage, a local CLI approval decision write surface aligned with API decision results, a local CLI session message append surface aligned with API append results, a local CLI session cancel surface aligned with shared control semantics, dedicated cross-surface contract matrices that lock API and CLI parity on shared delivery-audit, session diff, session stream, session commit, session pull-request, approval read, approval decision, session message append, session control, session artifact list, session inspect, and session resume execute fields, plus a local-first typed memory store with deterministic extraction, durable review controls, confirmed-memory prompt injection, governance-derived repo memory, refresh-target-driven singleton stale invalidation for governance and procedure families, `last_review` lifecycle metadata on session memory inventory reads, deterministic `source` provenance readback for reviewed and candidate memory rows, local operator inventory surfaces for repo-scoped, user-scoped, and tenant-scoped memory, matching local review controls across those scopes, candidate-only queue reads across the same scopes for operator triage, scoped bulk review controls that classify applied, skipped, and invalid batch outcomes, additive queue summary reads that expose pending counts and latest candidate metadata across those same scopes, one combined operations overview that aggregates queue health across repo-session, user, and tenant scopes, additive governance reads that expose backlog breakdown plus latest review activity signals across supported scopes, additive backlog-aging reads that expose oldest pending memory plus deterministic age-bucket rollups across those same scopes, additive review-velocity reads that expose recent review counts and latest review windows across those same supported scopes, additive backlog-pressure reads that expose deterministic pressure levels and highest-pressure rollups across those same supported scopes, additive memory-pressure action hints that expose deterministic next-step guidance and highest-priority operator focus across the same supported scopes, additive memory-pressure escalation recommendations that expose deterministic escalation guidance and highest-priority escalation focus across those same supported scopes, additive memory follow-up windows that expose deterministic re-check timing and highest-priority follow-up focus across those same supported scopes, additive memory overdue flags that expose deterministic missed-follow-up status and highest-priority overdue focus across those same supported scopes, additive memory overdue age buckets that expose deterministic overdue duration bucketing and highest-priority overdue-age focus across those same supported scopes, additive memory overdue type rollups that expose deterministic overdue memory-type counts and highest-priority overdue-type focus across those same supported scopes, additive memory overdue visibility rollups that expose deterministic overdue visibility counts and highest-priority overdue-visibility focus across those same supported scopes, additive memory overdue trend signals that expose deterministic overdue state classification and highest-priority overdue-trend focus across those same supported scopes, additive memory overdue intervention hints that expose deterministic next-step actions and highest-priority overdue-intervention focus across those same supported scopes, additive memory overdue escalation lanes that expose deterministic handling lanes and highest-priority overdue-escalation focus across those same supported scopes, additive memory overdue recovery paths that expose deterministic recovery planning and highest-priority overdue-recovery focus across those same supported scopes, additive memory overdue resolution checkpoints that expose deterministic closure checkpoints and highest-priority overdue-resolution focus across those same supported scopes, additive memory overdue resolution outcomes that expose deterministic result states and highest-priority overdue-resolution-outcome focus across those same supported scopes, additive memory overdue closure decisions that expose deterministic final handling decisions and highest-priority overdue-closure focus across those same supported scopes, additive memory overdue archive recommendations that expose deterministic archive posture and highest-priority overdue-archive focus across those same supported scopes, additive memory overdue retention guidance that exposes deterministic active-retention posture and highest-priority overdue-retention focus across those same supported scopes, additive memory overdue retention windows that expose deterministic revisit timing and highest-priority overdue-retention-window focus across those same supported scopes, additive memory overdue retention breaches that expose deterministic missed-window severity and highest-priority overdue-retention-breach focus across those same supported scopes, additive memory overdue retention breach aging that exposes deterministic breach-duration buckets and highest-priority overdue-retention-breach-aging focus across those same supported scopes, additive memory overdue retention breach actions that expose deterministic next-step handling and highest-priority overdue-retention-breach-action focus across those same supported scopes, additive memory overdue retention breach lanes that expose deterministic routing lanes and highest-priority overdue-retention-breach-lane focus across those same supported scopes, additive memory overdue retention breach owner targets that expose deterministic responsibility targets and highest-priority overdue-retention-breach-owner-target focus across those same supported scopes, and additive memory overdue retention breach follow-through modes that expose deterministic aftercare routing and highest-priority overdue-retention-breach-follow-through focus across those same supported scopes, and additive memory overdue retention breach follow-through outcomes that expose deterministic result-state routing and highest-priority overdue-retention-breach-follow-through-outcome focus across those same supported scopes, and additive memory overdue retention breach follow-through completion states that expose deterministic completion routing and highest-priority overdue-retention-breach-follow-through-completion focus across those same supported scopes, and additive memory overdue retention breach follow-through verification states that expose deterministic verification routing and highest-priority overdue-retention-breach-follow-through-verification focus across those same supported scopes, and additive memory overdue retention breach follow-through verification outcomes that expose deterministic verification-result routing and highest-priority overdue-retention-breach-follow-through-verification-outcome focus across those same supported scopes, plus scoped queue-sweep review controls that let operators confirm or expire the current session-scoped, user-scoped, or tenant-scoped candidate queue in one action without pre-enumerating memory ids, scoped queue-sweep preview controls that expose the exact target set for those review sweeps without mutating state, scoped queue-sweep dry-run summaries that expose projected post-review status and per-type outcome shape before execution, scoped queue-sweep target explanations that expose per-record target reasons and aggregate explanation counts before execution, and scoped queue-sweep filtered preview controls that let operators narrow preview targets by `memory_type` before execution.

Phase 101 closeout is documented in
`docs/Phase101_Scoped_Queue_Sweep_Filtered_Preview_Controls_验收记录.md`.

- `POST /sessions/{id}/messages` is now available on the current development line
- `POST /sessions/{id}/cancel` and `POST /sessions/{id}/suspend` are now available on the current development line
- `POST /approvals/{id}/approve` and `POST /approvals/{id}/reject` are now available on the current development line
- worker-loop stop reporting and daemon-friendly continuous polling are now available on the current development line
- `GET /sessions/{id}/diff` is now available on the current development line
- `GET /sessions/{id}/artifacts` is now available on the current development line
- `zebra-agent artifact list <session_id>` is now available on the current development line
- `POST /sessions/{id}/commit` is now available on the current development line
- `POST /sessions/{id}/resume` and `zebra-agent resume <session_id> --execute` are now parity-aligned for stable resume output and failure envelopes
- `POST /sessions/{id}/pull-request` is now available as a local-only dry-run planning path
- side-effect `Idempotency-Key` handling is now available for commit and pull-request retries
- delivery audit records now capture commit and pull-request attempts
- the GitHub PR provider can serialize dry-run request payloads without live GitHub access
- guarded GitHub PR execution is wired to the API but remains disabled unless the explicit provider, dry-run, token, and policy gates all pass
- explicit SCM provider settings are available and keep local-only as the default
- pull-request gateway selection can opt into GitHub dry-run without enabling remote execution
- delivery audit read API is available for session-level operator inspection
- API composition has been split so `app.py` is below the 500-line hard limit
- SCM credential boundary separates token env names from token values with deterministic redaction
- guarded GitHub pull-request execution is available only behind explicit provider, dry-run, token, and policy gates
- SCM execution audit metadata now records normalized provider, status, URL, commit SHA, dry-run flag, and unavailable reasons
- SCM token redaction regression coverage now checks PR plans, API responses, delivery audit records, and settings snapshots
- `agent-security` now exposes deterministic network-profile contracts for upcoming egress guards, with `none` preserved as the fail-closed default
- GitHub PR execution now enforces explicit egress checks before credential lookup or transport side effects; direct transport remains blocked unless `full-trusted-local` or a matching `domain-allowlist` profile is configured
- `docs/operator_runbook.md` now documents egress profiles, failure-class interpretation, and safe rollback to `network_profile=none`
- `agent-integrations` now exposes a standalone SCM proxy transport contract and deterministic serializable request/response models for future proxy-backed execution paths
- GitHub PR execution can now route through a proxy-backed adapter when `ZEBRA_SCM_GITHUB_TRANSPORT=proxy` and `ZEBRA_SCM_PROXY_ENDPOINT` are configured
- `agent-tools` and `agent-security` now expose MCP proxy starter contracts plus egress classification metadata for `mcp.<server>.<tool>` calls
- `docs/operator_runbook.md` now documents proxy-backed SCM execution, MCP proxy starter routing, remediation, and rollback to safe defaults
- `ToolExecutor` can now execute `mcp.<server>.<tool>` calls through an MCP proxy gateway when that gateway is wired in, without changing local builtin tool behavior
- proxy-backed SCM audit and MCP proxy execution metadata now share stable `route` / `proxy_target` / `proxy_transport` fields
- local policy evaluation and approval requests now distinguish local tool paths, proxy-routed MCP tool paths, and fail-closed blocked MCP routes deterministically
- `docs/Phase22_Proxy_Execution_And_Gateway_Wiring_验收记录.md` records the completed proxy gateway execution phase and its remaining deferrals
- `docs/Phase23_Proxy_Approval_Projection_And_Operator_Readback_验收记录.md` records the completed proxy-aware approval readback phase and its remaining deferrals
- remote SCM operator safety runbook coverage documents dry-run first, explicit opt-in, audit inspection, token rules, and rollback steps
- credential capability domain modeling covers provider, audience, scopes, expiry, and redacted serialization
- credential broker Port definition covers SCM credential requests, in-memory test broker, and missing/denied/unavailable errors
- SCM gateway construction can use broker-issued capabilities for GitHub non-dry-run execution while preserving local-only and dry-run defaults
- local environment-backed credential broker can issue scoped capabilities from configured env var names
- API pull-request composition can inject a credential broker and fake GitHub transport for broker-backed execution tests
- API composition builds a default environment broker from GitHub SCM settings when no explicit broker is supplied
- direct SCM env fallback is disabled by default and must be enabled explicitly
- broker-backed SCM operator docs cover default environment broker execution, token rules, audit inspection, and fallback boundary
- SCM delivery audit now records non-secret credential source and backend metadata for broker-backed and explicit env-fallback GitHub PR execution
- broker-missing credential failures now retain source metadata without exposing token values
- SCM delivery audit now classifies credential_missing, credential_denied, credential_unavailable, and transport_failure for operator remediation
- secret-store Port and redaction contract now exist in `agent-security`
- local secret-store backend now reads per-handle secret documents without exposing raw values in repr or redacted snapshots
- GitHub App-backed credential adapter skeleton now exists for test injection and guarded integration hardening
- projection rebuild, durable SQLite projection rows, and repeated approval reads now keep the same proxy-aware `approval_context` vocabulary for `route`, `target`, `network_profile`, and `scope`
- `docs/Phase24_Durable_Approval_Projection_And_Operator_Queue_验收记录.md` records the completed durable approval projection and operator queue phase
- durable workspace projection storage now exists for `workspace_root`, `policy_profile`, lifecycle status, current sequence, and last attempt number
- runtime contracts now expose explicit lifecycle methods for `provision`, `snapshot`, `restore`, `fork`, `suspend`, and `resume`, and the local adapter now supports filesystem-backed snapshot, restore, and fork flows for the supported subset
- worker recovery and execution now reuse durable workspace projection state instead of raw bootstrap payloads for workspace lifecycle control
- `docs/Phase25_Durable_Workspace_And_Snapshot_Foundations_验收记录.md` records the completed durable workspace and snapshot foundations phase
- `docs/local_snapshot_runtime.md` documents the supported local snapshot subset, storage layout, retention model, and explicit unsupported paths
- local suspend and resume now emit durable control-plane events, persist snapshot metadata in workspace projections, and restore suspended workspaces onto fresh runtime-managed directories before worker execution
- `docs/Phase26_Local_Snapshot_Operator_Controls_验收记录.md` records the completed local snapshot operator controls phase
- session readback now includes projection-backed workspace lifecycle and snapshot metadata when durable workspace state exists
- CLI inspect and resume-read output now includes durable workspace lifecycle state and suspended snapshot metadata when available
- local snapshot housekeeping now classifies retained payloads as valid, missing, or incompatible before restore proceeds
- worker resume now deletes consumed snapshot payloads explicitly after a successful local restore
- `docs/Phase27_Workspace_Lifecycle_Readback_And_Snapshot_Housekeeping_验收记录.md` records the completed workspace lifecycle readback and snapshot housekeeping phase
- durable local artifact payload storage now exists with SQLite-backed metadata and explicit missing-payload inspection for later retrieval wiring
- worker execution now persists supported text tool outputs into the local artifact payload store when no explicit artifact URI is already provided
- session artifact APIs now support detail and content readback with explicit indexed-only and payload-availability semantics
- CLI now supports `artifact list`, `artifact inspect`, and `artifact read` for local artifact inspection without going through the HTTP API
- artifact previews now expose explicit redaction/truncation state, and artifact detail/content reads are now recorded in delivery audit
- `docs/Phase28_Durable_Artifact_Storage_And_Retrieval_验收记录.md` records the completed durable artifact storage and retrieval phase
- Phase 50 approval queue CLI and operator parity is complete with API and CLI coverage
- Phase 50 now has both local CLI approval reads and a dedicated approval queue/detail API-vs-CLI contract matrix with CLI-local `database` normalization
- Phase 51 now has a dedicated approval decision API-vs-CLI contract matrix with CLI-local `database` normalization
- Phase 52 now has a local CLI session message append surface for durable session continuation
- Phase 52 now has a dedicated session message append API-vs-CLI contract matrix with CLI-local `database` normalization
- Phase 53 now has a restored cancel control entry plus a local CLI cancel surface for durable session control
- Phase 53 now has a dedicated session control API-vs-CLI contract matrix with CLI-local `database` normalization and suspend `snapshot_id` normalization
- Phase 54 now has a dedicated session artifact list API-vs-CLI contract matrix with CLI-local `database` normalization
- Phase 55 now has CLI inspect approval-context parity aligned with the API session read surface
- Phase 55 now has a dedicated session inspect API-vs-CLI contract matrix with CLI-local `database` normalization
- Phase 56 now has CLI resume execute failure shaping aligned with the API resume execution surface
- Phase 56 now has a dedicated session resume execute API-vs-CLI contract matrix with CLI-local `database` normalization
- Phase 56 is now closed with an operator parity acceptance record; next implementation lane is currently not yet defined
- Phase 57 now has a local memory-store foundation for typed derived memory records, a core store Port, and a local SQLite adapter
- Phase 57 is continuing with deterministic extraction of `procedure` memory candidates from successful tool executions
- Phase 57 is now wiring memory candidate persistence into the worker completion path for completed local sessions
- `GET /sessions/{id}/memory` and `zebra-agent memory <session_id>` are now available for local session memory inspection
- `POST /sessions/{id}/memory/{memory_id}/confirm`, `POST /sessions/{id}/memory/{memory_id}/expire`, and `zebra-agent memory-review <session_id> <memory_id>` are now available for local memory candidate review
- confirmed repo memory now renders into the stable system-prompt context for local API, CLI, runtime, and worker harness execution
- confirmed repo memory injection now keeps `memory_type`, ranks higher-priority records first, removes normalized duplicates, and labels prompt sections by memory type
- confirming a newer memory now supersedes older confirmed memories of the same scope and type, and review responses expose the affected memory ids
- successful reads of root `AGENTS.md` can now emit a narrow `project_rule` memory candidate from the `Local Commands` section
- the same root `AGENTS.md` read path can now also emit a narrow `architecture_fact` candidate from explicit package dependency boundary rules
- explicit user messages prefixed with `Preference:` can now emit narrow `preference` memory candidates on completed sessions
- confirmed repo memory lookup now filters out records whose `expires_at` is at or before the lookup time before prompt injection
- memory review conflict handling is now type-aware: `project_rule`, `architecture_fact`, and `procedure` remain single-active, while confirmed `preference` memories can coexist
- confirming a candidate that exactly matches an existing confirmed memory now expires the duplicate candidate and reports the matching confirmed memory id
- a full successful reread of root `AGENTS.md` now auto-expires stale confirmed doc-derived `project_rule` and `architecture_fact` memories that no longer match the current governance document
- session memory inventory reads now include `last_review` lifecycle metadata so auto-expired and manually reviewed memories expose operator, reason, and latest review status
- successful non-sensitive procedure refreshes can now auto-expire stale confirmed singleton repo procedures through the same durable lifecycle event contract
- session memory inventory rows now include deterministic `source` provenance so operators can distinguish tool-derived governance or procedure memory from explicit user-message memory
- local operators can now inspect user-scoped and tenant-scoped memory inventories in addition to the existing repo-memory inventory surface
- local operators can now confirm or expire eligible user-scoped and tenant-scoped memory without leaving the existing memory review lifecycle contract

Read in this order:

1. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
2. `AGENTS.md`
3. `PROGRESS.md`
4. `docs/operator_runbook.md`

## Repository Shape

- `apps/`: composition roots such as CLI, API, and worker
- `packages/`: reusable Python packages such as core, context, tools, security, and runtime
- `tests/`: cross-package smoke and future integration tests
- `scripts/`: operator and bootstrap scripts
- `examples/`: runnable examples and reference flows

## Local Development

This repo now uses `uv` workspace management.

```bash
make sync
make test
make check
```

Or directly:

```bash
uv sync --all-packages --group dev
uv run pytest
```

## Operator Entry

For the current local operator workflow, start with `docs/operator_runbook.md`. For local snapshot runtime semantics, also read `docs/local_snapshot_runtime.md`. For denied versus unavailable artifact access paths, also read `docs/artifact_access_operator_guidance.md`. The operator runbook covers:

- CLI session creation, durable execution, inspection, and approval
- writable local API session creation, execution, resume triggering, and approval decisions
- worker loop execution for queued ready sessions
- local FastAPI serving
- SSE session stream replay

For the latest completed phase closeout summary, see `docs/Phase69_Memory_Backlog_Pressure_Signals_验收记录.md`.

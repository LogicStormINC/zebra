![Zebra Agent](./assets/logo.png)

# Zebra Agent

Zebra Agent is a local-first engineering agent platform for real code repositories.

The current repository direction is:

- monorepo
- `uv` workspace
- `src/` layout in each member package
- modular monolith for phase 1
- explicit service boundaries only where security or runtime isolation requires them

## Current Status

Phase 26 is in progress. The repository now has a complete local delivery surface plus guarded GitHub pull-request execution, SCM proxy routing, concrete MCP proxy gateway execution, proxy-aware approval events, durable approval projections, projection-backed approval reads, trace normalization behind explicit provider, dry-run, network-profile, credential, and policy gates, a real local snapshot backend for workspace-backed runtime handles, and snapshot-backed suspend or resume control wiring across CLI, API, and worker execution.

The next milestone is `Phase 26 - Local Snapshot Operator Controls`. The current implementation lanes are:

- `POST /sessions/{id}/messages` is now available on the current development line
- `POST /sessions/{id}/cancel` and `POST /sessions/{id}/suspend` are now available on the current development line
- `POST /approvals/{id}/approve` and `POST /approvals/{id}/reject` are now available on the current development line
- worker-loop stop reporting and daemon-friendly continuous polling are now available on the current development line
- `GET /sessions/{id}/diff` is now available on the current development line
- `GET /sessions/{id}/artifacts` is now available on the current development line
- `POST /sessions/{id}/commit` is now available on the current development line
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
- Phase 26 operator runbook and closeout are the remaining implementation lanes

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

For the current local operator workflow, start with `docs/operator_runbook.md`. For local snapshot runtime semantics, also read `docs/local_snapshot_runtime.md`. The operator runbook covers:

- CLI session creation, durable execution, inspection, and approval
- writable local API session creation, execution, resume triggering, and approval decisions
- worker loop execution for queued ready sessions
- local FastAPI serving
- SSE session stream replay

For the latest phase closeout summary, see `docs/Phase25_Durable_Workspace_And_Snapshot_Foundations_验收记录.md`.

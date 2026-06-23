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

Phase 16 is closed and Phase 17 credential backend hardening is ready. The repository now has a complete local delivery surface plus guarded GitHub pull-request execution behind explicit provider, dry-run, credential, and policy gates.

The next milestone is `Phase 17 - Credential Backend Hardening`. The current implementation lanes are:

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
- remote SCM operator safety runbook coverage documents dry-run first, explicit opt-in, audit inspection, token rules, and rollback steps
- credential capability domain modeling covers provider, audience, scopes, expiry, and redacted serialization
- credential broker Port definition covers SCM credential requests, in-memory test broker, and missing/denied/unavailable errors
- SCM gateway construction can use broker-issued capabilities for GitHub non-dry-run execution while preserving local-only and dry-run defaults
- local environment-backed credential broker can issue scoped capabilities from configured env var names
- API pull-request composition can inject a credential broker and fake GitHub transport for broker-backed execution tests
- API composition builds a default environment broker from GitHub SCM settings when no explicit broker is supplied
- direct SCM env fallback is disabled by default and must be enabled explicitly
- broker-backed SCM operator docs are the next ready implementation lane

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

For the current local operator workflow, start with `docs/operator_runbook.md`. It covers:

- CLI session creation, durable execution, inspection, and approval
- writable local API session creation, execution, resume triggering, and approval decisions
- worker loop execution for queued ready sessions
- local FastAPI serving
- SSE session stream replay

For the latest phase closeout summary, see `docs/Phase16_Local_Credential_Backend_And_API_Wiring_验收记录.md`.

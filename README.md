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

Phase 10 is closed. The repository now has a complete local delivery surface: CLI durable run and resume execution, writable API session creation and resume execution, queued-session bootstrap persistence, worker-side ready-session execution, a local worker polling loop, read-only SSE replay, operator runbook coverage, optional API bearer auth, an OpenAI-compatible model gateway adapter, session diff and artifact reads, local Git commit delivery, and local-only pull-request planning.

The next milestone is `Phase 14 - SCM Execution Hardening`. The current implementation lanes are:

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
- a GitHub PR provider skeleton can serialize dry-run request payloads without live GitHub access
- remote SCM execution is not wired to the API yet; local-only dry-run remains the default safe behavior
- explicit SCM provider settings are available and keep local-only as the default
- pull-request gateway selection can opt into GitHub dry-run without enabling remote execution
- delivery audit read API is available for session-level operator inspection
- API composition has been split so `app.py` is below the 500-line hard limit
- SCM credential boundary separates token env names from token values with deterministic redaction
- guarded GitHub pull-request execution is available only behind explicit provider, dry-run, token, and policy gates
- SCM execution audit hardening is the next ready implementation lane

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

For the latest phase closeout summary, see `docs/Phase13_API_Composition_And_Guarded_SCM_Execution_验收记录.md`.

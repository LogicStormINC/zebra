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

Phase 8 is closed. The repository now has a complete local productization baseline: CLI durable run and resume execution, writable API session creation and resume execution, queued-session bootstrap persistence, worker-side ready-session execution, a local worker polling loop, settings-backed entry points, read-only SSE replay, operator runbook coverage, optional API bearer auth, and a real OpenAI-compatible model gateway adapter.

The next milestone is `Phase 9 - Session Control And Worker Hardening`. The immediate implementation lanes are:

- `POST /sessions/{id}/messages`
- `POST /sessions/{id}/cancel` and `POST /sessions/{id}/suspend`
- `POST /approvals/{id}/approve` and `POST /approvals/{id}/reject`
- continuous worker-loop hardening for longer-running local operator use

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

- CLI session creation, durable execution, and inspection
- writable local API session creation, execution, and resume triggering
- worker loop execution for queued ready sessions
- local FastAPI serving
- SSE session stream replay

For the latest phase closeout summary, see `docs/Phase8_CLI_API_Productization_验收记录.md`.

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

The repository is in `Phase 8 - CLI/API Productization`. The `apps/ + packages/` workspace skeleton is in place, the core contracts are typed, the local runtime and builtin tools are wired, the control-plane foundation includes durable session events and recovery/indexing primitives, Phase 5 has closed out with a typed workspace context compiler, Phase 6 has closed out with deterministic local policy and approval hardening, Phase 7 has closed out with local trace, replay, eval, and release-gate foundations wired into `make check`, and Phase 8 now has CLI command skeletons, local session operations, an explicit durable CLI run execution path, queued session bootstrap persistence for later worker recovery, CLI and API resume execution triggers for ready sessions, API health/session route adaptation, a writable API session creation and execution entry, a worker-side ready-session execution service, a worker polling loop with a local operator entry, settings-backed CLI/API database defaults, a thin FastAPI serving layer, read-only SSE session replay, an executable local operator runbook, optional bearer-token auth for non-health API routes, a real OpenAI-compatible model gateway adapter, and a CLI model smoke path.

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

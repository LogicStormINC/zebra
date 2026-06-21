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

The repository is ready for `Phase 6 - Policy And Approvals Hardening`. The `apps/ + packages/` workspace skeleton is in place, the core contracts are typed, the local runtime and builtin tools are wired, the control-plane foundation includes durable session events and recovery/indexing primitives, and Phase 5 has closed out with a typed workspace context compiler covering provenance, token-budget trimming, split ranking/scanning modules, related-files recall, typed conversation/tool-output compaction, deterministic prompt layout and cache-key rules, baseline trust marking and prompt-injection metadata, harness-side context input wiring, runtime-evidence feedback, retry-plan hints, and hardened context compiler input acceptance.

Read in this order:

1. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
2. `AGENTS.md`
3. `PROGRESS.md`

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

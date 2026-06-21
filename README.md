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

The repository is in `Phase 5 - Context Compiler`. The `apps/ + packages/` workspace skeleton is in place, the core contracts are typed, the local runtime and builtin tools are wired, the control-plane foundation includes durable session events and recovery/indexing primitives, and the mainline now includes a typed workspace context compiler with provenance, token-budget trimming, split ranking/scanning modules, related-files recall, typed conversation/tool-output compaction, deterministic prompt layout and cache-key rules, plus baseline trust marking and prompt-injection metadata, the first harness-side context input wiring through an abstract port, runtime-evidence reinjection into compiled context, and retry-attempt evidence feedback into later context builds.

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

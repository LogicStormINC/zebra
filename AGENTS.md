# Zebra Agent Repository Rules

## Purpose

This file defines the repository-level working rules for Zebra Agent.

This project is building a Codex-like engineering agent platform with these architectural anchors:

- durable session event store
- stateless harness worker
- typed tool gateway
- deterministic policy engine
- disposable and resumable sandbox
- trace and eval driven iteration

## Source Of Truth

Read these files first before making architectural or workflow changes:

1. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
2. `docs/实施任务拆解与阶段验收.md`
3. `PROGRESS.md`
4. `README.md`

If there is a conflict, use this priority:

1. Current user request
2. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
3. `docs/实施任务拆解与阶段验收.md`
4. `PROGRESS.md`
5. Older design notes

## Project Rules

- Build in phase order. Do not skip from repo bootstrap directly to Web UI or cloud services.
- Default to local-first execution. Cloud, remote sandbox, and independent security services come later.
- Keep the implementation centered on `agent-core` contracts. Infrastructure should adapt to core, not the reverse.
- Do not treat chat text as durable project state. Durable decisions must be written back into repository files.
- Any change to architecture, milestone sequencing, or repository structure must be reflected in `PROGRESS.md`.
- Any change large enough to affect future implementation decisions must be reflected in `docs/`.

## Repository Layout Rules

### Root Directory

Only keep cross-workspace and project-governance files at the repository root:

- `README.md`
- `AGENTS.md`
- `PROGRESS.md`
- `task_plan.md`
- `findings.md`
- `progress.md`
- `pyproject.toml`
- `uv.lock`
- `Makefile`
- `.env.example`
- `.python-version`

Do not place feature code directly in the root directory.

### apps/

`apps/` contains composition roots only.

Allowed responsibilities:

- process startup
- dependency wiring
- config loading
- entry commands
- HTTP or CLI adapters

Forbidden responsibilities:

- core domain rules
- session state machine logic
- policy decisions
- context ranking logic
- runtime internals
- tool execution rules

### packages/

`packages/` contains reusable workspace members.

Current intended package roles:

- `agent-core`: domain models, use cases, harness logic, Ports
- `agent-context`: context compiler, retrieval, ranking, compaction
- `agent-tools`: tool contracts, registry, builtin tools, validation
- `agent-security`: policy, approvals, hooks, redaction
- `agent-runtime`: runtime adapters, sandbox, workspace execution
- future `agent-storage`: event store, projections, artifacts, leases
- future `agent-integrations`: model providers, ACP or MCP adapters, SCM integrations
- future `agent-observability`: tracing, audit, metrics, cost

Rule:

- packages may depend on `agent-core`
- `agent-core` must not depend on other `agent-*` packages
- packages must not import from `apps/`

### tests/

`tests/` is for cross-package tests and integration validation.

Package-local tests may exist inside each workspace member, but cross-cutting behavior should be tested under root `tests/`.

### docs/

Use `docs/` for durable project documentation only:

- architecture
- ADRs
- threat model
- runbooks
- implementation plans

Do not create throwaway brainstorming files in `docs/`.

## Code Rules

### General

- Use Python 3.12 style and typing features.
- Prefer explicit types on public interfaces.
- Keep domain logic deterministic and testable.
- Favor small modules with single clear responsibilities.
- Avoid hidden global state.
- Avoid circular imports by enforcing package boundaries.
- Do not introduce infrastructure dependencies into `agent-core`.

### Layering

- `agent-core` may define Ports and domain models, but not infrastructure implementations.
- `agent-runtime`, `agent-tools`, `agent-security`, and future `agent-storage` implement or extend core Ports.
- `apps/*` only compose dependencies and expose operators to the outside world.

### File Size Limits

These limits are repository rules, not suggestions:

- target file length: under 300 lines
- hard limit for most source files: 500 lines
- hard limit for test files: 700 lines
- hard limit for markdown docs: 600 lines unless the file is a primary architecture document

If a file approaches the hard limit, split it before adding more logic.

Preferred split strategies:

- move domain types into separate modules
- move protocols or interfaces into dedicated port files
- move validation logic into helper modules
- move large test matrices into separate test files by behavior

Do not create “utils.py” or “helpers.py” as dumping grounds to bypass file limits.

### Naming

- Use descriptive module names based on responsibility.
- Name Ports as nouns or noun phrases, such as `event_store.py` or `model_gateway.py`.
- Name implementations by runtime or backend, such as `sqlite.py`, `local.py`, or `docker.py`.
- Avoid vague names like `misc.py`, `common.py`, `temp.py`, or `manager2.py`.

### Testing

- Every new core model or state transition should ship with tests.
- Every new Port implementation should have at least one smoke or integration path.
- Bug fixes should add a regression test whenever practical.
- Eval cases do not replace deterministic tests.

## Documentation Rules

When you change architecture, execution model, or milestone sequencing:

- update `PROGRESS.md`
- update `README.md` if the repo entry point becomes stale
- update or add a focused doc under `docs/` when the change affects future implementation

Keep planning file responsibilities separate:

- `PROGRESS.md`: project-level current state
- `task_plan.md`: current multi-step task plan
- `findings.md`: discoveries and durable implementation notes
- `progress.md`: session log

## Default Workflow

For non-trivial tasks, use this loop:

1. Read the relevant design section.
2. Check `PROGRESS.md` and `docs/实施任务拆解与阶段验收.md`.
3. Make the smallest coherent implementation slice.
4. Validate with targeted commands.
5. Update docs or progress files if the durable state changed.

## Branch And PR Workflow

- Do not commit implementation work directly on `main`.
- Keep local `main` aligned with `origin/main`; use it only as the base for new work.
- Create one focused branch per coherent implementation slice, using the `codex/` prefix by default, such as `codex/phase1-core-domain`.
- Prefer small PRs that map to the implementation plan phases and can be reviewed independently.
- Open PRs against `main`; merging into `main` is handled by the maintainer or an explicit merge task.
- After a PR is merged, return to `main`, pull the latest `origin/main`, then create the next branch from the updated base.

## Local Commands

Use these commands by default:

- `make sync`
- `make test`
- `make check`

## Definition Of Done

A slice is only done when all of the following are true:

- code is committed to the correct layer and folder
- file boundaries still respect the repository limits
- tests or smoke validation exist
- validation commands were run or the blocker is explicitly documented
- `PROGRESS.md` reflects any durable phase change

## Handoff Notes

If you stop mid-stream, leave behind:

- what changed
- what remains
- exact next commands or files to touch
- blockers, if any


<claude-mem-context>
# Memory Context

# [zebra-agent] recent context, 2026-06-18 5:38pm GMT+8

No previous sessions found.
</claude-mem-context>

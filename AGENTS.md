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
3. `docs/02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
4. `docs/AGENT_TASKS.md`
5. `PROGRESS.md`
6. `README.md`

If there is a conflict, use this priority:

1. Current user request
2. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
3. `docs/实施任务拆解与阶段验收.md`
4. `docs/02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
5. `docs/AGENT_TASKS.md`
6. `PROGRESS.md`
7. Older design notes

## Project Rules

- Build in phase order. Do not skip from repo bootstrap directly to Web UI or cloud services.
- Default to local-first execution. Cloud, remote sandbox, and independent security services come later.
- Keep the implementation centered on `agent-core` contracts. Infrastructure should adapt to core, not the reverse.
- Do not treat chat text as durable project state. Durable decisions must be written back into repository files.
- Any change to architecture, milestone sequencing, or repository structure must be reflected in `PROGRESS.md`.
- Any change large enough to affect future implementation decisions must be reflected in `docs/`.

## Collaboration Rules

These rules exist to prevent parallel contributors from redoing the same work or colliding in the same paths.

### Task Source Of Truth

- `docs/AGENT_TASKS.md` is the operational task registry for parallel development.
- `docs/02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md` is the role and responsibility reference.
- Phase documents define sequencing; task registry defines concurrent execution boundaries.

### Claim Before Coding

Before starting any non-trivial implementation:

1. choose one task from `docs/AGENT_TASKS.md`
2. confirm the task status is `Ready`
3. assign one human owner
4. create one branch for that task
5. work only inside the task's `Owned paths`

Do not start coding first and claim later.

### One Task, One Branch, One Owner

For active implementation work, enforce:

- one task card
- one primary owner
- one branch
- one worktree
- one main review thread or PR

Do not mix multiple unrelated tasks into the same branch or PR.

### Owned Paths Are Hard Boundaries

- A task may modify only its declared `Owned paths`.
- If a task requires edits outside its `Owned paths`, stop and either:
  - split the work into another task, or
  - update the task definition explicitly before coding
- Shared files such as `AGENTS.md`, `PROGRESS.md`, root configs, or contracts must be treated as coordination hotspots and should not be changed casually from unrelated tasks.

### Parallel Development Strategy

Multiple contributors should parallelize by task lane and path ownership, not just by phase label.

Preferred pattern:

- one contributor on core contracts
- one contributor on runtime
- one contributor on security or policy
- one contributor on docs or governance

Avoid assigning two contributors to the same package subarea unless one is explicitly doing review-only or follow-up work after the first PR merges.

### Dependency And Unlock Rules

- A `Locked` task cannot start until its dependency tasks are merged to `main`.
- `Ready` means it may be claimed by one owner.
- `In Progress` means nobody else should implement overlapping code for that task.
- `Review` means only review fixes or explicitly requested follow-up work should be added.
- `Done` means merged and reflected in the task registry if needed.

### Branch And PR Mapping

- Branch names should map directly to one task, such as `codex/p0-con-01-events-v1`.
- PR titles should include the task identifier when one exists.
- PR descriptions should restate:
  - task id
  - owned paths
  - validation commands
  - known risks or follow-up items

### Handoff Rules

If work stops before merge:

- update task status in `docs/AGENT_TASKS.md`
- record blockers or partial completion in `WORKLOG.md`
- record any durable decisions in `findings.md` or the relevant doc
- leave exact next steps for the next owner

### Conflict Resolution

If two tasks need the same file or boundary:

1. prefer merging the dependency task first
2. rebase the second task on updated `main`
3. if overlap remains, create a narrower follow-up task instead of force-combining both changes

Do not solve repeated overlap by allowing broad “temporary shared ownership”.

## Repository Layout Rules

### Root Directory

Only keep cross-workspace and project-governance files at the repository root:

- `README.md`
- `AGENTS.md`
- `PROGRESS.md`
- `task_plan.md`
- `findings.md`
- `WORKLOG.md`
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
- `WORKLOG.md`: session log

## Default Workflow

For non-trivial tasks, use this loop:

1. Read the relevant design section.
2. Check `PROGRESS.md`, `docs/实施任务拆解与阶段验收.md`, and `docs/AGENT_TASKS.md`.
3. Claim exactly one ready task and confirm its owned paths.
4. Make the smallest coherent implementation slice.
5. Validate with targeted commands.
6. Update docs or progress files if the durable state changed.

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

# [zebra-agent] recent context, 2026-07-23 7:55pm GMT+8

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (20,088t read) | 680,779t work | 97% savings

### Jul 22, 2026
261 5:46p 🔴 CTX-ART-02 Regression: API Artifact Read Does Not Guard Against Deleted File After access_uri Lookup
262 5:48p 🔵 CTX-ART-02 API Regression Root Cause: artifact:// Retrievability Bypasses Filesystem Check
264 5:49p 🔴 CTX-ART-02 API Regression Fixed: is_file() Guard Added Before read_bytes() in Session Artifact Read Mixin
265 5:54p ✅ Full Test Suite Green After CTX-ART-01 + CTX-ART-02 + API Mixin Fix
266 5:55p 🔵 make check Fails: 7 Pre-Existing Ruff I001 Import-Sort Errors in Integration Tests
267 5:56p 🔵 Ruff I001 Pre-Existing Violations: Full File List Confirmed, All Untouched by Current Branch
268 5:57p 🔵 Ruff + mypy Pre-Existing Failures Confirmed: Branch Fixes 10 of 17 Base Violations
269 5:58p 🔵 .zcode/ Not in .gitignore; sessions.sqlite Tracked Despite Being Ignored
270 5:59p ✅ CTX-ART-02 Test Consumer Migration: All Filesystem Operations Switch from .uri to .access_uri
S167 查看本地分支并提交到 GitHub — codex/har-tool-recovery-01 分支三项功能全部验证完毕，已提交并开 PR #191 (Jul 22 at 6:04 PM)
S165 Commit and push codex/har-tool-recovery-01 branch to GitHub — three feature areas (HAR-TOOL-RECOVERY-01, CTX-ART-01, CTX-ART-02) fully validated and shipped as PR #191 (Jul 22 at 6:04 PM)
S174 Local Branch Cleanup and GitHub Push — Post PR #191 Merge Housekeeping (Jul 22 at 6:06 PM)
276 6:20p 🔵 New Work Session Initiated — Local Branch Cleanup and GitHub Push Task
S179 Remote Branch Cleanup — Delete Stale/Obsolete Branches, Preserve Active Contributor Work (Jul 22 at 6:20 PM)
277 6:31p ✅ Remote Branch Cleanup Requested Post-PR #191 Merge
279 " 🔵 Remote Branch Audit: 3 Unmerged Codex Branches Found on Origin
280 " 🔵 codex/fix-artifact-ref-tail-commas Contains Unmerged Bug Fix Not Present on Main
281 " 🔵 PR #74 (finos-vision-mcp) Open Since Jul 14 — Blocked on Real FinOS Deploy
282 6:32p 🔵 Codex FinOS Branches Authored by vinson1101, PR #74 is Draft
S182 Git status check — are there any uncommitted changes on the current branch? (Jul 22 at 6:33 PM)
283 7:01p 🔵 Only Untracked Binary sessions.sqlite Has Uncommitted Changes on Main
S186 Session title generation investigation — how does the desktop sidebar derive conversation titles? (Jul 22 at 7:01 PM)
284 7:02p 🔵 Zebra Agent Desktop UI Architecture: Tauri + React/TypeScript with Checks System
285 7:03p 🔵 Session Title Derivation: First 36 Chars of User Message, Stored in localStorage
286 " 🔵 Workspace Session Reconciliation: Local-First with Server Merge on Startup
S203 Semantic Session Title Feature — Full Implementation Complete, All Checks Green, Awaiting Commit/PR Decision (Jul 22 at 7:04 PM)
287 7:04p 🔵 No Session Title Update Endpoint Exists in Backend — Title Is Permanently Set at Creation
288 7:05p 🔵 Session Title Stored in Projection Table, Not Tasks Table; Bounded on History Write
289 7:07p 🔵 Projection Store UPSERT Updates Title — Session Domain Object Title Change Would Auto-Persist
290 " 🔵 apply_event Never Updates Session.title; No SESSION_TITLE_UPDATED EventType Exists
291 7:09p ⚖️ Semantic Session Title Feature — Full Architecture Plan Written
292 7:12p 🟣 Semantic Session Title Feature Implementation Started — Tasks Created
293 " 🔵 SessionEvent.create() Has Optional Payload Validation — Unknown Event Types Fall Through Safely
294 7:13p 🟣 SESSION_TITLE_UPDATED Event Type Implemented — Domain Layer Complete
295 7:14p 🔵 Task 2 Groundwork — Key Payload Keys and Service Pattern Confirmed
296 7:16p 🟣 Task 2 Complete + Task 3 Partially Wired — SessionTitleService Created and Injected Into Worker
297 7:17p 🟣 Task 3 Complete — finalize_execution Wired to Call SessionTitleService After Memory Extraction
298 7:18p 🟣 Task 4 Complete + Task 5 Begun — Frontend Sync useEffect Landed, Projection Test Added
300 7:24p 🔵 Session Title Feature Files Pass mypy Type Check
301 7:25p 🔵 SESSION_TITLE_UPDATED Payload Contract: Auto-Strips Whitespace, Rejects Blank Titles
S207 Semantic Session Title Feature — Fully Shipped: Commit dfc04ca5, Branch feat/semantic-session-title, PR #192 Opened (Jul 22 at 7:25 PM)
302 7:26p ✅ Feature Branch Created and Files Staged for Semantic Session Title
303 7:27p 🟣 Semantic Session Title Feature Committed and PR #192 Opened
S213 Desktop UI Live Preview — Zebra Agent Desktop App Launched for Visual Inspection, Awaiting UI Change Request (Jul 22 at 7:29 PM)
304 7:32p 🔵 Desktop UI Component Hierarchy Mapped — CodexWorkspace as Top-Level Shell
305 " 🔵 Vite Dev Server Port Mismatch — Configured 1420, Running on 5173/5174
306 " 🔵 Zebra Desktop App Not Running — Ports 5173/5174 Belong to Other Projects
307 7:33p ✅ Zebra Desktop Vite Dev Server Started on Port 1420
330 8:12p 🔵 Publisher Platform Workspace vs Chat Differentiation — Evaluation Requested
332 8:13p 🔵 Zebra Agent Desktop UI — Workspace vs Chat Architecture Mapped
S229 Workspace home page differentiation design — Plan A approval checkpoint for four-cell execution environment card UI component (Jul 22 at 8:20 PM)
383 9:21p 🟣 Tool Calls Proposed — Animated Label + Collapsible Panel UI Request
384 " 🔵 Tool Call Proposed Event — Codebase Location Map
385 9:22p 🔵 SessionExecutionTrace Component — Tool Call Rendering Architecture
386 9:23p 🔵 "Tool calls proposed." Text — Backend-Injected Placeholder, Not Frontend Label
400 10:00p 🔵 Zebra Agent Desktop — Branch Clean, No Uncommitted Changes
401 10:01p 🔵 Zebra Agent Makefile Targets and API Architecture Confirmed
402 10:02p 🔵 Zebra Agent Default SQLite Database Path Confirmed
403 10:04p 🔵 Zebra Agent API Server Health Endpoint Response Confirmed
405 10:05p 🔵 Zebra Agent UI Connected to Local Runtime — Existing Tasks Surfaced

Access 681k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>

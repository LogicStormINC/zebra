# Progress Log

## 2026-08-10 ZNX-GOALPLAN-01 Goal/Plan v1 lifecycle

- started red-first from exact Zebra base `0a81c6d` on
  `codex/znx-goal-plan-v1`, then combined cleanly with Gate 2 `aa8c4d5`
- reused the existing Stable Task, `SessionPlan`, `agent.plan`, `PLAN_UPDATED`,
  and `Session.task_plan` paths; root Goal remains stable while the latest Plan
  persists across continuation, retry, suspend/resume, reconstruction, and rollover
- normal completion now receives one bounded Plan-closing opportunity and then
  suspends with `task_plan_incomplete` if pending/in-progress work remains;
  cancelled/closed Plans permit but never fabricate Goal completion
- deterministic WAITING_INPUT and real workspace snapshot/resume E2E paths pass;
  Goal/Plan plus Gate 2 targeted validation is `136 passed`
- full pytest is `2085 passed, 9 failed, 9 skipped`, matching the untouched
  exact-base failure set; release eval is `10/10`, changed-path Ruff/compileall
  and diff-check pass, and full static/file-size findings are inherited
- FinOS compatibility smoke is `23 passed` across Stable Task follow-up,
  clarification, retry/resume, WAITING_INPUT, public conversation, and model selection
- real dual-repository Gate 2 E2E is `1 passed` across Review v4 main/reference,
  typed reads, executed Skill provenance, candidate/save/history, and same-Task correction
- no Planner Agent, sub-agent, scheduler, finance/Review workflow, GUI, FinOS
  source, stable branch, provider, or deployment change was added

## 2026-08-02 AOR-DEF-01 governance P1 scope and size correction

- task-card `Owned paths` now explicitly names
  `apps/api/src/zebra_agent_api/agent_definition_binding.py` and
  `packages/agent-tools/src/agent_tools/skills_catalog.py`
- exact `base..HEAD` union is 42 tracked paths: 41 implementation/test/record
  paths plus `docs/AGENT_TASKS.md`; the earlier 24-file figure was only the
  `df6ac58` follow-up commit, not the cumulative union
- moved completion-evidence continuation/gating helpers into the existing
  `completion_evidence.py`; `sequential_loop.py` is now 521 lines versus 526
  at exact base (no net growth), while preserving P0 canonical validator tests
- post-split focused/API/worker/storage set: 87 passed; related set: 51 passed
  with one inherited cancellation-streaming failure; full suite: 1985 passed,
  10 failed, 9 skipped, with the same exact-base failure set
- changed-path Ruff, compileall, and diff-check passed; file-size gate remains
  11 inherited violations, including `sequential_loop.py` at 521/500

## 2026-08-02 AOR-DEF-01 P0 validator evidence trust correction

- red reproduced the real `record_tool_result` conflict: one successful tool
  event carried `validator_result.passed=false` and `validator_outcome=passed`,
  incorrectly satisfying the completion contract
- canonicalized validator outcome at successful emission; evaluator now reads
  only linked harness `TESTS_COMPLETED` evidence with consistent passed/failed
  fields, while failed/rejected/cancelled/untrusted sources fail closed
- P0 trust set: 6 passed; current focused/API/worker/storage set: 87 passed;
  related set: 51 passed with one inherited cancellation-streaming failure
- full suite: 1985 passed, 10 failed, 9 skipped; same exact-base failure set;
  make sync, focused Ruff, compileall, and diff-check passed
- full Ruff retains 7 inherited findings; make check retains 11 inherited
  file-size violations; no push, merge, deploy, or configuration change

## 2026-08-02 AOR-DEF-01 review follow-up

- closed identity injection, failed-validator evidence, default completion
  bypass, continuation evidence/capability bypass, trusted skill scope/state,
  and mutable skill-content drift on the existing branch
- bound continuation evaluation to durable successful events; API-generated
  skill context digests are rechecked by worker recovery and handoff paths
- focused follow-up tests: 70 passed; full suite: 1979 passed, 10 failed,
  9 skipped, with the same inherited ten failures
- API/worker/storage continuation set: 105 passed; one inherited worker
  cancellation-streaming failure remains
- make sync, focused Ruff, compileall, and diff-check passed; size gate remains
  the same 11 inherited violations and make check stops there

## 2026-08-02 AOR-DEF-01 AgentDefinition And Completion Evidence Contract

- claimed the narrow provider-neutral slice from exact base
  `c5b814500bbeebea0d4a0307f9a58c903bd5320f` on
  `codex/agent-definition-completion-contract-20260802`; no deployment,
  upstream synchronization, provider configuration, or real-data changes
- added versioned AgentDefinition identity/context/capability/policy metadata,
  typed evidence matching, one bounded missing-evidence observation, and
  suspend-on-repeat/budget behavior while preserving legacy no-definition flow
- propagated the definition through API, TaskPrepared, workspace SQLite,
  recovery, rollover/handoff, and trusted skill-catalog resolution; malformed,
  unknown, out-of-scope, or incompatible inputs fail closed
- red first failed on the missing core definition module; after `make sync`,
  focused contract/persistence/context/API/handoff tests are `24 passed`,
  relevant regressions are `59 passed`, and full eval is `10/10`
- exact-base full pytest is `1937 passed, 10 failed, 9 skipped`; development
  full pytest is `1951 passed, 10 failed, 9 skipped` with the same ten failures;
  inherited Ruff/mypy/file-size findings are recorded in the development
  version document

## 2026-07-28 CTX-MEM-01 Context Continuity And Governed Recall

- audited GitHub issue `#197` against the runtime path and found three real gaps:
  no exact multi-turn tail guarantee, terminal classification after persistent
  context overflow, and recency-only confirmed-memory recall
- compared official Codex/OpenAI, Claude, Pi Agent and Hermes behavior and
  recorded the Zebra-specific v1.1 architecture before runtime changes
- preserved the latest three real user turns and complete tool groups, rendered
  middle history from the existing ContextCapsule, and added one stricter retry
  from original history before recoverable suspension
- reused MemoryReviewService to auto-confirm only reconstructable, low-risk,
  conflict-free candidates and retained all uncertain candidates for review
- added repo-scoped SQLite FTS5 recall with deterministic fallback, stable-rule
  lane, expiry/deduplication checks and a token budget
- validation: `63 passed` focused; changed-file Ruff passed; relevant Mypy passed
  over `158` source files; release eval `10/10`; full suite `1747 passed, 8
  skipped, 9 failed`, with all nine failures reproduced on untouched `main`
- `make check` remains blocked only by inherited 561/500 and 505/500 file-size
  violations outside the task; all task source files remain below 500 lines
- committed the owned implementation as `752a3154`, pushed
  `codex/issue-197-context-memory-continuity`, and opened PR `#198` with
  `Closes #197`; merge remains a maintainer action
- GitHub Actions run `30332213200` created seven zero-step failures; the Backend
  quality check annotation says the jobs were not started because account
  payments failed or the spending limit must be increased. This is an external
  billing gate, not a code/test result.

## 2026-07-27 FINOS-RT-04 GitHub Review Snapshot

- registered `FINOS-RT-04` for `codex/finos-runtime-alignment`
- restored Zebra-owned JPEG/PNG Task attachment ingress and exact MiniMax Task
  workspace scoping
- added a short-lived Task-scoped FinOS grant and exactly eight read-only
  business tools; no FinOS write tool or database credential is exposed
- moved the real broker screenshot and temporary env out of the repository
  before staging
- fixed `Dockerfile.finos` defaults so UID/GID `999:999` writes the SQLite
  database and Task workspaces only under the two prepared volume paths
- focused tests pass; external FinOS staging records real image, eight-tool and
  zero-Core-write acceptance
- closed this branch's `task_api.py`/`settings.py` size violations, 13 MCP Mypy
  errors, and four MiniMax Ruff line-length errors; 81 focused/provider and
  settings-contract tests pass
- current `uv run pytest -q -p no:cacheprovider` is `1792 passed, 9 failed, 8
  skipped`, matching `origin/main` with no FinOS-focused regression: eight
  existing functional failures plus the existing file-size test. Main also has
  two file-size, 13 Ruff, and four Mypy findings; stopped at Draft status
  because `make check`, CI jobs blocked by the billing/spending limit,
  fresh-container, and authenticated private-network/TLS gates remain open;
  details are in
  `docs/FinOS_Runtime_Integration_Status_2026-07-27.md`
- local container validation could not start because this workstation has no
  `docker` CLI; the unit-level writable-path contract passed

## 2026-07-19 WEB-UX-01 Trusted Local Read-Only Web Auto Execution

- registered and claimed `WEB-UX-01` on
  `codex/web-ux-01-trusted-local-auto-web`
- changed authorized `web.fetch` and configured `web.search` routes from
  per-call approval to direct bounded execution
- enabled the existing `full-trusted-local` network profile for public Web
  Gateway routing and made it the new local Desktop launch default
- added a one-time Desktop migration from the previously persisted `none`
  default; the local API also normalizes stale or explicit client profiles to
  the operator-selected trusted authority
- retained API/core `none` defaults, exact allowlist checks, Web Gateway safety,
  MCP approval, and side-effecting tool policy
- focused validation passed: 57 backend tests, Desktop launch check, TypeScript,
  and Vite production build
- full validation passed: `1505 passed, 5 skipped`; file-size, Ruff, strict Mypy
  over `417` source files, `8/8` release Evals, every Desktop check, and real
  Chromium `8/8`
- an initial aggregate Desktop check inherited Node 20 and failed before running
  TypeScript; rerunning through the repository's Volta-pinned Node 22.17.0
  completed every check successfully
- follow-up local-runtime repair derives effective `full-trusted-local` authority
  for API/CLI/Worker execution, including old Tasks and automatic Segments, and
  removes approval pauses for local command and MCP calls while retaining hard
  validation, workspace, Gateway, Runtime, and audit boundaries
- centralized that derivation in the Agent Security network-profile resolver so
  API, CLI, Worker, recovery, and automatic Segment paths cannot drift apart
- local Web transports now honor the macOS system HTTPS proxy in trusted mode;
  direct and all non-local paths retain public-address DNS preflight
- real regression on the original Task `ff198e19-9f46-42d0-b2bd-4d64e6166e67`
  completed `web.fetch` against OpenAI `robots.txt` without approval; separate
  `/news/` 403 and RSS size-limit results were correctly reported as transport
  failures rather than Policy denials
- real Zhipu regression proved Policy `allow` and recoverable completion, then
  exposed and fixed empty failed-tool observations so the next model call sees
  the actual TLS `reason/detail` instead of inventing an allowlist explanation
- final validation passed: `101` focused tests, `1515 passed, 7 skipped` full
  suite, file-size `899`, Ruff, strict Mypy over `418` files, `8/8` release
  Evals, all Desktop checks/build, and real Chromium `8/8`
- real Zhipu Task `91fbddb3-d608-4e7c-a15b-694d6e55c9ae` recorded Policy
  `allow`, completed after an upstream expired-TLS failure, and the next model
  call accurately consumed the structured failure observation

## 2026-07-19 UI-COMPOSER-01 Compact Conversation Composer

- claimed `UI-COMPOSER-01` in an isolated worktree on
  `codex/ui-composer-compact-01`
- removed the separate idle/thread minimum-height contracts and reused one
  compact Ant Design X `Sender` surface
- moved the existing attachment action into the bottom toolbar, kept one-row
  default input growth bounded to six rows, and preserved all launch controls
- added `check:composer-layout` and passed all `21` deterministic Desktop checks
- passed TypeScript, Vite production build, file-size, Ruff, strict Mypy, and
  release Eval gates
- verified real Chromium desktop, idle, and `390px` mobile rendering with no
  horizontal overflow or console warnings
- merged PR `#174` after all seven required Quality jobs passed, including
  Desktop browser regressions and Packaged Tauri Runtime E2E

## 2026-07-19 CTX-SEG-01 Stable Task And Internal Segments

- implemented stable Task/Execution Segment domain and SQLite projections with
  lazy migration of existing Session lineage
- made Task active-Segment CAS atomic with the existing handoff transaction and
  retained idempotency, authority narrowing, drift, outbox, and no-replay checks
- added public Task API, monotonic cross-Segment read/tail stream, active-Segment
  routing, internal lifecycle/lineage routes, and hidden child Session reads
- moved Desktop core traffic to `/tasks`, removed terminal fallback session
  creation, and retained one conversation identity across automatic rollover
- validated completed follow-up with text attachment, failed recovery, unsafe
  boundary pause, migration, concurrent successor exclusion, and stream filtering
- fixed CI-discovered cancellation rendering and projected internal-Segment
  approvals back to the stable Task ID while retaining the internal approval ID
- limited inherited workspace drift validation to the first child attempt so
  legitimate runtime setup does not reject later approval continuations
- validation: `make test` (`1501 passed, 7 skipped`), `make check`, all Desktop
  `check:*` scripts, production build, and Playwright Chromium (`7 passed`)

## 2026-07-05 UI Desktop Workspace Bootstrap

- created `UI/desktop` as a dedicated frontend workspace for future Zebra Agent operator UI development
- scaffolded a minimal `Tauri + React + Tailwind CSS + TanStack Query + Ant Design + Ant Design X` desktop shell
- installed frontend dependencies with `pnpm install`
- verified frontend bundling with `pnpm build`
- added `UI/desktop/.cargo-home/config.toml` plus Tauri scripts pinned to local `CARGO_HOME` so Rust artifacts stay local to the UI workspace
- validation blocker: local `cargo check` still inherits a broken global `~/.cargo/config.toml` mirror replacement to `ustc`, so Tauri Rust dependency fetch is not yet verifiable on this machine without fixing the global Cargo source
- replaced the static landing page with a live operator surface backed by TanStack Query and typed API adapters
- wired frontend reads for health, approvals, session detail, event replay, repo memory inventory, and cross-scope memory overview
- wired frontend write for `POST /sessions`, with returned `session_id` promoted into the active inspector state
- validated the integrated frontend again with `cd UI/desktop && pnpm build`
- expanded the UI to cover approval decisions, session suspend or resume or cancel controls, workspace diff inspection, artifact list/detail/content inspection, and delivery audit reads
- validated the expanded UI again with `cd UI/desktop && pnpm build`
- validation note: `pnpm build` still emits a Vite warning because this environment resolves to `Node 20.10.0`, but the build completes successfully
- expanded the UI again to cover session message append, commit, pull-request, and direct candidate-memory confirm or expire actions
- validated the expanded UI again with `cd UI/desktop && pnpm build`
- added a dedicated memory queue operator card covering preview, queue sweep, and bulk review across session, user, and tenant scopes
- added a companion scope memory snapshot card so operators can read session, user, or tenant inventory plus queue summary before cross-scope review actions
- added session artifact prune control to the desktop inspector so operators can close the loop from artifact inspection to lifecycle writeback
- added selected-approval detail readback to the desktop control panel so approval actions are paired with route, target, scope, and policy context
- added a compact memory governance card that reads backlog totals and highest-priority action hints for the active session scopes
- split `UI/desktop` type and API foundations into smaller modules, then expanded the governance card to include pressure and escalation signals
- expanded the governance card again to include follow-up windows and overdue flags for the active scopes
- expanded the governance card again to include overdue age buckets and overdue type or visibility rollups
- expanded the governance card again to include overdue trend signals and overdue intervention hints
- split the governance surface into a dedicated query hook plus smaller presentation panels so the card stays under the repository file-length target
- split overdue memory frontend types into a dedicated module before the next governance slice pushed `memory.ts` past the repository target length
- expanded the governance card again to include overdue escalation lanes, recovery paths, resolution checkpoints, and resolution outcomes
- validated the expanded governance surface again with `cd UI/desktop && pnpm build`
- expanded the governance card again to include overdue closure decisions, archive recommendations, retention guidance, and retention windows
- split the governance scope list into a dedicated component so the panel can keep growing without crossing the repository target length
- validated the expanded governance surface again with `cd UI/desktop && pnpm build`

## 2026-07-05 Phase 101 Scoped Queue Sweep Filtered Preview Controls

- claimed `P101-MEM-01` on `codex/p101-mem-01-scoped-queue-sweep-filtered-preview-controls`
- added one minimal narrowing filter to scoped queue-sweep preview responses for repo-session, user, and tenant memory so operators can inspect a reduced target set before execution
- kept the implementation side-effect free by filtering only preview payloads and leaving queue-sweep review execution semantics unchanged
- completed `P101-MEM-01` with API and CLI `memory_type` preview filtering plus preview and review contract regression coverage
- completed `P101-CLOSE-01` with Phase 101 acceptance evidence and synchronized next-priority state
- validation:
  - `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_payloads.py apps/api/src/zebra_agent_api/session_memory_control.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_parser.py apps/cli/src/zebra_agent_cli/memory_review_write.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-05 Phase 100 Scoped Queue Sweep Target Explanations

- claimed `P100-MEM-01` on `codex/p100-mem-01-scoped-queue-sweep-target-explanations`
- added per-record target reasons and aggregate explanation counts to scoped queue-sweep preview responses for repo-session, user, and tenant memory so operators can inspect why each record is in the current target set
- kept the implementation side-effect free by layering explanation metadata on top of the existing preview target set rather than introducing a second preview selection path
- completed `P100-MEM-01` with API and CLI explanation metadata plus preview and review contract regression coverage
- completed `P100-CLOSE-01` with Phase 100 acceptance evidence and synchronized next-priority state
- validation:
  - `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/cli/src/zebra_agent_cli/memory_review_write.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-05 Phase 99 Scoped Queue Sweep Dry-Run Summaries

- claimed `P99-MEM-01` on `codex/p99-mem-01-scoped-queue-sweep-dry-run-summaries`
- added projected outcome summaries to scoped queue-sweep preview responses for repo-session, user, and tenant memory so operators can inspect target size and projected post-review shape before execution
- kept the implementation side-effect free by reusing the current preview target set and layering only additive projected status plus per-type summary metadata on top
- completed `P99-MEM-01` with API and CLI projected preview metadata plus preview and review contract regression coverage
- completed `P99-CLOSE-01` with Phase 99 acceptance evidence and synchronized next-priority state
- validation:
  - `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/cli/src/zebra_agent_cli/memory_review_write.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-05 Phase 98 Scoped Queue Sweep Preview Controls

- claimed `P98-MEM-01` on `codex/p98-mem-01-scoped-queue-sweep-preview-controls`
- added side-effect-free scoped queue-sweep preview controls for repo-session, user, and tenant memory so operators can inspect the exact target set before confirm or expire execution
- kept the implementation local-first by reusing the current queue query path and the same repo-session `source_session_id` narrowing already used by queue sweep execution
- completed `P98-MEM-01` with API and CLI preview entrypoints plus a dedicated API or CLI contract matrix
- completed `P98-CLOSE-01` with Phase 98 acceptance evidence and synchronized next-priority state
- validation:
  - `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/memory_review_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_parser.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-05 Phase 97 Scoped Queue Sweep Review Controls

- claimed `P97-MEM-01` on `codex/p97-mem-01-scoped-queue-sweep-review-controls`
- added scoped queue-sweep review controls for repo-session, user, and tenant memory without introducing a second review state machine
- kept the implementation local-first by deriving the current candidate set from existing scoped queue queries and reusing current bulk review semantics
- completed `P97-MEM-01` with API and CLI queue-sweep review entrypoints plus a dedicated API or CLI contract matrix
- completed `P97-CLOSE-01` with Phase 97 acceptance evidence and synchronized next-priority state
- validation:
  - `uv run pytest tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/memory_review_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_parser.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-05 Phase 96 Memory Overdue Retention Breach Follow-Through Verification Outcomes

- claimed `P96-MEM-01` on `codex/p96-mem-01-memory-overdue-retention-breach-follow-through-verification-outcomes`
- added one additive overdue-retention-breach-follow-through-verification-outcome layer on top of the current overdue-retention-breach-follow-through-verification-state read path
- kept the implementation local-first by deriving verification outcomes from current overdue breach follow-through-verification-state evidence instead of adding verification result persistence
- completed `P96-MEM-01` with per-scope overdue retention breach follow-through verification outcomes and cross-scope highest-priority overdue-retention-breach-follow-through-verification-outcome rollups across API and CLI
- completed `P96-CLOSE-01` with Phase 96 acceptance evidence and a synchronized closeout marker that the overdue-retention-breach follow-through sublane is complete
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_follow_through_verification_outcomes.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_verification_outcomes.py tests/test_memory_overdue_retention_breach_follow_through_verification_outcomes_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_follow_through_verification_outcomes.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_verification_outcomes.py tests/test_memory_overdue_retention_breach_follow_through_verification_outcomes_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-05 Phase 95 Memory Overdue Retention Breach Follow-Through Verification States

- claimed `P95-MEM-01` on `codex/p95-mem-01-memory-overdue-retention-breach-follow-through-verification-states`
- added one additive overdue-retention-breach-follow-through-verification-state layer on top of the current overdue-retention-breach-follow-through-completion-state read path
- kept the implementation local-first by deriving verification states from current overdue breach follow-through-completion-state evidence instead of adding verification persistence
- completed `P95-MEM-01` with per-scope overdue retention breach follow-through verification states and cross-scope highest-priority overdue-retention-breach-follow-through-verification rollups across API and CLI
- completed `P95-CLOSE-01` with Phase 95 acceptance evidence and Phase 96 planning for overdue retention breach follow-through verification outcomes
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_follow_through_verification_states.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_verification_states.py tests/test_memory_overdue_retention_breach_follow_through_verification_states_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_follow_through_verification_states.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_verification_states.py tests/test_memory_overdue_retention_breach_follow_through_verification_states_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`
## 2026-07-05 Phase 94 Memory Overdue Retention Breach Follow-Through Completion States

- claimed `P94-MEM-01` on `codex/p94-mem-01-memory-overdue-retention-breach-follow-through-completion-states`
- added one additive overdue-retention-breach-follow-through-completion-state layer on top of the current overdue-retention-breach-follow-through-outcome read path
- kept the implementation local-first by deriving completion states from current overdue breach follow-through-outcome evidence instead of adding completion persistence
- completed `P94-MEM-01` with per-scope overdue retention breach follow-through completion states and cross-scope highest-priority overdue-retention-breach-follow-through-completion rollups across API and CLI
- completed `P94-CLOSE-01` with Phase 94 acceptance evidence and Phase 95 planning for overdue retention breach follow-through verification states
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_follow_through_completion_states.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_completion_states.py tests/test_memory_overdue_retention_breach_follow_through_completion_states_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_follow_through_completion_states.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_completion_states.py tests/test_memory_overdue_retention_breach_follow_through_completion_states_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`
## 2026-07-05 Phase 93 Memory Overdue Retention Breach Follow-Through Outcomes

- claimed `P93-MEM-01` on `codex/p93-mem-01-memory-overdue-retention-breach-follow-through-outcomes`
- added one additive overdue-retention-breach-follow-through-outcome layer on top of the current overdue-retention-breach-follow-through-mode read path
- kept the implementation local-first by deriving follow-through outcomes from current overdue breach follow-through-mode evidence instead of adding completion state
- completed `P93-MEM-01` with per-scope overdue retention breach follow-through outcomes and cross-scope highest-priority overdue-retention-breach-follow-through-outcome rollups across API and CLI
- completed `P93-CLOSE-01` with Phase 93 acceptance evidence and Phase 94 planning for overdue retention breach follow-through completion states
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_follow_through_outcomes.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_outcomes.py tests/test_memory_overdue_retention_breach_follow_through_outcomes_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_follow_through_outcomes.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_outcomes.py tests/test_memory_overdue_retention_breach_follow_through_outcomes_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-04 Phase 92 Memory Overdue Retention Breach Follow-Through Modes

- claimed `P92-MEM-01` on `codex/p92-mem-01-memory-overdue-retention-breach-follow-through-modes`
- added one additive overdue-retention-breach-follow-through-mode layer on top of the current overdue-retention-breach-owner-target read path
- kept the implementation local-first by deriving follow-through modes from current overdue breach owner-target evidence instead of adding workflow state
- completed `P92-MEM-01` with per-scope overdue retention breach follow-through modes and cross-scope highest-priority overdue-retention-breach-follow-through rollups across API and CLI
- completed `P92-CLOSE-01` with Phase 92 acceptance evidence and Phase 93 planning for overdue retention breach follow-through outcomes
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_follow_through_modes.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_modes.py tests/test_memory_overdue_retention_breach_follow_through_modes_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_follow_through_modes.py tests/cli/test_cli_memory_overdue_retention_breach_follow_through_modes.py tests/test_memory_overdue_retention_breach_follow_through_modes_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 91 Memory Overdue Retention Breach Owner Targets

- claimed `P91-MEM-01` on `codex/p91-mem-01-memory-overdue-retention-breach-owner-targets`
- added one additive overdue-retention-breach-owner-target layer on top of the current overdue-retention-breach-lane read path
- kept the implementation local-first by deriving owner targets from current overdue breach lane evidence instead of adding identity state
- completed `P91-MEM-01` with per-scope overdue retention breach owner targets and cross-scope highest-priority overdue-retention-breach-owner-target rollups across API and CLI
- completed `P91-CLOSE-01` with Phase 91 acceptance evidence and Phase 92 planning for overdue retention breach follow-through modes
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_owner_targets.py tests/cli/test_cli_memory_overdue_retention_breach_owner_targets.py tests/test_memory_overdue_retention_breach_owner_targets_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_owner_targets.py tests/cli/test_cli_memory_overdue_retention_breach_owner_targets.py tests/test_memory_overdue_retention_breach_owner_targets_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 90 Memory Overdue Retention Breach Lanes

- claimed `P90-MEM-01` on `codex/p90-mem-01-memory-overdue-retention-breach-lanes`
- added one additive overdue-retention-breach-lane layer on top of the current overdue-retention-breach-action read path
- kept the implementation local-first by deriving breach lanes from current overdue breach action evidence instead of adding ownership state
- completed `P90-MEM-01` with per-scope overdue retention breach lanes and cross-scope highest-priority overdue-retention-breach-lane rollups across API and CLI
- completed `P90-CLOSE-01` with Phase 90 acceptance evidence and Phase 91 planning for overdue retention breach owner targets
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_lanes.py tests/cli/test_cli_memory_overdue_retention_breach_lanes.py tests/test_memory_overdue_retention_breach_lanes_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_lanes.py tests/cli/test_cli_memory_overdue_retention_breach_lanes.py tests/test_memory_overdue_retention_breach_lanes_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 89 Memory Overdue Retention Breach Actions

- claimed `P89-MEM-01` on `codex/p89-mem-01-memory-overdue-retention-breach-actions`
- added one additive overdue-retention-breach-action layer on top of the current overdue-retention-breach-aging read path
- kept the implementation local-first by deriving breach actions from current overdue breach age evidence instead of adding workflow state
- completed `P89-MEM-01` with per-scope overdue retention breach actions and cross-scope highest-priority overdue-retention-breach-action rollups across API and CLI
- completed `P89-CLOSE-01` with Phase 89 acceptance evidence and Phase 90 planning for overdue retention breach lanes
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_actions.py tests/cli/test_cli_memory_overdue_retention_breach_actions.py tests/test_memory_overdue_retention_breach_actions_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_actions.py tests/cli/test_cli_memory_overdue_retention_breach_actions.py tests/test_memory_overdue_retention_breach_actions_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 88 Memory Overdue Retention Breach Aging

- claimed `P88-MEM-01` on `codex/p88-mem-01-memory-overdue-retention-breach-aging`
- added one additive overdue-retention-breach-aging layer on top of the current overdue-retention-breach read path
- kept the implementation local-first by deriving breach aging from current overdue evidence instead of adding scheduler state
- completed `P88-MEM-01` with per-scope overdue retention breach aging buckets and cross-scope highest-priority overdue-retention-breach-aging rollups across API and CLI
- completed `P88-CLOSE-01` with Phase 88 acceptance evidence and Phase 89 planning for overdue retention breach actions
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breach_aging.py tests/cli/test_cli_memory_overdue_retention_breach_aging.py tests/test_memory_overdue_retention_breach_aging_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_aging.py tests/cli/test_cli_memory_overdue_retention_breach_aging.py tests/test_memory_overdue_retention_breach_aging_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 87 Memory Overdue Retention Breaches

- claimed `P87-MEM-01` on `codex/p87-mem-01-memory-overdue-retention-breaches`
- added one additive overdue-retention-breach layer on top of the current overdue-retention-window read path
- kept the implementation local-first by deriving breach severity from current overdue evidence instead of adding scheduler state
- completed `P87-MEM-01` with per-scope overdue retention breaches, breach due-at timestamps, and cross-scope highest-priority overdue-retention-breach rollups across API and CLI
- completed `P87-CLOSE-01` with Phase 87 acceptance evidence and Phase 88 planning for overdue retention breach aging
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_breaches.py tests/cli/test_cli_memory_overdue_retention_breaches.py tests/test_memory_overdue_retention_breaches_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breaches.py tests/cli/test_cli_memory_overdue_retention_breaches.py tests/test_memory_overdue_retention_breaches_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 86 Memory Overdue Retention Windows

- claimed `P86-MEM-01` on `codex/p86-mem-01-memory-overdue-retention-windows`
- added one additive overdue-retention-window layer on top of the current overdue-retention-guidance read path
- kept the implementation local-first by deriving revisit windows from current overdue evidence instead of adding scheduler state
- completed `P86-MEM-01` with per-scope overdue retention windows, due-at timestamps, and cross-scope highest-priority overdue-retention-window rollups across API and CLI
- completed `P86-CLOSE-01` with Phase 86 acceptance evidence and Phase 87 planning for overdue retention breaches
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_windows.py tests/cli/test_cli_memory_overdue_retention_windows.py tests/test_memory_overdue_retention_windows_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_windows.py tests/cli/test_cli_memory_overdue_retention_windows.py tests/test_memory_overdue_retention_windows_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 85 Memory Overdue Retention Guidance

- claimed `P85-MEM-01` on `codex/p85-mem-01-memory-overdue-retention-guidance`
- added one additive overdue-retention-guidance layer on top of the current overdue-archive-recommendation read path
- kept the implementation local-first by deriving retention posture from current overdue evidence instead of adding workflow state
- completed `P85-MEM-01` with per-scope overdue retention guidance, retention buckets, and cross-scope highest-priority overdue-retention rollups across API and CLI
- completed `P85-CLOSE-01` with Phase 85 acceptance evidence and Phase 86 planning for overdue retention windows
- validation:
  - `uv run pytest tests/api/test_memory_overdue_retention_guidance.py tests/cli/test_cli_memory_overdue_retention_guidance.py tests/test_memory_overdue_retention_guidance_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_guidance.py tests/cli/test_cli_memory_overdue_retention_guidance.py tests/test_memory_overdue_retention_guidance_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 84 Memory Overdue Archive Recommendations

- claimed `P84-MEM-01` on `codex/p84-mem-01-memory-overdue-archive-recommendations`
- added one additive overdue-archive-recommendation layer on top of the current overdue-closure-decision read path
- kept the implementation local-first by deriving archive posture from current overdue evidence instead of adding workflow state
- completed `P84-MEM-01` with per-scope overdue archive recommendations and cross-scope highest-priority overdue-archive rollups across API and CLI
- completed `P84-CLOSE-01` with Phase 84 acceptance evidence and Phase 85 planning for overdue retention guidance
- validation:
  - `uv run pytest tests/api/test_memory_overdue_archive_recommendations.py tests/cli/test_cli_memory_overdue_archive_recommendations.py tests/test_memory_overdue_archive_recommendations_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_archive_recommendations.py tests/cli/test_cli_memory_overdue_archive_recommendations.py tests/test_memory_overdue_archive_recommendations_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 83 Memory Overdue Closure Decisions

- claimed `P83-MEM-01` on `codex/p83-mem-01-memory-overdue-closure-decisions`
- added one additive overdue-closure-decision layer on top of the current overdue-resolution-outcome read path
- kept the implementation local-first by deriving final handling decisions from current overdue evidence instead of adding workflow state
- completed `P83-MEM-01` with per-scope overdue closure decisions and cross-scope highest-priority overdue-closure rollups across API and CLI
- completed `P83-CLOSE-01` with Phase 83 acceptance evidence and Phase 84 planning for overdue archive recommendations
- validation:
  - `uv run pytest tests/api/test_memory_overdue_closure_decisions.py tests/cli/test_cli_memory_overdue_closure_decisions.py tests/test_memory_overdue_closure_decisions_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_closure_decisions.py tests/cli/test_cli_memory_overdue_closure_decisions.py tests/test_memory_overdue_closure_decisions_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 82 Memory Overdue Resolution Outcomes

- claimed `P82-MEM-01` on `codex/p82-mem-01-memory-overdue-resolution-outcomes`
- added one additive overdue-resolution-outcome layer on top of the current overdue-resolution-checkpoint read path
- kept the implementation local-first by deriving result states from current overdue evidence instead of adding workflow state
- completed `P82-MEM-01` with per-scope overdue resolution outcomes and cross-scope highest-priority overdue-resolution-outcome rollups across API and CLI
- completed `P82-CLOSE-01` with Phase 82 acceptance evidence and Phase 83 planning for overdue closure decisions
- validation:
  - `uv run pytest tests/api/test_memory_overdue_resolution_outcomes.py tests/cli/test_cli_memory_overdue_resolution_outcomes.py tests/test_memory_overdue_resolution_outcomes_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_resolution_outcomes.py tests/cli/test_cli_memory_overdue_resolution_outcomes.py tests/test_memory_overdue_resolution_outcomes_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 81 Memory Overdue Resolution Checkpoints

- claimed `P81-MEM-01` on `codex/p81-mem-01-memory-overdue-resolution-checkpoints`
- added one additive overdue-resolution-checkpoint layer on top of the current overdue-recovery-path read path
- kept the implementation local-first by deriving closure checkpoints from current overdue evidence instead of adding workflow state
- completed `P81-MEM-01` with per-scope overdue resolution checkpoints and cross-scope highest-priority overdue-resolution rollups across API and CLI
- completed `P81-CLOSE-01` with Phase 81 acceptance evidence and Phase 82 planning for overdue resolution outcomes
- validation:
  - `uv run pytest tests/api/test_memory_overdue_resolution_checkpoints.py tests/cli/test_cli_memory_overdue_resolution_checkpoints.py tests/test_memory_overdue_resolution_checkpoints_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_resolution_checkpoints.py tests/cli/test_cli_memory_overdue_resolution_checkpoints.py tests/test_memory_overdue_resolution_checkpoints_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 80 Memory Overdue Recovery Paths

- claimed `P80-MEM-01` on `codex/p80-mem-01-memory-overdue-recovery-paths`
- added one additive overdue-recovery-path layer on top of the current overdue-escalation-lane read path
- kept the implementation local-first by deriving recovery planning from current overdue evidence instead of adding workflow state
- completed `P80-MEM-01` with per-scope overdue recovery paths and cross-scope highest-priority overdue-recovery rollups across API and CLI
- completed `P80-CLOSE-01` with Phase 80 acceptance evidence and Phase 81 planning for overdue resolution checkpoints
- validation:
  - `uv run pytest tests/api/test_memory_overdue_recovery_paths.py tests/cli/test_cli_memory_overdue_recovery_paths.py tests/test_memory_overdue_recovery_paths_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_recovery_paths.py tests/cli/test_cli_memory_overdue_recovery_paths.py tests/test_memory_overdue_recovery_paths_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 79 Memory Overdue Escalation Lanes

- claimed `P79-MEM-01` on `codex/p79-mem-01-memory-overdue-escalation-lanes`
- added one additive overdue-escalation-lane layer on top of the current overdue-intervention read path
- kept the implementation local-first by deriving handling lanes from current overdue evidence instead of adding workflow state
- completed `P79-MEM-01` with per-scope overdue escalation lanes and cross-scope highest-priority overdue-escalation rollups across API and CLI
- completed `P79-CLOSE-01` with Phase 79 acceptance evidence and Phase 80 planning for overdue recovery paths
- validation:
  - `uv run pytest tests/api/test_memory_overdue_escalation_lanes.py tests/cli/test_cli_memory_overdue_escalation_lanes.py tests/test_memory_overdue_escalation_lanes_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_escalation_lanes.py tests/cli/test_cli_memory_overdue_escalation_lanes.py tests/test_memory_overdue_escalation_lanes_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 78 Memory Overdue Intervention Hints

- claimed `P78-MEM-01` on `codex/p78-mem-01-memory-overdue-intervention-hints`
- added one additive overdue-intervention layer on top of the current overdue-trend read path
- kept the implementation local-first by deriving next-step hints from current overdue evidence instead of adding workflow state
- completed `P78-MEM-01` with per-scope overdue intervention hints and cross-scope highest-priority overdue-intervention rollups across API and CLI
- completed `P78-CLOSE-01` with Phase 78 acceptance evidence and Phase 79 planning for overdue escalation lanes
- validation:
  - `uv run pytest tests/api/test_memory_overdue_intervention_hints.py tests/cli/test_cli_memory_overdue_intervention_hints.py tests/test_memory_overdue_intervention_hints_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_intervention_hints.py tests/cli/test_cli_memory_overdue_intervention_hints.py tests/test_memory_overdue_intervention_hints_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 77 Memory Overdue Trend Signals

- claimed `P77-MEM-01` on `codex/p77-mem-01-memory-overdue-trend-signals`
- added one additive overdue-trend layer on top of the current overdue-age read path
- kept the implementation local-first by deriving trend state from current overdue evidence instead of adding historical storage
- completed `P77-MEM-01` with per-scope overdue trend classification and cross-scope highest-priority overdue-trend rollups across API and CLI
- completed `P77-CLOSE-01` with Phase 77 acceptance evidence and Phase 78 planning for overdue intervention hints
- validation:
  - `uv run pytest tests/api/test_memory_overdue_trend_signals.py tests/cli/test_cli_memory_overdue_trend_signals.py tests/test_memory_overdue_trend_signals_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_trend_signals.py tests/cli/test_cli_memory_overdue_trend_signals.py tests/test_memory_overdue_trend_signals_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 76 Memory Overdue Visibility Rollups

- claimed `P76-MEM-01` on `codex/p76-mem-01-memory-overdue-visibility-rollups`
- added one additive overdue-visibility layer on top of the current overdue-age, overdue-flag, and overdue-type read path
- kept the implementation local-first by reusing the current queue inventory and existing overdue scope evidence instead of adding a new projection
- completed `P76-MEM-01` with per-scope overdue visibility counts, target-memory visibility readback, and cross-scope highest-priority overdue-visibility rollups across API and CLI
- completed `P76-CLOSE-01` with Phase 76 acceptance evidence and Phase 77 planning for overdue trend signals
- validation:
  - `uv run pytest tests/api/test_memory_overdue_visibility_rollups.py tests/cli/test_cli_memory_overdue_visibility_rollups.py tests/test_memory_overdue_visibility_rollups_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_visibility_rollups.py tests/cli/test_cli_memory_overdue_visibility_rollups.py tests/test_memory_overdue_visibility_rollups_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 75 Memory Overdue Type Rollups

- claimed `P75-MEM-01` on `codex/p75-mem-01-memory-overdue-type-rollups`
- added one additive overdue-type layer on top of the current overdue-age and overdue-flag read path
- kept the implementation local-first by reusing the current queue inventory and existing overdue scope evidence instead of adding a new projection
- completed `P75-MEM-01` with per-scope overdue memory-type counts, target-memory type readback, and cross-scope highest-priority overdue-type rollups across API and CLI
- completed `P75-CLOSE-01` with Phase 75 acceptance evidence and Phase 76 planning for overdue visibility rollups
- validation:
  - `uv run pytest tests/api/test_memory_overdue_type_rollups.py tests/cli/test_cli_memory_overdue_type_rollups.py tests/test_memory_overdue_type_rollups_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_type_rollups.py tests/cli/test_cli_memory_overdue_type_rollups.py tests/test_memory_overdue_type_rollups_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 57 Local Memory Store Foundation

- claimed `P57-MEM-01` on `codex/p57-mem-01-memory-store-foundation`
- starting the first durable memory foundation with typed core contracts and a local SQLite store
- scope is intentionally limited to derived memory persistence and query semantics; memory extraction and Redis adapters remain later tasks
- completed `P57-MEM-01` with `MemoryRecord` / `MemoryQuery`, `MemoryStorePort`, and `SQLiteMemoryStore`
- validation:
  - `uv run pytest tests/agent_core/test_memories.py tests/agent_storage/test_sqlite_memories.py`
  - `uv run ruff check packages/agent-core/src/agent_core/domain/memories.py packages/agent-core/src/agent_core/ports/memory_store.py packages/agent-storage/src/agent_storage/memories.py tests/agent_core/test_memories.py tests/agent_storage/test_sqlite_memories.py`
  - `uv run mypy packages apps`

## 2026-07-02 Phase 57 Memory Candidate Extraction

- claimed `P57-MEM-02` on `codex/p57-mem-02-memory-candidate-extraction`
- extracting deterministic `procedure` memory candidates from successful `command.run` and `tests.run` session events
- keeping this slice narrow: typed extraction service plus emitted session events, without wiring worker triggers or Redis adapters yet
- completed `P57-MEM-02` with `MemoryCandidateExtractionService` and `memory_candidate_extracted` event payload validation
- validation:
  - `uv run pytest tests/agent_core/test_memory_candidates.py tests/agent_core/test_event_contracts.py`
  - `uv run ruff check packages/agent-core/src/agent_core/application/memory_candidates.py packages/agent-core/src/agent_core/contracts/events.py packages/agent-core/src/agent_core/domain/events.py packages/agent-core/src/agent_core/application/__init__.py tests/agent_core/test_memory_candidates.py tests/agent_core/test_event_contracts.py`
  - `make check`

## 2026-07-02 Phase 57 Worker Memory Candidate Persistence

- claimed `P57-MEM-03` on `codex/p57-mem-02-memory-candidate-extraction`
- wiring completed worker sessions to persist local procedure-memory candidates and append `memory_candidate_extracted` events
- repo scope for local mode uses the resolved `workspace_root` string to avoid directory-name collisions
- completed `P57-MEM-03` by wiring `SessionExecutionService` to persist local memory candidates after `session_completed`
- validation:
  - `uv run pytest tests/worker/test_execution.py`
  - `uv run ruff check apps/worker/src/zebra_agent_worker/execution.py tests/worker/test_execution.py`
  - `make check`

## 2026-07-02 Phase 57 Session Memory Read Surface

- claimed `P57-MEM-04` on `codex/p57-mem-02-memory-candidate-extraction`
- exposing persisted session memory inventory over the local API and CLI without adding write or review semantics yet
- keeping this slice session-scoped by deriving repo scope from the persisted session workspace root
- validation:
  - `uv run pytest tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_contract_matrix.py`
  - `make check`

## 2026-07-02 Phase 57 Memory Candidate Review Controls

- claimed `P57-MEM-05` on `codex/p57-mem-02-memory-candidate-extraction`
- added the first durable operator review path for memory candidates with confirm and expire decisions
- kept the state machine intentionally narrow: only `candidate -> confirmed` and `candidate -> expired`, with `memory_review_recorded` appended onto the source session stream
- split CLI parser construction into `cli_parser.py` so `cli.py` returns below the repository hard file limit
- validation:
  - `uv run pytest tests/agent_core/test_memory_reviews.py tests/agent_core/test_event_contracts.py tests/agent_storage/test_sqlite_memories.py tests/api/test_memory_review.py tests/cli/test_cli_memory_review.py tests/test_session_memory_review_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 57 Confirmed Memory Context Injection

- claimed `P57-MEM-06` on `codex/p57-mem-02-memory-candidate-extraction`
- wired confirmed repo memory into the stable section of the local context compiler prompt
- corrected a mainline gap by routing local harness execution through `LocalContextCompiler` instead of bypassing it
- kept retrieval intentionally narrow to repo-scoped `confirmed` memory text so memory remains an additive hint, not a recovery dependency
- validation:
  - `uv run pytest tests/agent_context/test_adapter.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_runtime/test_harness_runner.py tests/agent_storage/test_sqlite_memories.py tests/api/test_api_app.py -k confirmed_memory tests/cli/test_cli_commands.py -k confirmed_memory`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 57 Confirmed Memory Ranking And Typed Prompt Labels

- claimed `P57-MEM-07` on `codex/p57-mem-02-memory-candidate-extraction`
- upgraded confirmed-memory injection from plain strings to typed inputs so prompt assembly can preserve memory semantics
- ranked repo-scoped confirmed memories by type priority, then recency, and collapsed normalized duplicates before prompt injection
- updated stable prompt labels from generic confirmed-memory numbering to type-aware titles such as `Project Rule` and `Procedure`
- validation:
  - `uv run pytest tests/agent_storage/test_sqlite_memories.py tests/agent_context/test_adapter.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_runtime/test_harness_runner.py`
  - `uv run pytest tests/api/test_api_app.py -k confirmed_memory tests/cli/test_cli_commands.py -k confirmed_memory`
  - `uv run mypy packages apps`

## 2026-07-02 Phase 57 Confirmed Memory Supersession On Review

- claimed `P57-MEM-08` on `codex/p57-mem-02-memory-candidate-extraction`
- added deterministic supersession so confirming a candidate memory retires older confirmed memories with the same scope and `memory_type`
- kept the conflict rule intentionally narrow to existing `confirmed` records and reused the existing `memory_review_recorded` event instead of adding a new review event type
- extended API and CLI review responses to report `superseded_memory_ids` while preserving success and invalid-state parity
- validation:
  - `uv run pytest tests/agent_core/test_memory_reviews.py tests/agent_core/test_event_contracts.py tests/api/test_memory_review.py tests/cli/test_cli_memory_review.py tests/test_session_memory_review_contract_matrix.py`
  - `uv run mypy packages apps`

## 2026-07-02 Phase 57 Doc-Derived Project Rule Candidate Extraction

- claimed `P57-MEM-09` on `codex/p57-mem-02-memory-candidate-extraction`
- broadened memory extraction beyond `procedure` by adding a deterministic `project_rule` candidate path on successful `files.read` of root `AGENTS.md`
- kept the extraction intentionally narrow to the explicit `Local Commands` section and skipped truncated governance reads to avoid model-authored summaries or partial-doc rules
- worker persistence now covers both tool-derived `procedure` candidates and doc-derived `project_rule` candidates
- validation:
  - `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'memory_candidate or project_rule or agents_read'`
  - `uv run mypy packages apps`

## 2026-07-02 Phase 57 Doc-Derived Architecture Fact Candidate Extraction

- claimed `P57-MEM-10` on `codex/p57-mem-02-memory-candidate-extraction`
- extended the same root `AGENTS.md` read path so one deterministic governance read can emit multiple memory candidates
- added a narrow `architecture_fact` extraction rule from the explicit package dependency boundary bullets around `agent-core`
- kept the extraction rule text literal and section-scoped instead of attempting broader module summarization
- validation:
  - `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'memory_candidate or project_rule or architecture_fact or agents_read'`
  - `uv run mypy packages apps`

## 2026-07-02 Phase 57 Explicit User Preference Candidate Extraction

- claimed `P57-MEM-11` on `codex/p57-mem-02-memory-candidate-extraction`
- added a narrow `preference` extraction path on durable `USER_MESSAGE_RECEIVED` events using the explicit `Preference:` prefix as the only accepted marker
- kept preference extraction separate from free-form task prompts so ordinary execution requests do not get promoted into repo memory
- split memory-candidate source rules into dedicated modules so file boundaries stay within the repository target size while the extraction matrix grows
- validation:
  - `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'memory_candidate or project_rule or architecture_fact or preference or agents_read'`
  - `uv run mypy packages apps`

## 2026-07-03 Phase 57 Confirmed Memory Freshness Filtering

- claimed `P57-MEM-12` on `codex/p57-mem-02-memory-candidate-extraction`
- added `as_of`-aware filtering to confirmed repo memory lookup so records with expired `expires_at` values do not enter stable prompt context
- kept API, CLI, runtime, and worker contracts unchanged by defaulting lookup time to the current UTC timestamp
- validation:
  - `uv run pytest tests/agent_storage/test_sqlite_memories.py`
  - `uv run mypy packages apps`

## 2026-07-03 Phase 57 Type-Aware Memory Review Conflict Policy

- claimed `P57-MEM-13` on `codex/p57-mem-02-memory-candidate-extraction`
- narrowed review supersession so only single-active memory types (`project_rule`, `architecture_fact`, `procedure`) retire prior confirmed records in the same scope
- left confirmed `preference` memories coexistent so explicit user preferences no longer evict each other during confirm review
- validation:
  - `uv run pytest tests/agent_core/test_memory_reviews.py tests/api/test_memory_review.py tests/cli/test_cli_memory_review.py tests/test_session_memory_review_contract_matrix.py`
  - `uv run mypy packages apps`

## 2026-07-03 Phase 57 Duplicate Confirm Review Handling

- claimed `P57-MEM-14` on `codex/p57-mem-02-memory-candidate-extraction`
- added duplicate confirm detection so a candidate that normalizes to the same text as an existing confirmed memory is expired instead of becoming another confirmed record
- surfaced the matching confirmed memory id through the durable review event payload and both API and CLI review responses
- validation:
  - `uv run pytest tests/agent_core/test_event_contracts.py tests/agent_core/test_memory_reviews.py tests/api/test_memory_review.py tests/cli/test_cli_memory_review.py tests/test_session_memory_review_contract_matrix.py`
  - `uv run mypy packages apps`

## 2026-07-03 Phase 57 Stale Doc Memory Invalidation On Governance Refresh

- claimed `P57-MEM-15` on `codex/p57-mem-02-memory-candidate-extraction`
- added post-extraction invalidation so a full successful root `AGENTS.md` reread expires confirmed doc-derived memories whose normalized text no longer appears in the current extracted governance set
- kept the invalidation scope intentionally narrow to confirmed `project_rule` and `architecture_fact` repo memories and only when the governance document was fully reread
- validation:
  - `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'memory_candidate or agents_refresh or stale or architecture_fact or project_rule or preference'`
  - `uv run mypy packages apps`

## 2026-07-03 Phase 57 Closeout And Phase 58 Lifecycle Readback

- claimed `P57-CLOSE-01` and `P58-MEM-01` on `codex/p58-mem-01-session-memory-lifecycle-readback`
- closed `Phase 57` with `docs/Phase57_Local_Memory_Lifecycle_And_Governance_Refresh_验收记录.md`
- added shared memory inventory serialization so API and CLI session-memory reads expose `last_review` lifecycle metadata from the latest durable review event
- verified auto-expired governance-memory rows now surface system operator and invalidation reason during session-memory readback
- synchronized Phase 58 starter tasks and repository progress state across `docs/AGENT_TASKS.md`, `PROGRESS.md`, and `README.md`
- validation:
  - `uv run pytest tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/session_read.py apps/cli/src/zebra_agent_cli/session_memory_read.py packages/agent-core/src/agent_core/application/memory_inventory.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
  - `make check`

## 2026-07-03 Phase 58 Broader Invalidation And Closeout

- claimed `P58-MEM-02` and `P58-CLOSE-01`
- replaced the hard-coded governance-only stale invalidation path with refresh-target-driven invalidation for deterministic singleton repo memories
- kept auto-expire limited to `project_rule`, `architecture_fact`, and `procedure`, while leaving `preference` memories out of the singleton invalidation path
- added worker and core regression coverage for stale confirmed procedure expiry after a successful procedure refresh
- closed `Phase 58` with `docs/Phase58_Memory_Lifecycle_Readback_And_Broader_Invalidation_验收记录.md`
- added `Phase 59` starter tasks for memory source provenance readback and next planning
- validation:
  - `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'stale or procedure_refresh or agents_refresh or preference or architecture_fact or project_rule'`
  - `uv run ruff check packages/agent-core/src/agent_core/application tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 59 Memory Source Provenance Readback

- claimed `P59-MEM-01` on `codex/p59-mem-01-memory-source-provenance-readback`
- added shared `source` provenance projection on session memory inventory rows without changing the memory storage schema
- kept provenance deterministic by reconstructing it from `source_event_start/source_event_end` against the persisted session event stream
- covered tool-derived procedure memory, governance doc reads, and explicit user-message preference memory across API, CLI, and the session-memory contract matrix
- validation:
  - `uv run pytest tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`

## 2026-07-03 Phase 59 Closeout And Phase 60 Planning

- claimed `P59-CLOSE-01`
- closed `Phase 59` with `docs/Phase59_Memory_Source_Provenance_Readback_验收记录.md`
- synchronized `docs/AGENT_TASKS.md`, `PROGRESS.md`, and `README.md` so the phase state and next lane no longer lag the code
- added `Phase 60` starter tasks for user-scoped and tenant-scoped memory operator inventory

## 2026-07-03 Phase 60 Cross-Scope Memory Inventory And Closeout

- claimed `P60-MEM-01` and `P60-CLOSE-01`
- added shared cross-scope memory inventory reads for repo, user, and tenant scopes
- exposed local API surfaces for user-memory and tenant-memory inventory plus matching CLI commands
- kept provenance and lifecycle payloads aligned across all supported memory scopes
- closed `Phase 60` with `docs/Phase60_Cross_Scope_Memory_Operator_Inventory_验收记录.md`
- added `Phase 61` starter tasks for cross-scope memory review controls
- validation:
  - `uv run pytest tests/api/test_memory_scope_inventory.py tests/cli/test_cli_memory_scope_inventory.py tests/test_memory_scope_inventory_contract_matrix.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli packages/agent-core/src/agent_core/application tests/api/test_memory_scope_inventory.py tests/cli/test_cli_memory_scope_inventory.py tests/test_memory_scope_inventory_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 61 Cross-Scope Memory Review And Closeout

- claimed `P61-MEM-01` and `P61-CLOSE-01`
- extended local memory review controls from repo-session paths to user-scoped and tenant-scoped memory while keeping durable review events anchored to source sessions
- added local API routes and CLI commands for cross-scope confirm and expire flows
- preserved the existing lifecycle payload contract across repo, user, and tenant review responses
- closed `Phase 61` with `docs/Phase61_Cross_Scope_Memory_Review_Controls_验收记录.md`
- added `Phase 62` starter tasks for scope-aware memory review queue reads
- validation:
  - `uv run pytest tests/api/test_memory_review.py tests/cli/test_cli_memory_review.py tests/test_session_memory_review_contract_matrix.py tests/api/test_memory_scope_review.py tests/cli/test_cli_memory_scope_review.py tests/test_memory_scope_review_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli packages/agent-core/src/agent_core/application tests/api/test_memory_scope_review.py tests/cli/test_cli_memory_scope_review.py tests/test_memory_scope_review_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 56 Session Resume Execute Closeout

- claimed `P56-CLOSE-01` on `codex/p56-closeout-next-plan`
- closed `Phase 56` with `docs/Phase56_Session_Resume_Execute_CLI_And_Operator_Parity_验收记录.md`
- synchronized closeout evidence into `docs/AGENT_TASKS.md`、`PROGRESS.md`、`README.md`、`WORKLOG.md`
- validated current milestone text and implementation status documentation consistency

## 2026-07-02 Phase 56 Session Resume Execute Contract Matrix

- claimed `P56-TEST-01` on `codex/p56-test-01-session-resume-execute-contract-matrix`
- locking API and CLI parity for session resume execute output
- expect one explicit CLI-local normalization for `database`, with shared resume execute payloads compared otherwise field-for-field
- completed `P56-TEST-01` with a dedicated session resume execute cross-surface regression matrix
- validation:
  - `uv run pytest tests/test_session_resume_execute_contract_matrix.py tests/cli/test_cli_commands.py tests/api/test_http_app.py tests/api/test_routes.py`
  - `uv run ruff check tests/test_session_resume_execute_contract_matrix.py`

## 2026-07-02 Phase 55 Closeout And Phase 56 Planning

- claimed `P55-CLOSE-01` on `codex/p55-closeout-next-plan`
- added `docs/Phase55_Session_Inspect_CLI_And_Operator_Parity_验收记录.md`
- closed Phase 55 after CLI inspect parity alignment and cross-surface parity landed
- set the next active milestone to `Phase 56 - Session Resume Execute CLI And Operator Parity`
- added starter tasks:
  - `P56-CLI-01 - Session Resume Execute CLI Parity Alignment`
  - `P56-TEST-01 - Session Resume Execute Cross-Surface Contract Matrix`
  - `P56-CLOSE-01 - Phase 56 Closeout And Next Planning`

## 2026-07-02 Phase 56 Session Resume Execute CLI Parity Alignment

- claimed `P56-CLI-01` on `codex/p56-cli-01-session-resume-execute-parity`
- aligned local CLI `resume --execute` failure shaping with the API resume execution surface
- covered invalid-request, missing-session, lease-conflict, and not-resumable resume execute paths
- validation:
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_http_app.py tests/api/test_routes.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py tests/cli/test_cli_commands.py`

## 2026-07-02 Phase 55 Session Inspect Contract Matrix

- claimed `P55-TEST-01` on `codex/p55-test-01-session-inspect-contract-matrix`
- locking API and CLI parity for session inspect output
- expect one explicit CLI-local normalization for `database`, with shared session read fields compared otherwise field-for-field
- completed `P55-TEST-01` with a dedicated session inspect cross-surface regression matrix
- validation:
  - `uv run pytest tests/test_session_inspect_contract_matrix.py tests/cli/test_cli_commands.py tests/api/test_api_app.py`
  - `uv run ruff check tests/test_session_inspect_contract_matrix.py`

## 2026-07-02 Phase 55 Session Inspect CLI Parity Alignment

- claimed `P55-CLI-01` on `codex/p55-cli-01-session-inspect-parity`
- aligning local CLI `inspect` output with the API session read surface
- targeting `approval_context` parity while preserving the existing CLI-local `database` field
- completed `P55-CLI-01` by reusing the API approval-context serializer in the CLI inspect path
- validation:
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_api_app.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py tests/cli/test_cli_commands.py`
  - `make check`

## 2026-07-02 Phase 54 Closeout And Phase 55 Planning

- claimed `P54-CLOSE-01` on `codex/p54-closeout-next-plan`
- added `docs/Phase54_Session_Artifact_List_CLI_And_Operator_Parity_验收记录.md`
- closed Phase 54 after local artifact list CLI delivery and cross-surface parity landed
- set the next active milestone to `Phase 55 - Session Inspect CLI And Operator Parity`
- added starter tasks:
  - `P55-CLI-01 - Session Inspect CLI Parity Alignment`
  - `P55-TEST-01 - Session Inspect Cross-Surface Contract Matrix`
  - `P55-CLOSE-01 - Phase 55 Closeout And Next Planning`

## 2026-07-02 Phase 54 Session Artifact List Contract Matrix

- claimed `P54-TEST-01` on `codex/p54-test-01-session-artifact-list-contract-matrix`
- locking API and CLI parity for session artifact list output
- expect one explicit CLI-local normalization for `database`, with shared artifact payloads compared otherwise field-for-field
- completed `P54-TEST-01` with a dedicated session artifact list cross-surface regression matrix
- validation:
  - `uv run pytest tests/test_session_artifact_list_contract_matrix.py tests/cli/test_cli_artifacts.py tests/api/test_session_artifacts.py tests/api/test_session_artifact_access_projection.py`
  - `uv run ruff check tests/test_session_artifact_list_contract_matrix.py`

## 2026-07-02 Phase 54 Session Artifact List CLI Surface

- claimed `P54-CLI-01` on `codex/p54-cli-01-session-artifact-list`
- implementing a local `zebra-agent artifact list <session_id>` surface
- targeting deterministic non-empty, empty, and missing-session CLI results
- keeping the CLI payload aligned with the existing API artifact list envelope where practical
- completed `P54-CLI-01` with local artifact list inventory over the existing CLI artifact projection path
- validation:
  - `make sync`
  - `uv run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_commands.py`
  - `make check`

## 2026-07-02 Phase 53 Closeout And Phase 54 Planning

- claimed `P53-CLOSE-01` on `codex/p53-closeout-next-plan`
- added `docs/Phase53_Session_Control_CLI_And_Operator_Parity_验收记录.md`
- updated `docs/operator_runbook.md` with local cancel CLI and API control examples
- closed Phase 53 after session control CLI delivery and cross-surface parity landed on `main`
- set the next active milestone to `Phase 54 - Session Artifact List CLI And Operator Parity`
- added starter tasks:
  - `P54-CLI-01 - Session Artifact List CLI Surface`
  - `P54-TEST-01 - Session Artifact List Cross-Surface Contract Matrix`
  - `P54-CLOSE-01 - Phase 54 Closeout And Next Planning`

## 2026-07-02 Phase 53 Session Control Contract Matrix

- claimed `P53-TEST-01` on `codex/p53-test-01-session-control-contract-matrix`
- aligning cancel and suspend CLI payloads with API control responses while preserving CLI-local `database` context
- adding cross-surface regression coverage for cancelled, invalid-state, missing-session, and suspended control results
- validation:
  - `make sync`
  - `uv run pytest tests/test_session_control_contract_matrix.py tests/cli/test_cli_session_cancel.py tests/cli/test_cli_commands.py tests/api/test_http_session_cancel.py tests/api/test_http_app.py tests/api/test_route_session_cancel.py tests/api/test_routes.py tests/worker/test_control.py tests/worker/test_execution.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/session_suspend_write.py apps/cli/src/zebra_agent_cli/cli.py tests/test_session_control_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 53 Session Cancel Control Surface

- claimed `P53-CLI-01` on `codex/p53-cli-01-session-cancel`
- corrected the task boundary after finding that cancel control was not actually wired in the current codebase
- restoring the missing cancel control entry and adding local CLI cancel support with deterministic operator-facing results
- validation:
  - `make sync`
  - `uv run pytest tests/cli/test_cli_session_cancel.py tests/cli/test_cli_commands.py tests/api/test_http_session_cancel.py tests/api/test_http_app.py tests/api/test_route_session_cancel.py tests/api/test_routes.py tests/worker/test_control.py tests/worker/test_execution.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/session_cancel_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/api/src/zebra_agent_api/session_control.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/api/src/zebra_agent_api/session_payloads.py apps/worker/src/zebra_agent_worker/control.py apps/worker/src/zebra_agent_worker/__init__.py tests/cli/test_cli_session_cancel.py tests/api/test_http_session_cancel.py tests/api/test_route_session_cancel.py tests/worker/test_control.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 52 Closeout And Phase 53 Planning

- claimed `P52-CLOSE-01` on `codex/p52-closeout-next-plan`
- added `docs/Phase52_Session_Message_Append_CLI_And_Operator_Parity_验收记录.md`
- closed Phase 52 after session message append CLI delivery and cross-surface parity landed on `main`
- set the next active milestone to `Phase 53 - Session Control CLI And Operator Parity`
- added starter tasks:
  - `P53-CLI-01 - Session Cancel CLI Surface`
  - `P53-TEST-01 - Session Control Cross-Surface Contract Matrix`
  - `P53-CLOSE-01 - Phase 53 Closeout And Next Planning`

## 2026-07-02 Phase 52 Session Message Append Contract Matrix

- claimed `P52-TEST-01` on `codex/p52-test-01-session-message-contract-matrix`
- locking API and CLI append parity for appended, invalid-request, not-found, and terminal-session responses
- normalizing CLI-local `database` context out of the shared append contract
- validation:
  - `make sync`
  - `uv run pytest tests/test_session_message_append_contract_matrix.py tests/cli/test_cli_session_message_append.py tests/api/test_http_app.py tests/api/test_routes.py`
  - `uv run ruff check tests/test_session_message_append_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-02 Phase 52 Session Message Append CLI

- claimed `P52-CLI-01` on `codex/p52-cli-01-session-message-append`
- adding local CLI append support for durable session continuation
- keeping the append result contract aligned with the API while preserving CLI-local `database` context
- validation:
  - `make sync`
  - `uv run pytest tests/cli/test_cli_session_message_append.py tests/api/test_http_app.py tests/api/test_routes.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/session_message_append_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/cli/test_cli_session_message_append.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 Phase 51 Closeout And Phase 52 Planning

- claimed `P51-CLOSE-01` on `codex/p51-closeout-next-plan`
- added `docs/Phase51_Approval_Decision_Cross_Surface_Parity_验收记录.md`
- closed Phase 51 after approval decision parity landed on `main`
- set the next active milestone to `Phase 52 - Session Message Append CLI And Operator Parity`
- added starter tasks:
  - `P52-CLI-01 - Session Message Append CLI Surface`
  - `P52-TEST-01 - Session Message Append Cross-Surface Contract Matrix`
  - `P52-CLOSE-01 - Phase 52 Closeout And Next Planning`

## 2026-07-01 Phase 51 Approval Decision Contract Matrix

- claimed `P51-TEST-01` on `codex/p51-test-01-approval-decision-contract-matrix`
- aligning CLI approval decision payloads with API responses while preserving CLI-local `database` context
- adding cross-surface regression coverage for grant, reject, invalid-state, and missing-session approval decisions
- validation:
  - `make sync`
  - `uv run pytest tests/test_approval_decision_contract_matrix.py tests/api/test_approval_api_app.py tests/api/test_http_approvals.py tests/cli/test_cli_commands.py`
  - `uv run ruff check --fix apps/cli/src/zebra_agent_cli/cli.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/approval_decision_write.py apps/cli/src/zebra_agent_cli/cli.py tests/test_approval_decision_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 Phase 50 Closeout And Phase 51 Planning

- claimed `P50-CLOSE-01` on `codex/p50-closeout-next-plan`
- added `docs/Phase50_Approval_Queue_CLI_And_Operator_Parity_验收记录.md`
- closed Phase 50 after approval queue CLI delivery and cross-surface parity landed on `main`
- set the next active milestone to `Phase 51 - Approval Decision Cross-Surface Parity`
- added starter tasks:
  - `P51-TEST-01 - Approval Decision Cross-Surface Contract Matrix`
  - `P51-CLOSE-01 - Phase 51 Closeout And Next Planning`

## 2026-07-01 Phase 50 Approval Read Contract Matrix

- claimed `P50-TEST-01` on `codex/p50-test-01-approval-queue-contract-matrix`
- adding API and CLI approval queue/detail parity coverage with CLI-local `database` normalization
- work stays in `tests/` plus required task-board progress surfaces
- validation:
  - `make sync`
  - `uv run pytest tests/test_approval_read_contract_matrix.py tests/cli/test_cli_approval_read.py tests/api/test_api_app.py tests/api/test_http_approvals.py tests/api/test_routes.py`
  - `uv run ruff check tests/test_approval_read_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 Phase 50 CLI Approval Queue Read

- claimed `P50-CLI-01` on `codex/p50-cli-01-approval-queue-read`
- added local CLI `approval queue` and `approval inspect` read surfaces
- kept the change path-scoped to `apps/cli/` and `tests/cli/`; did not widen into API or shared package extraction
- validation:
  - `make sync`
  - `uv run pytest tests/cli/test_cli_approval_read.py tests/api/test_api_app.py tests/api/test_http_approvals.py tests/api/test_routes.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/approval_read.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py tests/cli/test_cli_approval_read.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-06-28 Phase 19 Closeout And Phase 20 Planning

- 执行 `P19-CLOSE-01 - Phase 19 Closeout And Next Planning`
- 新增 Phase 19 验收记录：
  - `docs/Phase19_Secret_Store_And_Broker_Credentials_验收记录.md`
- 汇总 Phase 19 已完成证据：
  - `SecretStore`
  - `LocalSecretStore`
  - `GitHubAppCredentialBroker`
  - provider-backed `failure_class`
- 将仓库主线状态推进到 Phase 20 ready
- 新增 Phase 20 starter tasks：
  - `P20-SEC-01 - Network Profile Contract`
  - `P20-INT-01 - SCM Transport Egress Guard`
  - `P20-DOC-01 - Egress Control Operator Docs`
  - `P20-CLOSE-01 - Phase 20 Closeout And Next Planning`
- Phase 20 方向依据：
  - 架构文档 `11.6 Egress Control`
  - `network none` 为默认 fail-closed posture
  - 目录规划中的 `policy/network_policy.py` 与 `credentials/egress_proxy.py`

## 2026-06-28 P20-SEC-01 Network Profile Contract

- 执行 `P20-SEC-01 - Network Profile Contract`
- 在 `packages/agent-security/src/agent_security/network_profile.py` 新增确定性网络配置契约：
  - 定义 `none`、`setup-only`、`domain-allowlist`、`mcp-proxy-only`、`git-proxy-only`、`full-trusted-local`
  - 保持 `DEFAULT_NETWORK_PROFILE=none` 的 fail-closed 本地默认值
  - 对无效 profile、空白 profile、歧义 allowlist、非 allowlist profile 附带域名列表等情况做显式拒绝
- 在 `tests/agent_security/test_network_profile.py` 增加定向回归覆盖
- 更新 `README.md`、`PROGRESS.md`、`docs/Credential_Broker_Foundation.md`，将 Phase 20 当前完成状态写回仓库
- 验证：
  - `poetry run pytest tests/agent_security/test_network_profile.py tests/agent_security/test_secret_store.py tests/agent_security/test_policy_profiles.py`
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security`

## 2026-06-28 P20-INT-01 SCM Transport Egress Guard

- 执行 `P20-INT-01 - SCM Transport Egress Guard`
- 在 `packages/agent-integrations/src/agent_integrations/scm.py` 为 GitHub PR 执行路径增加 egress gate：
  - 从环境读取 `ZEBRA_SCM_NETWORK_PROFILE`
  - 从环境读取 `ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST`
  - 在 credential lookup 与 transport side effect 之前先判断是否允许访问目标 GitHub API host
- 当前 direct GitHub transport 仅在以下 profile 下允许：
  - `full-trusted-local`
  - `domain-allowlist` 且 allowlist 命中目标 host
- 默认 `none` 下远程执行会返回 `failure_class=egress_policy`，并记录：
  - `network_profile`
  - `target_host`
- 保持 dry-run 与 local-only 行为不变；credential / transport 失败分类在放行 egress 后继续保留
- 更新 `tests/agent_integrations/test_scm.py` 与 `tests/api/test_session_pull_request.py`：
  - 新增默认 egress block 覆盖
  - 新增 domain allowlist 放行覆盖
  - 保持 broker / env / GitHub App / transport failure 审计语义
- 验证：
  - `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations tests/api/test_session_pull_request.py`

## 2026-06-28 P20-DOC-01 Egress Control Operator Docs

- 执行 `P20-DOC-01 - Egress Control Operator Docs`
- 更新 `docs/operator_runbook.md`：
  - 增加 `ZEBRA_SCM_NETWORK_PROFILE` 与 `ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST` 配置说明
  - 明确当前 direct GitHub transport 仅允许 `full-trusted-local` 或命中 API host 的 `domain-allowlist`
  - 增加默认 `network_profile=none` 下的阻断示例
  - 将 `egress_policy` 纳入 delivery audit `failure_class` 说明与 remediation 指引
  - 明确测试后要回退到 `network_profile=none` 的安全默认值
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`，将 Phase 20 文档状态与下一张 closeout 任务写回仓库

## 2026-06-28 P20-CLOSE-01 Phase 20 Closeout And Next Planning

- 执行 `P20-CLOSE-01 - Phase 20 Closeout And Next Planning`
- 新增 Phase 20 验收记录：
  - `docs/Phase20_Egress_Control_Foundations_验收记录.md`
- 汇总 Phase 20 已完成证据：
  - `NetworkProfile`
  - fail-closed `DEFAULT_NETWORK_PROFILE=none`
  - SCM egress gate with `failure_class=egress_policy`
  - operator runbook remediation and rollback guidance
- 将仓库主线状态推进到 Phase 21 ready
- 新增 Phase 21 starter tasks：
  - `P21-INT-01 - SCM Proxy Transport Contract`
  - `P21-INT-02 - GitHub Proxy Pull Request Adapter`
  - `P21-TOOL-01 - MCP Proxy Egress Starter Contract`
  - `P21-DOC-01 - Proxy Egress Operator Docs`
  - `P21-CLOSE-01 - Phase 21 Closeout And Next Planning`
- Phase 21 方向依据：
  - 当前 `git-proxy-only` 与 `mcp-proxy-only` 仍只有策略标签，没有真实 transport
  - 下一阶段应把 remote side effect 从 direct local transport 进一步收敛到 proxy-backed contract

## 2026-06-28 P21-INT-01 SCM Proxy Transport Contract

- 执行 `P21-INT-01 - SCM Proxy Transport Contract`
- 在 `packages/agent-integrations/src/agent_integrations/scm_proxy.py` 新增独立 proxy contract：
  - `ScmProxyRequest`
  - `ScmProxyResponse`
  - `ScmProxyTransport`
  - `build_github_pull_request_proxy_request(...)`
- 约束点：
  - request / response 形状必须是确定性的可序列化 JSON 结构
  - headers 去重、排序并标准化
  - contract 与现有 direct GitHub HTTP transport 分离，不改变当前执行路径
- 在 `tests/agent_integrations/test_scm_proxy.py` 增加定向回归：
  - request / response 标准化
  - 非 JSON 值拒绝
  - duplicate headers 拒绝
  - GitHub proxy request helper 的稳定输出
  - proxy transport Protocol 兼容性
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`，将下一张 adapter 任务和 MCP proxy starter 解锁
- 验证：
  - `poetry run pytest tests/agent_integrations/test_scm_proxy.py tests/agent_integrations/test_scm.py`
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations`
  - `uv run mypy packages/agent-integrations/src/agent_integrations/scm_proxy.py tests/agent_integrations/test_scm_proxy.py`

## 2026-06-28 P21-INT-02 GitHub Proxy Pull Request Adapter

- 执行 `P21-INT-02 - GitHub Proxy Pull Request Adapter`
- 在 `packages/agent-integrations/src/agent_integrations/scm.py` 增加 `GitHubProxyPullRequestTransport`
- 在 `packages/agent-integrations/src/agent_integrations/scm_proxy_http.py` 增加 `ScmHttpProxyTransport`
- 接线规则：
  - `ZEBRA_SCM_GITHUB_TRANSPORT=direct` 保持当前 direct GitHub HTTP transport
  - `ZEBRA_SCM_GITHUB_TRANSPORT=proxy` 时改走 proxy-backed adapter
  - `ZEBRA_SCM_PROXY_ENDPOINT` 缺失时显式失败
- 安全边界：
  - proxy request 的 public serializable shape 不包含 raw token
  - token 仅进入 runtime `secret_headers`
  - 现有 `egress_policy`、`credential_*`、`transport_failure` 分类保持不变
- 回归覆盖：
  - `tests/agent_integrations/test_scm.py` 覆盖 proxy created path 和缺少 proxy endpoint 的失败
  - `tests/api/test_session_pull_request.py` 覆盖 API proxy created path 与 proxy transport failure audit
  - `tests/agent_integrations/test_scm_proxy.py` 覆盖 secret header 不进入 serializable snapshot
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`，将 `P21-DOC-01` 解锁
- 验证：
  - `poetry run pytest tests/agent_integrations/test_scm_proxy.py tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations tests/api/test_session_pull_request.py`
  - `uv run mypy packages/agent-integrations/src/agent_integrations/scm_proxy.py packages/agent-integrations/src/agent_integrations/scm_proxy_http.py tests/agent_integrations/test_scm_proxy.py`

## 2026-06-28 P21-TOOL-01 MCP Proxy Egress Starter Contract

- 执行 `P21-TOOL-01 - MCP Proxy Egress Starter Contract`
- 在 `packages/agent-tools/src/agent_tools/mcp_proxy.py` 新增 MCP proxy starter contract：
  - `McpToolTarget`
  - `McpProxyRequest`
  - `McpProxyResponse`
  - `McpProxyTransport`
  - `parse_mcp_tool_name(...)`
  - `build_mcp_proxy_request(...)`
- 约定 `mcp.<server>.<tool>` 为 MCP tool naming contract，并要求 arguments 为确定性 JSON serializable 结构
- 在 `packages/agent-security/src/agent_security/mcp_proxy_policy.py` 新增 policy-facing egress classifier：
  - `ToolEgressRoute`
  - `ToolEgressMetadata`
  - `classify_tool_egress(...)`
- 当前 starter 行为：
  - builtin/local tools 标记为 `route=local`
  - MCP tool 在 `mcp-proxy-only` 和 `full-trusted-local` 下标记为 `route=mcp_proxy`
  - 其他 profile 下对 MCP tool 标记为 `route=blocked`
- 顺手将 `packages/agent-tools/src/agent_tools/__init__.py` 改为 lazy exports，避免工具包初始化时的循环导入
- 回归覆盖：
  - `tests/agent_tools/test_mcp_proxy.py`
  - `tests/agent_security/test_mcp_proxy_policy.py`
  - `tests/agent_tools/test_executor.py`
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`
- 验证：
  - `poetry run pytest tests/agent_tools/test_mcp_proxy.py tests/agent_security/test_mcp_proxy_policy.py tests/agent_tools/test_executor.py`
  - `uv run ruff check packages/agent-tools/src/agent_tools packages/agent-security/src/agent_security tests/agent_tools tests/agent_security`
  - `uv run mypy packages/agent-tools/src/agent_tools/__init__.py packages/agent-tools/src/agent_tools/mcp_proxy.py packages/agent-security/src/agent_security/mcp_proxy_policy.py tests/agent_tools/test_mcp_proxy.py tests/agent_security/test_mcp_proxy_policy.py`

## 2026-06-28 P21-DOC-01 Proxy Egress Operator Docs

- 执行 `P21-DOC-01 - Proxy Egress Operator Docs`
- 更新 `docs/operator_runbook.md`：
  - 增加 `ZEBRA_SCM_GITHUB_TRANSPORT` 与 `ZEBRA_SCM_PROXY_ENDPOINT` 配置说明
  - 明确 direct 与 proxy transport 的使用边界
  - 增加 proxy mode 的 preconditions、失败排查和回滚步骤
  - 新增 MCP proxy starter section，说明 `mcp.<server>.<tool>` 命名契约与 `route=local|mcp_proxy|blocked` 的 operator 含义
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`，将 Phase 21 当前文档状态写回仓库并解锁 closeout 任务

## 2026-06-28 P21-CLOSE-01 Phase 21 Closeout And Next Planning

- 执行 `P21-CLOSE-01 - Phase 21 Closeout And Next Planning`
- 新增 Phase 21 验收记录：
  - `docs/Phase21_Proxy_Egress_Contracts_验收记录.md`
- 汇总 Phase 21 已完成证据：
  - `ScmProxyRequest` / `ScmProxyResponse`
  - `GitHubProxyPullRequestTransport`
  - `McpProxyRequest` / `McpProxyResponse`
  - `classify_tool_egress(...)`
  - proxy operator runbook guidance
- 将仓库主线状态推进到 Phase 22 ready
- 新增 Phase 22 starter tasks：
  - `P22-TOOL-01 - MCP Proxy Gateway Execution Path`
  - `P22-OBS-01 - Proxy Audit Metadata Normalization`
  - `P22-SEC-01 - Proxy Route Policy Integration`
  - `P22-DOC-01 - Proxy Gateway Operator Docs`
  - `P22-CLOSE-01 - Phase 22 Closeout And Next Planning`
- Phase 22 方向依据：
  - 当前 SCM proxy 与 MCP proxy 仍偏 contract / adapter 层
  - 下一阶段应把 MCP proxy 接到真实 tool gateway execution path，并统一 proxy 审计语义

## 2026-06-28 P22-TOOL-01 MCP Proxy Gateway Execution Path

- 执行 `P22-TOOL-01 - MCP Proxy Gateway Execution Path`
- 在 `packages/agent-tools/src/agent_tools/mcp_gateway.py` 新增 `McpProxyToolGateway`
- 在 `packages/agent-tools/src/agent_tools/executor.py` 为 `ToolExecutor` 增加可选 `mcp_proxy_gateway`
- 当前行为：
  - 已注册 builtin/local tools 继续按原路径执行
  - 未注册但符合 `mcp.<server>.<tool>` 的调用，在配置了 `mcp_proxy_gateway` 时转入 MCP proxy execution path
  - 非 MCP 的未知 tool 仍保持 `UnknownToolError`
- `McpProxyToolGateway` 当前通过 `build_mcp_proxy_request(...)` 调用 `McpProxyTransport`，并返回稳定的 `ToolResult`
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`
- 验证：
  - `poetry run pytest tests/agent_tools/test_executor.py tests/agent_tools/test_mcp_proxy.py tests/agent_security/test_mcp_proxy_policy.py`
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/agent_security`
  - `uv run mypy packages/agent-tools/src/agent_tools/__init__.py packages/agent-tools/src/agent_tools/executor.py packages/agent-tools/src/agent_tools/mcp_gateway.py packages/agent-tools/src/agent_tools/mcp_proxy.py tests/agent_tools/test_executor.py tests/agent_tools/test_mcp_proxy.py`

## 2026-06-28 P22-OBS-01 Proxy Audit Metadata Normalization

- 执行 `P22-OBS-01 - Proxy Audit Metadata Normalization`
- 在 SCM proxy 与 MCP proxy 两侧统一稳定 metadata shape：
  - `route`
  - `proxy_target`
  - `proxy_transport`
- SCM 侧：
  - `PullRequestPlan` 增加 proxy metadata 字段
  - API pull request 响应和 delivery audit 记录 proxy metadata
  - direct path 默认记录 `route=direct`
- MCP 侧：
  - `McpProxyToolGateway` 返回的 `ToolResult.metadata` 对齐为相同字段
- 保持失败语义：
  - proxy availability 仍通过 `failure_class=transport_failure` 暴露
  - 既有 credential / egress policy 分类不变
- 回归覆盖：
  - `tests/agent_integrations/test_scm.py`
  - `tests/api/test_session_pull_request.py`
  - `tests/api/test_session_delivery_audit.py`
  - `tests/agent_tools/test_executor.py`
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`
- 验证：
  - `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_session_delivery_audit.py tests/agent_tools/test_executor.py`
  - `uv run ruff check packages/agent-integrations/src/agent_integrations packages/agent-tools/src/agent_tools apps/api/src/zebra_agent_api tests/agent_integrations tests/api tests/agent_tools`

## 2026-06-28 GitHub App Credential Adapter Skeleton

- 执行 `P19-INT-01 - GitHub App Credential Adapter Skeleton`
- 新增 `agent_integrations.github_app`：
  - `GitHubAppCredentialBinding`
  - `GitHubAppInstallationToken`
  - `GitHubAppTokenTransport`
  - `GitHubAppCredentialBroker`
- 适配路径：
  - 通过 `SecretStore` 读取 private key material
  - 通过 `GitHubAppTokenTransport` 交换 installation token
  - 返回标准 `CredentialCapability`
- 新增 provider-backed failure 语义：
  - `CredentialTransportError`
  - SCM audit `failure_class=transport_failure` 可从 GitHub App token exchange 透传
- 保持安全边界：
  - private key 不进入 `repr`
  - private key 不进入 API response
  - private key 不进入 delivery audit metadata
- 新增和更新测试：
  - `tests/agent_integrations/test_github_app.py`
  - `tests/agent_integrations/test_scm.py`
  - `tests/api/test_session_pull_request.py`
- 更新文档：
  - `docs/Credential_Broker_Foundation.md`
  - `docs/operator_runbook.md`
- 本轮验证结果：
  - `poetry run pytest tests/agent_integrations/test_github_app.py tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py` 通过
  - `uv run ruff check packages/agent-integrations/src/agent_integrations packages/agent-security/src/agent_security tests/agent_integrations tests/api/test_session_pull_request.py` 通过
  - `uv run mypy packages/agent-integrations/src/agent_integrations packages/agent-security/src/agent_security tests/agent_integrations` 通过

## 2026-06-28 Local Secret Store Backend

- 执行 `P19-SEC-02 - Local Secret Store Backend`
- 在 `agent_security.secret_store` 中新增：
  - `LocalSecretStore`
  - `get_secret_value(...)`
- 本地 backend 设计：
  - 以本地目录为 root
  - 按 handle 映射到分层 JSON secret document
  - 返回 `SecretMaterial`
  - 继续沿用 redacted contract，不暴露 raw value
- 当前错误语义：
  - missing secret -> `SecretMissingError`
  - missing/unreadable root or invalid document -> `SecretUnavailableError`
  - traversal or blank handle -> `ValueError`
- 更新文档：
  - `docs/Credential_Broker_Foundation.md`
- 本轮验证结果：
  - `poetry run pytest tests/agent_security/test_secret_store.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py tests/agent_security/test_environment_broker.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security` 通过

## 2026-06-28 Secret Store Port And Redaction Contract

- 执行 `P19-SEC-01 - Secret Store Port And Redaction Contract`
- 新增 `agent_security.secret_store`：
  - `SecretStore`
  - `SecretMaterial`
  - `SecretStoreError`
  - `SecretMissingError`
  - `SecretUnavailableError`
  - `InMemorySecretStore`
- 约束 secret-store contract：
  - raw secret value 不进入 `repr`
  - `redacted()` 统一输出 `<redacted>`
  - missing 与 unavailable 语义分离
- 更新 `agent_security.__init__` 导出和 `docs/Credential_Broker_Foundation.md`
- 新增测试：
  - `tests/agent_security/test_secret_store.py`
- 本轮验证结果：
  - `poetry run pytest tests/agent_security/test_secret_store.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py tests/agent_security/test_environment_broker.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security` 通过

## 2026-06-28 Phase 18 Closeout And Phase 19 Planning

- 执行 `P18-CLOSE-01 - Phase 18 Closeout And Next Planning`
- 新增 Phase 18 验收记录：
  - `docs/Phase18_SCM_Audit_Observability_验收记录.md`
- 汇总 Phase 18 已完成证据：
  - `credential_source`
  - `credential_backend`
  - `failure_class`
  - operator remediation guidance
- 将仓库主线状态推进到 Phase 19 ready
- 新增 Phase 19 starter tasks：
  - `P19-SEC-01 - Secret Store Port And Redaction Contract`
  - `P19-SEC-02 - Local Secret Store Backend`
  - `P19-INT-01 - GitHub App Credential Adapter Skeleton`
- Phase 19 方向依据：
  - 架构文档 `Credential Broker`
  - 架构文档 `Secret: OS Keychain / 本地安全存储`
  - 目录规划中的 `credentials/secret_store.py` 与 `protocols/github_app.py`

## 2026-06-28 Credential Failure Audit Classification

- 执行 `P18-OBS-02 - Credential Failure Audit Classification`
- 为 SCM pull-request 失败审计增加稳定的 `failure_class` 分类：
  - `credential_missing`
  - `credential_denied`
  - `credential_unavailable`
  - `transport_failure`
- 分类从集成层透传到 API delivery audit metadata：
  - broker missing / denied / unavailable 分别保留不同 failure class
  - GitHub transport failure 与 broker unavailable 明确区分
  - transport failure 仍保留 `credential_source` 与 `credential_backend`，便于排障
- 新增和更新测试：
  - `tests/agent_integrations/test_scm.py`
  - `tests/api/test_session_pull_request.py`
  - `tests/api/test_delivery_audit_metadata.py`
  - `tests/api/test_session_delivery_audit.py`
- 更新 `docs/operator_runbook.md`，补充基于 `failure_class` 的 remediation 指引
- 本轮验证结果：
  - `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py` 通过
  - `make check` 通过
  - `make test` 未通过；当前阻塞为与本任务无关的 `tests/worker/test_loop.py::test_worker_loop_skips_already_leased_ready_session`
  - 阻塞原因是该用例使用固定 `acquired_at=2026-06-23T09:00Z` 与真实当前时间比较，lease 已过期后被 worker 正常重新 claim；该问题位于 `tests/worker/`，不属于 `P18-OBS-02` owned paths

## 2026-06-23 SCM Credential Source Audit Metadata

- 执行 `P18-OBS-01 - SCM Credential Source Audit Metadata`
- 为 GitHub pull request 计划与 API delivery audit 增加非敏感凭证来源字段：
  - `credential_source`
  - `credential_backend`
- 打通三类语义路径：
  - broker-backed 成功执行记录 `credential_source=broker`
  - explicit env fallback 成功执行记录 `credential_source=env_fallback`
  - broker missing 失败记录保留来源元数据，便于和普通 transport failure 区分
- 保持安全边界不变：
  - API response 不暴露 token
  - delivery audit 不暴露 token
  - request payload 继续使用 redacted authorization header
- 新增和更新测试：
  - `tests/api/test_delivery_audit_metadata.py`
  - `tests/api/test_session_delivery_audit.py`
  - `tests/api/test_session_pull_request.py`
  - `tests/agent_integrations/test_scm.py`
- 本轮验证结果：
  - `poetry run pytest tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py` 通过
  - `make check` 通过

## 2026-06-22 CLI Durable Run Execution

- 执行 `P8-CLI-05 - CLI Durable Run Execution`
- 新增 `run --execute`：
  - 复用现有 harness loop 与 single-attempt orchestrator
  - 接入真实 model gateway
  - 接入本地 policy engine、runtime-backed builtin tools、SQLite event/projection persistence
- 默认 `run` 行为保持为仅创建 session，不隐式开始执行
- 新增测试：
  - assistant-only durable execution
  - `files.read` builtin tool durable execution

## 2026-06-22 API Session Create And Execute

- 执行 `P8-API-06 - API Session Create And Execute`
- 把本地 harness 执行 wiring 抽到 `agent-runtime.run_local_harness`
- CLI durable execution 改为复用共享 runtime-side helper
- 新增 API `POST /sessions`：
  - `execute=false` 时仅创建 durable session
  - `execute=true` 时立即运行一轮本地 harness，并持久化完整事件流
- 新增测试：
  - runtime shared harness runner
  - API app create-only / execute paths
  - route adapter `POST /sessions`
  - HTTP JSON request parsing、create、execute 与错误输入

## 2026-06-22 Queued Session Bootstrap Events

- 执行 `P8-QUE-01 - Queued Session Bootstrap Events`
- 在 `agent-core` 新增共享 `SessionBootstrapService`
- create-only CLI/API session 现在都会持久化：
  - `SESSION_CREATED`
  - `USER_MESSAGE_RECEIVED`
  - `TASK_PREPARED`
- create-only session 的 durable 状态从 `created` 前移到 `ready`
- 为后续 worker-owned execution 预埋了可恢复的任务输入与 workspace 信息

## 2026-06-22 Worker Execute Ready Session

- 执行 `P8-WKR-04 - Worker Execute Ready Session`
- `agent-runtime` 暴露可复用 `LocalToolGateway`
- `apps/worker` 新增 `SessionExecutionService`
- worker 现在可以：
  - 从 queued bootstrap events 重建任务输入
  - claim/resume 一个 `ready` session
  - 执行一轮本地 harness attempt
  - 持久化 terminal events、projection、model call index、tool run index
  - 在终态后释放 lease
- 新增测试：
  - assistant-only worker execution
  - builtin `files.read` worker execution 与 tool-run indexing

## 2026-06-22 CLI Resume Execute Trigger

- 执行 `P8-CLI-06 - CLI Resume Execute Trigger`
- `zebra-agent resume` 保持默认只读
- 新增 `zebra-agent resume --execute`：
  - 复用 worker-side `SessionExecutionService`
  - 允许显式传入 `--worker-id`
  - 返回终态 `status`、assistant message 和紧凑 tool trace
- 新增测试：
  - read-only resume 不变
  - assistant-only resume execution
  - `files.read` resume execution trace

## 2026-06-19

- 将会与 `PROGRESS.md` 冲突的旧 `progress.md` 会话日志文件重命名为 `WORKLOG.md`
- 执行 `P2-TOOL-01 Tool Contracts And Execution Results`
- 新增 `agent-tools` 执行层骨架：
  - `contracts.py`
  - `errors.py`
  - `registry.py`
  - `executor.py`
  - `gateway.py`
- 新增测试：
  - `tests/agent_tools/test_executor.py`
- 为 `agent-core` 和 `agent-tools` 增加 `py.typed`，消除 workspace 类型导入噪音
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools tests/agent_tools tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-tools/src/agent_tools tests/agent_tools` 通过

## 2026-06-19 Governance Alignment

- 恢复真正的 `PROGRESS.md` 项目状态文件
- 把文档中的会话日志引用统一从 `progress.md` 改为 `WORKLOG.md`
- 更新 `README.md`，将仓库状态从 bootstrap 调整为 `Phase 2 - Runtime And Tooling Spine`

## 2026-06-19 Runtime Workspace Baseline

- 执行 `P2-RT-02 - Workspace And Worktree Abstractions`
- 新增 `agent-runtime.workspace` 模块：
  - `errors.py`
  - `models.py`
  - `local.py`
- 新增 `LocalWorkspace` 和 `LocalWorktree`
- 增加 workspace root 绝对路径校验、相对路径归一化、越界路径拒绝、worktree 创建与销毁生命周期
- 新增测试：
  - `tests/agent_runtime/test_workspace.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_runtime/test_workspace.py tests/agent_runtime/test_local_runtime.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-runtime/src/agent_runtime tests/agent_runtime` 通过

## 2026-06-19 Builtin File Read Path

- 执行 `P2-TOOL-02 - Builtin File Read Path`
- 新增 `agent_tools.builtin.files`
- 实现 `files.read`：
  - 通过 `LocalWorkspace` 做相对路径归一化
  - 拒绝越界读取
  - 对大文件返回截断结果和结构化 metadata
- 为 `agent-tools` 增加对 `agent-runtime` 的 workspace 依赖声明
- 新增测试：
  - `tests/agent_tools/test_file_read_tool.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools/test_file_read_tool.py tests/agent_tools/test_executor.py tests/agent_runtime/test_workspace.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/smoke/test_workspace_bootstrap.py` 通过
  - `make check` 通过

## 2026-06-19 Builtin Command Execution Path

- 执行 `P2-TOOL-03 - Builtin Command Execution Path`
- 新增 `agent_tools.builtin.command`
- 实现 `command.run`：
  - `command` 必须是 typed argv，不接受自由 shell 字符串
  - 默认在 workspace 根目录执行
  - `cwd` 如果提供，必须仍然位于 workspace 内
  - `timeout_seconds` 透传到 `RuntimePort`
  - 返回结构化执行结果：`stdout` 作为输出，`exit_code`、`stderr`、`timed_out` 写入 metadata
- 新增测试：
  - `tests/agent_tools/test_command_run_tool.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools/test_command_run_tool.py tests/agent_tools/test_file_read_tool.py tests/agent_tools/test_executor.py tests/agent_runtime/test_workspace.py tests/agent_runtime/test_local_runtime.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools` 通过
  - `uv run mypy packages/agent-tools/src/agent_tools tests/agent_tools` 通过
  - `make check` 通过

## 2026-06-19 Builtin Patch And Validation Path

- 执行 `P2-TOOL-04 - Builtin Patch Apply Path`
- 新增 `agent_tools.builtin.patch`
- 实现 `patch.apply`：
  - 输入为 unified diff 字符串
  - 先校验 patch 头中的路径，拒绝越界到 workspace 外
  - 通过 typed `patch` 命令映射到 `RuntimePort`
  - 非零退出和 stderr 作为结构化结果返回
- 新增测试：
  - `tests/agent_tools/test_patch_apply_tool.py`

- 执行 `P2-TOOL-05 - Builtin Validation Commands`
- 新增 `agent_tools.builtin.tests`
- 实现 `tests.run`：
  - 使用 preset 映射，不接受任意自由 shell 文本
  - 支持 `cwd` 与 `timeout_seconds`
  - 返回结构化执行结果
- 新增测试：
  - `tests/agent_tools/test_tests_run_tool.py`

- 执行 `P2-IT-01 - Local Toolchain Integration Flow`
- 新增集成测试：
  - `tests/integration/test_local_toolchain_flow.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/agent_runtime tests/integration tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/integration` 通过
  - `make check` 通过

## 2026-06-19 Readonly Git Inspection Path

- 执行 `P2-GIT-01 - Readonly Git Inspection Tools`
- 新增 `agent_tools.builtin.git`
- 实现 `git.status`：
  - 只执行 readonly `git status --short --branch`
  - `cwd` 如果提供，必须仍然位于 workspace 内
  - 返回结构化结果，不引入写操作
- 新增测试：
  - `tests/agent_tools/test_git_status_tool.py`
- 补齐 `Phase 2` 最小本地工具闭环：
  - `files.read`
  - `patch.apply`
  - `command.run`
  - `tests.run`
  - `git.status`
  - `tests/integration/test_local_toolchain_flow.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/agent_runtime tests/integration tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/integration` 通过
  - `make check` 通过

## 2026-06-19 Harness Loop Skeleton

- 执行 `P3-HAR-01 - Harness Loop Skeleton`
- 新增 `agent_core.harness`
- 实现最小 loop 骨架：
  - `HarnessTask`
  - `HarnessAttempt`
  - `HarnessContext`
  - `HarnessAttemptResult`
  - `HarnessLoop`
- 新增 `HARNESS_ATTEMPT_STARTED` 事件，并接入 session projection
- 当前 loop 只协调一次注入式 `attempt_runner`，不提前耦合真实模型或真实工具执行
- 新增测试：
  - `tests/agent_core/test_harness_loop.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过

## 2026-06-19 Mock Model Gateway

- 执行 `P3-MOD-01 - Mock Model Gateway`
- 新增 `agent_core.domain.modeling.ModelCompletion`
- 调整 `ModelGatewayPort`，从返回单条消息升级为返回 `ModelCompletion`
- 新增 `agent_core.application.mock_model`：
  - `ScriptedModelGateway`
  - `ScriptedModelResponse`
- 新增 `HarnessModelStep`，用于构造初始用户消息并请求一次模型完成
- 新增测试：
  - `tests/agent_core/test_mock_model_gateway.py`
- 覆盖场景：
  - deterministic mock completion
  - tool call planning path
  - script exhaustion failure
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Single Attempt Tool Orchestration

- 执行 `P3-HAR-02 - Single Attempt Tool Orchestration`
- 新增 `SingleAttemptOrchestrator`
- 在单次 attempt 中串起：
  - model completion
  - tool call proposal
  - policy evaluation
  - tool execution
  - structured attempt result
- 为 harness 增加 `HarnessEventDraft` 机制，使 attempt 内部步骤能稳定写回事件流
- 新增测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
- 覆盖场景：
  - model -> policy -> tool success
  - tool execution failed path
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Structured Run Output And Retry Skeleton

- 执行 `P3-HAR-03 - Structured Run Output And Retry Skeleton`
- 新增：
  - `HarnessRunResult`
  - `HarnessStopReason`
  - `HarnessStoppingPolicy`
- `HarnessLoopResult` 现在包含结构化 `run_result`
- 当前 loop 仍然只执行单次 attempt，但已经能稳定给出：
  - 最终 outcome
  - stop reason
  - attempts used
  - max attempts
  - can retry
- 新增测试：
  - `tests/agent_core/test_harness_stopping.py`
- 覆盖场景：
  - failed but retryable
  - retry exhausted
  - loop 暴露结构化 run result
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Multi-Attempt Loop Driver

- 执行 `P3-HAR-04 - Multi-Attempt Loop Driver`
- `HarnessLoop` 从单次 attempt 升级为 bounded multi-attempt driver
- 当前行为：
  - 如果失败且 `can_retry=true`，继续下一次 attempt
  - 成功后立即停止
  - 达到重试预算后终止并返回 `retry_exhausted`
- `HarnessLoopResult` 现在保留 `attempt_results`
- 新增测试：
  - `tests/agent_core/test_harness_multi_attempt.py`
- 覆盖场景：
  - 第一次失败，第二次成功
  - 重试预算耗尽后失败终止
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Assistant And Tool Trace Projection

- 执行 `P3-HAR-05 - Assistant Message And Tool Trace Projection`
- 新增：
  - `HarnessToolTrace`
  - `HarnessAttemptTrace`
  - `HarnessRunTrace`
  - `HarnessTraceProjector`
- `SingleAttemptOrchestrator` 现在在 emitted events 中显式携带 `attempt_number`
- 当前 projection 可以把 assistant message、tool proposal、policy decision、tool result 投影为紧凑 run-facing trace
- 新增测试：
  - `tests/agent_core/test_harness_trace_projection.py`
- 覆盖场景：
  - successful tool trace
  - failed tool trace
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Attempt Event Timestamp Refinement

- 执行 `P3-HAR-06 - Attempt Event Timestamp Refinement`
- 新增：
  - `SystemClock`
  - `StepClock`
- `HarnessLoop` 现在通过 `ClockPort` 驱动事件时间，不再把整次 run 的所有事件压成同一个 `created_at`
- 当前行为：
  - 初始化事件按时钟顺序推进

## 2026-06-22 Model Call Index

- 执行 `P4-STO-05 - Model Call Index`
- 为核心模型调用补齐 durable 索引闭环：
  - `agent_core.domain.model_calls.ModelCallRecord`
  - `agent_core.ports.model_call_store.ModelCallStorePort`
  - `agent_core.domain.modeling` 中的 `ModelCallMetadata` 与 `ModelUsage`
- `SingleAttemptOrchestrator` 现在会把以下字段写入 `MODEL_RESPONSE_RECEIVED` 事件：
  - `provider`
  - `model_name`
  - `input_tokens`
  - `output_tokens`
  - `total_tokens`
  - `latency_ms`
  - `cache_hit`
  - `cost_usd`
- 新增 `agent_storage.model_calls.SQLiteModelCallStore`
- 新增 `zebra_agent_worker.model_call_index.ModelCallIndexer`
- 新增测试：
  - `tests/agent_storage/test_sqlite_model_calls.py`
  - `tests/worker/test_model_call_index.py`
  - `tests/agent_core/test_single_attempt_orchestrator.py` 中的模型响应元数据断言
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py tests/agent_core/test_single_attempt_orchestrator.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage apps/worker/src/zebra_agent_worker tests/agent_core/test_single_attempt_orchestrator.py tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage apps/worker/src/zebra_agent_worker tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py` 通过
  - `make check` 通过

## 2026-06-22 Context Compiler Bootstrap

- 执行 `P5-CTX-01 - Context Compiler Bootstrap`
- 将 `agent-context` 从占位返回值升级为最小可用的 deterministic compiler：
  - `ContextItemKind`
  - `ContextProvenance`
  - `ContextItem`
  - `ContextBudget`
  - `ContextCompileRequest`
  - `CompiledContext`
- `compile_context` 现在支持：
  - workspace 扫描
  - root/doc 文件优先
  - 基于任务词和路径的基础打分
  - repo map 引导项
  - token budget 裁剪与 `truncated` 标记
- 新增测试：
  - `tests/agent_context/test_compiler.py`
  - `tests/smoke/test_workspace_bootstrap.py` 中的真实编译路径断言
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Related Files Recall And Ranking Split

- 执行 `P5-CTX-02 - Related Files Recall And Ranking Split`
- 将 `agent-context` 进一步拆分为更清晰的职责边界：
  - `scanner.py`
  - `ranking.py`
  - `related.py`
  - `compiler.py`
- 新增 `ContextItemKind.RELATED_FILE`
- `compile_context` 现在除了主排序文件外，还会基于本地 Python import 关系补充 related file context items
- 新增测试：
  - `tests/agent_context/test_compiler.py` 中的 related-file recall 场景
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Conversation And Tool Output Compaction

- 执行 `P5-CTX-03 - Conversation And Tool Output Compaction`
- 新增 `agent_context.compaction`：
  - `ConversationCompactionRequest`
  - `ToolOutputCompactionRequest`
  - `ToolOutputEvidence`
  - `compact_conversation`
  - `compact_tool_outputs`
- 新增 `ContextItemKind`：
  - `CONVERSATION_SUMMARY`
  - `TOOL_OUTPUT_SUMMARY`
- 当前 compaction 行为：
  - 保留用户目标、验收、约束、计划、修改文件、失败尝试、未解决测试、审批、artifact 等关键 section
  - 对工具输出做结构化单行压缩
  - 在 token budget 下做 deterministic truncation
- 新增测试：
  - `tests/agent_context/test_compaction.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Prompt Layout And Cache Key Rules

- 执行 `P5-CTX-04 - Prompt Layout And Cache Key Rules`
- 新增 `agent_context.prompt_layout`：
  - `PromptSectionKind`
  - `PromptSection`
  - `PromptLayout`
  - `PromptCacheKeyRequest`
  - `build_prompt_layout`
  - `build_prompt_cache_key`
- 当前 prompt-layout 行为：
  - `AGENTS.md` / `README.md` 等稳定项目指导进入 stable section
  - `Repo Map`、代码片段、related files 进入 semi-stable section
  - conversation/tool-output compaction items 进入 dynamic section
- 当前 cache-key 行为会显式纳入：
  - `task_input`
  - `workspace_root`
  - `model_profile`
  - `policy_summary`
  - `tool_manifest`
  - 各 section 的序列化 context items
- 新增测试：
  - `tests/agent_context/test_prompt_layout.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Trust Marking And Prompt-Injection Baseline

- 执行 `P5-CTX-05 - Trust Marking And Prompt-Injection Baseline`
- 新增 `agent_context.trust`：
  - `trust_level_for_item`
  - `prompt_injection_metadata`
- `ContextItem` 现在补充：
  - `trust_level`
  - `metadata`
- 当前 trust baseline：
  - `Repo Map` 标记为 `system`
  - `AGENTS.md` / `README.md` / `pyproject.toml` / `Makefile` 标记为 `trusted`
  - conversation/tool-output summaries 标记为 `user`
  - 代码文件默认标记为 `untrusted`
- 当前 injection baseline：
  - 仅做 suspicious pattern metadata 标记
  - 不做自动拒绝或策略联动
- 新增测试：
  - `tests/agent_context/test_compiler.py` 中的 suspicious-content 标记断言
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - 每次 attempt 有独立 `started_at`
  - emitted events 和 terminal events 继续沿时钟推进
- 新增测试：
  - `tests/agent_core/test_harness_multi_attempt.py` 中的时间顺序断言
- 覆盖场景：
  - 多 attempt 事件时间递增
  - 同一 run 内时间顺序稳定可预测
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Planner And Verifier Hooks

- 执行 `P3-HAR-07 - Planner And Verifier Hooks`
- 新增：
  - `PlannerHook`
  - `VerifierHook`
  - `PlannerResult`
  - `VerifierResult`
  - `NoopPlanner`
  - `NoopVerifier`
- `SingleAttemptOrchestrator` 现在有显式 planner / verifier hook 点：
  - planner 在 tool call proposal 前参与
  - verifier 在 tool result 后参与
- emitted events 里新增：
  - `PLAN_PROPOSED`
  - `TESTS_COMPLETED` 作为最小 verifier 完成事件
- 新增测试：
  - `tests/agent_core/test_harness_hooks.py`
- 覆盖场景：
  - planner 和 verifier 在一次 run 中被调用
  - 结构化 metadata 回写到 attempt result
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Session Event Builder Cleanup

- 执行 `P3-HAR-08 - Session Event Builder Cleanup`
- 新增 `HarnessEventRecorder`
- 统一收拢：
  - `SessionEvent.create`
  - sequence 递增
  - append 到事件流
  - `apply_event` 投影回 session
  - clock 驱动的 `created_at`
- `HarnessLoop` 改为通过 recorder 记录初始化、attempt、draft 和 terminal 事件
- 新增测试：
  - `tests/agent_core/test_harness_recorder.py`
- 覆盖场景：
  - recorder 正常记录事件
  - sequence 递增
  - session projection 行为保持不变
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_recorder.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Tool Call Selection Strategy

- 执行 `P3-HAR-09 - Tool Call Selection Strategy`
- 新增：
  - `ToolCallSelection`
  - `ToolCallSelectionStrategy`
  - `FirstToolCallSelectionStrategy`
- `SingleAttemptOrchestrator` 现在通过显式 selector 选择 tool call，不再内联硬编码 `completion.tool_calls[0]`
- 当前行为：
  - 默认策略仍然稳定选择第一个 tool call
  - selection summary 和 metadata 会进入 proposal event 与 attempt metadata
- 新增测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
- 覆盖场景：
  - 默认选择策略的确定性
  - multi-tool completion 下 orchestrator 只执行选中的 tool call
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Explicit Harness Budgets

- 执行 `P3-HAR-10 - Explicit Harness Budgets`
- 新增：
  - `HarnessTask.max_model_calls`
  - `HarnessTask.max_tool_calls`
  - `HarnessRunResult` 的 budget usage / limit 字段
  - `MODEL_CALL_BUDGET_EXHAUSTED`
  - `TOOL_CALL_BUDGET_EXHAUSTED`
- `HarnessLoop` 现在会把 task budget 写入 `TASK_PREPARED` event，并累计每次 attempt 的 model/tool usage
- `SingleAttemptOrchestrator` 现在会在 attempt metadata 中显式回传：
  - `model_calls_used`
  - `tool_calls_executed`
- `HarnessStoppingPolicy` 现在会在 retry 判断前先检查 model/tool budget 是否已经耗尽
- 新增测试：
  - `tests/agent_core/test_harness_stopping.py`
  - `tests/smoke/test_mock_harness_loop.py`
- 覆盖场景：
  - tool call budget exhausted
  - model call budget exhausted
  - loop 因 tool budget 耗尽而停止重试
  - mock harness loop 端到端 smoke 闭环
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/smoke/test_mock_harness_loop.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core tests/smoke` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 SQLite Event Store And Session Projection

- 执行 `P4-STO-01 - SQLite Event Store And Session Projection`
- 新增 `agent-storage` workspace package
- 新增：
  - `SQLiteEventStore`
  - `SQLiteProjectionStore`
  - SQLite 连接与 event row 映射辅助模块
- 当前行为：
  - session events 可按 `session_id + sequence` 顺序持久化和读取
  - 同一 session 的重复 sequence 会被 SQLite 唯一约束拒绝
  - 读取出的 event stream 可以直接喂给 `rebuild_session`
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
  - `tests/agent_storage/test_sqlite_projection_store.py`
- 覆盖场景：
  - append/list session events
  - duplicate sequence rejection
  - replay into session projection
  - save/get session projection
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-storage/src/agent_storage tests/agent_storage tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-20 Event Idempotency Protection

- 执行 `P4-STO-02 - Event Idempotency Protection`
- `SQLiteEventStore` 现在会为 `session_id + idempotency_key` 建立唯一索引
- 当前行为：
  - 同一 session 下，带相同 `idempotency_key` 的重试写入不会产生第二条事件
  - `append()` 在幂等重试时会返回已存在的 durable event
  - 原有 `session_id + sequence` 冲突保护保持不变
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
- 覆盖场景：
  - idempotent retry returns existing event
  - duplicate sequence rejection still works
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py` 通过
  - `uv run ruff check packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `uv run mypy packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-20 Worker Recovery Entry

- 执行 `P4-WKR-01 - Worker Recovery Entry`
- `apps/worker` 新增：
  - `SessionRecoveryService`
  - `RecoveredSession`
  - `SessionRecoveryError`
- 当前行为：
  - worker 可以从 event store 读取一个 session 的完整事件流
  - 通过 `rebuild_session` 重建 durable session 视图
  - recovery 后会把最新 projection 写回 projection store
  - 缺失 session 会以确定性错误失败
- 新增测试：
  - `tests/worker/test_recovery.py`
- 覆盖场景：
  - interrupted running session recovery
  - terminal session recovery
  - missing session failure
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/worker/test_recovery.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-21 SQLite Worker Leases

- 执行 `P4-SCH-01 - SQLite Worker Leases`
- `agent-core` 新增：
  - `WorkerLease`
  - `LeaseStorePort`
- `agent-storage` 新增：
  - `SQLiteLeaseStore`
  - `LeaseConflictError`
- 当前行为：
  - worker 可以为某个 session 申请 lease
  - 未过期 lease 不允许被其他 worker 抢占
  - 过期 lease 可以被后续 worker 重新获取
  - 已持有 worker 可以 heartbeat 更新 checkpoint 和 expiry
  - release 后 lease 会被删除
- 新增测试：
  - `tests/agent_storage/test_sqlite_leases.py`
- 覆盖场景：
  - acquire and read active lease
  - reject other worker before expiry
  - allow reacquire after expiry
  - heartbeat owned lease
  - release owned lease
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_leases.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_storage tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-21 Worker Claim And Resume Flow

- 执行 `P4-WKR-02 - Worker Claim And Resume Flow`
- `apps/worker` 新增：
  - `SessionClaimService`
  - `ClaimedSession`
- 当前行为：
  - worker 可以先恢复 session，再申请 lease 完成 claim
  - claim 结果同时包含 recovery state 和 lease state
  - 已 claim session 可以 heartbeat 续租并推进 checkpoint
  - 可以显式 release claim
- 新增测试：
  - `tests/worker/test_claims.py`
- 覆盖场景：
  - claim running session
  - block concurrent claim before expiry
  - allow takeover after expiry
  - heartbeat and release claim
- 本轮验证结果：
  - `uv run pytest tests/worker/test_claims.py tests/worker/test_recovery.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-21 Core Event Schema Drafts

- 执行 `P4-GOV-01 - Core Event Schema Drafts`
- `agent-core` 新增：
  - `agent_core.contracts`
  - `event_payload_schema_for`
  - `validate_event_payload`
  - `EventPayloadValidationError`
- 当前行为：
  - `SessionCreated`、`UserMessageReceived`、`ToolExecutionCompleted` 已有 machine-checkable payload schema
  - covered payload 默认拒绝未知字段
  - 可以直接生成 JSON Schema dict，供后续 API / storage / docs 复用
- 新增测试：
  - `tests/agent_core/test_event_contracts.py`
- 覆盖场景：
  - schema generation
  - valid payload acceptance
  - unknown field rejection
  - unknown event schema lookup failure
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_event_contracts.py tests/agent_core/test_events.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/contracts tests/agent_core/test_event_contracts.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/contracts tests/agent_core/test_event_contracts.py` 通过
  - `make check` 通过

## 2026-06-21 Event Schema Enforcement

- 执行 `P4-GOV-02 - Event Schema Enforcement`
- `SessionEvent.create()` 现在会对已覆盖的 event payload 执行 schema 校验
- 当前行为：
  - covered event 在创建时即拒绝非法 payload
  - 未覆盖 event 暂时保持 passthrough，避免阻塞后续 schema 逐步补齐
- 新增测试：
  - `tests/agent_core/test_events.py`
- 覆盖场景：
  - invalid covered-event payload rejection
  - uncovered event payload passthrough
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py tests/agent_storage/test_sqlite_event_store.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/domain/events.py tests/agent_core/test_events.py tests/agent_storage/test_sqlite_event_store.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/domain/events.py tests/agent_core/test_events.py` 通过
  - `make check` 通过

## 2026-06-22 Incremental Event Replay

- 执行 `P4-STO-03 - Incremental Event Replay`
- `EventStorePort` 新增 `read_since(session_id, sequence)`
- `SQLiteEventStore` 现在支持按 sequence 增量读取 session 事件
- `SessionRecoveryService` 现在会优先读取已有 projection，并只回放其后的增量事件
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
  - `tests/worker/test_recovery.py`
- 覆盖场景：
  - event-store delta reads
  - projection-based resume with newer events
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/ports/event_store.py packages/agent-storage/src/agent_storage/sqlite.py apps/worker/src/zebra_agent_worker/recovery.py tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/ports/event_store.py packages/agent-storage/src/agent_storage/sqlite.py apps/worker/src/zebra_agent_worker/recovery.py tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `make check` 通过

## 2026-06-22 Explicit Resume Entry

- 执行 `P4-WKR-03 - Explicit Resume Entry`
- `apps/worker` 新增：
  - `SessionResumeService`
  - `ResumedSession`
  - `SessionResumeError`
- 当前行为：
  - worker 可以通过单个 resume entry 完成 claim + recovery
  - terminal session 会被明确拒绝
  - terminal resume 失败后不会遗留 lease
- 新增测试：
  - `tests/worker/test_resume.py`
- 覆盖场景：
  - resume running session
  - reject terminal session without dangling lease
- 本轮验证结果：
  - `uv run pytest tests/worker/test_resume.py tests/worker/test_claims.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-22 Tool Run Index

- 执行 `P4-STO-04 - Tool Run Index`
- `agent-core` 新增：
  - `ToolRunRecord`
  - `ToolRunStorePort`
- `agent-storage` 新增：
  - `SQLiteToolRunStore`
- `apps/worker` 新增：
  - `ToolRunIndexer`
- 当前行为：
  - tool execution event 可以被映射为 durable tool-run record
  - control plane 可以按 session 查询 tool run 索引，而不是每次直接扫描原始 event payload
- 新增测试：
  - `tests/agent_storage/test_sqlite_tool_runs.py`
  - `tests/worker/test_tool_run_index.py`
- 覆盖场景：
  - tool-run upsert and query
  - event-to-tool-run indexing
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/domain/tool_runs.py packages/agent-core/src/agent_core/ports/tool_run_store.py packages/agent-storage/src/agent_storage/tool_runs.py apps/worker/src/zebra_agent_worker/tool_run_index.py tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/domain/tool_runs.py packages/agent-core/src/agent_core/ports/tool_run_store.py packages/agent-storage/src/agent_storage/tool_runs.py apps/worker/src/zebra_agent_worker/tool_run_index.py tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py` 通过
  - `make check` 通过

## 2026-06-22 Runtime Evidence Context Injection

- 执行 `P5-CTX-07 - Runtime Evidence Context Injection`
- `ContextCompileRequest` 新增：
  - `runtime_evidence_items`
- 当前行为：
  - 允许把 `CONVERSATION_SUMMARY` 与 `TOOL_OUTPUT_SUMMARY` 作为 runtime evidence 注入编译输入
  - 这些 items 和普通 context items 一样参与统一 token budget
  - prompt layout 会把它们路由到 dynamic section
- 新增测试：
  - `tests/agent_context/test_runtime_evidence.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Attempt Evidence Feedback Loop

- 执行 `P5-CTX-08 - Attempt Evidence Feedback Loop`
- `agent-core` 新增：
  - `RuntimeEvidenceInput`
- `HarnessLoop` 现在支持：
  - 从 prior attempt result 提取 conversation summary evidence
  - 从 prior attempt result 提取 tool-output evidence
  - 在 retry attempt 前把 evidence 填回 `HarnessTask.runtime_evidence`
- `LocalContextCompiler` 现在支持：
  - 接收抽象 runtime-evidence inputs
  - 把它们压缩成 dynamic context items
- 新增测试：
  - `tests/agent_core/test_harness_runtime_evidence.py`
  - `tests/agent_context/test_adapter.py` 中的 runtime-evidence 渲染场景
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Path Risk Rules

- 执行 `P6-POL-03 - Path Risk Rules`
- `LocalPolicyEngine` 现在支持：
  - `files.read` path traversal 预检
  - `git.status` 与 `command.run` cwd traversal/absolute path 预检
  - `patch.apply` patch header path traversal 预检
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过

## 2026-06-22 Sensitive Output Rules

- 执行 `P6-POL-04 - Sensitive Output Rules`
- `LocalPolicyEngine` 现在支持：
  - sensitive path marker 检测
  - network-capable data transfer command 检测
  - 明显 secret exfiltration 风险进入 approval
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过

## 2026-06-22 Context-Aware Retry Plan Hint

- 执行 `P5-CTX-10 - Context-Aware Retry Plan Hint`
- `agent-core` 新增：
  - `RetryPlanHint`
  - `build_retry_plan_hint`
- 默认 `NoopPlanner` 现在支持：
  - 在 retry attempt 存在 runtime evidence 时生成 deterministic retry summary
  - 在 planner metadata 中暴露 retry focus、retry blockers、accepted constraints、prior tool outputs
- 当前行为：
  - `planner_summary` 会成为 retry focus
  - failed `verifier_summary` 与 failed `tool_status` 会成为 retry blockers
  - passed `verifier_summary` 会成为 accepted constraints
- 新增测试：
  - `tests/agent_core/test_harness_retry_plan.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `make check` 通过

## 2026-06-22 Context Compiler Acceptance Hardening

- 执行 `P5-CTX-11 - Context Compiler Acceptance Hardening`
- `ContextCompileRequest` 现在校验：
  - `workspace_root` 必须存在
  - `workspace_root` 必须是目录
  - runtime evidence 只能使用 conversation/tool-output summary kinds
  - runtime evidence provenance 必须来自 session projection 或 tool trace
- 新增/更新测试：
  - `tests/agent_context/test_compiler.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - `make check` 通过

## 2026-06-22 Phase 5 Closeout Record

- 执行 `P5-CTX-12 - Phase 5 Closeout Record`
- 新增文档：
  - `docs/Phase5_Context_Compiler_验收记录.md`
- 当前状态：
  - Phase 5 context compiler local MVP scope 已关闭
  - `PROGRESS.md` 已推进到 `Phase 6 - Policy And Approvals Hardening`
  - Git context provider、durable context-compacted events、persistent context cache 明确作为后续项
- 本轮验证结果：
  - `uv run pytest tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context packages/agent-core/src/agent_core/ports/context_compiler.py packages/agent-core/src/agent_core/harness/model_step.py packages/agent-core/src/agent_core/harness/loop.py packages/agent-core/src/agent_core/harness/retry_plan.py tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context packages/agent-core/src/agent_core/ports/context_compiler.py packages/agent-core/src/agent_core/harness/model_step.py packages/agent-core/src/agent_core/harness/loop.py packages/agent-core/src/agent_core/harness/retry_plan.py tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py` 通过
  - `make check` 通过

## 2026-06-22 Local Policy Profiles

- 执行 `P6-POL-01 - Local Policy Profiles`
- `agent-security` 新增：
  - `PolicyProfile`
  - `LocalPolicyEngine`
- 当前行为：
  - `read_only` 允许 `files.read`、`git.status`
  - `workspace_write` 允许 `patch.apply`、`tests.run`，但 `command.run` 进入 approval
  - `full_access` 允许已知本地工具
  - 未知工具在所有 profile 下拒绝
- 新增测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过

## 2026-06-22 Approval Request Model

- 执行 `P6-POL-05 - Approval Request Model`
- `agent-security` 新增：
  - `ApprovalRisk`
  - `ApprovalRequest`
  - `build_approval_request`
- 当前行为：
  - allow/deny decision 不生成 approval request
  - approval request 携带 tool、profile、reason、risk、scope
  - sensitive transfer approval 标记为 high risk
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过

## 2026-06-22 Approval Event Wiring

- 执行 `P6-POL-06 - Approval Event Wiring`
- `SingleAttemptOrchestrator` 现在支持：
  - `REQUIRE_APPROVAL` policy decision 发出 `APPROVAL_REQUESTED`
  - approval-required tool call 不执行 tool gateway
  - attempt metadata 保留 `policy_decision=require_approval`
- `Session` 状态机现在允许：
  - 当前 local MVP 里的 `waiting_approval -> failed` terminal path
- 更新测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
  - `tests/agent_core/test_session_projection.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_domain_models.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_domain_models.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_domain_models.py` 通过
  - `uv run pytest` 通过，144 passed
  - `make check` 通过

## 2026-06-22 Approval Decision Projection

- 执行 `P6-POL-07 - Approval Decision Projection`
- `SessionProjection` 现在支持：
  - `APPROVAL_GRANTED` 将 waiting approval session 恢复为 running
  - `APPROVAL_REJECTED` 将 waiting approval session 投影为 failed
- 更新测试：
  - `tests/agent_core/test_session_projection.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/application/session_projection.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/application/session_projection.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py` 通过
  - `uv run pytest` 通过，146 passed
  - `make check` 通过

## 2026-06-22 Approval Service Entry

- 执行 `P6-POL-08 - Approval Service Entry`
- `agent-core.application` 新增：
  - `ApprovalDecisionAction`
  - `ApprovalDecisionCommand`
  - `ApprovalDecisionService`
- 当前行为：
  - grant command 构造 `APPROVAL_GRANTED`
  - reject command 构造 `APPROVAL_REJECTED`
  - approval decision 必须基于 `WAITING_APPROVAL` session
  - approval decision sequence 必须连续
- 新增测试：
  - `tests/agent_core/test_approval_decisions.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_approval_decisions.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/domain/sessions.py tests/agent_core/test_approval_decisions.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/domain/sessions.py tests/agent_core/test_approval_decisions.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py` 通过
  - `uv run pytest` 通过，150 passed
  - `make check` 通过

## 2026-06-22 Phase 6 Closeout Record

- 执行 `P6-POL-09 - Phase 6 Closeout Record`
- 新增文档：
  - `docs/Phase6_Policy_Approvals_验收记录.md`
- 当前状态：
  - Phase 6 policy and approvals local MVP scope 已关闭
  - `PROGRESS.md` 已推进到 `Phase 7 - Eval And Observability`
  - MCP-specific rules、network egress broker、credential broker、approval API adapters 明确作为后续项
- 本轮验证结果：
  - `uv run pytest tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/harness/orchestrator.py packages/agent-core/src/agent_core/domain/sessions.py tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/harness/orchestrator.py packages/agent-core/src/agent_core/domain/sessions.py tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py` 通过
  - `uv run pytest` 通过，150 passed
  - `make check` 通过

## 2026-06-22 Observability Models Bootstrap

- 执行 `P7-OBS-01 - Observability Models Bootstrap`
- 新增 workspace package：
  - `packages/agent-observability`
- 当前行为：
  - session event stream 可以构造 `TraceRecord`
  - trace 包含 event count、tool result count、audit records、cost summary
  - 空 event stream 和 mixed session stream 会被拒绝
- 新增测试：
  - `tests/agent_observability/test_trace_models.py`
- 本轮验证结果：
  - `uv sync --all-packages --group dev` 通过
  - `uv run pytest tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability/test_trace_models.py` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability/test_trace_models.py` 通过
  - `uv run pytest` 通过，154 passed
  - `make check` 通过

## 2026-06-22 CLI Model Gateway Smoke

- 执行 `P8-MOD-02 - CLI Model Gateway Smoke`
- 新增：
  - `zebra-agent model "<prompt>"`
  - CLI 到 `agent-integrations.build_model_gateway(...)` 的依赖 wiring
- 当前行为：
  - 发送一条 user prompt 到当前 provider settings 对应的 model gateway
  - 返回 assistant response、provider/model/usage metadata
  - 缺失 API key 时在发请求前确定性失败
  - 不改变现有 `run` / `inspect` / `resume` / `approve` 行为
- 文档更新：
  - `docs/operator_runbook.md` 增加 model smoke 命令
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run pytest tests/cli/test_cli_commands.py` 通过，12 passed
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run pytest` 通过，216 passed
  - `make check` 通过

## 2026-06-22 OpenAI-Compatible Model Gateway Adapter

- 执行 `P8-MOD-01 - OpenAI-Compatible Model Gateway Adapter`
- 新增：
  - `packages/agent-integrations`
  - `OpenAICompatibleModelGateway`
  - `build_model_gateway(settings, env=...)`
- 当前行为：
  - 使用 OpenAI-compatible `/chat/completions` 接口
  - 将 core `SessionMessage` 序列化为 chat messages
  - 解析 assistant text、usage、tool calls 到 `ModelCompletion`
  - 缺失 API key 时在发请求前确定性失败
- 当前边界：
  - 这是 provider adapter foundation，还没有接到 CLI/API 执行主路径
  - 当前按 DeepSeek 文档使用 `https://api.deepseek.com/chat/completions`
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run pytest tests/agent_integrations/test_openai_compatible.py` 通过，4 passed
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations` 通过
  - `uv run mypy packages/agent-integrations tests/agent_integrations` 通过
  - `uv run pytest` 通过，213 passed
  - `make check` 通过

## 2026-06-22 Local API Auth Foundation

- 执行 `P8-API-05 - Local API Auth Foundation`
- 新增：
  - `ZEBRA_API_AUTH_TOKEN` settings support
  - optional bearer-token auth guard for non-health API routes
- 当前行为：
  - `/health` 始终公开
  - 未配置 auth token 时，当前本地 API 行为不变
  - 配置 auth token 后，session read 和 stream 路径要求 `Authorization: Bearer ...`
  - 鉴权失败返回确定性的 `401 unauthorized`
- 文档更新：
  - `docs/operator_runbook.md` 增加本地 token 用法
- 本轮验证结果：
  - `uv run pytest tests/config/test_settings.py tests/api/test_http_app.py tests/api/test_api_app.py tests/cli/test_cli_commands.py` 通过，29 passed
  - `uv run ruff check apps/config/src/zebra_agent_config apps/api/src/zebra_agent_api tests/config tests/api tests/cli` 通过
  - `uv run mypy apps/config apps/api tests/config tests/api` 通过
  - `uv run pytest` 通过，209 passed
  - `make check` 通过

## 2026-06-22 Operator Runbook

- 执行 `P8-DOC-01 - Operator Runbook`
- 新增：
  - `docs/operator_runbook.md`
  - `make api-serve`
  - `uvicorn` local operator dependency
- 行为对齐：
  - CLI `run` 现在会写入 `session_created` bootstrap event
  - 刚创建的 session 可以立即被 `/sessions/{id}/stream` replay
- 文档覆盖：
  - local bootstrap
  - CLI `run` / `inspect` / `resume` / `approve`
  - API `health` / `sessions/{id}`
  - SSE `sessions/{id}/stream`
- 手工验证结果：
  - `make api-serve` 可启动本地 API
  - `uv run zebra-agent run ...` 可创建 session
  - `curl /health`、`curl /sessions/{id}`、`curl -N /sessions/{id}/stream` 均验证通过
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run python -c "import uvicorn; print(uvicorn.__version__)"` 通过
  - `uv run pytest tests/cli/test_cli_commands.py` 通过，9 passed
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run pytest` 通过，204 passed
  - `make check` 通过

## 2026-06-22 Session Stream Foundation

- 执行 `P8-API-04 - Session Stream Foundation`
- 新增：
  - `GET /sessions/{session_id}/stream` 路径
  - API session event listing for one session
  - HTTP `text/event-stream` replay built from persisted session events
- 当前行为：
  - stream 端点按 sequence 顺序回放当前已持久化事件
  - 缺失 session 继续返回确定性的 `not_found`
  - 普通 `GET /sessions/{session_id}` 行为不变
  - 当前是 replay foundation，不是实时增量订阅
- 新增测试：
  - API session stream read path
  - route adapter session stream path handling
  - HTTP SSE replay and missing-session coverage
- 本轮验证结果：
  - `uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py` 通过，18 passed
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，204 passed
  - `make check` 通过

## 2026-06-22 FastAPI Serving Foundation

- 执行 `P8-API-03 - FastAPI Serving Foundation`
- 新增：
  - `zebra_agent_api.http.create_http_app`
  - FastAPI request/response adapter over existing `RouteAdapter`
  - HTTP tests for health, session lookup, unknown path, and unsupported method
- 当前行为：
  - `GET /health` 复用现有 health payload
  - `GET /sessions/{session_id}` 复用现有 session lookup payload
  - 未支持路径和方法继续返回确定性的 `not_found`
  - FastAPI handler 不直接承载领域逻辑
- 依赖更新：
  - `apps/api` 增加 `fastapi`
  - root dev group 增加 `httpx`
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py` 通过，12 passed
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，198 passed
  - `make check` 通过

## 2026-06-22 Entry Point Settings Wiring

- 执行 `P8-CONFIG-02 - Entry Point Settings Wiring`
- 新增行为：
  - CLI `run`、`resume`、`inspect`、`approve` 在未传 `--database` 时使用 `zebra-agent-config` 的 `database_url`
  - CLI 显式 `--database` 继续覆盖 settings
  - API `create_app()` 在未传 database path 时使用 settings database URL
  - API 显式 database path 继续覆盖 settings
- 更新依赖：
  - `apps/cli` 依赖 `zebra-agent-config`
  - `apps/api` 依赖 `zebra-agent-config`
- 新增测试：
  - CLI settings database default
  - CLI explicit database override
  - API settings database default
  - API explicit database override
- 本轮验证结果：
  - `uv lock` 通过
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_api_app.py` 通过，14 passed
  - `uv run ruff check apps/cli/src/zebra_agent_cli apps/api/src/zebra_agent_api tests/cli tests/api` 通过
  - `uv run mypy apps/cli apps/api tests/cli tests/api` 通过
  - `uv run pytest` 通过，194 passed
  - `make check` 通过

## 2026-06-22 Local Settings Loader

- 执行 `P8-CONFIG-01 - Local Settings Loader`
- 新增：
  - `apps/config`
  - `configs/default.env`
  - typed `ZebraAgentSettings`
  - typed `ModelSettings`
- 当前行为：
  - 默认 profile 为 `local`
  - 默认 database 为 `.zebra-agent/sessions.sqlite`
  - 默认 model provider 为 `deepseek`
  - 默认 model 为 `deepseek-v4-flash`
  - env values 可以覆盖 repository defaults
- 新增测试：
  - `tests/config/test_settings.py`
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/config/test_settings.py` 通过，2 passed
  - `uv run ruff check apps/config/src/zebra_agent_config tests/config` 通过
  - `uv run mypy apps/config tests/config` 通过
  - `uv run pytest` 通过，190 passed
  - `make check` 通过

## 2026-06-22 API Route Adapter

- 执行 `P8-API-02 - API Route Adapter`
- `apps/api` 新增：
  - `RouteRequest`
  - `RouteAdapter`
- 当前行为：
  - `GET /health` 路由到 health handler
  - `GET /sessions/{session_id}` 路由到 session lookup handler
  - unsupported routes 返回 deterministic 404/not_found
  - route adapter 仍不依赖外部 HTTP framework
- 新增测试：
  - `tests/api/test_routes.py`
- 本轮验证结果：
  - `uv run pytest tests/api/test_routes.py tests/api/test_api_app.py` 通过
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，188 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 API Health And Session Foundation

- 执行 `P8-API-01 - API Health And Session Foundation`
- `apps/api` 更新：
  - `ZebraAgentApi`
  - `ApiResponse`
  - health handler
  - session lookup handler
- 当前行为：
  - API app 仍是无外部 framework 的 composition object
  - health 返回 service status
  - session lookup 通过 `SQLiteProjectionStore` 读取 projection
  - missing session 返回 404/not_found
- 新增测试：
  - `tests/api/test_api_app.py`
- 更新测试：
  - `tests/smoke/test_workspace_bootstrap.py`
- 本轮验证结果：
  - `uv lock` 通过
  - `uv run pytest tests/api/test_api_app.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，185 passed
  - `make check` 通过，包含 eval release gate
  - 说明：直接 mypy `tests/smoke/test_workspace_bootstrap.py` 会触发既有未标记 `py.typed` 的包导入问题，默认 `make check` 不检查 tests

## 2026-06-22 CLI Approve Local Decision

- 执行 `P8-CLI-04 - CLI Approve Local Decision`
- `apps/cli` 更新：
  - `approve --database`
  - `approve --operator`
  - `ApprovalDecisionService` 本地组合
  - `SQLiteEventStore` approval event append
  - `SQLiteProjectionStore` session projection update
- 当前行为：
  - waiting approval session 可以通过 CLI 记录 grant/reject
  - non-waiting session 返回 deterministic `invalid_state`
  - missing session 返回 deterministic `not_found`
- 更新测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run pytest` 通过，182 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 CLI Inspect And Resume Session Read

- 执行 `P8-CLI-03 - CLI Inspect And Resume Session Read`
- `apps/cli` 更新：
  - `inspect --database`
  - `resume --database`
  - `SQLiteProjectionStore` session projection lookup
- 当前行为：
  - `inspect` 和 `resume` 可以读取 session title、status、current_sequence
  - missing session 返回 deterministic `not_found`
  - `resume` 仍不修改 session 状态，也不启动 worker execution
- 更新测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run zebra-agent run ...` 后接 `uv run zebra-agent inspect ...` 通过
  - `uv run pytest` 通过，181 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 CLI Run Local Session Creation

- 执行 `P8-CLI-02 - CLI Run Local Session Creation`
- `apps/cli` 更新：
  - `run --database`
  - `Session.create` 本地组合
  - `SQLiteProjectionStore` session projection 持久化
- 当前行为：
  - `zebra-agent run` 会创建本地 session id
  - 输出包含 session id、status、prompt、title、workspace、database
  - worker execution 和 model orchestration 仍留给后续任务
- 更新测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv lock` 通过
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run zebra-agent run "Fix tests" --title "Fix failing tests" --database /tmp/zebra-agent-cli-session.sqlite` 通过
  - `uv run pytest` 通过，180 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 CLI Command Skeleton

- 执行 `P8-CLI-01 - CLI Command Skeleton`
- `apps/cli` 新增：
  - deterministic CLI parser
  - `run` command intent output
  - `resume` command intent output
  - `inspect` command intent output
  - `approve` command intent output
- 当前行为：
  - CLI 命令只输出本地 intent，不提前接 storage、worker 或 API
  - `main.py` 保持入口转发，解析逻辑在 `cli.py`
- 新增测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run zebra-agent run "Fix tests" --title "Fix failing tests"` 通过
  - `uv run pytest` 通过，180 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 Phase 7 Closeout Record

- 执行 `P7-EVAL-06 - Phase 7 Closeout Record`
- Phase 7 验收证据：
  - trace/audit/cost models 已由 `P7-OBS-01` 覆盖
  - local JSONL trace persistence 已由 `P7-OBS-02` 覆盖
  - local replay runner 已由 `P7-OBS-03` 覆盖
  - eval case/grader/runner 已由 `P7-EVAL-01` 和 `P7-EVAL-02` 覆盖
  - bugfix/refactor/recovery/security/analysis baseline cases 已由 `P7-EVAL-03` 覆盖
  - local release gate 与 `make check` 集成已由 `P7-EVAL-04` 和 `P7-EVAL-05` 覆盖
- Phase 8 ready 状态：
  - 下一阶段从 CLI/API Productization 开始
  - 首批任务应围绕 `run`、`resume`、`inspect`、`approve` CLI 命令和 API health/session foundation 注册
- 本轮验证结果：
  - `make check` 通过，包含 ruff、mypy 和 eval release gate

## 2026-06-22 Eval Release Check Integration

- 执行 `P7-EVAL-05 - Eval Release Check Integration`
- 新增：
  - `scripts/eval_release_check.py`
  - `make eval`
  - `make check` eval release gate step
- 当前行为：
  - release check 加载 `evals/cases/`
  - 基于 case 阈值构造本地 baseline replay summaries
  - 输出 pass rate、average score、case count
  - release gate 失败时脚本返回非 0
- 新增测试：
  - `tests/agent_observability/test_eval_release_check.py`
- 本轮验证结果：
  - `make eval` 通过
  - `uv run pytest tests/agent_observability/test_eval_release_check.py tests/agent_observability/test_release_gate.py tests/agent_observability/test_eval_runner.py tests/agent_observability/test_evals.py` 通过
  - `uv run ruff check scripts/eval_release_check.py tests/agent_observability packages/agent-observability/src/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，175 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 Local Release Gate Baseline

- 执行 `P7-EVAL-04 - Local Release Gate Baseline`
- `agent-observability` 新增：
  - `ReleaseGatePolicy`
  - `ReleaseGateResult`
  - `LocalReleaseGate`
- 当前行为：
  - release gate 可以基于 eval pass rate 和 average score 做本地判定
  - empty eval result fail closed
  - invalid gate threshold 被拒绝
- 新增测试：
  - `tests/agent_observability/test_release_gate.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_release_gate.py tests/agent_observability/test_eval_runner.py tests/agent_observability/test_evals.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，174 passed
  - `make check` 通过

## 2026-06-22 Baseline Eval Case Expansion

- 执行 `P7-EVAL-03 - Baseline Eval Case Expansion`
- `evals/cases/` 新增：
  - `analysis-locate-error`
  - `bugfix-typescript-type-error`
  - `refactor-cross-file`
  - `refactor-control-unrelated-diff`
  - `recovery-dependency-lock-constraint`
- 当前行为：
  - 本地 eval dataset 覆盖 bugfix、refactor、recovery、security、analysis
  - case 数量从 3 扩展到 8
  - 测试锁定 Phase 7 baseline category coverage
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_evals.py tests/agent_observability/test_eval_runner.py` 通过
  - `uv run ruff check tests/agent_observability packages/agent-observability/src/agent_observability` 通过
  - `uv run mypy tests/agent_observability packages/agent-observability/src/agent_observability` 通过
  - `uv run pytest` 通过，170 passed
  - `make check` 通过

## 2026-06-22 Local Eval Runner

- 执行 `P7-EVAL-02 - Local Eval Runner`
- `agent-observability` 新增：
  - `EvalRunResult`
  - `LocalEvalRunner`
- 当前行为：
  - eval cases 和 replay summaries 可以按顺序组合评分
  - eval run result 暴露 total count、pass count、all-pass status、average score
  - missing replay result 会成为显式失败
  - empty eval run 被拒绝
- 新增测试：
  - `tests/agent_observability/test_eval_runner.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_eval_runner.py tests/agent_observability/test_evals.py tests/agent_observability/test_replay.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，169 passed
  - `make check` 通过

## 2026-06-22 Eval Case And Grader Bootstrap

- 执行 `P7-EVAL-01 - Eval Case And Grader Bootstrap`
- `agent-observability` 新增：
  - `EvalCase`
  - `EvalGrade`
  - `LocalEvalGrader`
  - `load_eval_cases`
- `evals/cases/` 新增最小本地数据集：
  - `bugfix-python-test`
  - `security-block-env`
  - `recovery-resume-task`
- 当前行为：
  - eval case 可以从 JSON 文件或目录加载
  - grader 可以基于 replay summary 产出 typed pass/fail result
  - invalid case path、threshold、category 会被拒绝
- 新增测试：
  - `tests/agent_observability/test_evals.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_evals.py tests/agent_observability/test_replay.py tests/agent_observability/test_jsonl_trace_store.py tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，166 passed
  - `make check` 通过

## 2026-06-22 Local Replay Runner

- 执行 `P7-OBS-03 - Local Replay Runner`
- `agent-observability` 新增：
  - `LocalReplayRunner`
  - `ReplayResult`
- 当前行为：
  - 单个 trace record 可以 replay 成 deterministic summary
  - JSONL trace store 可以按写入顺序 replay
  - missing store file replay 返回空结果
  - zero-event trace 被拒绝
- 新增测试：
  - `tests/agent_observability/test_replay.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_replay.py tests/agent_observability/test_jsonl_trace_store.py tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，161 passed
  - `make check` 通过

## 2026-06-22 Local Trace JSONL Store

- 执行 `P7-OBS-02 - Local Trace JSONL Store`
- `agent-observability` 新增：
  - `JsonlTraceStore`
- 当前行为：
  - trace records 可以 append 到本地 JSONL 文件
  - trace records 可以按写入顺序读回
  - missing store file 返回空列表
  - directory path 被拒绝
- 新增测试：
  - `tests/agent_observability/test_jsonl_trace_store.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_jsonl_trace_store.py tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `make check` 通过

## 2026-06-22 Command Risk Rules

- 执行 `P6-POL-02 - Command Risk Rules`
- `LocalPolicyEngine` 现在支持：
  - `command.run` 参数级风险判断
  - shell interpreter execution 进入 approval
  - shell metacharacter usage 进入 approval
  - malformed command arguments 进入 approval
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Harness Context Input Wiring

- 执行 `P5-CTX-06 - Harness Context Input Wiring`
- `agent-core` 新增：
  - `ContextCompilerPort`
  - `HarnessTask.workspace_root`
  - `HarnessTask.context_token_budget`
- `HarnessModelStep` 现在支持：
  - 通过抽象 `ContextCompilerPort` 生成 system message
  - 在 user message 前注入 compiled context prompt
- `agent-context` 新增：
  - `LocalContextCompiler`
- 新增测试：
  - `tests/agent_core/test_harness_model_step.py`
  - `tests/agent_context/test_adapter.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Structured Planner And Verifier Evidence

- 执行 `P5-CTX-09 - Structured Planner And Verifier Evidence`
- `RuntimeEvidenceInput` 新增：
  - `metadata`
- `HarnessLoop` 现在支持：
  - 把 prior attempt 的 planner summary 提取为 `planner_summary`
  - 把 prior attempt 的 verifier result 提取为带 pass/fail metadata 的 `verifier_summary`
  - 把 tool status 与 tool output 分别保留为结构化 evidence
- `LocalContextCompiler` 现在支持：
  - 把 planner summaries 合并进 conversation compaction 的 current plan
  - 把 failed verifier summaries 合并进 unresolved tests
  - 把 passed verifier summaries 合并进 acceptance criteria
- 更新测试：
  - `tests/agent_core/test_harness_runtime_evidence.py`
  - `tests/agent_context/test_adapter.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-23 API Resume Execute Trigger

- 执行 `P8-API-07 - API Resume Execute Trigger`
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/resume`
  - `worker_id` 与 `lease_ttl_seconds` 请求参数校验
  - 对 missing session、terminal resume、lease conflict、execution error 的确定性响应映射
- 新增模块：
  - `apps/api/src/zebra_agent_api/responses.py`
  - `apps/api/src/zebra_agent_api/session_payloads.py`
  - `apps/api/src/zebra_agent_api/serialization.py`
- 更新测试：
  - `tests/api/test_routes.py`
  - `tests/api/test_http_app.py`
- 本轮验证结果：
  - `uv run pytest tests/api/test_routes.py tests/api/test_http_app.py` 通过

## 2026-06-23 Worker Ready Session Loop

- 执行 `P8-WKR-05 - Worker Ready Session Loop`
- `packages/agent-core` 现在支持：
  - `ProjectionStorePort.list_ready_sessions(limit=...)`
- `packages/agent-storage` 现在支持：
  - `SQLiteProjectionStore.list_ready_sessions()` 按 `updated_at` 顺序扫描 ready session
- `apps/worker` 现在支持：
  - `WorkerLoopService`
  - `zebra-agent-worker` 本地 operator 入口
  - 单次 poll 与多 cycle ready session 执行
- 更新测试：
  - `tests/agent_storage/test_sqlite_projection_store.py`
  - `tests/worker/test_loop.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_projection_store.py tests/worker/test_loop.py` 通过

## 2026-06-23 Phase 8 Mainline Alignment

- 执行 `P8-INT-01 - Phase 8 Mainline Alignment`
- 主线对齐后同时包含：
  - CLI `resume --execute`
  - API `POST /sessions/{session_id}/resume`
  - `zebra-agent-worker` ready session loop
- 冲突整理：
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `WORKLOG.md`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_http_app.py tests/api/test_routes.py tests/agent_storage/test_sqlite_projection_store.py tests/worker/test_loop.py` 通过
  - `make check` 通过

## 2026-06-23 Phase 8 Closeout Record

- 执行 `P8-CLOSE-01 - Phase 8 Closeout Record`
- 新增文档：
  - `docs/Phase8_CLI_API_Productization_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P8-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 9 Task Board`
  - `PROGRESS.md` 切换到 `phase 9 ready`
  - `README.md` 补充 Phase 8 closeout 与 Phase 9 starter lanes
- 本轮验证结果：
  - `make check` 通过

## 2026-06-23 Session Messages Entry

- 执行 `P9-API-01 - Session Messages Entry`
- `agent-core` 现在支持：
  - `SessionMessageAppendService`
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/messages`
  - non-blank content payload 校验
  - terminal session append rejection
- 更新测试：
  - `tests/agent_core/test_session_messages.py`
  - `tests/api/test_routes.py`
  - `tests/api/test_http_app.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_session_messages.py tests/api/test_routes.py tests/api/test_http_app.py` 通过

## 2026-06-23 Approval HTTP Entry

- 执行 `P9-API-03 - Approval HTTP Entry`
- `apps/api` 现在支持：
  - `POST /approvals/{approval_id}/approve`
  - `POST /approvals/{approval_id}/reject`
  - approval operator/reason payload 校验与默认值
  - waiting approval session 的 grant/reject durable event 写入
  - invalid approval state 的 deterministic 409 映射
- 本轮新增测试：
  - `tests/api/test_approval_api_app.py`
  - `tests/api/test_approval_routes.py`
  - `tests/api/test_http_approvals.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Worker Continuous Loop Behavior

- 执行 `P9-WKR-01 - Worker Continuous Loop Behavior`
- `zebra-agent-worker` loop 现在支持：
  - omitted `--max-cycles` 的连续 daemon-style polling
  - `stop_reason` 机器可读输出
  - idle 多轮 polling 的 deterministic sleep 语义
  - 单轮 `--max-cycles 1 --stop-when-idle` 行为继续可用
- 更新测试：
  - `tests/worker/test_loop.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 本轮验证结果：
  - `uv run pytest tests/worker/test_loop.py tests/worker/test_execution.py tests/worker/test_claims.py tests/worker/test_resume.py` 通过

## 2026-06-23 Phase 9 Closeout And Phase 10 Planning

- 执行 `P9-CLOSE-01 - Phase 9 Closeout And Phase 10 Planning`
- 新增文档：
  - `docs/Phase9_Session_Control_Worker_Hardening_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P9-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 10 Task Board`
  - `PROGRESS.md` 切换到 `phase 10 ready`
  - `README.md` 补充 Phase 10 starter lanes
- Phase 10 首批任务：
  - `P10-API-01 - Session Diff Read API`
  - `P10-API-02 - Session Artifacts Read API`
  - `P10-API-03 - Session Commit API`
  - `P10-API-04 - Session Pull Request API`

## 2026-06-23 Session Diff Read API

- 执行 `P10-API-01 - Session Diff Read API`
- `agent-runtime` 现在支持：
  - `WorkspaceDiffService`
  - clean/dirty Git workspace diff projection
  - non-Git workspace deterministic rejection
- `apps/api` 现在支持：
  - `GET /sessions/{session_id}/diff`
  - missing session 404
  - missing or non-Git workspace `diff_unavailable` conflict
  - bearer auth behavior inherited from existing session routes
- 更新测试：
  - `tests/agent_runtime/test_git_diff.py`
  - `tests/api/test_session_diff.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Session Artifacts Read API

- 执行 `P10-API-02 - Session Artifacts Read API`
- `agent-storage` 现在支持：
  - `SQLiteArtifactStore`
  - model call artifact projection
  - tool run artifact projection
  - explicit empty artifact list
- `apps/api` 现在支持：
  - `GET /sessions/{session_id}/artifacts`
  - missing session 404
  - inherited bearer auth behavior for session routes
- 更新测试：
  - `tests/agent_storage/test_artifacts.py`
  - `tests/api/test_session_artifacts.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Session Commit API

- 执行 `P10-API-03 - Session Commit API`
- `agent-runtime` 现在支持：
  - `WorkspaceCommitService`
  - dirty Git workspace commit
  - clean or non-Git workspace deterministic rejection
- `agent-security` 现在支持：
  - `CommitPolicy`
  - commit requires `full_access` session policy
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/commit`
  - commit message and author validation
  - missing session 404
  - policy-blocked conflict
  - inherited bearer auth behavior for session routes
- 更新测试：
  - `tests/agent_runtime/test_git_commit.py`
  - `tests/agent_security/test_delivery_policy.py`
  - `tests/api/test_session_commit.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Session Pull Request API

- 执行 `P10-API-04 - Session Pull Request API`
- `agent-integrations` 现在支持：
  - `LocalOnlyPullRequestGateway`
  - PR dry-run plan
  - local-only unavailable response for network execution
- `agent-security` 现在支持：
  - `PullRequestPolicy`
  - PR requires `full_access` session policy
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/pull-request`
  - PR title/body/base/head/dry_run payload validation
  - missing session 404
  - policy-blocked conflict
  - local-only unavailable conflict when `dry_run=false`
- 更新测试：
  - `tests/agent_integrations/test_scm.py`
  - `tests/agent_security/test_delivery_policy.py`
  - `tests/api/test_session_pull_request.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Phase 10 Closeout And Phase 11 Planning

- 执行 `P10-CLOSE-01 - Phase 10 Closeout And Phase 11 Planning`
- 新增文档：
  - `docs/Phase10_Code_Delivery_Surface_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P10-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 11 Task Board`
  - `PROGRESS.md` 切换到 `phase 11 ready`
  - `README.md` 补充 Phase 11 starter lanes
- Phase 11 首批任务：
  - `P11-API-01 - Side Effect Idempotency Keys`
  - `P11-OBS-01 - Delivery Audit Events`
  - `P11-INT-01 - GitHub Pull Request Provider Skeleton`

## 2026-06-23 Phase 11 Side Effect Idempotency Keys

- 执行 `P11-API-01 - Side Effect Idempotency Keys`
- 新增 `SQLiteIdempotencyStore`：
  - 以 `action + idempotency_key` 记录首次请求 hash、状态码和响应体
  - 同 key 同 payload 重放首次响应
  - 同 key 不同 payload 返回确定性冲突
- API 集成：
  - `POST /sessions/{session_id}/commit`
  - `POST /sessions/{session_id}/pull-request`
  - HTTP/Route 层透传 `Idempotency-Key`
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P11-API-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P11-OBS-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_storage/test_idempotency.py tests/api/test_session_commit.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 11 Delivery Audit Events

- 执行 `P11-OBS-01 - Delivery Audit Events`
- 修正任务边界：
  - `docs/AGENT_TASKS.md` 为 P11-OBS-01 增加 `apps/api/` 和 `tests/api/` owned paths，用于显式 API wiring
- 新增 core/storage 能力：
  - `DeliveryAuditRecord`
  - `DeliveryAuditStorePort`
  - `SQLiteDeliveryAuditStore`
- API 集成：
  - commit 成功、policy blocked、unavailable 会记录 delivery audit
  - pull-request dry-run、policy blocked、unavailable 会记录 delivery audit
  - idempotent replay 不重复写入审计记录
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P11-OBS-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P11-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_storage/test_delivery_audit.py tests/api/test_session_commit.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 11 GitHub Pull Request Provider Skeleton

- 执行 `P11-INT-01 - GitHub Pull Request Provider Skeleton`
- 新增集成骨架：
  - `GitHubPullRequestConfig`
  - `GitHubPullRequestGateway`
  - `GitHubPullRequestPayload`
- 行为边界：
  - local-only 仍是默认 PR gateway
  - GitHub dry-run 可以生成可审查的 request payload
  - GitHub non-dry-run 缺 token 时在网络调用前失败
  - GitHub non-dry-run 即使有 token 也仍 fail-closed，真实执行尚未实现
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P11-INT-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 11 Closeout And Phase 12 Planning

- 执行 `P11-CLOSE-01 - Phase 11 Closeout And Phase 12 Planning`
- 新增文档：
  - `docs/Phase11_Delivery_Hardening_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P11-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 12 Task Board`
  - `PROGRESS.md` 切换到 `phase 12 ready`
  - `README.md` 指向最新 Phase 11 closeout summary
- Phase 12 首批任务：
  - `P12-CONFIG-01 - SCM Provider Settings`
  - `P12-INT-01 - Pull Request Gateway Selection`
  - `P12-API-01 - Delivery Audit Read API`
- 验证：
  - `make check`

## 2026-07-03 Phase 62 Scope-Aware Memory Review Queue

- 执行 `P62-MEM-01 - Scope-Aware Memory Review Queue`
- 行为更新：
  - 新增 repo-session、user、tenant 三个 scope 的 candidate-only memory queue 读路径
  - 新增 API 路由 `/sessions/{id}/memory/queue`、`/users/{id}/memory/queue`、`/tenants/{id}/memory/queue`
  - 新增 CLI 命令 `memory-queue`、`memory-user-queue`、`memory-tenant-queue`
  - 复用现有 inventory serializer，保留 `source` provenance 与 `last_review` lifecycle 字段
- 文档更新：
  - `docs/Phase62_Scope_Aware_Memory_Review_Queue_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_scope_queue.py tests/cli/test_cli_memory_scope_queue.py tests/test_memory_scope_queue_contract_matrix.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py tests/api/test_memory_scope_inventory.py tests/cli/test_cli_memory_scope_inventory.py tests/test_memory_scope_inventory_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_scope_queue.py tests/cli/test_cli_memory_scope_queue.py tests/test_memory_scope_queue_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 63 Bulk Memory Review Decisions

- 执行 `P63-MEM-01 - Bulk Memory Review Decisions`
- 行为更新：
  - 新增 repo-session、user、tenant 三个 scope 的 bulk memory review 控制面
  - API 新增 `/sessions/{id}/memory/bulk-review`、`/users/{id}/memory/bulk-review`、`/tenants/{id}/memory/bulk-review`
  - CLI 新增 `memory-bulk-review`、`memory-user-bulk-review`、`memory-tenant-bulk-review`
  - bulk 响应显式区分 `applied`、`skipped`、`invalid`，并保留现有单条 review 语义不变
- 文档更新：
  - `docs/Phase63_Bulk_Memory_Review_Decisions_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_scope_bulk_review.py tests/cli/test_cli_memory_scope_bulk_review.py tests/test_memory_scope_bulk_review_contract_matrix.py tests/api/test_memory_scope_review.py tests/cli/test_cli_memory_scope_review.py tests/test_memory_scope_review_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_scope_bulk_review.py tests/cli/test_cli_memory_scope_bulk_review.py tests/test_memory_scope_bulk_review_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 64 Cross-Scope Memory Queue Summary

- 执行 `P64-MEM-01 - Cross-Scope Memory Queue Summary`
- 行为更新：
  - 新增 repo-session、user、tenant 三个 scope 的 queue summary 读面
  - API 新增 `/sessions/{id}/memory/queue-summary`、`/users/{id}/memory/queue-summary`、`/tenants/{id}/memory/queue-summary`
  - CLI 新增 `memory-queue-summary`、`memory-user-queue-summary`、`memory-tenant-queue-summary`
  - summary 响应新增 `pending_count`、`queue_status`、`latest_memory_id`、`latest_updated_at`
- 文档更新：
  - `docs/Phase64_Cross_Scope_Memory_Queue_Summary_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_scope_queue_summary.py tests/cli/test_cli_memory_scope_queue_summary.py tests/test_memory_scope_queue_summary_contract_matrix.py tests/api/test_memory_scope_queue.py tests/cli/test_cli_memory_scope_queue.py tests/test_memory_scope_queue_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_scope_queue_summary.py tests/cli/test_cli_memory_scope_queue_summary.py tests/test_memory_scope_queue_summary_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 65 Cross-Scope Memory Operations Overview

- 执行 `P65-MEM-01 - Cross-Scope Memory Operations Overview`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory operations overview 读面
  - API 新增 `POST /sessions/{id}/memory-overview`
  - CLI 新增 `memory-overview <session_id> [--user-id ...] [--tenant-id ...]`
  - overview 响应新增 `scope_count`、`total_pending_count` 与 per-scope `scopes[]` 健康摘要
- 文档更新：
  - `docs/Phase65_Cross_Scope_Memory_Operations_Overview_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py tests/api/test_memory_scope_queue_summary.py tests/cli/test_cli_memory_scope_queue_summary.py tests/test_memory_scope_queue_summary_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 66 Memory Review Governance Signals

- 执行 `P66-MEM-01 - Memory Review Governance Signals`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory governance 读面
  - API 新增 `POST /sessions/{id}/memory-governance`
  - CLI 新增 `memory-governance <session_id> [--user-id ...] [--tenant-id ...]`
  - governance 响应新增 `pending_by_type`、`reviewed_count`、`review_status_counts`、`latest_reviewed_at`、`latest_review_status`、`latest_review_operator`
- 文档更新：
  - `docs/Phase66_Memory_Review_Governance_Signals_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 67 Memory Backlog Aging Signals

- 执行 `P67-MEM-01 - Memory Backlog Aging Signals`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory backlog aging 读面
  - API 新增 `POST /sessions/{id}/memory-aging`
  - CLI 新增 `memory-aging <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - aging 响应新增 `reference_at`、`pending_age_buckets`、`oldest_pending_memory_id`、`oldest_pending_captured_at`、`oldest_pending_age_seconds`、`oldest_pending_age_days`
  - 聚合响应新增 `pending_age_bucket_totals` 与跨 scope 的 oldest pending rollup
- 文档更新：
  - `docs/Phase67_Memory_Backlog_Aging_Signals_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 68 Memory Review Velocity Signals

- 执行 `P68-MEM-01 - Memory Review Velocity Signals`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory review velocity 读面
  - API 新增 `POST /sessions/{id}/memory-velocity`
  - CLI 新增 `memory-velocity <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - velocity 响应新增 `reviewed_last_24h_count`、`reviewed_last_7d_count`、`reviewed_last_30d_count`、`latest_review_window`
  - 聚合响应新增 `total_reviewed_last_24h_count`、`total_reviewed_last_7d_count`、`total_reviewed_last_30d_count` 与跨 scope 的 latest review rollup
- 文档更新：
  - `docs/Phase68_Memory_Review_Velocity_Signals_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_review_velocity_signals.py tests/cli/test_cli_memory_review_velocity_signals.py tests/test_memory_review_velocity_signals_contract_matrix.py tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_review_velocity_signals.py tests/cli/test_cli_memory_review_velocity_signals.py tests/test_memory_review_velocity_signals_contract_matrix.py tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 69 Memory Backlog Pressure Signals

- 执行 `P69-MEM-01 - Memory Backlog Pressure Signals`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory backlog pressure 读面
  - API 新增 `POST /sessions/{id}/memory-pressure`
  - CLI 新增 `memory-pressure <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - pressure 响应新增 `pressure_level` 与 `pressure_reasons`
  - 聚合响应新增 `pressure_level_counts`、`highest_pressure_level`、`highest_pressure_scope_kind`、`highest_pressure_scope_id`、`highest_pressure_reasons`
- 文档更新：
  - `docs/Phase69_Memory_Backlog_Pressure_Signals_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_backlog_pressure_signals.py tests/cli/test_cli_memory_backlog_pressure_signals.py tests/test_memory_backlog_pressure_signals_contract_matrix.py tests/api/test_memory_review_velocity_signals.py tests/cli/test_cli_memory_review_velocity_signals.py tests/test_memory_review_velocity_signals_contract_matrix.py tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_backlog_pressure_signals.py tests/cli/test_cli_memory_backlog_pressure_signals.py tests/test_memory_backlog_pressure_signals_contract_matrix.py tests/api/test_memory_review_velocity_signals.py tests/cli/test_cli_memory_review_velocity_signals.py tests/test_memory_review_velocity_signals_contract_matrix.py tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 70 Memory Pressure Action Hints

- 执行 `P70-MEM-01 - Memory Pressure Action Hints`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory pressure action hint 读面
  - API 新增 `POST /sessions/{id}/memory-action-hints`
  - CLI 新增 `memory-action-hints <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - scope 响应新增 `action_hint`、`action_priority`、`action_target_memory_id`、`action_reasons`
  - 聚合响应新增 `action_hint_counts`、`highest_priority_action_hint`、`highest_priority_action_priority`、`highest_priority_action_scope_kind`、`highest_priority_action_scope_id`、`highest_priority_action_target_memory_id`、`highest_priority_action_reasons`
- 文档更新：
  - `docs/Phase70_Memory_Pressure_Action_Hints_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_pressure_action_hints.py tests/cli/test_cli_memory_pressure_action_hints.py tests/test_memory_pressure_action_hints_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_pressure_action_hints.py tests/cli/test_cli_memory_pressure_action_hints.py tests/test_memory_pressure_action_hints_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 71 Memory Pressure Escalation Recommendations

- 执行 `P71-MEM-01 - Memory Pressure Escalation Recommendations`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory escalation 读面
  - API 新增 `POST /sessions/{id}/memory-escalations`
  - CLI 新增 `memory-escalations <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - scope 响应新增 `escalation_recommendation`、`escalation_priority`、`escalation_target_memory_id`、`escalation_reasons`
  - 聚合响应新增 `escalation_recommendation_counts`、`highest_priority_escalation_recommendation`、`highest_priority_escalation_priority`、`highest_priority_escalation_scope_kind`、`highest_priority_escalation_scope_id`、`highest_priority_escalation_target_memory_id`、`highest_priority_escalation_reasons`
- 文档更新：
  - `docs/Phase71_Memory_Pressure_Escalation_Recommendations_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_pressure_escalations.py tests/cli/test_cli_memory_pressure_escalations.py tests/test_memory_pressure_escalations_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_pressure_escalations.py tests/cli/test_cli_memory_pressure_escalations.py tests/test_memory_pressure_escalations_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 72 Memory Escalation Follow-Up Windows

- 执行 `P72-MEM-01 - Memory Escalation Follow-Up Windows`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory follow-up-window 读面
  - API 新增 `POST /sessions/{id}/memory-follow-up-windows`
  - CLI 新增 `memory-follow-up-windows <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - scope 响应新增 `follow_up_window`、`follow_up_priority`、`follow_up_due_at`、`follow_up_target_memory_id`、`follow_up_reasons`
  - 聚合响应新增 `follow_up_window_counts`、`highest_priority_follow_up_window`、`highest_priority_follow_up_priority`、`highest_priority_follow_up_scope_kind`、`highest_priority_follow_up_scope_id`、`highest_priority_follow_up_due_at`、`highest_priority_follow_up_target_memory_id`、`highest_priority_follow_up_reasons`
- 文档更新：
  - `docs/Phase72_Memory_Escalation_Follow_Up_Windows_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_follow_up_windows.py tests/cli/test_cli_memory_follow_up_windows.py tests/test_memory_follow_up_windows_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_follow_up_windows.py tests/cli/test_cli_memory_follow_up_windows.py tests/test_memory_follow_up_windows_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 73 Memory Follow-Up Overdue Flags

- 执行 `P73-MEM-01 - Memory Follow-Up Overdue Flags`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory overdue 读面
  - API 新增 `POST /sessions/{id}/memory-overdue-flags`
  - CLI 新增 `memory-overdue-flags <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - scope 响应新增 `follow_up_overdue`、`follow_up_overdue_priority`、`follow_up_overdue_since`、`follow_up_overdue_target_memory_id`、`follow_up_overdue_reasons`
  - 聚合响应新增 `overdue_scope_count`、`highest_priority_overdue_scope_kind`、`highest_priority_overdue_scope_id`、`highest_priority_overdue_priority`、`highest_priority_overdue_since`、`highest_priority_overdue_target_memory_id`、`highest_priority_overdue_reasons`
- 文档更新：
  - `docs/Phase73_Memory_Follow_Up_Overdue_Flags_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_overdue_flags.py tests/cli/test_cli_memory_overdue_flags.py tests/test_memory_overdue_flags_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_overdue_flags.py tests/cli/test_cli_memory_overdue_flags.py tests/test_memory_overdue_flags_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-03 Phase 74 Memory Overdue Age Buckets

- 执行 `P74-MEM-01 - Memory Overdue Age Buckets`
- 行为更新：
  - 新增一条以 session 为锚点、可选拼接 user 与 tenant scope 的 memory overdue-age 读面
  - API 新增 `POST /sessions/{id}/memory-overdue-age-buckets`
  - CLI 新增 `memory-overdue-age-buckets <session_id> [--user-id ...] [--tenant-id ...] [--as-of ...]`
  - scope 响应新增 `overdue_age_bucket`、`overdue_age_seconds`、`overdue_age_days`、`overdue_age_reasons`
  - 聚合响应新增 `overdue_age_bucket_counts`、`highest_priority_overdue_age_bucket`、`highest_priority_overdue_age_scope_kind`、`highest_priority_overdue_age_scope_id`、`highest_priority_overdue_age_seconds`、`highest_priority_overdue_age_days`、`highest_priority_overdue_age_target_memory_id`、`highest_priority_overdue_age_reasons`
- 文档更新：
  - `docs/Phase74_Memory_Overdue_Age_Buckets_验收记录.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `uv run pytest tests/api/test_memory_overdue_age_buckets.py tests/cli/test_cli_memory_overdue_age_buckets.py tests/test_memory_overdue_age_buckets_contract_matrix.py`
  - `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_overdue_age_buckets.py tests/cli/test_cli_memory_overdue_age_buckets.py tests/test_memory_overdue_age_buckets_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-06-23 Phase 12 SCM Provider Settings

- 执行 `P12-CONFIG-01 - SCM Provider Settings`
- 配置新增：
  - `ScmSettings`
  - `ZEBRA_SCM_PROVIDER`
  - `ZEBRA_GITHUB_OWNER`
  - `ZEBRA_GITHUB_REPO`
  - `ZEBRA_GITHUB_TOKEN_ENV`
  - `ZEBRA_GITHUB_API_BASE_URL`
  - `ZEBRA_SCM_PULL_REQUEST_DRY_RUN`
- 行为边界：
  - 默认 provider 为 `local-only`
  - GitHub provider 必须显式配置 owner、repo 和 token env name
  - 配置只保存 token 环境变量名，不保存 token 值
  - 现有手动构造 `ZebraAgentSettings` 默认仍得到 local-only SCM settings
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P12-CONFIG-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P12-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/config/test_settings.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 Pull Request Gateway Selection

- 执行 `P12-INT-01 - Pull Request Gateway Selection`
- 新增集成能力：
  - `PullRequestGateway` protocol
  - `build_pull_request_gateway(settings.scm)`
- API 集成：
  - `SessionPullRequestApi` 接收可注入 PR gateway
  - `ZebraAgentApi` 基于 `settings.scm` 选择 local-only 或 GitHub gateway
  - GitHub dry-run 会返回 provider=`github` 和可审查 `request_payload`
  - GitHub non-dry-run 仍 fail-closed
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P12-INT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P12-API-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 Delivery Audit Read API

- 执行 `P12-API-01 - Delivery Audit Read API`
- 新增 API：
  - `GET /sessions/{session_id}/delivery-audit`
  - `SessionDeliveryAuditApi`
- 响应字段：
  - `action`
  - `status`
  - `status_code`
  - `policy_profile`
  - `idempotency_key`
  - `result_metadata`
  - `created_at`
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P12-API-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/api/test_session_delivery_audit.py tests/api/test_routes.py tests/api/test_http_app.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 Closeout And Phase 13 Planning

- 执行 `P12-CLOSE-01 - Phase 12 Closeout And Phase 13 Planning`
- 新增文档：
  - `docs/Phase12_Remote_SCM_Configuration_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P12-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 13 Task Board`
  - `PROGRESS.md` 切换到 `phase 13 ready`
  - `README.md` 指向最新 Phase 12 closeout summary
- Phase 13 首批任务：
  - `P13-API-01 - API Composition Split`
  - `P13-INT-01 - Guarded GitHub Pull Request Execution`
  - `P13-SEC-01 - SCM Credential Boundary Draft`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 API Composition Split

- 执行 `P13-API-01 - API Composition Split`
- 新增：
  - `apps/api/src/zebra_agent_api/session_read.py`
- 拆分内容：
  - session lookup
  - session stream
  - session diff
  - session artifacts
  - session delivery audit read delegation
- 结果：
  - `apps/api/src/zebra_agent_api/app.py` 从 489 行降到 384 行
  - endpoint 行为不变
  - `P13-SEC-01` 解锁为下一步，`P13-INT-01` 等待 credential boundary
- 验证：
  - `uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py tests/api/test_session_diff.py tests/api/test_session_artifacts.py tests/api/test_session_delivery_audit.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 SCM Credential Boundary Draft

- 执行 `P13-SEC-01 - SCM Credential Boundary Draft`
- 新增：
  - `ScmCredentialCapability`
  - `ScmCredentialBoundary`
  - `REDACTED_SECRET`
- 行为边界：
  - local-only 不产生 token capability
  - GitHub capability 只保留 token env name 和运行时 token value
  - settings snapshot 不包含 token value
  - redacted serialization 输出 `<redacted>`
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P13-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P13-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_security/test_credentials.py tests/config/test_settings.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 Guarded GitHub Pull Request Execution

- 执行 `P13-INT-01 - Guarded GitHub Pull Request Execution`
- 新增：
  - `GitHubPullRequestTransport`
  - `GitHubHttpPullRequestTransport`
  - settings-driven token lookup in `build_pull_request_gateway`
- 行为边界：
  - local-only 仍为默认 provider
  - GitHub execution 必须显式关闭 `ZEBRA_SCM_PULL_REQUEST_DRY_RUN`
  - 缺 token 时在网络调用前失败
  - 测试使用 fake transport，不依赖 live GitHub
  - 成功执行返回 `status=created` 和 PR URL
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P13-INT-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 Closeout And Phase 14 Planning

- 执行 `P13-CLOSE-01 - Phase 13 Closeout And Phase 14 Planning`
- 新增文档：
  - `docs/Phase13_API_Composition_And_Guarded_SCM_Execution_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P13-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 14 Task Board`
  - `PROGRESS.md` 切换到 `phase 14 ready`
  - `README.md` 指向最新 Phase 13 closeout summary
- Phase 14 首批任务：
  - `P14-OBS-01 - SCM Execution Audit Hardening`
  - `P14-SEC-01 - SCM Token Redaction Regression Gate`
  - `P14-DOC-01 - Remote SCM Operator Safety Runbook`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 14 SCM Execution Audit Hardening

- 执行 `P14-OBS-01 - SCM Execution Audit Hardening`
- 行为更新：
  - pull-request delivery audit 记录规范化 `provider`
  - dry-run 和 created 响应记录 `status`、`commit_sha`、`dry_run`、`url`
  - policy blocked、missing workspace、transport unavailable 等失败路径记录 provider、dry-run flag 和 reason
  - delivery audit read API 返回同一套 result metadata，不引入 token value
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P14-OBS-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P14-SEC-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py tests/api/test_session_pull_request.py tests/agent_storage/test_delivery_audit.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 14 SCM Token Redaction Regression Gate

- 执行 `P14-SEC-01 - SCM Token Redaction Regression Gate`
- 新增回归覆盖：
  - GitHub PR plan 不暴露真实 token
  - API pull-request created 响应不暴露真实 token
  - delivery audit result metadata 不暴露真实 token
  - credential redacted snapshot 和 settings snapshot 不暴露真实 token value
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P14-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P14-DOC-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_security/test_credentials.py tests/agent_integrations/test_scm.py tests/api/test_scm_token_redaction.py tests/api/test_session_pull_request.py tests/api/test_delivery_audit_metadata.py`

## 2026-06-23 Phase 14 Remote SCM Operator Safety Runbook

- 执行 `P14-DOC-01 - Remote SCM Operator Safety Runbook`
- 文档更新：
  - `docs/operator_runbook.md` 增加 remote GitHub PR execution checklist
  - checklist 从 local-only dry-run 开始，再切换 GitHub dry-run，最后才允许 live execution
  - live execution 前明确 token env、`full_access` policy、payload review 和 target branch 前置条件
  - live execution 后要求立即读取 delivery audit
  - rollback 和 failure handling 覆盖 accidental PR、`policy_blocked`、`pull_request_unavailable`
- 规划更新：
  - `docs/AGENT_TASKS.md` 将 `P14-DOC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 增加 `P14-CLOSE-01 - Phase 14 Closeout And Next Planning`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-23 Phase 14 Closeout And Phase 15 Planning

- 执行 `P14-CLOSE-01 - Phase 14 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase14_SCM_Execution_Hardening_验收记录.md`
- Phase 14 验收结论：
  - SCM execution audit metadata 完成
  - token redaction regression gate 完成
  - remote SCM operator safety runbook 完成
  - local-only 和 dry-run 默认安全边界保持不变
- Phase 15 首批任务：
  - `P15-SEC-01 - Credential Capability Domain Model`
  - `P15-SEC-02 - Credential Broker Port`
  - `P15-INT-01 - SCM Broker Lookup Adapter`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 15 Credential Capability Domain Model

- 执行 `P15-SEC-01 - Credential Capability Domain Model`
- 新增：
  - `CredentialCapability`
- 行为边界：
  - capability 包含 provider、audience、scopes、expires_at
  - runtime token value 仅保留为运行时字段，`repr` 不显示
  - `redacted()` 只输出 `<redacted>`，不输出真实 token
  - expiry 使用 timezone-aware datetime 判断
  - 未引入任何具体 secret backend
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P15-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P15-SEC-02` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_security/test_capabilities.py tests/agent_security/test_credentials.py`
  - `make check`

## 2026-06-23 Phase 15 Credential Broker Port

- 执行 `P15-SEC-02 - Credential Broker Port`
- 新增：
  - `CredentialBroker`
  - `InMemoryCredentialBroker`
  - `CredentialMissingError`
  - `CredentialDeniedError`
  - `CredentialUnavailableError`
  - `docs/Credential_Broker_Foundation.md`
- 行为边界：
  - broker Port 通过 provider、audience、scopes 和 now 请求 SCM credential
  - fake broker 可返回 runtime capability，但 redacted snapshot 不暴露 token
  - missing、denied、unavailable 错误语义分离
  - 未引入 durable token storage 或具体 secret backend
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P15-SEC-02` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P15-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py`
  - `make check`

## 2026-06-23 Phase 15 SCM Broker Lookup Adapter

- 执行 `P15-INT-01 - SCM Broker Lookup Adapter`
- 行为更新：
  - `build_pull_request_gateway` 支持可选 `credential_broker`
  - GitHub dry-run 不请求 broker credential
  - GitHub non-dry-run 可使用 broker-issued capability
  - broker missing/denied/unavailable 错误在网络执行前转为 `ScmUnavailableError`
  - 没有传入 broker 时保留现有 env-token fallback，以兼容当前 API composition path
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P15-INT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 增加 `P15-CLOSE-01 - Phase 15 Closeout And Next Planning`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/agent_security/test_broker.py`

## 2026-06-23 Phase 15 Closeout And Phase 16 Planning

- 执行 `P15-CLOSE-01 - Phase 15 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase15_Credential_Broker_Foundation_验收记录.md`
- Phase 15 验收结论：
  - credential capability domain model 完成
  - credential broker Port 完成
  - SCM broker lookup adapter 完成
  - env-token fallback 仍保留为兼容边界
- Phase 16 首批任务：
  - `P16-SEC-01 - Local Environment Credential Broker`
  - `P16-APP-01 - API Credential Broker Composition`
  - `P16-CLOSE-01 - Phase 16 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 16 Local Environment Credential Broker

- 执行 `P16-SEC-01 - Local Environment Credential Broker`
- 新增：
  - `EnvironmentCredentialBinding`
  - `EnvironmentCredentialBroker`
- 行为边界：
  - provider、audience、scopes、token env name 和 expiry 通过 binding 显式配置
  - broker 从配置的 env var name 读取 runtime token value
  - missing env value 映射为 `CredentialMissingError`
  - unsupported provider 或 scope 映射为 `CredentialDeniedError`
  - raw token 不出现在 capability repr、redacted snapshot 或 broker repr
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P16-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P16-APP-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_security/test_environment_broker.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py`

## 2026-06-23 Phase 16 API Credential Broker Composition

- 执行 `P16-APP-01 - API Credential Broker Composition`
- 行为更新：
  - `ZebraAgentApi` 支持注入 `credential_broker`
  - `ZebraAgentApi` 支持注入 GitHub transport 以便 API 层 fake execution 测试
  - `create_app` 与 `create_http_app` 保持默认行为不变，同时支持 dependency injection
  - GitHub non-dry-run API 路径可使用 broker-issued capability
  - broker missing credential 在网络执行前失败并记录 delivery audit metadata
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P16-APP-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P16-CLOSE-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py tests/agent_security/test_environment_broker.py`

## 2026-06-23 Phase 16 Closeout And Phase 17 Planning

- 执行 `P16-CLOSE-01 - Phase 16 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase16_Local_Credential_Backend_And_API_Wiring_验收记录.md`
- Phase 16 验收结论：
  - local environment credential broker 完成
  - API credential broker composition 完成
  - missing credential audit metadata 覆盖完成
  - direct env fallback 仍保留为兼容边界
- Phase 17 首批任务：
  - `P17-APP-01 - API Default Environment Broker Factory`
  - `P17-INT-01 - SCM Env Fallback Boundary`
  - `P17-DOC-01 - Broker-Backed SCM Operator Docs`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 17 API Default Environment Broker Factory

- 执行 `P17-APP-01 - API Default Environment Broker Factory`
- 新增：
  - `zebra_agent_api.credential_broker.build_default_credential_broker`
- 行为更新：
  - local-only API 不构造 credential broker
  - GitHub API composition 在未显式注入 broker 时从 SCM settings 构造 `EnvironmentCredentialBroker`
  - GitHub non-dry-run API 路径可通过默认 environment broker 使用 fake transport 测试
  - missing default broker env value 在网络执行前失败并记录 delivery audit metadata
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P17-APP-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P17-INT-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/api/test_credential_broker.py tests/api/test_session_pull_request.py tests/agent_security/test_environment_broker.py`

## 2026-06-23 Phase 17 SCM Env Fallback Boundary

- 执行 `P17-INT-01 - SCM Env Fallback Boundary`
- 行为更新：
  - `build_pull_request_gateway` 默认不再读取 direct env token fallback
  - retained fallback 必须显式传入 `allow_env_token_fallback=True`
  - broker-backed path 保持优先
  - local-only 和 GitHub dry-run 行为不变
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P17-INT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P17-DOC-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_credential_broker.py`

## 2026-06-23 Phase 17 Broker-Backed SCM Operator Docs

- 执行 `P17-DOC-01 - Broker-Backed SCM Operator Docs`
- 文档更新：
  - `docs/operator_runbook.md` 改为 broker-backed GitHub PR execution 说明
  - 明确 API composition 默认从 SCM settings 构造 environment broker
  - 明确 `ZEBRA_GITHUB_TOKEN_ENV` 只存 env var name，token value 只存在 API process env
  - 明确 direct SCM adapter env fallback 默认关闭，只保留 integration compatibility flag
  - delivery audit checklist 增加 missing broker env value 的 reason
- 规划更新：
  - `docs/AGENT_TASKS.md` 将 `P17-DOC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 增加 `P17-CLOSE-01 - Phase 17 Closeout And Next Planning`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-23 Phase 17 Closeout And Phase 18 Planning

- 执行 `P17-CLOSE-01 - Phase 17 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase17_Credential_Backend_Hardening_验收记录.md`
- Phase 17 验收结论：
  - API default environment broker factory 完成
  - direct SCM env fallback 默认关闭，显式 compatibility flag 保留
  - broker-backed SCM operator docs 完成
- Phase 18 首批任务：
  - `P18-OBS-01 - SCM Credential Source Audit Metadata`
  - `P18-OBS-02 - Credential Failure Audit Classification`
  - `P18-CLOSE-01 - Phase 18 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-28 Phase 22 Proxy Route Policy Integration

- 执行 `P22-SEC-01 - Proxy Route Policy Integration`
- 行为更新：
  - `LocalPolicyEngine` 现可结合 `network_profile` 对 `mcp.<server>.<tool>` 调用输出确定性的 local / proxy-routed / blocked 策略结果
  - fail-closed 默认值 `network_profile=none` 下，MCP 工具仍被明确拒绝
  - 代理可达的 MCP 工具会生成稳定的 approval reason，并把 `route`、`target`、`network_profile` 投影进 `ApprovalRequest`
  - 本地 builtin 工具的 allow / approval reason 明确标识为 local route
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P22-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P22-DOC-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_security/test_policy_profiles.py tests/agent_security/test_mcp_proxy_policy.py`
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
  - `uv run mypy packages/agent-security/src/agent_security/policy.py tests/agent_security/test_policy_profiles.py tests/agent_security/test_mcp_proxy_policy.py`
  - `make check`

## 2026-06-28 Phase 22 Proxy Gateway Operator Docs

- 执行 `P22-DOC-01 - Proxy Gateway Operator Docs`
- 文档更新：
  - 新增 `docs/proxy_gateway_operator_runbook.md`，集中记录 proxy-backed SCM 与 MCP gateway 的 operator model
  - `docs/operator_runbook.md` 改为保留主线本地操作说明，并跳转到新的 proxy runbook
  - `docs/operator_runbook.md` 从 651 行降到 423 行，重新满足 markdown 文件长度约束
  - `docs/AGENT_TASKS.md` 将 `P22-DOC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P22-CLOSE-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 文档结论：
  - operator docs 明确区分了 Phase 21 starter-contract 与 Phase 22 concrete gateway execution
  - audit interpretation 覆盖了 SCM proxy 与 MCP proxy 的 route / target / transport 证据
  - rollback guidance 保持 fail-closed 默认值和窄化启用原则
- 验证：
  - `make check`

## 2026-06-28 Phase 22 Closeout And Phase 23 Planning

- 执行 `P22-CLOSE-01 - Phase 22 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase22_Proxy_Execution_And_Gateway_Wiring_验收记录.md`
- Phase 22 验收结论：
  - MCP proxy contract 已进入 concrete gateway execution path
  - SCM proxy 与 MCP proxy 已共享稳定的 route / target / transport 观测字段
  - policy 与 approval surface 已能区分 local、proxy-routed、blocked 三类 MCP 路径
  - operator runbook 已拆分为主 runbook 与 proxy gateway runbook
- Phase 23 starter tasks：
  - `P23-HAR-01 - Proxy Approval Event Projection`
  - `P23-API-01 - Proxy Approval Readback Surface`
  - `P23-OBS-01 - Proxy Approval Trace Normalization`
  - `P23-CLOSE-01 - Phase 23 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-28 Phase 23 Proxy Approval Event Projection

- 执行 `P23-HAR-01 - Proxy Approval Event Projection`
- 行为更新：
  - `PolicyDecision` 现在可选承载 `route`、`target`、`network_profile`、`scope`
  - `SingleAttemptOrchestrator` 在 `POLICY_DECISION_MADE` 与 `APPROVAL_REQUESTED` 事件中按需透传这些代理审批字段
  - 旧的 local-only policy payload 在无代理字段时保持不变
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P23-HAR-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P23-API-01` 与 `P23-OBS-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/smoke/test_mock_harness_loop.py`
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core tests/smoke`
  - `uv run mypy packages/agent-core/src/agent_core/domain/policies.py packages/agent-core/src/agent_core/harness/orchestrator.py tests/agent_core/test_single_attempt_orchestrator.py`

## 2026-06-28 Phase 23 Proxy Approval Readback Surface

- 执行 `P23-API-01 - Proxy Approval Readback Surface`
- 行为更新：
  - 新增 `zebra_agent_api.approval_context.latest_approval_context(...)`
  - `GET /sessions/{id}` 在存在 `approval_requested` 事件时返回只读 `approval_context`
  - approval approve/reject 响应在存在 proxy-aware 审批上下文时回显同一份 `approval_context`
  - readback 仅暴露 `tool_name`、`reason`、`policy_profile`、`route`、`target`、`network_profile`、`scope`，不暴露任何 secret
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P23-API-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_approval_api_app.py tests/api/test_http_app.py tests/api/test_approval_routes.py tests/api/test_http_approvals.py`
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api`
  - `make check`

## 2026-06-29 Phase 23 Proxy Approval Trace Normalization

- 执行 `P23-OBS-01 - Proxy Approval Trace Normalization`
- 行为更新：
  - `HarnessToolTrace` 新增 `policy_route`、`policy_target`、`policy_network_profile`、`policy_scope`
  - `HarnessTraceProjector` 现在会从 `policy_decision_made` 事件中提取并归一化代理审批字段
  - API trace payload 与 `serialize_trace_events(...)` 复用同一套代理审批字段命名
  - non-proxy trace 继续返回 `None` / 空列表或空元组，不改变既有 allow 本地路径语义
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P23-OBS-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P23-CLOSE-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_single_attempt_orchestrator.py tests/api/test_api_app.py tests/api/test_http_app.py`
  - `uv run ruff check packages/agent-core/src/agent_core apps/api/src/zebra_agent_api tests/agent_core tests/api`
  - `make check`

## 2026-06-29 Phase 23 Closeout And Phase 24 Planning

- 执行 `P23-CLOSE-01 - Phase 23 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase23_Proxy_Approval_Projection_And_Operator_Readback_验收记录.md`
- Phase 23 验收结论：
  - proxy-aware approval metadata 已进入 harness events
  - session read 与 approval decision 响应已暴露安全的 `approval_context`
  - trace 与 API trace 已归一化 proxy approval metadata vocabulary
- Phase 24 starter tasks：
  - `P24-STO-01 - Durable Approval Context Projection`
  - `P24-API-01 - Approval Queue And Detail Read API`
  - `P24-OBS-01 - Approval Projection Consistency Checks`
  - `P24-CLOSE-01 - Phase 24 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-29 Phase 24 Durable Approval Context Projection

- 执行 `P24-STO-01 - Durable Approval Context Projection`
- 行为更新：
  - `Session` 新增 durable `approval_context`
  - `session_projection.apply_event(...)` 在 `approval_requested` 事件携带足够字段时持久化审批上下文
  - `approval_granted` / `approval_rejected` 路径保持已有上下文，projection rebuild 结果稳定
  - `SQLiteProjectionStore` 新增 `approval_context_json` 持久化列，并兼容已有表结构升级
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P24-STO-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P24-API-01` 与 `P24-OBS-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_session_projection.py tests/agent_storage/test_sqlite_projection_store.py`
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_core tests/agent_storage`
  - `uv run mypy packages/agent-core/src/agent_core/domain/sessions.py packages/agent-core/src/agent_core/application/session_projection.py packages/agent-storage/src/agent_storage/projections.py tests/agent_core/test_session_projection.py tests/agent_storage/test_sqlite_projection_store.py`

## 2026-06-29 Phase 24 Approval Queue And Detail Read API

- 执行 `P24-API-01 - Approval Queue And Detail Read API`
- 行为更新：
  - 新增 projection-backed `GET /approvals`
  - 新增 projection-backed `GET /approvals/{id}`
  - `GET /sessions/{id}` 与 approval approve/reject 回读现在统一使用 durable `approval_context`
  - approval queue/detail 仅暴露安全字段集，不暴露 secrets 或 raw credential material
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P24-API-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P24-CLOSE-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_approvals.py tests/api/test_approval_api_app.py tests/api/test_http_app.py`
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api`
  - `make check`

## 2026-06-29 Phase 24 Approval Projection Consistency Checks

- 执行 `P24-OBS-01 - Approval Projection Consistency Checks`
- 行为更新：
  - `ApprovalContext` 新增 `to_mapping()`，统一 replay、projection 与 repeated-read 断言使用的安全字段映射
  - `SQLiteEventStore` 回放测试现在校验 `approval_requested` 事件、rebuild 后的 session projection、以及 durable SQLite projection row 之间的 proxy-aware approval vocabulary 一致性
  - `SQLiteProjectionStore` repeated-read 回归覆盖现在验证多次读取 `approval_context` 不会漂移
  - `docs/proxy_gateway_operator_runbook.md` 新增 projection drift check，明确 queue/detail read 与 event replay 或 trace 不一致时的排查顺序
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P24-OBS-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py`
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_core tests/agent_storage`
  - `uv run mypy packages/agent-core/src/agent_core/domain/sessions.py packages/agent-core/src/agent_core/application/session_projection.py packages/agent-storage/src/agent_storage/projections.py tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py`
  - `make check`

## 2026-06-29 Phase 24 Closeout And Phase 25 Planning

- 执行 `P24-CLOSE-01 - Phase 24 Closeout And Next Planning`
- closeout 结论：
  - Phase 24 已完成 durable approval context projection、projection-backed approval queue/detail reads、以及 projection drift consistency coverage
  - proxy-aware approval vocabulary 现在在 event replay、projection、API readback、以及 trace surfaces 上保持一致
  - 下一阶段主线调整为 durable workspace and snapshot foundations
- 新增文档：
  - `docs/Phase24_Durable_Approval_Projection_And_Operator_Queue_验收记录.md`
- 下一阶段 starter tasks：
  - `P25-STO-01 - Durable Workspace Projection Store`
  - `P25-RT-01 - Runtime Snapshot And Resume Contracts`
  - `P25-WKR-01 - Worker Snapshot Lifecycle Wiring`
  - `P25-CLOSE-01 - Phase 25 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-29 Phase 25 Durable Workspace Projection Store

- 执行 `P25-STO-01 - Durable Workspace Projection Store`
- 行为更新：
  - 新增 `WorkspaceProjection` / `WorkspaceStatus` 域模型，持久化当前事件流里已经存在的 durable workspace facts
  - 新增 `rebuild_workspace(...)`，从 `task_prepared`、attempt、approval 与 terminal session events 重建 workspace lifecycle state
  - 新增 `SQLiteWorkspaceProjectionStore`，持久化 `workspace_root`、`policy_profile`、`current_sequence`、`status`、`prepared_at`、`updated_at`、`last_attempt_number`
  - 现有 session projection 路径保持兼容，未提前引入 snapshot-specific runtime fields
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P25-STO-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_workspace_projection.py tests/agent_storage/test_sqlite_workspace_store.py tests/agent_storage/test_sqlite_projection_store.py tests/agent_core/test_session_projection.py`
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_core tests/agent_storage`
  - `uv run mypy packages/agent-core/src/agent_core/domain/workspaces.py packages/agent-core/src/agent_core/application/workspace_projection.py packages/agent-core/src/agent_core/ports/workspace_projection_store.py packages/agent-storage/src/agent_storage/workspaces.py tests/agent_core/test_workspace_projection.py tests/agent_storage/test_sqlite_workspace_store.py`
  - `make check`

## 2026-06-29 Phase 25 Runtime Snapshot And Resume Contracts

- 执行 `P25-RT-01 - Runtime Snapshot And Resume Contracts`
- 行为更新：
  - `RuntimePort` 新增 `RuntimeHandle`、`RuntimeSnapshot` 和 `RuntimeCapabilityError`
  - runtime contract 现在显式建模 `provision`、`snapshot`、`restore`、`fork`、`suspend`、`resume`
  - `LocalRuntime` 新增 deterministic `provision/suspend/resume` handle lifecycle
  - `LocalRuntime` 对 `snapshot/restore/fork` 明确 fail-closed 返回 unsupported，而不伪造本地 snapshot 行为
  - 现有 `execute(...)` 调用面保持兼容，tool/runtime tests 继续通过
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P25-RT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P25-WKR-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_runtime/test_local_runtime.py tests/agent_tools/test_command_run_tool.py tests/agent_tools/test_patch_apply_tool.py tests/agent_tools/test_tests_run_tool.py tests/agent_tools/test_git_status_tool.py`
  - `uv run ruff check packages/agent-core/src/agent_core/ports/runtime.py packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/agent_tools`
  - `uv run mypy packages/agent-core/src/agent_core/ports/runtime.py packages/agent-runtime/src/agent_runtime/adapters/local.py packages/agent-runtime/src/agent_runtime/__init__.py tests/agent_runtime/test_local_runtime.py`
  - `make check`

## 2026-06-29 Phase 25 Worker Snapshot Lifecycle Wiring

- 执行 `P25-WKR-01 - Worker Snapshot Lifecycle Wiring`
- 行为更新：
  - `SessionRecoveryService` 现在优先读取 durable workspace projection，并在缺失时从事件流回放补齐
  - `RecoveredSession` 现在同时携带 `session` 与 `workspace`，避免 worker resume path 再去依赖原始 bootstrap payload 作为 workspace lifecycle state source of truth
  - `SessionExecutionService` 现在从 recovered workspace projection 恢复 `workspace_root` / `policy_profile`
  - worker 追加 `HARNESS_ATTEMPT_STARTED`、tool/policy events、以及 terminal events 时，会同步推进并持久化 workspace projection lifecycle
  - `SessionRecoveryService` 对未提供 workspace store 的调用点保持向后兼容，避免越过本任务 owned paths 去改 CLI/API
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P25-WKR-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P25-CLOSE-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/worker/test_claims.py tests/worker/test_resume.py tests/worker/test_recovery.py tests/worker/test_execution.py tests/worker/test_loop.py`
  - `uv run ruff check apps/worker/src/zebra_agent_worker packages/agent-storage/src/agent_storage tests/worker`
  - `uv run mypy packages apps`
  - `make check`

## 2026-06-29 Phase 25 Closeout And Phase 26 Planning

- 执行 `P25-CLOSE-01 - Phase 25 Closeout And Next Planning`
- closeout 结论：
  - Phase 25 已完成 durable workspace projection、runtime snapshot lifecycle contracts、以及 worker-side workspace lifecycle wiring
  - workspace lifecycle state 现在可以 durable replay，并贯穿 recovery、resume、execution 这条 worker 主链
  - 仍未交付真实 local snapshot backend，也未把 session suspend control path 接到 runtime lifecycle 和 operator surface 上
- 新增文档：
  - `docs/Phase25_Durable_Workspace_And_Snapshot_Foundations_验收记录.md`
- 下一阶段 starter tasks：
  - `P26-RT-01 - Local Snapshot Backend`
  - `P26-APP-01 - Suspend And Resume Control Wiring`
  - `P26-DOC-01 - Snapshot Operator Runbook`
  - `P26-CLOSE-01 - Phase 26 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-29 Phase 26 Local Snapshot Backend

- 执行 `P26-RT-01 - Local Snapshot Backend`
- 行为更新：
  - `LocalRuntime` 现在支持对带 `workspace_root` 的本地句柄执行真实 snapshot
  - snapshot 会把工作目录复制到 runtime-managed `snapshots/<snapshot_id>/workspace/`，并写出 `manifest.json`
  - `restore(...)` 和 `fork(...)` 现在会从 snapshot payload 复制出新的 runtime-managed 工作目录，并返回新的 local runtime handle
  - `RuntimeSnapshot` 现在携带 `workspace_root` 与 `snapshot_path`，避免 restore path 依赖隐藏的进程内状态
  - local snapshot retention 按 source handle 确定性裁剪，超出保留上限时优先删除最旧 snapshot
  - 对无 `workspace_root` 句柄、非 local snapshot、以及已被裁剪或缺失的 snapshot，仍保持显式 fail-closed
- 文档更新：
  - `docs/local_snapshot_runtime.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_runtime/test_local_runtime.py`
  - `uv run ruff check --fix packages/agent-core/src/agent_core/ports/runtime.py packages/agent-runtime/src/agent_runtime/adapters/local.py packages/agent-runtime/src/agent_runtime/adapters/local_snapshots.py tests/agent_runtime/test_local_runtime.py`
  - `uv run mypy packages/agent-core/src/agent_core/ports/runtime.py packages/agent-runtime/src/agent_runtime/adapters/local.py packages/agent-runtime/src/agent_runtime/adapters/local_snapshots.py tests/agent_runtime/test_local_runtime.py`

## 2026-06-29 Phase 26 Suspend And Resume Control Wiring

- 执行 `P26-APP-01 - Suspend And Resume Control Wiring`
- 行为更新：
  - 新增 durable `session_suspended` / `session_resumed` 事件，并把 session 与 workspace projection 的状态映射接通
  - workspace projection 现在持久化 `runtime_name`、`snapshot_id`、`snapshot_path`，用于 suspend 后的 resume restore
  - `SessionControlService` 现在负责本地 suspend snapshot 与 suspended workspace restore
  - worker `execute_session(...)` 在恢复到 suspended session 时，会先 restore 到新的 runtime-managed workspace，再继续原有 harness 执行
  - CLI 新增 `suspend` 命令，API 新增 `POST /sessions/{id}/suspend`，现有 `resume` 执行路径会复用同一套 snapshot-backed restore 逻辑
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_session_projection.py tests/agent_core/test_workspace_projection.py tests/agent_storage/test_sqlite_workspace_store.py tests/worker/test_execution.py tests/api/test_routes.py tests/api/test_http_app.py tests/cli/test_cli_commands.py`
  - `make check`

## 2026-06-29 Phase 26 Snapshot Operator Runbook

- 执行 `P26-DOC-01 - Snapshot Operator Runbook`
- 文档更新：
  - `docs/operator_runbook.md` 现在改为 Phase 26 operator 语义，覆盖 CLI/API suspend、snapshot-backed resume、worker restore 前置、failure interpretation、以及已实现边界
  - `docs/local_snapshot_runtime.md` 去掉了“尚未接线”的旧描述，并补充当前 control-plane integration 说明
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-29 Phase 26 Closeout And Phase 27 Planning

- 执行 `P26-CLOSE-01 - Phase 26 Closeout And Next Planning`
- closeout 结论：
  - Phase 26 已完成 local snapshot backend、snapshot-backed suspend/resume control wiring、以及 Phase 26 operator runbook
  - runtime、workspace projection、worker、CLI、API 与 operator docs 现在共享同一套本地 snapshot 控制语义
  - 仍缺少 projection-backed workspace lifecycle readback 与 snapshot housekeeping/compatibility read surface
- 新增文档：
  - `docs/Phase26_Local_Snapshot_Operator_Controls_验收记录.md`
- 下一阶段 starter tasks：
  - `P27-API-01 - Workspace Lifecycle Readback Surface`
  - `P27-CLI-01 - Workspace Lifecycle Inspect Output`
  - `P27-RT-01 - Snapshot Housekeeping And Compatibility Checks`
  - `P27-CLOSE-01 - Phase 27 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-29 Phase 27 Workspace Lifecycle Readback Surface

- 执行 `P27-API-01 - Workspace Lifecycle Readback Surface`
- 行为更新：
  - `GET /sessions/{id}` 现在在存在 durable workspace projection 时返回 projection-backed `workspace`
  - workspace readback 现在包含 lifecycle status、sequence、prepared/updated time、policy_profile、last_attempt_number
  - suspended workspace readback 会额外返回 snapshot-safe metadata：`runtime_name`、`snapshot_id`、`snapshot_path`
  - 保持向后兼容：没有 workspace projection 的 session read surface 仍然返回既有字段
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_api_app.py tests/api/test_http_app.py tests/api/test_routes.py`
  - `make check`

## 2026-06-29 Phase 27 Workspace Lifecycle Inspect Output

- 执行 `P27-CLI-01 - Workspace Lifecycle Inspect Output`
- 行为更新：
  - `zebra-agent inspect <session_id>` 现在在存在 durable workspace projection 时返回 projection-backed `workspace`
  - `zebra-agent resume <session_id>` 的只读模式现在也返回相同的 workspace lifecycle readback
  - suspended session 的 CLI readback 现在包含 snapshot-safe metadata：`runtime_name`、`snapshot_id`、`snapshot_path`
  - 保持向后兼容：旧的 `session_id`、`title`、`status`、`current_sequence` 字段保持不变
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_commands.py`
  - `make check`

## 2026-06-29 Phase 27 Snapshot Housekeeping And Compatibility Checks

- 执行 `P27-RT-01 - Snapshot Housekeeping And Compatibility Checks`
- 行为更新：
  - local snapshot inspection 现在显式区分 `valid`、`missing`、`incompatible`
  - local runtime restore/fork 会先校验 retained snapshot manifest 与 payload，再决定是否 fail closed
  - worker 恢复 suspended workspace 时会在成功 restore 后显式清理已消费的 retained snapshot payload
  - 新增 retention prune、manifest mismatch、显式 cleanup、以及 worker restore fail-closed 的 regression coverage
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `docs/local_snapshot_runtime.md`
  - `docs/operator_runbook.md`
- 验证：
  - `poetry run pytest tests/agent_runtime/test_local_runtime.py`
  - `poetry run pytest tests/worker/test_execution.py`
  - `make check`

## 2026-06-29 Phase 27 Closeout And Phase 28 Planning

- 执行 `P27-CLOSE-01 - Phase 27 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase27_Workspace_Lifecycle_Readback_And_Snapshot_Housekeeping_验收记录.md`
  - 归档 Phase 27 的 API readback、CLI inspect、snapshot housekeeping 验收结论
  - 将下一阶段定义为 `Phase 28 - Durable Artifact Storage And Retrieval`
  - 新增 `P28-STO-01`、`P28-WKR-01`、`P28-API-01`、`P28-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-29 Phase 28 Durable Artifact Payload Store

- 执行 `P28-STO-01 - Durable Artifact Payload Store`
- 行为更新：
  - 新增 artifact payload 领域模型和 `ArtifactPayloadStorePort`
  - 新增 `SQLiteArtifactPayloadStore`，用 SQLite 持久化 artifact metadata，并用本地文件布局持久化 payload bytes
  - payload inspection 现在显式区分 metadata 缺失与 payload 文件缺失
  - 旧的 `SQLiteArtifactStore.list_for_session(...)` 行为保持不变，避免打破既有 artifact list read surface
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_storage/test_artifact_payloads.py tests/agent_storage/test_artifacts.py tests/agent_core/test_domain_models.py`

## 2026-06-29 Phase 28 Worker Artifact Capture Wiring

- 执行 `P28-WKR-01 - Worker Artifact Capture Wiring`
- 行为更新：
  - `ToolRunIndexer` 现在会把没有显式 `artifact_uri` 的文本 tool output 写入 durable artifact payload store
  - worker execution 产出的 `ToolRunRecord.artifact_uri` 现在可以直接指向本地持久化 payload
  - 已有显式 `artifact_uri` 的工具结果保持原样，避免破坏既有外部 artifact 引用
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/worker/test_tool_run_index.py tests/worker/test_execution.py`

## 2026-06-29 Phase 28 Artifact Detail And Retrieval Surface

- 执行 `P28-API-01 - Artifact Detail And Retrieval Surface`
- 行为更新：
  - 新增 `GET /sessions/{id}/artifacts/{artifact_id}`，返回 artifact detail 和 retrieval state
  - 新增 `GET /sessions/{id}/artifacts/{artifact_id}/content`，对本地 payload-backed artifact 返回 base64 内容
  - retrieval state 现在显式区分 `indexed_only`、`payload_available`、`payload_missing`、`external_reference`
  - 既有 `GET /sessions/{id}/artifacts` 列表响应保持不变
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py`
  - `make check`

## 2026-06-29 Phase 28 Closeout And Phase 29 Planning

- 执行 `P28-CLOSE-01 - Phase 28 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase28_Durable_Artifact_Storage_And_Retrieval_验收记录.md`
  - 归档 Phase 28 的 artifact payload store、worker capture、artifact retrieval 验收结论
  - 将下一阶段定义为 `Phase 29 - Artifact Governance And Operator Parity`
  - 新增 `P29-STO-01`、`P29-CLI-01`、`P29-OBS-01`、`P29-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 29 Artifact Inspect And Read Commands

- 执行 `P29-CLI-01 - Artifact Inspect And Read Commands`
- 行为更新：
  - 新增 `zebra-agent artifact inspect <session_id> <artifact_id>`
  - 新增 `zebra-agent artifact read <session_id> <artifact_id>`
  - CLI retrieval state 现在与 API 对齐，显式区分 `indexed_only`、`payload_available`、`payload_missing`、`external_reference`
  - payload-backed artifact read 现在返回 machine-readable base64 内容
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_commands.py`

## 2026-06-30 Phase 29 Artifact Audit And Preview Redaction

- 执行 `P29-OBS-01 - Artifact Audit And Preview Redaction`
- 行为更新：
  - artifact list/detail 现在暴露 `preview_state`，显式标记 preview 是否发生 redaction/truncation
  - artifact detail/content 读取现在写入 delivery audit，至少记录 `session_id`、`artifact_id`、`action`、`retrieval_status`
  - 非敏感 preview 保持原有可读行为，敏感 preview 会做显式 redaction 和必要截断
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_storage/test_artifacts.py tests/api/test_session_artifacts.py tests/api/test_session_delivery_audit.py`

## 2026-06-30 Phase 29 Artifact Metadata Governance

- 执行 `P29-STO-01 - Artifact Metadata Governance`
- 行为更新：
  - artifact payload metadata 现在显式记录 `lifecycle_status`，并新增可选的 `retained_until` 与 `pruned_at`
  - SQLite artifact payload store 现在支持对既有库做增量列迁移，并保留已有 retrieval contract
  - artifact payload inspection 现在稳定区分 `available`、`missing`、`pruned`
  - pruned payload 会清理本地文件并保留 metadata，后续读取得到显式 `pruned` 失败而不是混同为缺文件
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_storage/test_artifact_payloads.py`

## 2026-06-30 Phase 29 Closeout And Phase 30 Planning

- 执行 `P29-CLOSE-01 - Phase 29 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase29_Artifact_Governance_And_Operator_Parity_验收记录.md`
  - 归档 Phase 29 的 artifact lifecycle metadata、CLI parity、audit and preview safety 验收结论
  - 将下一阶段定义为 `Phase 30 - Local Artifact Retention Enforcement`
  - 新增 `P30-POL-01`、`P30-STO-01`、`P30-API-01`、`P30-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 30 Artifact Retention Policy Profiles

- 执行 `P30-POL-01 - Artifact Retention Policy Profiles`
- 行为更新：
  - 新增 `ArtifactRetentionProfile` 与 `ArtifactRetentionPolicy`，为后续 retention enforcement 提供稳定 core contract
  - `agent-security` 现在根据 `policy_profile` 确定性解析 artifact retention defaults，并提供 `retained_until` 计算入口
  - `local-bootstrap`、`read_only`、`workspace_write`、`full_access` 与未知 profile 的 retention fallback 都有显式规则
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_artifact_retention.py tests/agent_security/test_artifact_retention_policy.py tests/agent_security/test_policy_profiles.py`

## 2026-06-30 Phase 30 Artifact Retention Sweep And Prune Enforcement

- 执行 `P30-STO-01 - Artifact Retention Sweep And Prune Enforcement`
- 行为更新：
  - `SQLiteArtifactPayloadStore.prune_payload()` 现在对已 `pruned` payload 保持幂等，不再覆盖既有 `pruned_at`
  - 新增 `sweep_expired_payloads(as_of=...)`，按 `retained_until <= as_of` 批量清理仍处于 `active` 的本地 payload
  - 到期 sweep 只影响已过期 payload，未过期 payload 保持原状
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_storage/test_artifact_payloads.py`

## 2026-06-30 Phase 30 Artifact Lifecycle Operator Readback

- 执行 `P30-API-01 - Artifact Lifecycle Operator Readback`
- 行为更新：
  - artifact list/detail 现在为 payload-backed local artifact 暴露 additive `lifecycle` 字段
  - lifecycle readback 现在显式返回 `status`、`retained_until`、`pruned_at`、`expired`
  - artifact content 读取现在将 `payload_pruned` 与通用 `payload_missing` 区分开
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py`

## 2026-06-30 Phase 30 Closeout And Phase 31 Planning

- 执行 `P30-CLOSE-01 - Phase 30 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase30_Local_Artifact_Retention_Enforcement_验收记录.md`
  - 归档 Phase 30 的 retention policy、sweep enforcement、lifecycle readback 验收结论
  - 将下一阶段定义为 `Phase 31 - Artifact Operator Controls And Access Foundations`
  - 新增 `P31-SEC-01`、`P31-API-01`、`P31-CLI-01`、`P31-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 31 Artifact Access Classification Foundations

- 执行 `P31-SEC-01 - Artifact Access Classification Foundations`
- 行为更新：
  - 新增 `ArtifactAccessClass` 与 `ArtifactAccessDescriptor`，为 ACL-ready artifact policy 建立稳定 core contract
  - `agent-security` 现在可以将 artifact 分类为 `operator_safe`、`sensitive`、`restricted`
  - local artifact control policy 现在有确定性的最小 policy profile 映射，可供后续 manual prune API/CLI 复用
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_core/test_domain_models.py tests/agent_security/test_artifact_access_policy.py tests/agent_security/test_policy_profiles.py`

## 2026-06-30 Phase 31 Artifact Manual Lifecycle Controls

- 执行 `P31-API-01 - Artifact Manual Lifecycle Controls`
- 行为更新：
  - 新增 `POST /sessions/{id}/artifacts/{artifact_id}/prune`
  - manual prune 现在只作用于 managed payload-backed local artifact
  - prune 结果现在显式区分 `pruned`、`already_pruned`、`artifact_prune_unavailable`、`artifact_prune_denied`
  - delivery audit 现在记录 manual prune 的 access class、required policy 和结果状态
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py`

## 2026-06-30 Phase 31 Artifact Lifecycle CLI Controls

- 执行 `P31-CLI-01 - Artifact Lifecycle CLI Controls`
- 行为更新：
  - 新增 `zebra-agent artifact prune <session_id> <artifact_id>`
  - CLI prune 现在与 API 对齐，显式区分 `pruned`、`already_pruned`、`artifact_prune_unavailable`、`artifact_prune_denied`
  - 现有 artifact inspect/read 路径保持兼容
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifacts.py`

## 2026-06-30 Phase 31 Closeout And Phase 32 Planning

- 执行 `P31-CLOSE-01 - Phase 31 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase31_Artifact_Operator_Controls_And_Access_Foundations_验收记录.md`
  - 归档 Phase 31 的 access classification、manual prune API、CLI parity 验收结论
  - 将下一阶段定义为 `Phase 32 - Artifact Access Enforcement And Audit Parity`
  - 新增 `P32-API-01`、`P32-CLI-01`、`P32-OBS-01`、`P32-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 32 Artifact Access Read Enforcement

- 执行 `P32-API-01 - Artifact Access Read Enforcement`
- 行为更新：
  - artifact detail/content 现在按 access class 做 deterministic gate，而不是只看 payload presence
  - `workspace_write` 现在会被 sensitive artifact read 明确拒绝，`full_access` 仍可读取
  - deny 结果现在显式返回 `artifact_access_denied`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py`

## 2026-06-30 Phase 32 Artifact Access CLI Enforcement

- 执行 `P32-CLI-01 - Artifact Access CLI Enforcement`
- 行为更新：
  - CLI `artifact inspect`、`artifact read`、`artifact prune` 现在共享与 API 一致的 access enforcement 语义
  - CLI deny 结果现在显式返回 `artifact_access_denied`
  - 允许路径保持现有 machine-readable 输出结构
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifacts.py`

## 2026-06-30 Phase 32 Artifact Access Audit Expansion

- 执行 `P32-OBS-01 - Artifact Access Audit Expansion`
- 行为更新：
  - artifact detail/content/prune audit 现在统一记录 `access_class`、`required_policy_profile`、`session_policy_profile`
  - denied 与 unavailable artifact action 现在通过 `result_status`、`retrieval_status` 和 unavailable reason 显式区分
  - 允许路径的 artifact audit 现在也携带 access decision metadata
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py`

## 2026-06-30 Phase 32 Closeout And Phase 33 Planning

- 执行 `P32-CLOSE-01 - Phase 32 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase32_Artifact_Access_Enforcement_And_Audit_Parity_验收记录.md`
  - 归档 Phase 32 的 access enforcement、CLI parity、audit expansion 验收结论
  - 将下一阶段定义为 `Phase 33 - Artifact Access Explainability And Operator Guidance`
  - 新增 `P33-API-01`、`P33-CLI-01`、`P33-DOC-01`、`P33-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 33 Artifact Access Projection Readback

- 执行 `P33-API-01 - Artifact Access Projection Readback`
- 行为更新：
  - API artifact list、detail、content 返回现在统一附带 additive `access` explainability block
  - denied 与 unavailable artifact 响应现在都显式返回 `class`、`required_policy_profile`、`session_policy_profile`、`allowed`
  - operator-facing API readback 现在无需依赖外部规则即可解释 artifact access decision
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifact_access_projection.py tests/api/test_session_artifacts.py`

## 2026-06-30 Phase 33 Artifact Access Explainability CLI Parity

- 执行 `P33-CLI-01 - Artifact Access Explainability Parity`
- 行为更新：
  - CLI `artifact inspect`、`artifact read` 输出现在与 API 对齐，统一携带 additive `access` metadata
  - denied read 输出现在保持 machine-readable，并显式暴露 required policy
  - 允许路径保持兼容，仅新增 explainability 字段
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifact_access_explainability.py tests/cli/test_cli_artifacts.py`

## 2026-06-30 Phase 33 Artifact Access Operator Guidance

- 执行 `P33-DOC-01 - Artifact Access Operator Guidance`
- 行为更新：
  - 新增 `docs/artifact_access_operator_guidance.md`
  - 文档现在明确区分 `artifact_access_denied` 与 `artifact_unavailable`
  - 补充何时提升到 `full_access`，何时应回到 payload regeneration 或上游排查的 operator 指引
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 33 Closeout And Phase 34 Planning

- 执行 `P33-CLOSE-01 - Phase 33 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase33_Artifact_Access_Explainability_And_Operator_Guidance_验收记录.md`
  - 归档 Phase 33 的 API/CLI explainability 与 operator guidance 验收结论
  - 将下一阶段定义为 `Phase 34 - Artifact Access Consolidation And Contract Hardening`
  - 新增 `P34-API-01`、`P34-CLI-01`、`P34-TEST-01`、`P34-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - 复用当前实现分支已经通过的 `make check`

## 2026-06-30 Phase 34 API Artifact Access Projection Consolidation

- 执行 `P34-API-01 - Artifact Access Projection Consolidation`
- 行为更新：
  - API artifact read path 现在通过共享 helper 统一组装 access-denied 与 artifact-unavailable 响应
  - delivery audit 的 access-related result metadata 现在通过单一 helper 构建，减少 detail/content 路径重复逻辑
  - Phase 33 引入的 additive access contract 保持不变，但 API 侧扩展点更集中
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifact_access_projection.py tests/api/test_session_artifacts.py`
  - `make check`

## 2026-06-30 Phase 34 Artifact Access CLI Shared Projection Reuse

- 执行 `P34-CLI-01 - Artifact Access CLI Shared Projection Reuse`
- 行为更新：
  - CLI artifact read path 现在通过共享 helper 统一组装 denied 与 unavailable access response
  - CLI unavailable artifact read 现在补齐 additive `access` metadata，与 API explainability vocabulary 对齐
  - 既有 CLI machine-readable contract 保持兼容，新增字段仅为 additive explainability
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifact_access_explainability.py tests/cli/test_cli_artifacts.py`

## 2026-06-30 Phase 34 Artifact Access Contract Regression Matrix

- 执行 `P34-TEST-01 - Artifact Access Contract Regression Matrix`
- 行为更新：
  - 新增 `tests/test_artifact_access_contract_matrix.py`
  - 新增跨 API/CLI 的 allowed、denied、unavailable artifact access contract matrix
  - matrix 现在直接比较两侧 surface 的 normalized access payload，避免 future refactor 只修一边
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifact_access_projection.py tests/cli/test_cli_artifact_access_explainability.py tests/cli/test_cli_artifacts.py`

## 2026-06-30 Phase 34 Closeout And Phase 35 Planning

- 执行 `P34-CLOSE-01 - Phase 34 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase34_Artifact_Access_Consolidation_And_Contract_Hardening_验收记录.md`
  - 归档 Phase 34 的 API consolidation、CLI parity、cross-surface matrix 验收结论
  - 将下一阶段定义为 `Phase 35 - Artifact Envelope Normalization And Surface Consistency`
  - 新增 `P35-API-01`、`P35-CLI-01`、`P35-TEST-01`、`P35-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-30 Phase 35 API Artifact Success Envelope Normalization

- 执行 `P35-API-01 - Artifact Success Envelope Normalization`
- 行为更新：
  - API artifact detail 成功响应现在显式返回 `status: ok`
  - API artifact content 成功响应现在显式返回 `status: ok`
  - Phase 34 contract matrix 不再需要容忍 API 成功路径“隐式成功”差异，success envelope 语义更稳定
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifact_access_projection.py tests/api/test_session_artifacts.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 35 CLI Artifact Envelope Consistency Parity

- 执行 `P35-CLI-01 - Artifact Envelope Consistency Parity`
- 行为更新：
  - CLI `artifact inspect` 成功 payload 现在补齐 `preview_state` 与 `lifecycle`
  - CLI artifact retrieval 现在显式区分 `payload_pruned`，与 API unavailable reason 对齐
  - CLI 继续保留 `database` 作为本地 operator context；该字段仍是 CLI 特有，不作为 cross-surface strict parity 的一部分
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py`

## 2026-06-30 Phase 35 Artifact Envelope Contract Matrix Expansion

- 执行 `P35-TEST-01 - Artifact Envelope Contract Matrix Expansion`
- 行为更新：
  - 扩展 `tests/test_artifact_access_contract_matrix.py`
  - cross-surface matrix 现在覆盖 operator-safe detail envelope、pruned unavailable envelope，以及既有 allowed/denied/missing 路径
  - API/CLI 共享 envelope 字段现在直接做 normalized 对比，不再只校验 access payload 局部字段
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`

## 2026-06-30 Phase 35 Closeout And Phase 36 Planning

- 执行 `P35-CLOSE-01 - Phase 35 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase35_Artifact_Envelope_Normalization_And_Surface_Consistency_验收记录.md`
  - 归档 Phase 35 的 API success normalization、CLI envelope parity、matrix expansion 验收结论
  - 将下一阶段定义为 `Phase 36 - Shared Artifact Projection Serialization And Adapter Reuse`
  - 新增 `P36-STO-01`、`P36-API-01`、`P36-CLI-01`、`P36-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-30 Phase 36 Shared Artifact Projection Serializer

- 执行 `P36-STO-01 - Shared Artifact Projection Serializer`
- 行为更新：
  - 新增 `packages/agent-storage/src/agent_storage/artifact_projection.py`
  - 抽出 `payload_for_artifact_uri()`、`serialize_artifact_lifecycle()`、`serialize_artifact_retrieval()`、`serialize_session_artifact_projection()`
  - 共享 serializer 现在集中管理 payload lookup、retrieval state、lifecycle state、base artifact envelope 组装，为后续 API/CLI adapter adoption 做准备
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_storage/test_artifact_projection.py tests/agent_storage/test_artifact_payloads.py tests/agent_storage/test_artifacts.py`

## 2026-06-30 Phase 36 API Adapter Shared Projection Adoption

- 执行 `P36-API-01 - API Adapter Shared Projection Adoption`
- 行为更新：
  - API artifact list/detail/content 现在改为复用 `agent-storage` 里的 shared artifact projection serializer
  - 删除 API 本地重复的 retrieval 与 lifecycle 组装逻辑，`session_read.py` 从 470 行降到 422 行
  - access gating、audit metadata、operator-facing API contract 保持兼容
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py tests/api/test_session_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 36 CLI Adapter Shared Projection Adoption

- 执行 `P36-CLI-01 - CLI Adapter Shared Projection Adoption`
- 行为更新：
  - CLI artifact inspect/read 现在改为复用 `agent-storage` 里的 shared artifact projection serializer
  - 删除 CLI 本地重复的 retrieval 与 lifecycle 组装逻辑，`artifact_read.py` 从 411 行降到 368 行
  - CLI 继续保留 `database` 等本地 operator context 字段；共享 envelope 字段由 shared serializer 统一提供
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 36 Closeout And Phase 37 Planning

- 执行 `P36-CLOSE-01 - Phase 36 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase36_Shared_Artifact_Projection_Serialization_And_Adapter_Reuse_验收记录.md`
  - 归档 Phase 36 的 shared serializer、API adoption、CLI adoption 验收结论
  - 将下一阶段定义为 `Phase 37 - Shared Artifact Access Projection And Adapter Reuse`
  - 新增 `P37-SEC-01`、`P37-API-01`、`P37-CLI-01`、`P37-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-30 Phase 37 Shared Artifact Access Projection Serializer

- 执行 `P37-SEC-01 - Shared Artifact Access Projection Serializer`
- 行为更新：
  - 新增 `packages/agent-security/src/agent_security/artifact_access_projection.py`
  - 抽出 `ArtifactAccessProjection`、`build_artifact_access_projection()`、`serialize_artifact_access_projection()`、`policy_rank()`
  - 共享 helper 现在集中管理 access explainability payload 与 session policy rank 判断，为后续 API/CLI access adoption 做准备
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/agent_security/test_artifact_access_policy.py tests/agent_security/test_artifact_access_projection.py tests/agent_security/test_policy_profiles.py`

## 2026-06-30 Phase 37 API Shared Access Projection Adoption

- 执行 `P37-API-01 - API Shared Access Projection Adoption`
- 行为更新：
  - API artifact access adapter 现在改为复用 `agent-security` 里的 shared access projection helper
  - API prune path 也跟随新的 access context 字符串语义完成兼容，不再依赖 enum `.value`
  - access payload、audit metadata、prune contract 保持兼容
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/api/test_session_artifacts.py tests/api/test_session_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 37 CLI Shared Access Projection Adoption

- 执行 `P37-CLI-01 - CLI Shared Access Projection Adoption`
- 行为更新：
  - CLI artifact access adapter 现在改为复用 `agent-security` 里的 shared access projection helper
  - CLI access explainability payload、deny/unavailable contract、prune access fields 继续保持兼容
  - `artifact_read.py` 从 368 行降到 343 行
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 37 Closeout And Phase 38 Planning

- 执行 `P37-CLOSE-01 - Phase 37 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase37_Shared_Artifact_Access_Projection_And_Adapter_Reuse_验收记录.md`
  - 归档 Phase 37 的 shared access helper、API adoption、CLI adoption 验收结论
  - 将下一阶段定义为 `Phase 38 - Shared Artifact Audit Metadata And Denial Response Reuse`
  - 新增 `P38-OBS-01`、`P38-API-01`、`P38-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-30 Phase 38 Shared Artifact Access Audit Metadata Helper

- 执行 `P38-OBS-01 - Shared Artifact Access Audit Metadata Helper`
- 行为更新：
  - 新增 `packages/agent-security/src/agent_security/artifact_access_audit.py`
  - 抽出 `build_artifact_access_audit_metadata()`，集中生成 allow、deny、prune 成功等共享 audit metadata
  - API artifact read 与 prune 的 audit metadata 现在复用同一条 `agent-security` helper 路径
  - `session_artifact_control.py` 改为复用共享 payload lookup 与 lifecycle serializer，压缩 API 侧重复组装逻辑
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py packages/agent-security/src/agent_security tests/agent_security`
  - `uv run mypy packages/agent-security/src/agent_security apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py`
  - `uv run pytest tests/agent_security/test_artifact_access_audit.py tests/agent_security/test_artifact_access_projection.py tests/api/test_session_artifacts.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 38 API Shared Denial Response Adoption

- 执行 `P38-API-01 - API Shared Denial Response Adoption`
- 行为更新：
  - API artifact read adapters 现在复用共享 denial 与 unavailable response helper 路径
  - deny reason 推导集中到 `artifact_access.py`，不再在 `session_read.py` 多处分支内内联拼接
  - read deny 与 unavailable 的 API body 保持兼容，prune deny contract 保持原样
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/session_artifact_control.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/api/test_session_artifacts.py tests/test_artifact_access_contract_matrix.py tests/agent_security/test_artifact_access_audit.py`

## 2026-06-30 Phase 38 Closeout And Phase 39 Planning

- 执行 `P38-CLOSE-01 - Phase 38 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase38_Shared_Artifact_Audit_Metadata_And_Denial_Response_Reuse_验收记录.md`
  - 归档 Phase 38 的 shared audit metadata helper 与 API denial-response adoption 验收结论
  - 将下一阶段定义为 `Phase 39 - CLI Shared Denial Response Reuse And Failure Contract Parity`
  - 新增 `P39-CLI-01`、`P39-TEST-01`、`P39-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-30 Phase 39 CLI Shared Denial Response Adoption

- 执行 `P39-CLI-01 - CLI Shared Denial Response Adoption`
- 行为更新：
  - 新增 `apps/cli/src/zebra_agent_cli/artifact_access.py`
  - CLI artifact inspect 或 read 现在复用共享 denial 与 unavailable response helper 路径
  - CLI 本地 `database` 上下文字段与 prune deny 或 unavailable contract 保持原样
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 39 Artifact Failure Contract Matrix Expansion

- 执行 `P39-TEST-01 - Artifact Failure Contract Matrix Expansion`
- 行为更新：
  - 扩展 `tests/test_artifact_access_contract_matrix.py`
  - 新增 `detail_denied` 场景，显式锁定 API 与 CLI 在 detail deny failure envelope 上的 parity
  - deny 与 unavailable helper adoption 后的跨表面 failure contract 继续保持兼容
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`

## 2026-06-30 Phase 39 Closeout And Phase 40 Planning

- 执行 `P39-CLOSE-01 - Phase 39 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase39_CLI_Shared_Denial_Response_Reuse_And_Failure_Contract_Parity_验收记录.md`
  - 归档 Phase 39 的 CLI denial-response helper adoption 与 failure contract matrix 扩展验收结论
  - 将下一阶段定义为 `Phase 40 - Shared Artifact Control Response Reuse And Prune Contract Parity`
  - 新增 `P40-API-01`、`P40-CLI-01`、`P40-TEST-01`、`P40-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 Phase 40 API Shared Artifact Control Response Adoption

- 执行 `P40-API-01 - API Shared Artifact Control Response Adoption`
- 行为更新：
  - `apps/api/src/zebra_agent_api/artifact_access.py` 新增 shared prune-control denied 与 unavailable response helper
  - `apps/api/src/zebra_agent_api/session_artifact_control.py` 改为复用共享 helper 路径，移除 adapter 内联的 prune conflict body 组装
  - API prune denied 与 unavailable contract 保持原样，不引入额外 `access` 字段
  - 新增 external reference prune unavailable 回归，锁定 shared control-unavailable helper 的返回语义
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py tests/api/test_session_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/api/test_session_artifacts.py`

## 2026-07-01 Phase 40 CLI Shared Artifact Control Response Adoption

- 执行 `P40-CLI-01 - CLI Shared Artifact Control Response Adoption`
- 行为更新：
  - `apps/cli/src/zebra_agent_cli/artifact_access.py` 新增 shared prune-control denied 与 unavailable result helper
  - `apps/cli/src/zebra_agent_cli/artifact_read.py` 改为复用共享 helper 路径，移除 CLI adapter 内联的 prune failure result 组装
  - CLI prune denied 与 unavailable contract 保持原样，继续保留本地 `database` 字段
  - 新增 external reference prune unavailable 回归，锁定 shared control-unavailable helper 的返回语义
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/cli/test_cli_artifacts.py`

## 2026-07-01 Phase 40 Artifact Prune Contract Matrix Expansion

- 执行 `P40-TEST-01 - Artifact Prune Contract Matrix Expansion`
- 行为更新：
  - 扩展 `tests/test_artifact_access_contract_matrix.py`
  - 新增 `prune_denied` 与 `prune_unavailable_external_reference` 场景，显式锁定 API 与 CLI 的 prune failure envelope parity
  - shared prune-control helper adoption 后的跨表面 contract 继续保持兼容
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py tests/test_artifact_access_contract_matrix.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py tests/test_artifact_access_contract_matrix.py`

## 2026-07-01 Phase 40 Closeout And Phase 41 Planning

- 执行 `P40-CLOSE-01 - Phase 40 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase40_Shared_Artifact_Control_Response_Reuse_And_Prune_Contract_Parity_验收记录.md`
  - 归档 Phase 40 的 API/CLI prune failure helper adoption 与 prune contract matrix 扩展验收结论
  - 将下一阶段定义为 `Phase 41 - Shared Artifact Control Success Projection And Prune Success Parity`
  - 新增 `P41-API-01`、`P41-CLI-01`、`P41-TEST-01`、`P41-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 Phase 41 API Shared Artifact Control Success Projection

- 执行 `P41-API-01 - API Shared Artifact Control Success Projection`
- 行为更新：
  - `apps/api/src/zebra_agent_api/artifact_access.py` 新增 shared prune-control success response helper
  - `apps/api/src/zebra_agent_api/session_artifact_control.py` 改为复用共享 helper 路径，移除 API adapter 内联的 prune success body 组装
  - API prune success contract 保持原样，继续暴露 `status`、`access_class`、`required_policy_profile`、`lifecycle`
  - 补强 prune success 回归，显式锁定 `session_id`、`artifact_id` 与 lifecycle 字段边界
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py tests/api/test_session_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/api/test_session_artifacts.py`

## 2026-07-01 Phase 41 CLI Shared Artifact Control Success Projection

- 执行 `P41-CLI-01 - CLI Shared Artifact Control Success Projection`
- 行为更新：
  - `apps/cli/src/zebra_agent_cli/artifact_access.py` 新增 shared prune-control success result helper
  - `apps/cli/src/zebra_agent_cli/artifact_read.py` 改为复用共享 helper 路径，移除 CLI adapter 内联的 prune success result 组装
  - CLI prune success contract 保持原样，继续保留 `database`、`access`、`access_class`、`required_policy_profile`、`lifecycle`
  - 补强 CLI prune success 回归，显式锁定 success result 的字段边界
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/cli/test_cli_artifacts.py`

## 2026-07-01 Phase 41 Artifact Prune Success Contract Matrix Expansion

- 执行 `P41-TEST-01 - Artifact Prune Success Contract Matrix Expansion`
- 行为更新：
  - 扩展 `tests/test_artifact_access_contract_matrix.py`
  - 新增 `prune_success` 与 `prune_already_pruned` 场景，显式锁定 API 与 CLI 的 prune success envelope parity
  - 对非稳定时间戳做 lifecycle 归一化，锁定稳定 contract 而不是瞬时值
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check tests/test_artifact_access_contract_matrix.py apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py tests/test_artifact_access_contract_matrix.py`

## 2026-07-01 Phase 41 Closeout And Phase 42 Planning

- 执行 `P41-CLOSE-01 - Phase 41 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase41_Shared_Artifact_Control_Success_Projection_And_Prune_Success_Parity_验收记录.md`
  - 归档 Phase 41 的 API/CLI prune success helper adoption 与 success contract matrix 扩展验收结论
  - 将下一阶段定义为 `Phase 42 - Shared Artifact Control Audit Metadata Helper`
  - 新增 `P42-OBS-01`、`P42-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 Phase 42 Shared Artifact Control Audit Metadata Helper

- 执行 `P42-OBS-01 - Shared Artifact Control Audit Metadata Helper`
- 行为更新：
  - 新增 `packages/agent-security/src/agent_security/artifact_control_audit.py`
  - 抽出 `build_artifact_control_audit_metadata()`，集中生成 prune denied、success、unavailable 的共享 audit metadata
  - API prune audit path 现在复用同一条 `agent-security` helper 路径，移除 adapter 内联 metadata 组装
  - 新增 security-layer 回归，锁定 shared control audit helper 的稳定输出
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check apps/api/src/zebra_agent_api/session_artifact_control.py packages/agent-security/src/agent_security tests/agent_security tests/api/test_session_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/agent_security/test_artifact_control_audit.py tests/api/test_session_artifacts.py`

## 2026-07-01 Phase 42 Closeout And Phase 43 Planning

- 执行 `P42-CLOSE-01 - Phase 42 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase42_Shared_Artifact_Control_Audit_Metadata_Helper_验收记录.md`
  - 归档 Phase 42 的 shared control audit helper adoption 验收结论
  - 将下一阶段定义为 `Phase 43 - Shared Artifact Audit Metadata Convergence`
  - 新增 `P43-OBS-01`、`P43-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 Phase 43 Shared Artifact Audit Metadata Convergence

- 执行 `P43-OBS-01 - Shared Artifact Audit Metadata Convergence`
- 行为更新：
  - 新增 `packages/agent-security/src/agent_security/artifact_audit_metadata.py`
  - read-side 与 control-side audit helper 现在都复用同一条底层 metadata builder
  - `build_artifact_access_audit_metadata()` 与 `build_artifact_control_audit_metadata()` 保持兼容接口，但不再重复维护核心投影逻辑
  - 新增 shared reason-field variant 回归，锁定 converged audit builder 的稳定输出
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security apps/api/src/zebra_agent_api/session_artifact_control.py tests/api/test_session_artifacts.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/agent_security/test_artifact_access_audit.py tests/agent_security/test_artifact_control_audit.py tests/api/test_session_artifacts.py`

## 2026-07-01 Phase 43 Closeout And Phase 44 Planning

- 执行 `P43-CLOSE-01 - Phase 43 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase43_Shared_Artifact_Audit_Metadata_Convergence_验收记录.md`
  - 归档 Phase 43 的 shared artifact audit convergence 验收结论
  - 将下一阶段定义为 `Phase 44 - Artifact Audit Metadata Contract Coverage`
  - 新增 `P44-TEST-01`、`P44-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 P44-TEST-01 Artifact Audit Metadata Contract Coverage

- 执行 `P44-TEST-01 - Artifact Audit Metadata Contract Coverage`
- 行为更新：
  - 新增 `tests/api/test_artifact_delivery_audit_contract.py`
  - 为 `GET /sessions/{id}/delivery-audit` 增加 artifact read-side denied 与 control-side prune success 的端到端契约回归
  - 显式锁定 `reason`、`retrieval_status`、`payload_artifact_id`、`lifecycle_status` 等 metadata 边界
  - 将 `created_at` 作为唯一的非确定性字段，仅校验 ISO 时间格式
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/api/test_artifact_delivery_audit_contract.py tests/api/test_session_delivery_audit.py tests/api/test_session_artifacts.py`
  - `uv run ruff check tests/api/test_artifact_delivery_audit_contract.py tests/api/test_session_delivery_audit.py tests/api/test_session_artifacts.py`
  - `uv run mypy apps packages tests/api/test_artifact_delivery_audit_contract.py`
  - `make check`

## 2026-07-01 Phase 44 Closeout And Phase 45 Planning

- 执行 `P44-CLOSE-01 - Phase 44 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase44_Artifact_Audit_Metadata_Contract_Coverage_验收记录.md`
  - 归档 Phase 44 的 artifact delivery-audit contract coverage 验收结论
  - 将下一阶段定义为 `Phase 45 - Delivery Audit CLI And Operator Parity`
  - 新增 `P45-CLI-01`、`P45-TEST-01`、`P45-CLOSE-01` 的 path-scoped 任务板
  - 记录主线已合并到 `main`，Phase 44 closeout 基于最新 `origin/main` 完成
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 P45-CLI-01 Delivery Audit CLI Read Surface

- 执行 `P45-CLI-01 - Delivery Audit CLI Read Surface`
- 行为更新：
  - 新增 `apps/cli/src/zebra_agent_cli/delivery_audit_read.py`
  - 新增顶层 CLI 命令 `zebra-agent delivery-audit <session_id>`
  - 本地 CLI 现在可直接读取 session delivery-audit 历史，不再依赖 HTTP API
  - 显式锁定 populated、empty、missing-session 三类 machine-readable 输出语义
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make sync`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/delivery_audit_read.py tests/cli/test_cli_delivery_audit.py`
  - `uv run mypy packages apps`
  - `uv run pytest tests/cli/test_cli_delivery_audit.py tests/cli/test_cli_commands.py tests/cli/test_cli_artifacts.py`

## 2026-07-01 P45-TEST-01 Delivery Audit Cross-Surface Contract Matrix

- 执行 `P45-TEST-01 - Delivery Audit Cross-Surface Contract Matrix`
- 行为更新：
  - 新增 `tests/test_delivery_audit_contract_matrix.py`
  - 显式锁定 API 与 CLI 在 populated、empty、missing-session 三类 delivery-audit 读取路径上的共享契约
  - 将 CLI 本地 `database` 上下文字段视为 CLI-only 差异，不纳入 cross-surface 共享契约比较
  - 用同一条 matrix 同时覆盖 SCM audit record 与空历史或缺失 session 边界
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make sync`
  - `uv run pytest tests/test_delivery_audit_contract_matrix.py tests/api/test_session_delivery_audit.py tests/api/test_artifact_delivery_audit_contract.py tests/cli/test_cli_delivery_audit.py`
  - `uv run ruff check tests/test_delivery_audit_contract_matrix.py`
  - `uv run mypy packages apps`

## 2026-07-01 Phase 45 Closeout And Phase 46 Planning

- 执行 `P45-CLOSE-01 - Phase 45 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase45_Delivery_Audit_CLI_And_Operator_Parity_验收记录.md`
  - 归档 Phase 45 的 delivery-audit CLI parity 与 cross-surface contract matrix 验收结论
  - 将下一阶段定义为 `Phase 46 - Session Diff CLI And Operator Parity`
  - 新增 `P46-CLI-01`、`P46-TEST-01`、`P46-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 P46-CLI-01 Session Diff CLI Read Surface

- 执行 `P46-CLI-01 - Session Diff CLI Read Surface`
- 行为更新：
  - 新增 `apps/cli/src/zebra_agent_cli/session_diff_read.py`
  - 新增顶层 CLI 命令 `zebra-agent diff <session_id>`
  - 复用现有 workspace diff service 与 session bootstrap 事件中的 `workspace_root`
  - 本地 CLI 现在可直接读取 session workspace diff，不再依赖 HTTP API
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/cli/test_cli_session_diff.py tests/api/test_session_diff.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_diff_read.py tests/cli/test_cli_session_diff.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 P46-TEST-01 Session Diff Cross-Surface Contract Matrix

- 执行 `P46-TEST-01 - Session Diff Cross-Surface Contract Matrix`
- 行为更新：
  - 新增 `tests/test_session_diff_contract_matrix.py`
  - 显式锁定 API 与 CLI 在 dirty、clean、missing-session、non-git 四类 session diff 读取路径上的共享契约
  - 将 CLI 本地 `database` 上下文字段排除在 cross-surface 共享契约之外
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/test_session_diff_contract_matrix.py tests/api/test_session_diff.py tests/cli/test_cli_session_diff.py`
  - `uv run ruff check tests/test_session_diff_contract_matrix.py`

## 2026-07-01 Phase 46 Closeout And Phase 47 Planning

- 执行 `P46-CLOSE-01 - Phase 46 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase46_Session_Diff_CLI_And_Operator_Parity_验收记录.md`
  - 归档 Phase 46 的 session diff CLI parity 与 cross-surface contract matrix 验收结论
  - 将下一阶段定义为 `Phase 47 - Session Stream CLI And Operator Parity`
  - 新增 `P47-CLI-01`、`P47-TEST-01`、`P47-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 P47-CLI-01 Session Stream CLI Read Surface

- 执行 `P47-CLI-01 - Session Stream CLI Read Surface`
- 行为更新：
  - 新增 `apps/cli/src/zebra_agent_cli/session_stream_read.py`
  - 新增顶层 CLI 命令 `zebra-agent stream <session_id>`
  - 复用现有 session stream 事件投影格式作为 CLI 本地读面
  - 本地 CLI 现在可直接读取 persisted session event stream，不再依赖 HTTP API
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/cli/test_cli_session_stream.py tests/api/test_api_app.py tests/api/test_http_app.py tests/api/test_routes.py -k stream`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_stream_read.py tests/cli/test_cli_session_stream.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 P47-TEST-01 Session Stream Cross-Surface Contract Matrix

- 执行 `P47-TEST-01 - Session Stream Cross-Surface Contract Matrix`
- 行为更新：
  - 新增 `tests/test_session_stream_contract_matrix.py`
  - 显式锁定 API SSE replay 与 CLI stream 在 populated、bootstrap-only、missing-session 三类读取路径上的共享契约
  - 将 SSE framing 与 CLI 本地 `database` 上下文字段排除在 cross-surface 共享契约之外
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/test_session_stream_contract_matrix.py tests/cli/test_cli_session_stream.py tests/api/test_api_app.py tests/api/test_http_app.py tests/api/test_routes.py -k stream`
  - `uv run ruff check tests/test_session_stream_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 Phase 47 Closeout And Phase 48 Planning

- 执行 `P47-CLOSE-01 - Phase 47 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase47_Session_Stream_CLI_And_Operator_Parity_验收记录.md`
  - 归档 Phase 47 的 session stream CLI parity 与 cross-surface contract matrix 验收结论
  - 将下一阶段定义为 `Phase 48 - Session Commit CLI And Operator Parity`
  - 新增 `P48-CLI-01`、`P48-TEST-01`、`P48-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-07-01 P48-CLI-01 Session Commit CLI Delivery Surface

- 执行 `P48-CLI-01 - Session Commit CLI Delivery Surface`
- 行为更新：
  - 新增 `apps/cli/src/zebra_agent_cli/session_commit_write.py`
  - 新增顶层 CLI 命令 `zebra-agent commit <session_id> --message ...`
  - CLI 复用现有 `SessionCommitApi`，继承 policy、idempotency、delivery-audit 与 runtime commit 语义
  - 本地 CLI 现在可直接执行 session commit，不再依赖 HTTP API
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/cli/test_cli_session_commit.py tests/api/test_session_commit.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/session_commit_write.py tests/cli/test_cli_session_commit.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 P48-TEST-01 Session Commit Cross-Surface Contract Matrix

- 执行 `P48-TEST-01 - Session Commit Cross-Surface Contract Matrix`
- 行为更新：
  - 新增 `tests/test_session_commit_contract_matrix.py`
  - 显式锁定 API 与 CLI 在 committed、policy-blocked、clean-workspace unavailable、missing-session 路径上的共享 commit 契约
  - 使用 cross-surface idempotency replay 覆盖 API->CLI 与 CLI->API 两个方向
  - 将 CLI 本地 `database` 字段排除在共享契约边界之外
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `make sync`
  - `uv run pytest tests/test_session_commit_contract_matrix.py tests/cli/test_cli_session_commit.py tests/api/test_session_commit.py`
  - `uv run ruff check tests/test_session_commit_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 Phase 48 Closeout And Phase 49 Planning

- 执行 `P48-CLOSE-01 - Phase 48 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase48_Session_Commit_CLI_And_Operator_Parity_验收记录.md`
  - 归档 Phase 48 的 session commit CLI parity 与 cross-surface contract matrix 验收结论
  - 将下一阶段定义为 `Phase 49 - Session Pull Request CLI And Operator Parity`
  - 新增 `P49-CLI-01`、`P49-TEST-01`、`P49-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `make check`

## 2026-07-01 P49-CLI-01 Session Pull Request CLI Delivery Surface

- 执行 `P49-CLI-01 - Session Pull Request CLI Delivery Surface`
- 行为更新：
  - 新增 `apps/cli/src/zebra_agent_cli/session_pull_request_write.py`
  - 新增顶层 CLI 命令 `zebra-agent pull-request <session_id> --title ...`
  - CLI 复用现有 `ZebraAgentApi.open_session_pull_request` 组合路径，继承 SCM gateway、policy、idempotency、delivery-audit 与 guarded execution 语义
  - 本地 CLI 现在可直接执行 session pull-request 规划或显式 guarded execution，不再依赖 HTTP API
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
  - `WORKLOG.md`
- 验证：
  - `make sync`
  - `uv run pytest tests/cli/test_cli_session_pull_request.py tests/api/test_session_pull_request.py`
  - `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/session_pull_request_write.py tests/cli/test_cli_session_pull_request.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 P49-TEST-01 Session Pull Request Cross-Surface Contract Matrix

- 执行 `P49-TEST-01 - Session Pull Request Cross-Surface Contract Matrix`
- 行为更新：
  - 新增 `tests/test_session_pull_request_contract_matrix.py`
  - 显式锁定 API 与 CLI 在 dry-run、created、policy-blocked、unavailable、missing-session 路径上的共享 pull-request 契约
  - 使用 cross-surface idempotency replay 覆盖 `API -> CLI` 与 `CLI -> API` 两个方向
  - 将 CLI 本地 `database` 字段排除在共享契约边界之外
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `make sync`
  - `uv run pytest tests/test_session_pull_request_contract_matrix.py tests/cli/test_cli_session_pull_request.py tests/api/test_session_pull_request.py`
  - `uv run ruff check tests/test_session_pull_request_contract_matrix.py`
  - `uv run mypy packages apps`
  - `make check`

## 2026-07-01 Phase 49 Closeout And Phase 50 Planning

- 执行 `P49-CLOSE-01 - Phase 49 Closeout And Next Planning`
- 行为更新：
  - 新增 `docs/Phase49_Session_Pull_Request_CLI_And_Operator_Parity_验收记录.md`
  - 归档 Phase 49 的 session pull-request CLI parity 与 cross-surface contract matrix 验收结论
  - 将下一阶段定义为 `Phase 50 - Approval Queue CLI And Operator Parity`
  - 新增 `P50-CLI-01`、`P50-TEST-01`、`P50-CLOSE-01` 的 path-scoped 任务板
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
  - `WORKLOG.md`
- 验证：
  - `make check`
## 2026-07-17 CTX-LC-01 Context Lifecycle And Hybrid Compaction

- Split provider-specific DeepSeek work into independent `DS-OPT-01` task/thread.
- Added model-window reserves and a non-bypassable initial/follow-up hard gate.
- Added complete Artifact persistence with bounded head/tail model projection
  for command/test output; existing small stdout compatibility remains intact.
- Added versioned transparent `ContextCapsule`, durable compaction events,
  pending-tool/source-hash state, and worker recovery reinjection.
- Added provider continuation capability/reference contracts with deterministic
  Capsule fallback; opaque provider state is never event authority.
- Added API/CLI context inspect and non-running-boundary manual compact controls.
- Completed typed micro-compaction, protected-instruction projection, exact-tail
  preservation, policy/provenance-checked Artifact rehydration, atomic Capsule
  activation, provider-scoped continuation lifecycle, focus/preview/through-event
  controls, historical recovery, and pre/post compaction hooks.
- Validation: focused context/tool/API/CLI/recovery suites passed; `make test`
  passed `1379` with one gVisor platform skip; `make check` passed file-size,
  Ruff, strict Mypy (`379` files), and `8` release evals.

## 2026-07-18 UI-LOBE-01 Lobe UI Component Library Integration

- Created and claimed the path-bounded `UI-LOBE-01` task on
  `codex/ui-lobe-01-component-library` without touching the dirty governance
  worktree.
- Added current Lobe UI and aligned its top-level React/Ant Design ecosystem:
  `@lobehub/ui 5.22.3`, `antd 6.5.1`, `antd-style 4.1.0`, Motion 12,
  Lobe Icons 5, and Fluent Emoji 4.
- Replaced the root Ant Design-only provider with Lobe `ThemeProvider` while
  preserving Zebra's dark tokens, Ant App, React Query, Ant Design X, and all
  durable session/event behavior.
- Switched TypeScript module resolution to Bundler for the package's official ESM
  subpath export and migrated the one Drawer `width` deprecation to `size`.
- Added `check:lobe-ui`; all 20 Desktop checks, TypeScript, Vite build, and real
  browser rendering passed with no console warnings. The existing aggregate
  chunk warning remains, but size did not regress from the mainline baseline.
- Repository validation passed `1452` tests with four documented environment /
  credential skips, file-size `868`, Ruff, strict Mypy across `403` source files,
  and all `8` release Evals.

## 2026-07-19 CTX-SEG-P0-01 Invisible Internal Execution Segments

- Claimed `CTX-SEG-P0-01` on `codex/ctx-seg-p0-invisible-ui` in an isolated
  worktree and recorded ADR-013 plus the dependency-ordered P0-P4 roadmap.
- Superseded explicit user-operated handoff as the normal product interaction;
  one stable Task is now the user-visible boundary and execution Segments are
  defined as backend-internal state.
- Removed Desktop's stage handoff card, client hook/helpers, API methods, types,
  and prop plumbing. Existing backend safety contracts remain unchanged and
  disabled by default.
- Replaced the old handoff helper check with a source-level regression that
  prevents ordinary user surfaces from regaining child-Session creation controls.
- Validation completed so far:
  - `volta run --node 22.17.0 pnpm run check:handoff`
  - `volta run --node 22.17.0 pnpm run build`
  - all `20` Desktop `check:*` scripts
  - initial `make test`: `1491 passed, 7 skipped`; the file-size test required
    staging deleted tracked files before its Git-index-based scan could complete
  - final `make test`: `1492 passed, 7 skipped`
  - `make check`: file-size `887`, Ruff, strict Mypy over `412` source files,
    and all `8` release evals passed

## 2026-07-19 SUBAGENT-UX-01 Model-Native Subagent Delegation

- Created and independently reviewed the focused model-native delegation design.
- Rebuilt `codex/subagent-delegation-model-native` directly from `origin/main`
  instead of shipping a stacked dependency on the unmerged Web UX branch.
- Added manifest-aware parent guidance, mandatory non-empty delegation reasons,
  bounded actionable validation results, result usage/reason evidence, and
  non-recursive child prompt behavior.
- Returned sequential and concurrent failed tools to the model for correction or
  fallback while preserving hard deterministic stop conditions.
- Added direct-answer, direct-parent-tool, explicit complex delegation, invalid
  reason correction, failed-child fallback, and child non-recursion regressions.
- Validation: focused `39 passed`; full `1509 passed, 5 skipped`; file-size `898`,
  Ruff, strict Mypy `417`, and release Eval `8/8` passed.
- Real-model isolated API Task `79c59c46-4869-4fd0-8383-db2528e955fc` answered
  `1+1` as `2` with no tools or Subagent lifecycle events.

## 2026-07-20 CTX-SEG-02 Follow-up Context And Budget Recovery

- Reconstructed failed Task `d3206b32-fcb2-435a-9bca-34143cb3072f` from its
  durable Task/Segment stream and identified context loss before tool-budget failure.
- Added bounded previous user/Assistant evidence to automatic Handoff Envelopes.
- Replaced implicit API/Harness `4/3` and `8/6` call ceilings with optional limits.
- Explicit over-budget batches now start nothing and suspend recoverably; batches
  that exactly consume a tool allowance may use a remaining model turn to close.
- Hid NoopVerifier status noise from Desktop timeline and log presentation.
- Focused API/Core/Worker regression: `74 passed`.
- Full deterministic suite: `1519 passed, 7 skipped`.
- File-size gate checked `899` files; Ruff, strict Mypy over `419` source files,
  and all `8/8` release Evals passed.
- All `22` Desktop checks and the production Vite build passed with bundled
  Node 22; Tauri was intentionally omitted per the explicit scope waiver.
- Closeout review found the local harness wrapper still imposed the legacy `4/3`
  limits and the synchronous API dropped explicit budgets. The shared wrapper now
  defaults both budgets to `None`, the API forwards caller limits, and direct
  runtime/API regressions cover both paths.
- Final closeout validation: focused `56 passed`; full `1520 passed, 7 skipped`;
  file-size `901`, Ruff, strict Mypy over `419` source files, release Eval `8/8`,
  affected Desktop timeline check, and production Vite build all passed.

## 2026-07-22 — HAR-TOOL-RECOVERY-01: tool failure must not produce session terminal

- **Trigger**: a `web.fetch` of a non-existent `README.md` returned HTTP 404;
  the agent re-issued the identical call and hit `repeated_tool_call` which
  produced `session_failed`, terminating the task instead of letting the model
  self-correct to `SKILL.md`.
- **Root cause**: `ToolBatchExecutor` treated the first repeated call as a
  terminal `FAILED`, and sequential batches returned on the first tool failure
  (leaving sibling calls unexecuted). There was also no provider-protocol
  validation before model requests, so an unpaired tool batch could leak as a
  DeepSeek `invalid_request`.
- **Branch**: `codex/har-tool-recovery-01`.
- **Changes**:
  - `tool_batch.py`: repeated calls now become `ToolResult(FAILED)` observations
    with `reason=repeated_tool_call`; a per-fingerprint counter in metadata
    gates a `loop_guard_exhausted` hard stop at threshold (default 3). Sequential
    batches `continue` past a mid-batch failure instead of returning early.
  - `concurrent_batch.py`: same repeat-as-observation + threshold semantics;
    duplicate calls inside a concurrent batch are excluded from execution and
    merged as observations.
  - `protocol_invariants.py` (new): `HarnessInvariantError` +
    `validate_tool_call_pairing` enforcing orphan-result, dangling-call, and
    duplicate-id invariants using the same wire key as the serializer.
  - `model_step.py`: `request_completion` calls the firewall after the context
    budget gate, before any gateway branch.
  - `__init__.py`: export `HarnessInvariantError`.
- **Tests**: `test_tool_failure_recovery.py` (9 new cases: batch-continues-after-
  failure, all-failed-returns-to-model, 404-correction, repeat-as-observation,
  firewall accepts/rejects orphan/unpaired/duplicate/out-of-order). Updated 3
  existing tests whose `repeated_tool_call` terminal assertions no longer hold.
- **Validation**: `tests/agent_core/` `222 passed, 1 skipped` (the single
  `test_context_capsule_validation` failure is pre-existing on `main`). Full
  suite `1719 passed, 6 skipped, 13 failed` — all 13 failures are pre-existing
  on `main` (capsule artifact-refs + web-pipeline-v2 authority + one oversized
  test file). Ruff and mypy clean on all touched source files.

## 2026-07-22 — Pre-existing test failures resolved (13 → 0)

While validating HAR-TOOL-RECOVERY-01, resolved 13 pre-existing test failures
on `main` that fell into three independent root causes:

### Cluster A — artifact_refs trailing-punctuation not stripped (8 tests)
- **Root cause**: `_ARTIFACT_URI` regex in `agent_context/capsule.py` used
  `[^\s\])]+` which did not exclude quotes/commas/parens, so
  `file:///tmp/payload.txt",` was captured verbatim. The `ContextCapsule`
  validator compared raw refs against `readable_artifact_refs` without
  normalization, and `persist_context_compaction` built `readable_refs` only
  from `artifact_refs` (omitting `recent_exact_tail_refs`).
- **Fix**: tightened the regex character class, added `_normalize_artifact_ref`
  in both `capsule.py` and `context_capsule.py` (field_validator on
  `artifact_refs`/`recent_exact_tail_refs`), added `referenced_artifact_refs`
  computed property, and expanded the worker's `readable_refs` to include
  non-file refs from `recent_exact_tail_refs`.
- **Files**: `packages/agent-context/src/agent_context/capsule.py`,
  `packages/agent-core/src/agent_core/domain/context_capsule.py`,
  `apps/worker/src/zebra_agent_worker/context_lifecycle.py`,
  `apps/api/src/zebra_agent_api/session_context_control.py` (consumer of the
  new property).

### Cluster B — web pipeline v2 never activated in worker (4 tests)
- **Root cause**: `LocalToolGateway` construction in
  `apps/worker/src/zebra_agent_worker/execution.py` did not pass
  `web_pipeline_v2=self._settings.web_pipeline_v2`, so the worker always used
  the legacy v1 path regardless of the `ZEBRA_WEB_PIPELINE_V2` setting.
  Additionally, `RecordingFetchProvider`/`RecordingSearchProvider` were defined
  in `test_web_pipeline_v2_authority.py` but referenced (undefined) in
  `test_approved_continuation.py`.
- **Fix**: added the missing `web_pipeline_v2` kwarg to the worker's
  `LocalToolGateway` call; extracted the two provider doubles into a shared
  `tests/worker/web_v2_providers.py` module imported by both test files.
- **Files**: `apps/worker/src/zebra_agent_worker/execution.py`,
  `tests/worker/web_v2_providers.py` (new),
  `tests/worker/test_web_pipeline_v2_authority.py`,
  `tests/worker/test_approved_continuation.py`.

### Cluster C — oversized test file (1 test)
- **Root cause**: `tests/worker/test_approved_continuation.py` was 807 lines
  (limit 700), inflated by two web-v2 tests that duplicated
  `test_web_pipeline_v2_authority.py`.
- **Fix**: removed the two duplicate v2 tests (already covered by the
  authority test file) and their now-unused imports. File is now 684 lines.
- **Files**: `tests/worker/test_approved_continuation.py`.

### Validation
- `make test`: `1730 passed, 6 skipped` (was `1719 passed, 13 failed`).
- `make check`: file-size gate `956 checked, 0 violations`; Ruff clean on all
  touched files; mypy clean on `agent-core` + `agent-context`.

## 2026-07-22 — CTX-ART-01: Authoritative Artifact Refs And Safe Compaction Fallback

System-level fix for the Context/Artifact architecture problems that caused the
original capsule test failures. Rejects the "fix the regex" approach (which only
hides the symptom) and addresses two root causes:

### P1: Artifact refs come only from structured metadata
- **Removed** free-text URI scanning from `agent_context/capsule.py`
  (`_ARTIFACT_URI.findall(message.content)`) and `agent_context/projection.py`
  (`_artifact_uri` helper). A URI appearing in a file read, command stdout, or
  error traceback can no longer be promoted to a capsule artifact ref.
- **Kept** only the structured `message.metadata["artifact_uri"]` channel, set
  exclusively by `ToolOutputProjector`, `WebResultEnvelope`, and `SearchHit`.
- **Tests**: `test_capsule.py` rewritten to verify that URIs in free text
  produce no refs; only structured metadata is collected.

### P3: Compaction failure degrades instead of terminating
- **`apps/worker/.../context_lifecycle.py`**: `persist_context_compaction` now
  catches `ContextCapsuleValidationError`, records a non-terminal
  `CONTEXT_COMPACTION_REJECTED` diagnostic event, preserves the existing active
  projection, and returns normally. The Agent continues with the in-memory
  compacted conversation. Implements design doc §L4 item 4: "验证失败时回退到
  确定性 Capsule;不得替换当前可用投影".
- **`apps/worker/.../execution.py`**: the defensive `except` that previously
  mapped `ContextCapsuleValidationError` to `session_failed` now classifies it
  as `SUSPENDED` (`stop_reason="context_recovery_required"`) — a recovery
  signal, not a model execution failure.
- **`events.py`**: added `CONTEXT_COMPACTION_REJECTED` event type.
- **`execution_errors.py` (new)**: extracted `exception_attempt_result` and
  `error_metadata` helpers to keep `execution.py` under the 500-line limit.
- **Test**: `test_compaction_validation_failure_degrades_instead_of_raising`
  proves a capsule with an unreadable artifact ref produces
  `CONTEXT_COMPACTION_REJECTED` (not `SESSION_FAILED`) and preserves the active
  projection.

### Validation
- `make test`: `1732 passed, 6 skipped, 0 failed`.
- `make check`: file-size `959 checked, 0 violations`; Ruff clean; mypy clean
  on `agent-context` + `agent-core/domain/events.py`.

### Not in scope (follow-up tasks)
- CTX-ART-02: stable `artifact://` identity migration (file:// → artifact://).
- CTX-OBS-01: terminal accounting for model/tool call count accuracy.

## 2026-07-22 — CTX-ART-02: Stable artifact:// Identity Migration

Migrates emitted artifact URIs from volatile `file://` locators to a stable
`artifact://<uuid>` identity, resolved back to a file path only at the point of
actual byte access.

- **`agent_storage/artifact_payloads.py`**: `SQLiteArtifactPayloadStore.store`
  now emits `uri=f"artifact://{artifact_id}"` and adds a new `access_uri` column
  holding the original `file://` locator; `inspect_payload`/`prune_payload`/
  `read_payload_bytes` resolve the file path through the new
  `_stored_payload_path` helper (prefers `access_uri`, falls back to `uri` for
  legacy rows).
- **`agent_core/domain/artifact_payloads.py`**: `StoredArtifactPayload` gains
  `access_uri: str | None`.
- **`agent_storage/artifact_projection.py`**: `payload_for_artifact_uri` and
  `serialize_artifact_retrieval` accept both `artifact://` and `file://`
  schemes; `artifact://` retrievability is derived from lifecycle status
  (identity is stable, file location is volatile).
- **`agent_security/artifact_access.py`**: `artifact` added alongside `file` to
  the non-`RESTRICTED` local URI scheme allowlist.
- **API/CLI read paths** (`session_artifact_read_mixin.py`,
  `artifact_read.py`): resolve `artifact://` through the payload store to the
  volatile `access_uri` before reading bytes.
- **Regression caught in review**: the API mixin's `artifact://` branch relied
  on `serialize_artifact_retrieval`'s lifecycle-based `payload_available`
  status and skipped the filesystem check the `file://` branch had, so a
  physically-deleted-but-still-`ACTIVE` payload raised an unhandled
  `FileNotFoundError` instead of the `artifact_payload_missing` response (2
  test failures). Fixed by adding the same `read_path.is_file()` guard already
  present in the CLI path.
- **Validation**: `make test` `1732 passed, 6 skipped, 0 failed`; `make check`
  file-size `959 checked, 0 violations`; Ruff and mypy clean on all touched
  files (pre-existing failures in `web_crawl.py`, `mcp_proxy_policy.py`, and
  the `web-native` test/tool cluster confirmed unrelated via `git stash`
  comparison against the base commit).
# 2026-07-28 CTX-MEM-01 Issue #197 Context Continuity

- verified main at `f7d16c45`; preserved dirty user-owned `AGENTS.md` and
  `.zebra-agent/sessions.sqlite` in the main checkout
- created `codex/issue-197-context-memory-continuity` in isolated worktree
  `../zebra-agent-issue-197` from `origin/main`
- ran `make sync`; corrected focused baseline passed `33` tests
- confirmed no implementation overlap with stacked `MEM-GW-CON-01`; shared
  governance files may require ordinary rebase reconciliation later
- completed current official-source comparison for Codex/OpenAI, Claude,
  Pi Agent and Hermes; design and implementation plan are being written first

# 2026-07-28 HAR-CONV-01 Design Handoff

- created `codex/runtime-convergence-phase1` in isolated worktree
  `../zebra-runtime-convergence`; the branch is stacked on PR `#198` and merges
  the current `origin/main@a6b47c3` proposal baseline without modifying `main`
- added the executable two-stage convergence design and task cards; only
  `HAR-CONV-01` is active, while `CTX-REHYDRATE-02` remains locked
- Phase 1 owns the shared `agent-core` Harness convergence path and focused
  tests; `model_step.py`, Context, Storage, Worker, providers/MCP and FinOS are
  explicit stop boundaries
- `git diff --check` passed and the uncommitted task diff is documentation-only
- `make check` reached the inherited file-size gate and stopped on the same two
  out-of-scope files already recorded by PR `#198`:
  `CodexConversationPane.styles.ts` (561/500) and `events.py` (505/500)
- next action: commit and push the documentation baseline, then hand the exact
  branch/worktree and red-test-first instructions to Codex task
  `019f9a26-59b5-77e2-b42e-5e6ede10520c`

# 2026-07-28 HAR-CONV-01 Phase 1 Coding Handoff

- **Scope**: implemented only the authorized shared Harness paths plus
  `tests/agent_core/test_harness_convergence.py`; did not modify `model_step.py`,
  Context, Storage, Worker, provider/MCP, UI, FinOS, or `main`.
- **Root fix**: exact action fingerprints remain the effect/idempotency guard.
  Executed results now produce stable observation fingerprints from tool name,
  status, normalized output, and stable artifact/source references, excluding
  provider IDs, timestamps, and JSON display order. Batch-level new evidence or
  durable Plan/Approval state changes reset the no-progress counter.
- **Convergence**: threshold exhaustion writes a structured model-visible
  observation, permits exactly one `allow_tools=False` synthesis, completes on
  non-empty text, and otherwise returns `SUSPENDED` with
  `stop_reason=tool_loop_no_progress`. No default call limit, state database,
  business heuristic, retry framework, or Phase 2 rehydration work was added.
- **Deterministic evidence**: red-first convergence suite initially failed `5`;
  final focused suite passed `63`, including semantic argument variants,
  provider-id/timestamp and JSON-order stability, exact-repeat dedupe,
  Plan/Approval reset, sequential/concurrent parity, one terminal synthesis,
  typed suspension, and a progressing nine-tool chain. Touched-file Ruff and
  Mypy passed; `git diff --check` passed.
- **Full validation**: `make test` ran `1773` tests: `1756 passed, 9 failed,
  8 skipped`. The nine failures are inherited outside owned paths (two provider
  parser cases, five SCM credential cases, the two-file size gate, and one
  worker cancellation case). `make check` stops at the documented file-size
  gate: `CodexConversationPane.styles.ts` `561/500` and `events.py` `505/500`.
- **Commit / review**: the Phase 1 delivery commit is on
  `codex/runtime-convergence-phase1` only; do not merge or push it to `main`.
  This original handoff treated the read-only three-image A/B as remaining user
  acceptance; the 2026-07-29 record below supersedes that boundary and assigns
  image/MiniMax acceptance to the FinOS project branch. Phase 2
  `CTX-REHYDRATE-02` stays `Locked`.

# 2026-07-29 HAR-CONV-01 Post-review Repair And Text A/B

- separated the Zebra `main` convergence line from FinOS image attachment and
  MiniMax MCP acceptance; HAR-CONV-01 now uses the same Skill plus manually
  transcribed evidence with no image attachment, MCP allowlist or FinOS provider
- added red regressions for volatile production Artifact URIs, mixed batches
  containing historical and fresh work, convergence instructions displacing
  real user turns, typed stop-reason propagation, and raw DeepSeek DSML tool
  requests being falsely accepted as final answers
- the minimal repair uses `output_sha256` before volatile projection references,
  preserves fresh mixed-batch calls and Policy/Plan/Approval audit, emits one
  internal SYSTEM convergence instruction, and returns typed
  `tool_loop_no_progress` when tool-disabled synthesis still requests a tool
- deterministic verification passes `70` focused tests plus touched-file Ruff,
  Mypy and `git diff --check`; the latest full run is `1763 passed, 9 failed,
  8 skipped`, with the same inherited provider, SCM credential, Worker
  cancellation and two file-size failures
- live baseline evidence on unmodified `main@a6b47c3` had no image/MiniMax/FinOS
  dependency and was manually cancelled after 10 complete model responses,
  13 `web.fetch` calls and 7 compactions without a final answer
- the final isolated Phase 1 replay used the same 14,118-character prompt and
  no default model/tool budgets; after one valid clarification it stopped at
  sequence 225 with 11 model calls, 12 `web.fetch` calls, 7 compactions,
  `status=suspended`, `stop_reason=tool_loop_no_progress`, and exactly one
  terminal synthesis instead of continuing or falsely completing
- FinOS `accounts`, snapshots, transactions, import drafts, journal artifacts
  and notes had identical pre/post row hashes; temporary prompt, database,
  container and remote acceptance files were removed after verification
- Phase 2 `CTX-REHYDRATE-02` remains `Locked`; this branch stays `Review` until
  external review and maintainer merge authorization

# 2026-07-29 A-Line Completion Gate And Phase 1.5 Activation

- user acceptance supersedes the prior handoff: typed `SUSPENDED` proves the
  Runtime no longer loops, but does not pass the A line unless the fixed Skill +
  14,118-character text input produces the complete transaction log
- ChatGPT Pro and local source tracing agree that the existing recovery slice is
  present but bypassed by `_request_terminal_synthesis()`; the previous proposal
  to add another Runtime state model was rejected
- activated `CTX-REHYDRATE-02` as a narrow Phase 1.5 task stacked on
  `HAR-CONV-01@efbb8a3`, with a separate branch/worktree and no direct `main` merge
- implementation must reuse `ContextCapsule`, `ProtectedInstructionLedger`,
  `ActiveContextProjection` and `rehydrate_projection()` through the existing
  Core Port boundary; `agent-core` must not import `agent-context`
- the slice allows at most one recovered `allow_tools=False` synthesis and does
  not add a second Attempt, Memory 2.0, finance/Skill/provider heuristics,
  Worker/Storage changes or FinOS orchestration without new red-test evidence
- hard live gate: complete log after any necessary clarification, no continued
  tool loop or false completion, and identical FinOS core-table full-row hashes

# 2026-07-29 Phase 1.5 Recoverable Policy Deny P1

- the first pure A-line live replay used the complete Phase 1.5 source, the same
  14,118-character text input, `read_only` Policy and `full-trusted-local` network,
  with FinOS provider, MiniMax, MCP and image input disabled
- after 5 model calls and 6 tool calls, the model proposed a read-only
  `web.fetch` URL containing a fragment; `parse_web_target()` and Policy correctly
  denied the request, but Harness immediately failed the only Attempt as
  `retry_exhausted`, leaving a 15-character assistant fragment and no transaction log
- ChatGPT Pro classified this as a Phase 1.5 P1 rather than a new stage: Policy
  enforcement stays fail closed, while an explicitly marked model-correctable
  read-only input deny may become one non-executed failed-tool observation in the
  same Attempt
- `HAR-CONV-01-POLICY-RECOVERY` is recorded as a work item inside
  `CTX-REHYDRATE-02` on the existing branch/worktree; it must not parse reason
  strings, strip URL fragments, start a second Attempt, or relax any authority
- a second recoverable deny routes to the existing one-shot recovered
  `allow_tools=False` synthesis; approval, human refusal, side-effect/write,
  network-authority, credential, sensitive-path, sandbox/workspace and all
  unmarked denies remain terminal or waiting
- coding remains blocked until this incremental docs baseline is committed and
  receives a fresh coding-before review

# 2026-07-29 CTX-SEG-02 Long-Context Terminal Follow-up P1

- Phase 1.5 plus Policy Recovery passed `71` focused tests; the full suite is
  `1773 passed, 9 inherited failures, 8 skipped`, with changed-file Ruff, Mypy
  and `git diff --check` green
- a pure A-line live Segment now completes in one Attempt after 14 model responses,
  13 tool proposals and 7 compactions, producing an 8,655-character structured
  log; it still correctly requests confirmation for a conflicting sell record
- the stable Task follow-up route accepted `确认存在这笔卖出，纳入今日日志`, created a
  `terminal_follow_up` Segment and resumed it, but the child returned only 167
  characters and asked again for the stock, quantity and price
- source evidence proves the child lost long context rather than model capability:
  the source had a final 14,118-character Capsule objective with one acceptance
  criterion and eight plan entries, while the Handoff Envelope had no active
  Capsule fields and only two roughly 2,000-character checkpoint strings
- the mismatch comes from two existing paths: synchronous `execute=true` persists
  compaction events without advancing `SQLiteContextLifecycleStore`, and handoff
  runtime evidence later truncates the combined checkpoint to about 2,000 characters
- ChatGPT Pro classified this as a narrow `CTX-SEG-02` P1, not Memory 2.0: align
  synchronous API and Worker active-Capsule persistence, then make terminal handoff
  prefer existing Capsule/Projection rehydration with checkpoint text only as fallback
- no new Memory, table, Event schema, provider/private continuation, raw tool output,
  finance/Skill special case or FinOS change is authorized; coding waits for this
  docs increment to be committed and reviewed

# 2026-07-29 A-Line Continuity Budget And Terminal Contract Review

- the first terminal-follow-up implementation passed its synthetic tests but failed
  the fixed live A line: the valid active Capsule retained a 14,118-character
  objective, while the child handoff compiled only 427 characters and omitted every
  required transaction fact after character 12,000
- the test was falsely green because its goal/completion markers were placed in the
  objective prefix that survived the 60-character adapter limit; the replacement red
  test must place required evidence after 12K and inspect the actual child compiled
  messages
- the same isolated replay produced a 7,571-character intermediate log but exposed
  only a 387-character non-self-contained completion notice as FINAL; after the user
  confirmation and rollover, the child returned a 311-character prefixed raw DSML
  tool request and was incorrectly marked `COMPLETED`
- PostgreSQL counts and full-row hashes for accounts, snapshots, transactions,
  import drafts, journal artifacts and notes were identical before and after; the
  temporary acceptance container/image/directories were removed and official FinOS
  services remained healthy
- ChatGPT Pro locked route A without Conversation Message Replay: for
  `active_projection`, `HarnessModelStep` computes
  `max(task.context_token_budget, ModelContextWindow.compaction_reserve_tokens)` and
  passes it to the existing Context Compiler; adapter-level 60/128/85/65 character
  limits and `capsule.plan`-as-visible-conversation are forbidden
- terminal completion uses a stronger self-contained synthesis instruction and the
  existing typed suspension path for any unfenced DSML `tool_calls` + `invoke`
  grammar, even with ordinary explanatory text before it; business-log completeness
  remains the fixed live A-line Eval, not a finance/language/length validator in Harness
- A-line input is the already recognized Skill + 14,118-character OCR text. Zebra
  `main` does not gain image recognition, MiniMax MCP, FinOS provider or image fixtures
  from this repair; Memory 2.0, new Task/Storage/Event schema and direct `main` changes
  remain forbidden

# 2026-07-29 A-Line Follow-up Resolution Contract P1

- the continuity-budget / FINAL / DSML repair passes `43` core and `36` API/Worker
  focused regressions, Ruff, Mypy over 19 changed source files and `git diff --check`;
  the full suite is `1783 passed, 9 inherited failures, 8 skipped`
- the isolated pure A-line replay used the same recognized Skill + 14,118-character
  OCR text with MiniMax, MCP and image input disabled; its initial Segment completed
  in one Attempt with a 7,757-character structured log containing the known sell facts
- the source active Capsule and child compiled system both preserved the full objective;
  the sell name was after character 12,000 and its price after character 14,000, proving
  that this failure is no longer context truncation
- after `确认存在这笔卖出，纳入今日日志`, terminal rollover succeeded, but the child
  called `files.list`, observed an empty workspace, then repeated the same
  `agent.clarify` and entered `waiting_input` instead of producing the final log
- all six FinOS PostgreSQL business-table counts and full-row hashes were byte-for-byte
  unchanged before and after the failed replay
- ChatGPT Pro selected route A: the latest follow-up must first resolve a matching
  recovered pending clarification before new planning/tool exploration; normal tool
  access remains available for genuinely new follow-up work
- no finance/Skill/language/length/provider heuristic, Conversation Replay, Memory 2.0,
  new Runtime state/schema, FinOS, MCP or direct `main` change is authorized

# 2026-07-29 A-Line Route A Final Acceptance

- route A adds a generic continuation contract only when runtime evidence is both
  `active_projection` and `internal_terminal_follow_up`; the existing handoff reason
  is carried as metadata, without a new schema or state model
- non-terminal active handoffs do not receive the terminal guidance, while genuinely
  new terminal follow-ups retain normal `allow_tools=true` capability
- local validation is `80` related regressions, touched-file Ruff, Mypy over 19 source
  files and `git diff --check`; the full suite is `1784 passed, 9 inherited failures,
  8 skipped`, matching the inherited nine-failure baseline
- the fixed 14,118-character pure Zebra input first entered structured clarification;
  the exact confirmation resumed the same Segment and produced an 8,536-character
  complete structured transaction log
- after completion, the exact same confirmation triggered terminal rollover; the child
  restored the complete objective with the sell name after character 12,000 and price
  after character 14,000, then completed in two model calls with a 6,686-character,
  261-line self-contained log
- the final includes account overview, the confirmed sell, all 18 visible holdings,
  costs, risk notes and `review_ready_data`; it has no repeated `agent.clarify`,
  `waiting_input`, raw DSML, completion-only notice, suspension or failure
- one empty, read-only `files.list` preceded the final answer but caused no loop or
  state change; ChatGPT Pro classified it as non-blocking and optional P2 optimization
- FinOS PostgreSQL counts and full-row hashes for accounts, snapshots, transactions,
  import drafts, journal artifacts and notes were exactly identical before and after
- ChatGPT Pro final verdict: `DECISION: PASS`, `BUSINESS GATE: PASS`,
  `RUNTIME GATE: PASS`, `FILES.LIST VERDICT: non-blocking`, `P1: none`

# 2026-07-30 MDL-PROFILE-02 Docs-First Claim

- Owner confirmed that Zebra work must be developed in `vinson1101/zebra`
  before a PR is submitted to `hellolukeding/zebra`.
- `codex/generic-model-profile-v2` is based on the accepted Phase 1 media branch
  and is isolated from the deployed FinOS acceptance line.
- The design removes exact model-name capability inference. It reuses
  `ModelMediaCapabilities`, adds one explicit verified profile selection at the
  integration boundary, and keeps absent profiles text-only and fail closed.
- No provider factory, automatic model/provider routing, fallback state machine,
  FinOS behavior, deployment, upstream push, or `main` mutation is authorized.
- ChatGPT repository review accepted the direction and removed remaining
  over-design: the runtime record is only expected provider/model plus existing
  media capabilities, keyed by versioned profile ID. Request defaults,
  verification dates, disabled state, a Registry service and package exports
  are outside this slice.

# 2026-07-30 MDL-PROFILE-02 Implementation Review

- Red test first proved that the exact Flash model name received image
  capability with no configured profile.
- `cf0dff9` replaces that condition with one immutable mapping, one pure
  resolver and `ZEBRA_MODEL_PROFILE_ID`; no Core, Context, FinOS, MiniMax,
  DeepSeek router, provider routing or fallback change was made.
- Root review reran `46` focused tests, changed-source Ruff/Mypy and
  `git diff --check`; all pass. Full pytest is `1900 passed, 9 skipped,
  9 inherited failures`, comprising two existing provider-contract tests, five
  existing SCM credential tests, the existing file-size gate and one existing
  cancellation test.
- Delivery remains fork-only. No upstream branch, `main`, deployment or PR is
  part of this review state.

# 2026-07-30 MM-NATIVE-QWEN-PHASE1 Docs-First Claim

- Coordinator Owner authorized `vinson / Codex coordinated` to claim the
  generic native-model-media Phase 1 slice on
  `codex/qwen-native-multimodal@c3cc79c3a54f8a0be3a933bbcc43628bf82210ba`.
- The contract is documented before code: durable state retains only controlled
  artifact metadata, adapters resolve bytes in memory under authorization, and
  `media_replay_policy=always` remains fail closed across compaction, terminal
  synthesis, and reachable child recovery.
- No real Qwen request, FinOS E2E, MiniMax replacement, deployment, merge,
  push, or commit is asserted by this in-progress claim.

# 2026-07-30 MM-NATIVE-QWEN-PHASE1 Implementation And Validation

- Implemented the generic `ModelMediaInput` / capability / resolver contract;
  durable media carries only an authorized artifact reference, MIME, size,
  digest, ordinal, and source event identity. The existing payload store is
  reused without a schema or second-store addition.
- API direct execution and Worker recovery use the same capability-selected,
  task-scoped resolver. Legacy MiniMax image guidance is only added when native
  media is not active; native execution disables the legacy MCP image tool.
- Focused regressions and changed-source Ruff pass. Full deterministic pytest
  is `1870 passed, 9 inherited failures, 9 skipped`; the inherited failures are
  the existing DeepSeek, GitHub credential, file-size, and cancellation cases.
- One Owner-authorized live smoke first confirmed only that a non-default
  endpoint was configured, then stopped on normalized `authentication_failed`.
  No credential, request header, private endpoint value, image data URL, or
  real-provider acceptance is recorded here.
- Post-review, source event IDs are declared only on the current semantic USER
  message, then matched exactly by the shared OpenAI-compatible serializer;
  missing or ambiguous mappings fail before byte resolution. This preserves
  always-replay across child Segments without reconstructing historical user
  prose. The Qwen profile gate now explicitly enables native media only for
  `qwen3.7-flash-2026-07-15`; a Qwen text model fails closed. `81` related
  deterministic tests and changed-path Ruff pass; Mypy has only the four
  inherited findings in `agent_tools` and `agent_security`.

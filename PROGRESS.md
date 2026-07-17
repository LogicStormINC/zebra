# Progress

## Addendum

- 2026-07-17: completed the plan-only `CTX-HO-PLAN-01` on
  `codex/ctx-handoff-stage-plan`. The new stage Session handoff architecture keeps
  same-Session Compaction as the default and permits a new durable Session only at an
  explicit safe stage boundary. It specifies immutable parent/root/child lineage, a
  versioned transparent `SessionHandoffEnvelope`, authority inheritance or narrowing,
  cross-event-stream atomicity, idempotent creation, workspace/Git binding, child context
  reconstruction, no replay of completed tools, rejection of pending or uncertain side
  effects, API/CLI/UI readback, recovery, observability, Eval, rollout, and rollback.
  Runtime implementation remains inactive; coding requires dependency-ordered,
  path-bounded follow-up tasks after `CTX-LC-01` merges.

- 2026-07-17: split the former integrated `CTX-DS-01` into parallel,
  path-bounded tasks. `CTX-LC-01` owns provider-neutral context planning,
  compaction, artifacts, capsule recovery, and operator controls on
  `codex/ctx-lc-01-hybrid-compaction`; `DS-OPT-01` owns DeepSeek profiles,
  protocol safety, telemetry, and provider evals on
  `codex/ds-opt-01-deepseek-specialization` in a separate Codex task.
  `CTX-LC-01` is complete for review: all provider calls share a hard model-window
  gate; command/test output uses complete Artifact storage plus bounded model
  projection; compaction emits a versioned transparent Capsule that worker
  recovery reinjects; provider-native continuation is capability-gated with a
  deterministic Capsule fallback; API/CLI context inspect and manual compact
  controls are live. Validation passed `1379` tests with one platform-gated
  gVisor skip, file-size and Ruff gates, strict Mypy across `379` source files,
  and all `8` release evals.

- 2026-07-17: implemented `ARCH-129-RT-01` on
  `codex/arch-129-hard-runtime`. Runtime now has explicit trusted-local,
  rootless OCI, and gVisor classes; hard modes perform fail-closed preflight,
  run a digest-pinned image with read-only root, non-root identity, no network,
  no capabilities, no-new-privileges and bounded CPU/memory/PID/tmpfs/time/output,
  persist effective authority before tools, reject recovery drift, snapshot
  safely, and clean stale or cancelled containers by session label. API/CLI
  readback, adversarial contract tests, operator guidance, and a real Linux
  gVisor CI smoke are included. Workspace disk quota remains an explicit
  storage-layer production prerequisite rather than an unenforceable bind-mount
  claim.
  Local validation passed all `1345` runnable tests with only the platform-gated
  gVisor smoke skipped, plus the file-size gate, Ruff, strict Mypy across `361`
  source files, and all `8` release evals. PR `#142` then passed Backend,
  Desktop, and the real Linux `runsc` gVisor isolation smoke.
  PR `#142` is merged to `main` as `8919e6a`; the task is closed as `Done`.

- 2026-07-17: activated `ARCH-129-RT-01` on
  `codex/arch-129-hard-runtime` by explicit maintainer request. The production
  v1 boundary is Linux-first gVisor/OCI with a rootless OCI compatibility mode,
  durable effective authority, fail-closed capability preflight, offline Agent
  execution, bounded resources and output, deterministic lifecycle cleanup,
  and explicit macOS/unsupported behavior. Kubernetes orchestration, warm
  pools, multi-tenant scheduling, Kata/Firecracker, and a new credential or
  arbitrary-egress platform remain outside this task. The executable plan is
  recorded in `docs/生产级Runtime实施方案_v1.0.md`.

- 2026-07-17: completed `QA-CI-01` for review on `codex/qa-ci-mainline`.
  The read-only, SHA-pinned workflow runs frozen Python workspace sync, all
  backend tests, file-size checks, Ruff, strict Mypy, release evals, every
  desktop `check:*` script, and the production build on pull requests and
  `main` pushes. Validation exposed that root `uv.lock` was ignored and absent;
  the task now tracks the generated lock and removes that ignore rule instead
  of weakening frozen CI. Workflow YAML parsed successfully, all 1320 backend
  tests, the 779-file gate, 353-source Mypy, 8 evals, 16 desktop checks, and the
  Node 22 build passed. The existing desktop chunk warning remains unchanged.

- 2026-07-17: started `QA-CI-01` on `codex/qa-ci-mainline`, stacked on the
  documentation-only `QA-GOV-01` branch to avoid conflicting task-registry
  edits before that dependency merges. The first workflow will reuse frozen
  backend and desktop commands on pull requests and `main` pushes with
  read-only permissions, pinned Actions, superseded-run cancellation, no
  provider credentials, no deployment, and no Tauri packaging.

- 2026-07-17: completed `QA-GOV-01` for review on
  `codex/qa-mainline-closeout`. The evidence-backed mainline assessment is
  recorded in `docs/主线架构工程完成度审计与收口计划_v1.0.md`: remote `main`
  and local `origin/main` both resolved to `f56afc0`; a detached mainline
  worktree passed all 1320 backend tests, the 779-file size gate, Ruff, strict
  Mypy across 353 source files, all 8 release evals, all 16 desktop checks, and
  the Node 22 production build. The plan separates 80%-85% local-beta readiness
  from 55%-65% final-platform readiness and prioritizes verified UI integration,
  minimal CI, documentation reconciliation, an explicit Hard Runtime decision,
  and measured desktop bundle work without unlocking deferred architecture.

- 2026-07-17: started `QA-GOV-01` on `codex/qa-mainline-closeout` to persist an
  evidence-backed mainline architecture and engineering completion assessment.
  The document will separate local-beta readiness from the final platform
  roadmap, record current validation and governance drift, and define the next
  closeout tasks without activating the locked hard-runtime, ACP, optional code
  intelligence, private-cloud, multi-tenant, or ecosystem scopes.

- 2026-07-17: completed `ARCH-129-PLAN-01` on
  `codex/issue-129-remediation-plan`. GitHub Issue `#129` is now represented by
  a durable remediation and deferral document plus three dependency-ordered
  task cards for hard-enforced runtime, ACP entry, and optional code
  intelligence. All three implementation cards remain `Locked`, unassigned,
  and excluded from the current phase until an explicit maintainer activation;
  no runtime, protocol, context, security, or product capability changed.

- 2026-07-17: completed `QA-2-ARCH-01` for review. `agent-tools` no longer
  depends on or imports `agent-runtime`; builtin tools target the new minimal
  core `WorkspacePort`, while runtime `LocalWorkspace` remains the structural
  implementation and runtime continues composing the local tool gateway. A new
  workspace package graph test rejects future dependency cycles. All 1320 tests
  and `make check` passed, including the 779-file size gate, Ruff, Mypy across
  353 source files, and all 8 release-gate evals.

- 2026-07-17: started `QA-2-ARCH-01` on
  `codex/issue-2-break-runtime-tools-cycle` to remove the package-level
  `agent-tools -> agent-runtime` edge. Builtin tools will depend on a minimal
  core Workspace Port while the existing runtime LocalWorkspace remains the
  concrete implementation; behavior and public tool contracts stay unchanged.

- 2026-07-17: completed `QA-2-STO-01` for review. SQLite worker lease
  acquisition now uses one conditional UPSERT with `RETURNING`, so competing
  workers cannot both report ownership; active same-worker renewal preserves
  the original acquisition time and expired takeover remains supported. The
  deterministic regression forces the former read-then-upsert race. All 1314
  tests and `make check` passed, including the 776-file size gate, Ruff, Mypy
  across 351 source files, and all 8 release-gate evals.

- 2026-07-17: started `QA-2-STO-01` on
  `codex/issue-2-atomic-sqlite-leases` to replace the SQLite lease
  read-then-upsert race with one atomic conditional claim and add a real
  concurrent worker regression test. The separate runtime/tools package cycle
  remains outside this task.
- 2026-07-17: completed `QA-39-MEM-01` for review. Repo-session memory queue
  sweeps now filter by `source_session_id` inside SQLite before the 500-row
  limit, malformed session ids return stable API/CLI `invalid_request` results,
  and the stale Phase 56 README status was removed. All 1317 tests and
  `make check` passed, including the 777-file size gate, Ruff, Mypy across 352
  source files, and all 8 release-gate evals.

- 2026-07-17: started `QA-39-MEM-01` on
  `codex/issue-39-memory-queue-reliability` to fix GitHub Issue `#39` by pushing
  repo-session filtering into the memory-store query, stabilizing malformed
  session-id handling, and removing the stale Phase 56 README status line.

- 2026-07-17: completed `P144-WEB-01`; approved HTML now reaches the model as
  bounded readable text. All `1312` tests, 351-source Mypy, 8 evals, 14 desktop
  checks, Node 22 build, offline Tauri, browser and real-provider proof
  `WEB_HTML_FINAL_OK: WEB_HTML_PROVIDER_PROOF_144_2A7C` passed.
- 2026-07-17: started `P144-WEB-01` on
  `codex/p144-web-01-bounded-html-text-projection`. Phase 144 keeps the existing
  typed `web.fetch` contract, durable domain allowlist, Policy approval, public
  DNS checks, redirect denial, and raw response limits while converting approved
  HTML locally into bounded readable text. Script, style, template, SVG, and
  other non-readable containers do not reach the model; output truncation and
  safe projection metadata are deterministic. Browser automation, third-party
  extraction APIs, caching, credentials, network widening, visual input, and
  Research-child Web access remain excluded. Hermes main `659d1123c` informed
  the clean-content and explicit-truncation boundary only.
- 2026-07-17: completed `P143-DOC-01`; standard PPTX visible slide text now
  shares the durable bounded material path with text, PDF, DOCX, and XLSX input.
  Extraction preserves slide order without rendering, OCR, speaker notes, or
  native multimodal messages; safe provenance retains original size, digest,
  slide count, and extraction status. Shared OOXML safety rejects malformed,
  encrypted, macro-enabled, externally linked, ActiveX, embedded, text-empty,
  image-only, and over-limit packages before mutation. All `1305` backend tests,
  Ruff, Mypy across `350` sources, 8 evals, 14 desktop checks, Node 22 build,
  offline Tauri, 769-file size gate, responsive browser acceptance, and real
  `deepseek-v4-flash` response
  `PPTX_FINAL_OK: PPTX_PROVIDER_PROOF_143_6D9A` passed. The existing Vite bundle
  warning remains unchanged.
- 2026-07-17: started `P143-DOC-01` on
  `codex/p143-doc-01-bounded-pptx-input`. Phase 143 adds bounded deterministic
  visible-slide text extraction for standard PPTX input to the existing durable
  attachment path. Malformed, encrypted, macro-enabled, externally linked,
  embedded-object, image-only, text-empty, and over-limit packages fail before
  mutation. Recovery consumes only persisted normalized UTF-8 extraction with
  safe slide-count provenance. Legacy or macro-enabled presentations, speaker
  notes, OCR, native multimodal input, remote URLs, and authority changes remain
  excluded.
- 2026-07-17: completed `P142-DOC-01`; standard XLSX worksheets now share the
  durable bounded material path with text, PDF, and DOCX input. Extraction emits
  deterministic sheet names, coordinates, and cached values without executing
  formulas; safe provenance retains original size, digest, worksheet count, and
  populated-cell count. Shared OOXML safety rejects malformed, encrypted,
  macro-enabled, externally linked or connected, query-backed, pivot, ActiveX,
  embedded, text-empty, and over-limit packages before mutation. All `1293`
  backend tests, Ruff, Mypy across `349` sources, 8 evals, 14 desktop checks,
  Node 22 build, Tauri, 766-file size gate, responsive browser acceptance, and
  real `deepseek-v4-flash` response
  `XLSX_FINAL_OK: XLSX_PROVIDER_PROOF_142_4F6C` passed. The existing Vite bundle
  warning remains unchanged.
- 2026-07-17: started `P142-DOC-01` on
  `codex/p142-doc-01-bounded-xlsx-input`. Phase 142 adds bounded deterministic
  XLSX worksheet-value extraction to the existing durable attachment path.
  Formula expressions are never executed and only cached values are eligible;
  malformed, encrypted, macro-enabled, externally linked or connected,
  query-backed, embedded-object, text-empty, and over-limit packages fail before
  mutation. Recovery consumes only persisted normalized UTF-8 extraction with
  safe workbook provenance. Spreadsheet editing, other formats, OCR, remote
  URLs, and authority changes remain excluded.
- 2026-07-17: completed `QA-UI-RUNTIME-01` implementation on
  `codex/qa-ui-runtime-feedback`. OpenAI-compatible providers now consume real
  upstream SSE, coalesce only public Assistant content, reconstruct fragmented
  tool calls, and preserve final response and usage semantics. Harness and
  Worker persist correlated `model_response_delta` events as generation occurs;
  durable cancellation or suspension interrupts continued provider consumption,
  while `model_response_received` remains authoritative. HTTP session streaming
  now replays from `after_sequence` and tails SQLite with keepalive, disconnect,
  and terminal-close behavior without blocking the FastAPI event loop. The
  desktop replaced finite replay polling with one cancellable, reconnectable
  stream per active session and atomically converges partial text onto the final
  Assistant row. Hidden reasoning fields remain excluded. All `1327` backend
  tests, the 782-file size gate, Ruff, Mypy across 357 sources, 8 evals, all 18
  Node 22 desktop checks, the production build, and Tauri check passed. Real
  browser/provider acceptance with `deepseek-v4-flash` persisted two deltas
  (`ST` + `REAM_BROWSER_OK_20260717`) before the authoritative final response,
  rendered one final message, restored it after reload, and produced no console
  errors. The existing 1.37 MB Vite chunk warning remains unchanged.
- 2026-07-17: completed `QA-UI-UNBOUND-01` on
  `codex/qa-ui-unbound-session-continuation`. Historical sessions without
  durable workspace metadata no longer disable the Composer: continuation uses
  the current valid launch configuration while bound sessions retain their
  durable configuration. Node 22 focused launch checks and production build
  passed, and browser regression on session `a5b155fa` enabled the send action
  and returned `UNBOUND_CONTINUATION_OK` through the real execution path.
- 2026-07-17: merged `P145-UI-01` through PR `#133`. The desktop
  now projects one chronological conversation stream from durable events,
  groups modern and legacy tool lifecycles deterministically across attempts,
  defaults successful evidence closed and failed evidence open, preserves one
  inline task plan plus existing approval, clarification, inspector, Logs, and
  Composer behavior, and reports suspended sessions truthfully. Existing API
  fields were sufficient, so no backend contract changed. All 16 desktop checks,
  the Node 22 production build, 776-file size gate, Ruff, Mypy across 351 source
  files, all 8 evals, all 1312 backend tests, desktop and 900px browser
  acceptance, keyboard disclosure, zero-overflow and zero-console-error checks,
  and screenshot design QA passed.
- 2026-07-17: started `P145-UI-01` on
  `codex/p145-ui-01-event-stream-conversation`. Phase 145 replaces the fixed
  desktop stage timeline with one chronological conversation stream projected
  from durable session events. It preserves existing task-plan, approval,
  clarification, inspector, Composer, attachment, MCP, Policy, and HITL
  behavior, and permits additive API work only if current safe event fields are
  insufficient for deterministic tool lifecycle grouping.
- 2026-07-16: completed `P141-DOC-01`; standard DOCX body and table text now
  shares the durable bounded attachment path with UTF-8 text and text-layer PDF
  material on new tasks and ordinary follow-up messages. Unsafe ZIP paths,
  duplicate or encrypted entries, zip-bomb limits, malformed OOXML, macros,
  external relationships, embedded objects, `altChunk`, text-empty documents,
  and all raw or extracted size breaches fail before session mutation. Only
  normalized UTF-8 extraction is stored, with safe original size, digest,
  paragraph count, and extraction status. All `1279` backend tests, Ruff, Mypy
  across `347` source files, 8 evals, 14 desktop checks, Node 22 build, Tauri,
  764-file size gate, desktop plus 900px browser acceptance, and a real
  `deepseek-v4-flash` response passed. The provider returned
  `DOCX_FINAL_OK: DOCX_PROVIDER_PROOF_141_8E2A`; the existing Vite bundle warning
  remains unchanged.
- 2026-07-16: started `P141-DOC-01` on
  `codex/p141-doc-01-bounded-docx-input`. Phase 141 adds bounded standard DOCX
  body and table text extraction to the existing durable attachment path. Raw
  archives are accepted only at the API boundary; malformed, encrypted,
  macro-enabled, externally linked, embedded-object, text-empty, and over-limit
  documents fail before session mutation. Recovery consumes only persisted
  normalized UTF-8 extraction with safe original-document provenance. Legacy
  Office formats, other OOXML applications, OCR, native multimodal input,
  remote URLs, and authority changes remain excluded.
- 2026-07-16: completed `P140-DOC-01`; new tasks and ordinary follow-up messages
  now accept mixed bounded UTF-8 text and text-layer PDF materials. PDFs are
  rejected before mutation when malformed, encrypted, image-only, over 4 MiB,
  over 64 pages, or beyond decoded-stream or extracted-text budgets. Only
  normalized UTF-8 extraction is stored, while safe readback retains original
  media type, byte size, SHA-256, page count, and `text_extracted` status. Worker
  recovery proved it never reparses the PDF. All `1262` backend tests, Ruff,
  Mypy across `346` source files, the 8-case eval gate, 14 desktop checks, Node
  22 production build, Tauri cargo check, 763-file size gate, desktop plus 900px
  browser acceptance, and a real `deepseek-v4-flash` response passed. The model
  returned `PDF_FINAL_OK: PDF_PROVIDER_PROOF_140_7C9D` from a 687-byte, one-page
  PDF whose durable extraction was 40 bytes. The existing Vite main-bundle
  warning remains unchanged.
- 2026-07-16: started `P140-DOC-01` on `codex/p140-doc-01-bounded-pdf-input`.
  Phase 140 adds bounded text-layer extraction for user-selected PDFs to the
  existing durable attachment path. Raw PDF bytes are accepted only at the API
  boundary; malformed, encrypted, over-limit, and image-only inputs fail before
  session mutation, while recovery consumes only persisted normalized UTF-8
  extraction with safe original-document provenance. OCR, native multimodal
  provider messages, remote URLs, other office formats, and authority changes
  remain excluded.
- 2026-07-16: completed Phase 139 session-configuration surface correction. Active-session Composer cards now contain only mode, attachment, input, and send affordances; durable workspace, policy, tool, network, MCP tool/resource counts, captured Prompt safe provenance, material count, model configuration, attempt, and sequence readback live in the right-side context inspector. New-task and unbound draft launch summaries and editable controls remain unchanged. All 13 existing desktop checks plus the new session-surface regression check, Node 22 production build, Tauri cargo check, 762-file size gate, and desktop plus 900px responsive browser acceptance passed. The existing Vite main-bundle warning remains unchanged.
- 2026-07-16: Phase 139 is limited to one desktop information-architecture correction: durable active-session configuration moves from the Composer header into the existing right-side context inspector. New-task launch configuration remains editable before session creation, while active-session workspace, policy, tool, network, MCP, captured Prompt provenance, material count, model, attempt, and sequence become one read-only inspector surface. No backend, event, storage, Policy, model, MCP authority, or HITL contract changes.
- 2026-07-16: completed Phase 138 across bounded local stdio Prompt discovery, durable API/CLI task launch, immutable Worker recovery, and explicit desktop new-task selection. One user-selected opaque Prompt ID plus exact bounded string arguments is resolved once before creation, persisted as untrusted attachment bytes with safe provenance, and never exposed as model-visible Prompt tools or re-read during recovery. All `1252` backend tests, Ruff, Mypy across `346` source files, the 8-case eval gate, 13 desktop checks, the Node 22 production build, Tauri cargo check, browser fixture acceptance, and a real `deepseek-v4-flash` server-loss recovery pass succeeded; the provider returned the captured proof token `P138_CAPTURED_PROMPT_71F4` after the MCP server script was removed and the MCP call log remained unchanged. The existing Vite main-bundle size warning remains a follow-up, not a Phase 138 regression.
- 2026-07-16: Phase 137 is merged through PRs `#111`-`#115` and final merge commit `b1a95c6`. Phase 138 is limited to application-controlled MCP Prompt templates as explicit new-task input: bounded local stdio discovery, one exact user-selected Prompt plus string arguments, one-time text-only resolution before task creation, durable untrusted capture, immutable recovery, and desktop launch configuration. Prompt operations are never model-visible tools. PDF, office, image, audio, remote MCP, OAuth, notifications, sampling, automatic selection, later-message Prompt use, ordinary-state HITL, and Research-child inheritance remain excluded. This phase turns configured MCP servers into reusable general-task entry points without making coding delivery the default workflow or widening runtime authority.
- 2026-07-16: completed Phase 137 boundary restoration across merged PRs `#112` (desktop conversation UI), `#113` (test suite), and `#114` (API/CLI source), following the coordination claim merged in PR `#111`. The behavior-preserving split removes every known source and test hard-limit violation without changing public API, CLI, event, storage, model, UI, or error contracts. `P137-GATE-01` now enforces tracked Python, TypeScript, and TSX production files at 500 lines and test files at 700 lines through `make check`; explicit generated, dependency, environment, cache, build, and Tauri binding paths are excluded. The final audit covers 748 tracked files with zero violations. All 1211 backend tests, Ruff, Mypy across 342 source files, the 8-case eval gate, twelve desktop contract checks, the Node 22 production build, Tauri cargo check, and focused browser acceptance passed.
- 2026-07-16: merged `P136-MCP-01` through GitHub PR `#109` at merge commit `8516916` and closed Phase 136. The next mainline deliberately pauses capability expansion: a tracked source audit found nine production files above the repository's 500-line hard limit (`session_read.py` 5801, `session_memory_read.py` 5734, `memory_inventory_read.py` 4588, `app.py` 1198, `read_commands.py` 1032, `memory_review_write.py` 774, `session_memory_control.py` 757, `cli.py` 684, and `CodexConversationPane.tsx` 510), while six test files exceed the 700-line test limit. Phase 137 is a behavior-preserving boundary-restoration phase with three non-overlapping Ready lanes for API/CLI source, desktop conversation UI, and tests, followed by one Locked repository-size gate. It adds no product feature and preserves API, CLI, event, storage, model, UI, and error contracts while restoring maintainable ownership boundaries required for safe parallel development.
- 2026-07-16: completed `P136-MCP-01` on `codex/p136-mcp-01-durable-resource-context`; local stdio MCP discovery now supports tools-only, resources-only, and combined servers while exposing only bounded Resource display metadata and opaque IDs. API, CLI, direct Harness, Worker recovery, context compilation, durable attachment storage, and desktop task launch share one explicit at-most-four selection path: each UTF-8 text Resource is read once before task creation, stored with safe server/ID/SHA provenance, compiled under a 16 KiB untrusted-material boundary, and recovered without MCP rereads or model-visible Resource tools. Authenticated browser acceptance persisted and restored one selected Resource without viewport overflow; all 1208 backend tests, Ruff, Mypy across 258 source files, the 8-case eval gate, all twelve desktop checks, the Node 22 production build, Tauri cargo check, and real `deepseek-v4-flash` answer `RESOURCE_FINAL_OK: MCP_RESOURCE_CONTEXT_136` passed. The browser retained only the pre-existing Ant Design 5 / React 19 compatibility warning. Automatic selection, prompts, templates, subscriptions, blobs, remote MCP, OAuth, later-message Resource attachment, ordinary-state HITL, and Research-child access remain excluded.
- 2026-07-16: merged `P135-MCP-01` through GitHub PR `#107` at merge commit `89cced2` and closed Phase 135; task-authorized MCP catalogs now retain direct small-catalog behavior and switch oversized schemas to bounded stateless search, exact description, and call bridging without widening authority. Phase 136 is limited to application-controlled, durable, bounded MCP Resource context for newly created parent tasks. It will extend the existing local stdio discovery path to safely enumerate resources, expose only bounded metadata plus opaque selection IDs, read explicitly selected UTF-8 text resources once, reuse the existing attachment payload and untrusted context pipeline, and preserve immutable recovery without model-visible resource tools. Hermes `f8ddf4fd8` informs resource list/read shapes only; Zebra retains capability negotiation, strict pagination and payload ceilings, task-scoped selection, durable provenance, and fixed Research-child isolation. Prompts, templates, subscriptions, blobs, remote MCP, OAuth, automatic selection, later-message resource attachment, and ordinary-state HITL remain outside the slice.
- 2026-07-16: completed `P135-MCP-01` on `codex/p135-mcp-01-authorized-progressive-disclosure`; small effective MCP catalogs remain directly model-visible, while catalogs whose deterministic serialized provider schemas exceed 8 KiB expose only bounded `agent.tools.search`, `agent.tools.describe`, and `agent.tools.call` bridges alongside ordinary built-ins. The stateless catalog is rebuilt only from the current task's Phase 134 authority, search and exact description return explicitly untrusted metadata, and bridge calls resolve to the immutable underlying selected MCP call before duplicate, budget, Policy, HITL, event, trace, execution, and recovery handling. All `1196` backend tests, Ruff, Mypy across `257` source files, the 8-case eval gate, and focused 42-test compatibility coverage passed. A real `deepseek-v4-flash` search/describe/approval/recovery run made no MCP server call before approval and returned `MCP_DISCLOSURE_FINAL_OK: echo:MCP_PROVIDER_PROOF_135` after recovery.
- 2026-07-16: started `P135-MCP-01` on `codex/p135-mcp-01-authorized-progressive-disclosure`; implementation is limited to stateless progressive disclosure over only the current task's effective Phase 134 MCP catalog. Small catalogs remain directly visible, oversized serialized schemas receive bounded search and exact-description tools, and one bridge call must resolve to the immutable underlying MCP call before duplicate, budget, Policy, approval, execution, event, trace, and recovery handling. Built-ins remain directly visible. Configuration mutation, remote MCP, OAuth, automatic grants, approval bypass, plugins, vector retrieval, code mode, desktop browsing, and Research inheritance remain excluded.
- 2026-07-16: merged `P134-MCP-01` through GitHub PR `#105` and closed Phase 134; new tasks now default to no MCP tools and preserve one exact selected catalog through durable execution and recovery. Phase 135 is limited to bounded progressive disclosure when that effective selected MCP schema catalog becomes oversized. It will rebuild a stateless catalog only from current task authority, keep built-ins directly visible, provide deterministic search and exact description, and unwrap one bridge call to the real selected MCP tool before Policy, approval, events, execution, and recovery. Updated Hermes commit `f8ddf4fd8` informs session scoping, catalog rebuild, and bridge guardrails only. MCP configuration mutation, remote transports, OAuth, plugins, automatic grants, approval bypass, vector retrieval, code mode, desktop catalog browsing, and Research inheritance remain outside the slice.
- 2026-07-16: completed `P134-MCP-01` on `codex/p134-mcp-01-task-scoped-capability-allowlist`; every new task now records an explicit normalized MCP capability list, defaults to no MCP tools, and preserves the exact selection through bootstrap events, SQLite workspace projection, API/CLI readback, direct execution, queued Worker recovery, and approval continuation. Unknown fields, malformed or duplicate names, incompatible network profiles, unavailable capabilities, and removed selected tools fail closed, while legacy pre-field tasks retain Phase 132 configured-tool behavior. The desktop selects only current safe inventory entries inside launch configuration and adds no ordinary-state approval controls. All `1181` backend tests, Ruff, Mypy across `255` source files, the 8-case eval gate, all twelve desktop checks, the Node 22 production build, online plus offline Tauri validation, authenticated HTTP/CORS and browser acceptance, and a real `deepseek-v4-flash` approval/recovery pass succeeded; the provider returned `MCP_ALLOWLIST_FINAL_OK: echo:MCP_PROVIDER_PROOF_134` after exactly one approved selected-tool call.
- 2026-07-16: started `P134-MCP-01` on `codex/p134-mcp-01-task-scoped-capability-allowlist`; implementation is limited to one explicit durable `mcp_allowlist` recorded by every new task and enforced across direct execution, queued Worker recovery, approval continuation, API/CLI readback, and desktop launch configuration. New tasks default to no MCP tools; legacy tasks without the field retain Phase 132 behavior. Wildcards, automatic model selection, remote MCP, configuration mutation, ordinary-state HITL, and Research-child access remain excluded.
- 2026-07-16: merged `P133-MCP-01` through GitHub PR `#103` and closed Phase 133; operators now have a safe authenticated MCP capability inventory in desktop runtime settings without background MCP polling or ordinary-state HITL. Phase 134 is limited to a durable task-scoped MCP allowlist. Every new task will record an explicit list, default to no MCP capability, expose only selected configured tools, and preserve that boundary through direct execution, queued Worker recovery, and approval continuation. Legacy pre-field tasks retain Phase 132 behavior, while unknown, removed, or unselected targets fail closed. Remote transports, OAuth, configuration mutation, dynamic reload, automatic model selection, and Research inheritance remain outside the slice.
- 2026-07-16: completed `P133-MCP-01` on `codex/p133-mcp-01-safe-capability-inventory`; authenticated operators now have one truthful read-only MCP preflight inventory backed by bounded Phase 132 discovery. The API and desktop runtime settings expose only availability, safe server/tool identity, bounded descriptions, input-field names, and counts; unconfigured state starts no process, failures expose no stale tools, and the desktop performs no MCP background polling. Commands, arguments, environment, paths, credentials, raw schemas, configuration mutation, execution authority, ordinary-state HITL, and Research-child access remain excluded. All `1169` backend tests, Ruff, Mypy across `254` source files, the 8-case eval gate, all twelve desktop checks, the Node 22 production build, online plus offline Tauri validation, authenticated HTTP/CORS smoke, and browser settings acceptance succeeded.
- 2026-07-16: started `P133-MCP-01` on `codex/p133-mcp-01-safe-capability-inventory`; implementation is limited to one authenticated safe readback over the existing bounded MCP discovery result plus one desktop runtime-settings projection. It exposes only configured, available, server/tool identity, bounded descriptions, input-field names, and counts. Commands, arguments, environment, paths, credentials, raw schemas, configuration mutation, background polling, task authority, ordinary-state HITL, and Research-child access remain excluded.
- 2026-07-16: merged `P132-MCP-01` through GitHub PR `#101` and closed Phase 132; explicitly configured general and coding parent sessions now have bounded local stdio MCP discovery and approval-gated execution without credential inheritance or Research-child exposure. Phase 133 is limited to a truthful authenticated MCP capability inventory and preflight readback. It will expose only safe server/tool identity, descriptions, input-field names, counts, and availability through the API and desktop runtime settings while keeping commands, arguments, environment, paths, credentials, raw schemas, configuration mutation, background polling, remote transports, and ordinary-state HITL outside the slice.
- 2026-07-15: completed `P132-MCP-01` on `codex/p132-mcp-01-bounded-local-stdio-bridge`; explicitly configured general and coding parent sessions can now discover and call bounded local stdio MCP tools through the existing typed registry, `mcp_proxy` Policy, durable HITL, event, and recovery boundaries. Strict JSON configuration allows at most three absolute non-shell executables, discovery is capped at 32 tools, short-lived JSON-RPC sessions enforce frame, page, schema, timeout, nesting, argument, and output limits, subprocesses receive no model credentials, and all descriptions, schemas, and results remain untrusted. Fixed Research children remain unchanged. All `1163` backend tests, Ruff, Mypy across `253` source files, the 8-case eval gate, all eleven desktop checks, the Node 22 build, offline Tauri validation, and a real `deepseek-v4-flash` approval/recovery pass succeeded; the provider returned `MCP_FINAL_OK: echo:MCP_PROVIDER_PROOF_132` after exactly one approved call.
- 2026-07-15: started `P132-MCP-01` on `codex/p132-mcp-01-bounded-local-stdio-bridge`; implementation is limited to at most three explicitly configured local stdio servers using absolute executables and argument vectors. Discovery and calls use bounded short-lived JSON-RPC sessions, model-visible tools remain deterministic and untrusted, every call retains the existing `mcp_proxy` network-profile and approval boundary, and fixed Research children remain unchanged. Shells, installers, inline interpreter execution, secret environment injection, remote transports, dynamic reload, and plugin UI remain excluded.
- 2026-07-15: merged `P131-INP-01` through GitHub PR `#99` and closed Phase 131; parent tasks now accept durable bounded UTF-8 text attachments without widening authority. Phase 132 is limited to a bounded local stdio MCP bridge for at most three explicitly configured servers. It will reuse the existing MCP proxy contracts, typed registry, deterministic Policy, durable approval, event, and recovery paths; register tools only for general and coding parents; and fail closed on invalid commands, schemas, protocol traffic, timeouts, counts, and output limits. Streamable HTTP, SSE, OAuth, remote credentials, dynamic reload, package installation, prompts, resources, sampling, plugin UI, and Research-child inheritance remain outside this slice. Refreshed Hermes commit `07be37d99` informs configuration validation and lifecycle limits only; Zebra retains its typed, durable, approval-gated architecture.
- 2026-07-15: completed `P131-INP-01` on `codex/p131-inp-01-durable-bounded-text-attachments`; new tasks and later ordinary messages now accept at most four strictly validated UTF-8 text attachments, limited to 64 KiB each and 128 KiB total. Payload bytes reuse the local artifact lifecycle while user events and session reads expose only stable safe metadata. API, direct Harness, and Worker recovery compile at most 16 KiB into explicitly untrusted parent context and state that the content is already inline, preventing models from mistaking attachment names for workspace paths. Recovery verifies both payload size and SHA-256 and fails closed on corruption. The desktop Composer supports selection, removable pending chips, actionable validation, successful-submit clearing, and durable material-count readback without idle HITL controls. All `1147` backend tests, Ruff, Mypy across `251` source files, the 8-case eval gate, all eleven desktop checks, the Node 22 build, offline Tauri validation, live browser readback, and a real `deepseek-v4-flash` attachment pass succeeded; the provider returned `ATTACHMENT_FINAL_OK: ZEBRA_P131_PROVIDER_ATTACHMENT_B7F1` and session readback contained no payload or storage URI.
- 2026-07-15: started `P131-INP-01` on `codex/p131-inp-01-durable-bounded-text-attachments`; implementation is limited to at most four base64-transported UTF-8 text attachments with 64 KiB per-file and 128 KiB aggregate input limits. Safe metadata is linked to the originating user event, bytes reuse the existing local artifact payload lifecycle, Worker recovery fails closed, and parent-model context receives at most 16 KiB of explicitly untrusted material. Desktop selection remains an ordinary Composer input and introduces no idle HITL controls. Binary documents, OCR, vision, remote URLs, Research-child access, and authority widening remain excluded.
- 2026-07-15: merged `P130-OBS-01` through GitHub PR `#97` and closed Phase 130; newly written tool traces now correlate parallel same-name calls across core, API, and CLI while legacy events retain deterministic provider-order fallback. Phase 131 is limited to durable bounded UTF-8 text attachments on task creation and later ordinary messages. It will reuse the local artifact payload lifecycle, preserve message linkage, project explicitly untrusted bounded material into parent-model context, and add truthful desktop Composer selection and readback. PDF, office documents, OCR, vision, arbitrary binary uploads, remote URLs, workspace mutation, Research-child access, and authority widening remain outside this slice.
- 2026-07-15: completed `P130-OBS-01` on `codex/p130-obs-01-durable-tool-trace-correlation`; newly emitted tool proposals, policy decisions, starts, and terminal execution events now share the existing internal `tool_call_id`. One core projector tracks multiple pending calls by ID, and both API and CLI persisted-event serializers reuse it while preserving their existing public response fields. Legacy no-ID events use deterministic same-name provider-order fallback. All `1134` backend tests, Ruff, Mypy across `245` source files, the 8-case eval gate, all ten desktop checks, the Node 22 production build, and Tauri `cargo check` passed. A real `deepseek-v4-flash` parallel batch correlated `a.txt -> TRACE-A-130` and `b.txt -> TRACE-B-130` exactly and returned `TRACE_FINAL_OK: TRACE-A-130|TRACE-B-130`.
- 2026-07-15: started `P130-OBS-01` on `codex/p130-obs-01-durable-tool-trace-correlation`; implementation is limited to propagating the existing `tool_call_id` through tool proposal, policy, start, and terminal events, then using one shared core correlation projector from core/API/CLI with deterministic provider-order fallback for legacy events. Execution order, scheduling, policy authority, public trace fields, historical event rewrites, distributed tracing, dashboards, and desktop trace UI remain excluded.
- 2026-07-15: merged `P129-TOOL-01` through GitHub PR `#95` and closed Phase 129; general and coding parent sessions now have bounded read-only workspace inventory before search/read. Phase 130 is limited to correcting the pre-existing trace correlation defect exposed by the real provider batch: new proposal, policy, start, and terminal tool events will share the existing `tool_call_id`, and core/API/CLI projectors will associate parallel same-name calls by ID while retaining provider-order compatibility for legacy events. Tool execution, scheduling, authority, public trace shape, event types, historical payload migration, distributed tracing, dashboards, and desktop trace UI remain outside this slice.
- 2026-07-15: completed `P129-TOOL-01` on `codex/p129-tool-01-bounded-workspace-inventory`; general and coding parent sessions now expose one typed read-only `files.list` capability with workspace-relative roots, depth `1..4`, deterministic directory-first ordering, explicit pagination, 10,000-entry scan and 32 KiB output ceilings, and fail-closed hidden, symlink, VCS, dependency, virtual-environment, cache, and generated-build exclusions. Fixed Research children remain unchanged. All `1132` backend tests, Ruff, Mypy across `245` source files, the 8-case eval gate, all ten desktop checks, the Node 22 production build, Tauri `cargo check`, and live browser acceptance passed. A real `deepseek-v4-flash` run executed `files.list -> files.read` and returned `LIST_FINAL_OK: ZEBRA_P129_LIST_READ_8C41`. Acceptance also exposed a pre-existing CLI trace projection gap for parallel same-name tools: durable events preserve each proposal and result correctly, but the summarized trace uses one pending slot and can misassociate arguments; the next planning slice must address correlation across both core and CLI projections.
- 2026-07-15: started `P129-TOOL-01` on `codex/p129-tool-01-bounded-workspace-inventory`; implementation is limited to one typed read-only `files.list` parent tool with workspace-relative roots, depth and pagination controls, deterministic ordering, scan and output ceilings, and fail-closed exclusions for hidden, symlinked, dependency, cache, VCS, virtual-environment, and generated-build paths. File content, mutation, indexes, Research-child expansion, desktop file browsing, browser automation, MCP, connectors, and dynamic tool discovery remain excluded.
- 2026-07-15: merged `P128-HIST-01` through GitHub PR `#93` and closed Phase 128; general and coding parent sessions now have explicit bounded prior-session browse, literal search, and paginated safe-text reads without automatic recall or fixed Research-child exposure. Phase 129 is limited to one typed read-only `files.list` capability for bounded workspace-relative directory and shallow-tree discovery. It will provide stable ordering, depth and pagination controls, scan and output ceilings, LocalWorkspace containment, and default exclusion of hidden, symlinked, dependency, cache, VCS, virtual-environment, and generated-build paths. File mutation, content reads, persistent indexes, desktop file browsing, Research-child expansion, browser automation, MCP, connectors, and `tool_search` remain outside this slice. Updated Hermes commit `3f0b0e20e` is the source reference for file-discovery interaction only; Zebra retains its typed registry, runtime, Policy, budget, event, and recovery boundaries.
- 2026-07-15: completed `P128-HIST-01` on `codex/p128-hist-01-bounded-durable-session-recall`; general and coding parent sessions can now explicitly browse, literally search, and page through bounded prior local sessions through one optional typed read-only Port and `sessions.search` tool. The SQLite adapter excludes the active session, scans fixed recent-session and safe-message ceilings, returns only bounded session metadata plus user/assistant text, labels all historical content untrusted, and preserves existing Policy and authority boundaries. API, CLI, direct runtime, and Worker share the same adapter contract while fixed Research children remain unchanged. All `1111` backend tests, Ruff, Mypy across `244` source files, the 8-case eval gate, all ten desktop checks, the Node 22 production build, Tauri `cargo check`, live browser acceptance, and a real `deepseek-v4-flash` search/read/final-answer pass succeeded.
- 2026-07-15: started `P128-HIST-01` on `codex/p128-hist-01-bounded-durable-session-recall`; implementation is limited to an optional typed read-only history Port plus bounded `sessions.search` browse, literal-query, and paginated-read shapes over safe prior user/assistant text. The active session, raw events, tool payloads, approvals, credentials, automatic recall, and fixed Research children remain excluded.
- 2026-07-15: merged `P127-SKILL-01` through GitHub PR `#91` and closed Phase 127; explicitly configured general and coding parent sessions now have bounded Hermes-compatible local Skill discovery and reads without authority widening or fixed Research-child exposure. Phase 128 is limited to one typed read-only `sessions.search` capability over the configured local SQLite history Port. It will support bounded recent browsing, case-insensitive literal search, and paginated single-session reads while excluding the active session and projecting only safe user/assistant text. Raw control events, tool payloads, approvals, credentials, FTS, vectors, summaries, cross-profile or cross-tenant history, automatic recall, and a desktop search page remain outside this slice. Hermes `session_search_tool.py` informs the interaction shapes only; Zebra retains its typed Port, SQLite, Policy, budget, event, and recovery boundaries.
- 2026-07-15: completed `P127-SKILL-01` on `codex/p127-skill-01-local-progressive-disclosure`; explicitly configured general and coding parent sessions now conditionally expose typed `skills.list` and `skills.read` tools backed by one deterministic bounded local catalog. Discovery reads only bounded frontmatter, omits ambiguous names, excludes dependency, cache, VCS, virtual-environment, symlink, and nested support-package paths, and keeps oversized Skill bodies metadata-visible but unreadable. Support-file reads require approved directories, canonical containment, UTF-8 text, and fixed byte limits; every result is labeled untrusted procedural guidance and grants no execution authority. API, CLI, direct runtime, and Worker share `ZEBRA_SKILL_ROOTS`, while no configuration means no model-visible Skill tools and fixed Research children remain unchanged. The refreshed Hermes commit `47d853fdf` exposed all 72 current Skills. Browser acceptance remained viewport-bound with no console errors or idle HITL controls, and real `deepseek-v4-flash` executed `skills.list` then `skills.read` before returning `SKILL_FINAL_OK`. All 1,091 backend tests, Ruff, Mypy across 240 source files, the 8-case eval gate, all ten desktop checks, the Node 22 production build, and Tauri `cargo check` passed.
- 2026-07-15: started `P127-SKILL-01` on `codex/p127-skill-01-local-progressive-disclosure`; implementation is limited to explicitly configured local Skill roots plus typed metadata-first `skills.list` and bounded `skills.read` tools. Skill content remains untrusted guidance with no implicit execution or authority, and fixed Research children remain unchanged.
- 2026-07-15: merged `P126-WEB-01` through GitHub PR `#89` and closed Phase 126; configured general and coding parent sessions now have one approval-gated bounded SearXNG discovery path while fixed Research children remain offline. Phase 127 is limited to local Skill progressive disclosure from explicitly configured roots through typed `skills.list` and `skills.read` tools. The implementation will follow the refreshed Hermes source at commit `47d853fdf` for discovery exclusions, metadata-first disclosure, support-file isolation, and ambiguous-name handling, while preserving Zebra's registry, Policy, approval, Gateway, session, event, and recovery boundaries. Skill installation, editing, marketplace behavior, automatic execution, prompt-wide injection, plugin or MCP discovery, and Research-child Skills remain outside this slice.
- 2026-07-15: completed `P126-WEB-01` on `codex/p126-web-01-bounded-web-search-gateway`; general and coding parent sessions now conditionally advertise one typed `web.search` capability only when an explicit credential-free HTTPS SearXNG JSON endpoint is configured. Core input validation, exact durable endpoint-host allowlisting, Policy approval, bounded local Gateway transport, public-DNS enforcement, strict JSON normalization, untrusted result labeling, API/CLI/Worker composition, exact approval continuation, and Web-specific desktop HITL readback now share one fail-closed path; fixed Research children remain offline. Browser acceptance showed the exact tool, endpoint, query, limit, and read-only scope with zero search-provider requests before approval, no console errors, and viewport containment. A real `deepseek-v4-flash` pass selected `web.search`, consumed one deterministic result, and returned `SEARCH_SYNTHESIS_OK: SEARCH-SOURCE-126`. All `1067` backend tests, Ruff, Mypy across `238` source files, the 8-case eval release gate, all ten desktop checks, the Node 22 production build, and Tauri `cargo check` passed. Tauri now explicitly reuses the tracked project logo so native validation no longer depends on a missing default icon path.
- 2026-07-15: merged `P125-PLAN-01` through GitHub PR `#87` and closed Phase 125; parent sessions now have one bounded projection-backed task plan that remains distinct from execution authority and inferred UI stages. Phase 126 is limited to one typed, read-only `web.search` capability through an explicitly configured SearXNG JSON Gateway. Search remains unavailable by default, requires durable `domain-allowlist` authority for the exact provider hostname plus concrete approval, returns at most five bounded untrusted results, and remains absent from fixed Research children. Browser automation, recursive fetch, credentials, multi-provider fallback, ranking, indexing, caching, Web memory, Skills, MCP discovery, and SaaS connectors remain outside this slice. Hermes Web tools inform provider separation and normalization only; Zebra retains its existing Policy, Gateway, event, and recovery boundaries.
- 2026-07-15: completed `P125-PLAN-01` on `codex/p125-plan-01-durable-session-task-plan`; parent sessions now expose a typed `agent.plan` capability backed by one bounded `plan_updated` event and deterministic SQLite projection. Plans allow at most 12 ordered steps, one active step, full-list replacement/readback, and stable counts without granting execution authority. Worker recovery and context construction restore only unfinished work, API and CLI share one safe serializer, fixed Research children cannot mutate the parent plan, and the desktop renders only concrete non-empty plans without editing controls. Browser acceptance verified the real two-step plan, the empty-plan absence rule, and viewport containment. A real `deepseek-v4-flash` run called `agent.plan`, persisted exactly one update, returned `PLAN_FINAL_OK`, and read back `1/2` complete. All `1049` backend tests, Ruff, Mypy across `235` source files, the 8-case eval release gate, all nine desktop checks, the Node 22 production build, and Tauri `cargo check` passed.
- 2026-07-15: merged `P124-HITL-01` through GitHub PR `#85` and closed Phase 124; durable parent-session clarification now pauses and resumes one correlated model conversation without blocking workers or widening authority. Phase 125 is limited to one durable session task-plan capability with at most 12 ordered steps, strict statuses, one active step, projection-backed readback, and truthful desktop rendering. Hermes `todo` informs only the bounded ordered-list interaction; Zebra will use session events and SQLite projections rather than process-local state or chat-history hydration. Project kanban, scheduling, user editing, plan approval, DAGs, and Research-child plan mutation remain outside this slice.
- 2026-07-15: completed `P124-HITL-01` on `codex/p124-hitl-01-durable-clarification`; parent sessions now expose a typed `agent.clarify` tool that persists one bounded request, transitions to `waiting_input`, releases the worker, requires an exact correlated response, and resumes the original assistant/tool conversation exactly once. API, CLI, SQLite projections, worker recovery, and desktop controls share the same safe active-request projection; stale or mismatched responses and uncertain prior continuation fail closed, provider failures become durable terminal failures, and fixed Research children do not receive clarification authority. Browser acceptance verified that controls appear only for a concrete request and ordinary composition is hidden while waiting. A real `deepseek-v4-flash` run moved from `waiting_input` through an `Operators` response to `completed` with `AUDIENCE=Operators`. All `1040` backend tests, Ruff, Mypy across `231` source files, the 8-case eval release gate, all eight desktop checks, and the Node 22 production frontend build passed.
- 2026-07-15: merged `P122-WEB-01` through GitHub PR `#81` and closed Phase 122; general and coding agents now have one approval-gated bounded Web fetch path while Research children remain offline. Phase 123 is limited to a typed, read-only `files.search` capability for local content and filename discovery under workspace containment, pagination, and output ceilings. It references the updated local Hermes `search_files` design for bounded interaction lessons but retains Zebra's registry, Policy, runtime, event, and subagent boundaries. Persistent indexing, semantic or vector search, LSP, Web Search, hidden credential discovery, directory mutation, and shell fallback remain outside this slice.
- 2026-07-15: completed `P122-WEB-01` on `codex/p122-web-01-bounded-read-only-web-gateway`; general and coding tasks now advertise a typed `web.fetch` capability behind one dedicated Gateway contract. Core URL validation accepts only credential-free public-hostname HTTPS targets without ports, fragments, spaces, or IP literals. Policy blocks the default offline profile, requires an exact durable domain-allowlist match, and persists structured `web_gateway` approval context before any transport call. The local adapter performs one credential-free GET with environment proxies disabled, rejects non-public DNS answers and redirects, accepts only bounded textual responses, labels returned content untrusted, and records body-free route metadata. Worker acceptance proved zero transport calls before approval and exactly one after exact continuation. Real `deepseek-v4-flash` selected `web.fetch` from the general manifest, while browser validation showed durable launch authority and a Web-specific HITL card with zero executed tools. All `1017` backend tests, Ruff, Mypy across `224` source files, the 8-case eval release gate, all seven desktop checks, and the production frontend build passed; browser console errors were empty.
- 2026-07-15: started `P122-WEB-01` on `codex/p122-web-01-bounded-read-only-web-gateway`; the slice is limited to a typed, read-only `web.fetch` capability behind durable network authority, Policy approval, and a dedicated gateway transport. Tasks remain offline by default, Research children remain offline and Web-free, and no browser automation, search, credentials, redirects, private-network access, or write-capable HTTP behavior is added.
- 2026-07-15: merged `P121-NET-01` through GitHub PR `#79` and closed Phase 121; durable per-task network authority now reaches Policy and worker recovery without a process-global fail-open path. Phase 122 is limited to one typed, read-only `web.fetch` capability routed through a dedicated Web Gateway contract. New and legacy tasks remain offline by default; HTTPS targets require an exact durable domain allowlist match and explicit Policy approval before transport. Direct arbitrary URL access, redirects, credentials, private-network targets, Web search, browser automation, SaaS connectors, and networked Research children remain outside this slice.
- 2026-07-15: completed `P121-NET-01` on `codex/p121-net-01-durable-network-authority`; per-task network authority now defaults to fail-closed `none` and persists as a typed core profile plus normalized domain allowlist through task events, workspace projections, legacy SQLite migration, API and CLI readback, Worker recovery, and desktop launch or reload. Direct runtime and Worker execution construct `LocalPolicyEngine` with recovered network authority, while fixed Research children retain the default no-network ceiling. API and CLI reject unsupported profiles, malformed domains, and profile or allowlist mismatches. Browser validation captured a `domain-allowlist` create request, 201 response, durable readback, and Inspector state for `docs.example.com`. All `999` backend tests, Ruff, Mypy across `221` source files, the 8-case eval release gate, all seven desktop contract checks, and the production frontend build passed. No external tool or transport was added.
- 2026-07-15: started `P121-NET-01` on `codex/p121-net-01-durable-network-authority`; implementation is limited to durable fail-closed per-task network authority across core, Policy composition, storage, API, CLI, worker, and desktop launch paths. No external tool or transport is added in this phase.
- 2026-07-15: merged `P120-CAP-01` through GitHub PR `#77` and closed Phase 120; general and coding tool profiles are now durable and independent of security policy. Phase 121 is limited to making per-task network authority durable and fail closed from launch through Policy and worker recovery before any new external information tool is model-visible. New and legacy tasks default to `network_profile=none`; supported broader profiles remain explicit, validated, and separate from tool and filesystem or command policy. Web search, URL fetch, browser automation, MCP discovery or transport, SaaS integrations, provider networking control, and arbitrary egress rules remain later boundaries.
- 2026-07-15: completed `P120-CAP-01` on `codex/p120-cap-01-durable-tool-profiles`; task capability selection is now a provider-neutral durable `tool_profile` independent of security `policy_profile`. New API, CLI, runtime, and desktop launches default to `general` with `agent.research`, `command.run`, `files.read`, and `patch.apply`; explicit `coding` additionally exposes `git.status` and `tests.run`, while legacy events and SQLite rows without the field recover as `coding`. The selected profile persists through bootstrap events, workspace projection storage and migration, API or CLI readback, worker recovery, and desktop launch or reload; unknown values fail closed and every enabled tool still passes the existing Policy and approval path. Browser validation captured an explicit coding `POST /sessions` and durable session readback. Real `deepseek-v4-flash` calls received exactly four general tools or six coding tools and returned `PROFILE_OK` without tool calls. All `996` backend tests, Ruff, Mypy across `220` source files, the 8-case eval release gate, all seven desktop contract checks, and the production frontend build passed.
- 2026-07-15: merged `P119-SUB-01` through GitHub PR `#75` and closed Phase 119; Phase 120 is limited to durable fixed task tool profiles that separate model-visible capability selection from security authority. New tasks will default to a general-purpose manifest while the current coding-oriented manifest remains an explicit option; legacy sessions retain their original effective behavior. Tool profiles will filter registration and advertisement but cannot bypass Policy or approval, and Research children keep their narrower read-only non-recursive ceiling. Arbitrary manifests, prompt-based inference, new external tools, role-specific subagents, write-capable children, and distributed scheduling remain later boundaries.
- 2026-07-15: completed `P119-SUB-01` implementation on `codex/p119-sub-01-bounded-parallel-research-fanout`; independent `agent.research` calls from one provider batch now reuse the safe concurrent executor under a fixed production child and concurrency limit of `3`. Policy, duplicate, parent tool budget, and research batch capacity are checked before any child starts; child results, lifecycle events, and aggregate identity, status, model-call, tool-call, and source evidence remain in provider order without raw findings in control metadata. Children still share only the parent workspace inspection boundary, expose `files.read` and `git.status` under `READ_ONLY`, cannot recursively delegate, and are cancelled and joined on parent teardown. Deterministic acceptance proved overlapping children, ordered results, zero-start limit rejection, sibling terminal observation, and compatibility. A real `deepseek-v4-flash` parent issued two Research calls in one response, both children completed with one source each, aggregate child usage was four model calls and two tool calls, and the parent returned the exact `FANOUT-PROVIDER-OK` answer. All `990` tests, Ruff, Mypy across `219` source files, and the 8-case eval release gate passed.
- 2026-07-14: merged `P118-SUB-01` through GitHub PR `#72` and closed Phase 118; Phase 119 is limited to bounded local parallel fan-out for independent `agent.research` calls from one provider batch. It reuses the existing safe-batch preflight and provider-order projection, raises child and concurrency limits only to a conservative fixed bound, preserves the read-only authority ceiling and no-recursion rule, and joins all local children on teardown. Adaptive dependency graphs, write-capable children, fixed Reviewer or Coder roles, separate worktrees, distributed recovery, A2A, and repository indexing remain later boundaries.
- 2026-07-14: completed `P118-SUB-01` implementation on `codex/p118-sub-01-bounded-read-only-research`; `agent-core` now defines provider-neutral child identity, task, lifecycle, budget, source, result, and `spawn/join/cancel/collect` contracts. Production local runtime and worker composition advertise one `agent.research` capability backed by a single-child standard-library coordinator and the existing Harness. Children inherit the parent workspace but expose only `files.read` and `git.status` under `READ_ONLY` policy, cannot recursively delegate, and are bounded by child, concurrency, depth, model-call, and tool-call ceilings before work starts. Structured child results carry summaries, source references, confidence, status, and usage; lifecycle events contain only identities, bounds, counts, confidence, and provenance. A real `deepseek-v4-flash` parent delegated one file investigation, the child completed in two model calls and one tool call with one source at confidence `1.0`, and the parent returned the exact `PARENT-SUBAGENT-OK` answer. All `987` tests, Ruff, Mypy across `218` source files, and the 8-case eval release gate passed.
- 2026-07-14: merged `P117-CTX-01` through GitHub PR `#70` and closed Phase 117; Phase 118 is limited to one bounded local-first read-only Research Subagent primitive. The child inherits the parent workspace under a strictly narrower inspection-only profile, returns structured sourced evidence, cannot recursively delegate, and remains subject to explicit child, concurrency, model, tool, and depth budgets. Write-capable children, Reviewer role behavior, separate worktrees, durable distributed child recovery, A2A, and repository indexing remain later boundaries.
- 2026-07-14: completed `P117-CTX-01` implementation on `codex/p117-ctx-01-bounded-conversation-compaction`; provider follow-up calls now apply a deterministic dynamic-conversation budget through an `agent-core` port implemented by `agent-context`. Compaction preserves the stable system prefix, original goal, latest working exchange, complete assistant/tool pairs, and unresolved approval state while replacing only completed older evidence with a bounded summary. Metrics-only `context_compacted` events record estimates, counts, and provenance without raw tool output. Approval continuation resumes the exact pending call without replaying earlier tools. A real `deepseek-v4-flash` run read two files sequentially, compacted the estimate from `2616` to `521` tokens, and returned the exact `COMPACT-OK` answer in three model calls. All `980` tests, Ruff, Mypy across `214` source files, and the 8-case eval release gate passed.
- 2026-07-14: merged `P116-HAR-01` through GitHub PR `#68` and closed Phase 116; Phase 117 is limited to deterministic compaction of completed older conversation and tool-result exchanges inside the provider loop. Stable context, the original goal, recent working state, complete tool-call pairs, and unresolved approval evidence must remain intact. Model-generated summaries, vector retrieval, provider-specific token guarantees, and subagent delegation remain later boundaries.
- 2026-07-14: completed `P116-HAR-01` implementation on `codex/p116-har-01-bounded-safe-concurrent-batches`; tool contracts now default to non-parallel and explicitly mark only `files.read` and `git.status` as parallel-safe. Fully eligible provider batches complete policy, duplicate, and budget preflight before a standard-library thread pool starts, enforce a configurable bound, and project results and events in provider order. Mixed, unknown, write-capable, approval continuation, and single-call paths remain sequential. Concurrent failures observe every already-started sibling and make no rollback claim. A real `deepseek-v4-flash` batch entered the production concurrent path with size 2 and limit 3, read two isolated files, and returned the exact `SAFE-A|SAFE-B` answer. All `975` tests, Ruff, Mypy across `212` source files, and the 8-case eval release gate passed.
- 2026-07-14: merged `P115-HAR-01` through GitHub PR `#66` and closed Phase 115; Phase 116 is limited to bounded concurrency for complete batches whose members are all explicitly parallel-safe. Mixed, unknown, write-capable, denied, or approval-required batches retain deterministic sequential handling. Dependency graphs, call reordering, concurrent writes, subagents, and distributed scheduling remain later boundaries.
- 2026-07-14: completed `P115-HAR-01` implementation on `codex/p115-har-01-deterministic-multi-call-batches`; one provider assistant turn now retains its complete ordered tool-call batch, each call receives independent proposal, policy, execution, verification, and budget handling, and all matching tool results reach the next model request without silently dropping siblings. Denied, repeated, failed, or over-budget members stop before the remaining tail. Approval events persist the exact pending call, prior conversation, counters, and unconsumed tail; resume skips re-proposal of the granted call, continues later calls through normal policy, and now preserves all continuation execution events. A real `deepseek-v4-flash` response returned two `files.read` calls at once and converged in two model calls to the exact `BATCH-A|BATCH-B` answer. All `965` tests, Ruff, Mypy across `211` files, and the 8-case eval release gate passed.
- 2026-07-14: merged `P114-HAR-01` through GitHub PR `#64` and closed Phase 114; Phase 115 is limited to consuming complete provider tool-call batches in deterministic order with per-call policy, budgets, and exact approval continuation. True concurrent execution, automatic reordering, and subagent scheduling remain later boundaries.
- 2026-07-14: completed `P114-HAR-01` implementation on `codex/p114-har-01-bounded-sequential-tool-loop`; one attempt now carries provider-neutral assistant and tool turns through a bounded sequential loop, reserves the last model call for a final answer, blocks repeated name-and-argument actions, and persists prior conversation plus counters when a later call requires approval. Approval resume executes the exact pending call without replaying completed tools, while text-only, one-tool, rejection, and uncertain-side-effect behavior remains covered. Production defaults are now four model calls and three tool calls. A real `deepseek-v4-flash` run called `files.read` twice in sequence and returned the exact combined `ALPHA|BETA` proof. All `960` tests, Ruff, Mypy across `210` files, and the 8-case eval release gate passed.
- 2026-07-14: merged `P113-HITL-01` through GitHub PR `#62` and closed Phase 113; Phase 114 is limited to a budgeted sequential tool loop that preserves exact approval continuation on later steps. Parallel tool execution, subagent delegation, and generic distributed scheduling remain later boundaries.
- 2026-07-14: completed `P113-HITL-01` implementation on `codex/p113-hitl-01-exact-approved-tool-continuation`; approval-required attempts now remain durably `waiting_approval` instead of being overwritten by `session_failed`, approval context preserves immutable tool identity, arguments, provider call id, original assistant turn, and a canonical fingerprint, and grants bind to that exact call. Worker resume executes the recovered call without a replacement model proposal, returns its result for final synthesis, blocks duplicate terminal resume, and refuses automatic replay after uncertain execution start. The desktop approve action now chains the existing resume endpoint before durable refresh. A local `command.run` acceptance covered waiting, exact readback, grant, one execution, final response, and duplicate protection. All `956` backend tests, Ruff, Mypy across `205` files, the 8-case eval release gate, focused desktop approval check, and production frontend build passed.
- 2026-07-14: merged `P112-HAR-01` through GitHub PR `#60` and closed Phase 112; Phase 113 is limited to binding approval to one immutable pending tool call, executing that exact call after grant, and converging to a grounded final answer without a replacement model proposal. Multi-tool execution and automatic replay of uncertain side effects remain later boundaries.
- 2026-07-14: completed `P112-HAR-01` implementation and real-provider acceptance on `codex/p112-har-01-tool-result-synthesis`; provider-neutral messages now preserve assistant tool calls and matching provider call ids, the OpenAI-compatible adapter serializes assistant and tool turns, and production local runtime and worker composition use a two-call budget to persist the final grounded answer. A real `deepseek-v4-flash` run read the isolated `ZEBRA_TOOL_RESULT_SYNTHESIS_OK` payload through `files.read`, returned that exact value as the final answer, and durably recorded both model responses plus `model_calls_used=2`. All `953` tests, Ruff, Mypy across `204` files, and the 8-case eval release gate passed. Approval continuation and additional tool calls remain explicit non-goals.
- 2026-07-14: merged `P111-MDL-01` through GitHub PR `#58` and closed Phase 111; Phase 112 is limited to feeding one allowed tool result back to the provider for a final grounded answer, while approval continuation and multi-tool loops remain later boundaries.
- 2026-07-14: completed `P111-MDL-01` implementation and real-provider acceptance on `codex/p111-mdl-01-provider-tool-discovery`; `agent-core` now defines provider-neutral model tool contracts, the executable `ToolRegistry` deterministically projects its registered builtins into JSON Schema definitions, and the OpenAI-compatible adapter maps dotted internal names to provider-safe aliases while rejecting unadvertised calls. Local API, CLI, and worker execution now advertise the same tools they execute. A real `deepseek-v4-flash` run selected `files.read`, passed the `workspace_write` policy, and read the isolated proof payload through the local tool gateway. The ignored credential remained untracked; `950` tests, Ruff, Mypy across `204` files, and the 8-case eval release gate passed. Tool-result synthesis and exact approval continuation remain explicit later boundaries.
- 2026-07-14: merged `P110-INT-01` through GitHub PR `#56` and closed Phase 110; Phase 111 is limited to advertising executable typed tools to the real provider and proving one policy-allowed provider-selected tool execution, while exact approval continuation remains a later boundary.
- 2026-07-14: completed `P110-INT-01` implementation and browser acceptance on `codex/p110-int-01-provider-backed-desktop-execution`; Zebra Agent is now documented and presented as a general executing-agent runtime and workspace rather than a code-delivery product. Normal tasks no longer render or request Diff, artifact, delivery-audit, Commit, or Pull Request surfaces; generic activity stages and context/log inspection remain. A projection-backed HITL session showed operation, target, policy, scope, and approve/reject controls only while approval was active, and the panel disappeared after approval. A real `deepseek-v4-flash` task reached `completed`, streamed its response without reload, and restored the selected task, title, workspace, seven events, response, and terminal status after reload. The provider credential remained in ignored `.env.local`; all focused frontend checks, the production build, `946` backend tests, Ruff, Mypy, and the 8-case eval release gate passed.
- 2026-07-14: merged `P109-UI-01` through GitHub PR `#54` and closed Phase 109; Phase 110 is limited to proving one provider-backed desktop execution from durable creation through terminal readback and fixing only defects exposed by that real flow.
- 2026-07-14: completed `P109-UI-01` implementation and browser acceptance on `codex/p109-ui-01-reversible-task-visibility`; local drafts now expose explicit deletion while durable sessions expose local hiding, persisted tombstones survive reload, and an in-product restore control rehydrates hidden recent sessions from an authoritative `GET /sessions` snapshot without any backend delete request. Browser validation covered durable hide, storage persistence, reload, restore, preserved title/workspace/status/session binding, distinct draft deletion, and a viewport-bound layout. All `946` backend tests, Ruff, Mypy, the eval release gate, focused project, index, launch, delivery, live, and runtime checks, and the production build passed.
- 2026-07-14: merged `P108-UI-01` through GitHub PR `#52` and closed Phase 108; Phase 109 is limited to replacing misleading task deletion semantics with explicit local draft deletion and reversible durable-session hiding.
- 2026-07-14: completed `P108-UI-01` implementation and browser acceptance on `codex/p108-ui-01-project-aware-workspace-identity`; idle workspace titles now follow selected workspace projects, unbound navigation remains explicitly unbound, and active-session Inspector identity comes only from durable session workspace evidence with full paths retained as accessible titles. Browser validation covered B-to-A switching, unbound selection, durable B session readback, and a viewport-bound `1200x762` layout. All `946` backend tests, Ruff, Mypy, the eval release gate, focused project, index, launch, delivery, live, and runtime checks, and the production build passed.
- 2026-07-14: merged `P107-UI-01` through GitHub PR `#50` and closed Phase 107; Phase 108 is limited to replacing the remaining hard-coded desktop project identity with selected-project or durable-session workspace evidence.
- 2026-07-14: completed `P107-UI-01` implementation and browser acceptance on `codex/p107-ui-01-workspace-project-navigation`; the desktop now projects project navigation from configured launch state plus durable workspace roots, filters task lists by exact normalized workspace identity, keeps unbound tasks visible, and updates only the new-task launch target when a project is selected. Browser validation covered two durable workspaces, the unbound bucket, Composer workspace synchronization, unchanged existing-session configuration, and a viewport-bound `1200x762` layout. All `946` backend tests, Ruff, Mypy, the eval release gate, focused project, index, launch, delivery, live, and runtime checks, and the production build passed.
- 2026-07-14: merged `P106-APP-01` through GitHub PR `#48` and closed Phase 106; Phase 107 is limited to replacing the hard-coded desktop project card with workspace-backed project navigation derived from durable session evidence and the configured launch workspace.
- 2026-07-14: completed `P106-APP-01` implementation and browser acceptance on `codex/p106-app-01-durable-session-discovery`; the projection store now provides bounded newest-first recent sessions, authenticated `GET /sessions` returns compact summaries through the same workspace and approval serializer as session detail, and the desktop reconciles those durable records with local drafts and explicit local hide tombstones. Browser validation recovered a real session after clearing the task index, preserved an unsent draft across reconciliation, and kept a locally hidden durable session out of the list after reload. All `946` backend tests, Ruff, Mypy, the eval release gate, focused index, launch, delivery, live, and runtime checks, and the production build passed.
- 2026-07-14: merged `P105-UI-01` through GitHub PR `#46` and closed Phase 105; Phase 106 is limited to bounded durable recent-session discovery and desktop index reconciliation so persisted sessions remain discoverable after browser-local state is lost.
- 2026-07-13: completed `P105-UI-01` implementation and browser acceptance on `codex/p105-ui-01-task-launch-configuration`; new tasks now persist and preflight an explicit workspace plus supported policy, send both through the existing create-session API, and display durable session configuration after creation. Browser validation observed a `201` create response for `/tmp/zebra-agent-p105` with `full_access`, verified invalid-workspace submission blocking and restored launch defaults, and confirmed the page remained viewport-bound. Unsupported attachment and model-selection affordances were removed or represented as fixed API runtime state. All `941` backend tests, Ruff, Mypy, the eval release gate, focused launch, delivery, live, and runtime checks, and the production build passed.
- 2026-07-13: merged `P104-UI-01` through GitHub PR `#44` and closed Phase 104; Phase 105 is limited to truthful task-launch configuration, explicit workspace binding, and removal of unsupported Composer affordances.
- 2026-07-13: completed `P104-UI-01` implementation and browser acceptance on `codex/p104-ui-01-result-review-delivery`; the active task workspace now combines Diff, artifacts, delivery audit, typed Commit, plan-first Pull Request, policy-aware availability, and explicit remote execution confirmation. Browser validation covered workspace-write denial, full-access local-only dry-run, durable audit refresh, and provider-gated execution.
- 2026-07-13: merged `P103-UI-01` through GitHub PR `#42` and closed Phase 103; Phase 104 is limited to mounting existing result-review and delivery APIs into the active Codex task workspace with plan-first pull-request behavior.
- 2026-07-13: completed `P103-UI-01` implementation and browser acceptance on `codex/p103-ui-01-live-execution-approvals`; the active desktop task now consumes SSE events incrementally, polls durable session state during execution, sends real cancellation requests, and exposes approval context with approve or reject actions. Cancel and approval state convergence were verified against the local API. A complete provider-backed model reply remains an environment check because this worktree has no `DEEPSEEK_API_KEY`.
- 2026-07-10: merged `P102-UI-01` through GitHub PR `#40`; the Codex-style desktop workspace now restores its local task index, reloads session state, verifies the Zebra service identity, exposes runtime configuration, and only presents workspace metadata backed by session evidence.
- 2026-07-05: bootstrapped `UI/desktop` as an isolated desktop UI workspace using `Tauri + React + Tailwind CSS + TanStack Query + Ant Design + Ant Design X`.
- 2026-07-05: upgraded `UI/desktop` from a static shell to a live operator surface wired to the local HTTP API for health, approvals, session creation, session detail, stream replay, repo memory inventory, and cross-scope memory overview reads. This does not change the backend phase sequence, but it does establish the first reusable frontend integration seam.
- 2026-07-05: expanded the desktop operator surface to cover approval decisions, session suspend or resume or cancel controls, workspace diff readback, session artifact inspection and content reads, and delivery-audit inspection. The frontend now spans both read and write operator flows for the local API, though Tauri Rust-side validation is still blocked by the machine-level Cargo mirror configuration.
- 2026-07-05: expanded the same desktop surface again to cover session message append, local commit delivery, pull-request planning or execution, and direct candidate-memory review decisions. The UI now reaches most of the current local operator API, with the remaining gap shifting from endpoint coverage toward product polish, stream ergonomics, and environment validation.
- 2026-07-05: expanded the desktop surface again to cover scoped memory queue preview, queue-sweep review, and bulk-review operations for session, user, and tenant scopes. The UI now reaches the newer queue-sweep memory control surfaces rather than only the single-record review endpoints.
- 2026-07-05: expanded the desktop surface once more to expose active scope memory snapshots for session, user, and tenant inventory plus queue-summary reads, so cross-scope queue review no longer happens without local readback.
- 2026-07-05: expanded the desktop surface again to cover session artifact prune control, completing a first local artifact lifecycle write path from the UI alongside existing artifact inspection and delivery-audit readback.
- 2026-07-05: expanded the desktop surface again to read explicit approval detail for the selected waiting session, so approval actions in the UI now sit next to the concrete route, target, scope, and policy context they act on.
- 2026-07-05: expanded the desktop surface again with one compact memory governance card wired to governance and action-hint signals, so operators can see backlog health and the highest-priority next review action without dropping to CLI.
- 2026-07-05: split the frontend type and API foundations into smaller modules before they crossed the repository hard limits, and expanded the memory governance card again to include pressure and escalation signals for the active scopes.
- 2026-07-05: expanded the same governance card further to include follow-up windows and overdue flags, so the UI now carries the continuous triage chain from backlog pressure through escalation into overdue handling cues.
- 2026-07-05: expanded the same governance card again to include overdue age buckets plus overdue type and visibility rollups, so operators can now see not just that a scope is overdue, but how overdue it is and what kind of memory is accumulating there.
- 2026-07-05: expanded the same governance card again to include overdue trend signals and overdue intervention hints, and split the frontend governance surface into smaller files before the card crossed repository size limits.
- 2026-07-05: expanded the same governance card again to include overdue escalation lanes, recovery paths, resolution checkpoints, and resolution outcomes, and split overdue frontend types into a dedicated module so the UI can keep scaling without crossing repository file-size targets.
- 2026-07-05: expanded the same governance card again to include overdue closure decisions, archive recommendations, retention guidance, and retention windows, and split the scope-list rendering into a dedicated component so the governance view can keep extending without breaching repository file targets.

## Current Phase

- Active phase: `Phase 145 - Event-Driven Conversation Stream complete`
- Repository status: `P145-UI-01 merged; ready for next-phase planning`
- Current focus:
  - Phase 139 keeps durable active-session configuration in the context inspector and preserves editable launch configuration only for new tasks and drafts
  - Phase 138 final acceptance passed across compatibility, persistence, immutable recovery, desktop, browser, and real-provider gates
  - Phase 138 turns user-selected MCP Prompt templates into durable untrusted task input without exposing Prompt operations to the model
  - Phase 137 restores maintainable ownership boundaries and permanently enforces the source and test file hard limits; it intentionally adds no product capability
  - `P137-SRC-01`, `P137-UI-01`, and `P137-TEST-01` are merged to `main`; `P137-GATE-01` is the final integration slice
  - `P130-OBS-01` is complete on `codex/p130-obs-01-durable-tool-trace-correlation`, providing exact core/API/CLI evidence association for parallel same-name calls plus deterministic legacy-event compatibility
  - `P129-TOOL-01` was merged through GitHub PR `#95` after deterministic, full-repository, desktop, browser, and real `deepseek-v4-flash` acceptance
  - `P128-HIST-01` was merged through GitHub PR `#93` after deterministic, full-repository, desktop, browser, and real `deepseek-v4-flash` acceptance
  - `P127-SKILL-01` was merged through GitHub PR `#91` after deterministic, full-repository, desktop, browser, Hermes-catalog, and real `deepseek-v4-flash` acceptance
  - `P126-WEB-01` was merged through GitHub PR `#89` after deterministic, full-repository, desktop, browser, approval-continuation, and real `deepseek-v4-flash` acceptance
  - `P125-PLAN-01` was merged through GitHub PR `#87` after deterministic, full-repository, desktop, browser, recovery, and real `deepseek-v4-flash` acceptance
  - `P124-HITL-01` was merged through GitHub PR `#85` after deterministic, full-repository, desktop, browser, recovery, and real `deepseek-v4-flash` clarification acceptance
  - `P119-SUB-01` was merged through GitHub PR `#75` after deterministic, full-repository, and real `deepseek-v4-flash` acceptance of fixed bounded parallel read-only research fan-out
  - `P119-CLOSE-01` records the Phase 119 closeout and the explicit Phase 120 ownership boundary
  - `P118-SUB-01` was merged through GitHub PR `#72` after lifecycle, authority-ceiling, cancellation, full-repository, and real `deepseek-v4-flash` acceptance
  - `P118-CLOSE-01` records the Phase 118 closeout and the explicit Phase 119 ownership boundary
  - `P117-CTX-01` was merged through GitHub PR `#70` after deterministic compaction, approval-continuation, full-repository, and real `deepseek-v4-flash` acceptance
  - `P117-CLOSE-01` records the Phase 117 closeout and the explicit Phase 118 ownership boundary
  - `P116-HAR-01` was merged through GitHub PR `#68` after deterministic concurrency, preflight, fallback, failure-observation, full-repository, and real `deepseek-v4-flash` acceptance
  - `P116-CLOSE-01` records the Phase 116 closeout and the explicit Phase 117 ownership boundary
  - `P115-HAR-01` was merged through GitHub PR `#66` after deterministic, full-repository, middle-batch approval, and real `deepseek-v4-flash` acceptance of complete provider batch consumption
  - `P115-CLOSE-01` records the Phase 115 closeout and the explicit Phase 116 ownership boundary
  - `P114-HAR-01` was merged through GitHub PR `#64` after deterministic, full-repository, later-step approval, and real `deepseek-v4-flash` acceptance of a bounded sequential observe-act loop
  - `P114-CLOSE-01` records the Phase 114 closeout and the explicit Phase 115 ownership boundary
  - `P113-HITL-01` was merged through GitHub PR `#62` after backend and desktop acceptance of immutable approval binding, exact one-call continuation, grounded final synthesis, duplicate protection, and uncertain-execution replay refusal
  - `P113-CLOSE-01` records the Phase 113 closeout and the explicit Phase 114 ownership boundary
  - `P112-HAR-01` was merged through GitHub PR `#60` after deterministic, full-repository, and real `deepseek-v4-flash` acceptance of one-tool result synthesis and durable final-answer readback
  - `P112-CLOSE-01` records the Phase 112 closeout and the explicit Phase 113 ownership boundary
  - `P111-MDL-01` was merged through GitHub PR `#58` after registry-backed JSON Schema advertisement, provider-safe tool-name mapping, real DeepSeek `files.read` execution, and full repository gates
  - `P111-CLOSE-01` records the Phase 111 closeout and the explicit Phase 112 ownership boundary
  - `P110-INT-01` was merged through GitHub PR `#56` after the product-positioning correction, default code-delivery UI removal, approval-driven HITL validation, real DeepSeek completion, active-task reload restoration, and full repository gates
  - `P110-CLOSE-01` records the Phase 110 closeout and the explicit Phase 111 ownership boundary
  - `P109-UI-01` was merged through GitHub PR `#54` after full backend and frontend gates plus browser validation of truthful draft/session actions, persisted local hiding, no backend deletion, immediate authoritative restoration, and viewport containment
  - `P109-CLOSE-01` records the Phase 109 closeout and the explicit Phase 110 ownership boundary
  - `P108-UI-01` was merged through GitHub PR `#52` after full backend and frontend gates plus browser validation of selected-project titles, explicit unbound identity, durable session identity, full-path accessibility, and viewport containment
  - `P108-CLOSE-01` records the Phase 108 closeout and the explicit Phase 109 ownership boundary
  - `P107-UI-01` was merged through GitHub PR `#50` after full backend and frontend gates plus browser validation of durable project grouping, exact-workspace task filtering, unbound visibility, launch-target synchronization, and existing-session immutability
  - `P107-CLOSE-01` records the Phase 107 closeout and the explicit Phase 108 ownership boundary
  - `P106-APP-01` was merged through GitHub PR `#48` after full backend and frontend gates plus browser validation of fresh-profile recovery, local-draft preservation, durable workspace readback, and local hide persistence
  - `P106-CLOSE-01` records the Phase 106 closeout and the explicit Phase 107 ownership boundary
  - `P105-UI-01` was merged through GitHub PR `#46` after full backend and frontend gates plus browser validation of launch preflight, invalid-workspace blocking, request payloads, durable session configuration, and restored defaults
  - `P105-CLOSE-01` records the Phase 105 closeout and the explicit Phase 106 ownership boundary
  - `P104-UI-01` was merged through GitHub PR `#44` after `941` backend tests, Ruff, Mypy, the eval release gate, focused delivery, live execution, and runtime checks, the production build, and browser validation of policy denial, plan-first pull requests, and delivery-audit convergence
  - `P104-CLOSE-01` records the Phase 104 closeout and the explicit Phase 105 ownership boundary
  - `P103-UI-01` was merged through GitHub PR `#42` after `941` backend tests, Ruff, Mypy, the eval release gate, focused frontend checks, the production build, and browser validation of incremental events, real cancellation, approval decisions, and durable state convergence
  - `P103-CLOSE-01` records the Phase 103 closeout and the explicit Phase 104 ownership boundary
  - `P102-UI-01` was merged through GitHub PR `#40` after `make check`, frontend build, state projection checks, CORS preflight, service identity rejection, runtime configuration switching, and persisted session restoration passed
  - `P102-CLOSE-01` records the Phase 102 closeout and the explicit Phase 103 ownership boundary
  - `P101-CLOSE-01` is complete on `codex/p101-closeout-next-plan` with Phase 101 acceptance evidence on `docs/Phase101_Scoped_Queue_Sweep_Filtered_Preview_Controls_验收记录.md`
  - `Phase 101` is closed with `docs/Phase101_Scoped_Queue_Sweep_Filtered_Preview_Controls_验收记录.md`
  - `P101-MEM-01` is complete on `codex/p101-mem-01-scoped-queue-sweep-filtered-preview-controls` with one minimal narrowing filter for repo-session, user, and tenant queue-sweep previews plus API and CLI parity coverage
  - The next memory workflow priority is not yet defined
  - `P100-CLOSE-01` is complete on `codex/p100-closeout-next-plan` with Phase 100 acceptance evidence on `docs/Phase100_Scoped_Queue_Sweep_Target_Explanations_验收记录.md`
  - `Phase 100` is closed with `docs/Phase100_Scoped_Queue_Sweep_Target_Explanations_验收记录.md`
  - `P100-MEM-01` is complete on `codex/p100-mem-01-scoped-queue-sweep-target-explanations` with per-record target reasons and aggregate explanation counts for repo-session, user, and tenant queue-sweep previews plus API and CLI parity coverage
  - `P99-CLOSE-01` is complete on `codex/p99-closeout-next-plan` with Phase 99 acceptance evidence on `docs/Phase99_Scoped_Queue_Sweep_Dry_Run_Summaries_验收记录.md`
  - `Phase 99` is closed with `docs/Phase99_Scoped_Queue_Sweep_Dry_Run_Summaries_验收记录.md`
  - `P99-MEM-01` is complete on `codex/p99-mem-01-scoped-queue-sweep-dry-run-summaries` with projected outcome summaries for repo-session, user, and tenant queue-sweep previews plus API and CLI parity coverage
  - `P98-CLOSE-01` is complete on `codex/p98-closeout-next-plan` with Phase 98 acceptance evidence on `docs/Phase98_Scoped_Queue_Sweep_Preview_Controls_验收记录.md`
  - `Phase 98` is closed with `docs/Phase98_Scoped_Queue_Sweep_Preview_Controls_验收记录.md`
  - `P98-MEM-01` is complete on `codex/p98-mem-01-scoped-queue-sweep-preview-controls` with side-effect-free preview controls for repo-session, user, and tenant queue sweeps plus API and CLI parity coverage
  - `P97-CLOSE-01` is complete on `codex/p97-closeout-next-plan` with Phase 97 acceptance evidence on `docs/Phase97_Scoped_Queue_Sweep_Review_Controls_验收记录.md`
  - `Phase 97` is closed with `docs/Phase97_Scoped_Queue_Sweep_Review_Controls_验收记录.md`
  - `P97-MEM-01` is complete on `codex/p97-mem-01-scoped-queue-sweep-review-controls` with scoped queue-sweep review controls for repo-session, user, and tenant memory plus API and CLI parity coverage
  - `P96-CLOSE-01` is complete on `codex/p96-closeout-next-plan` with Phase 96 acceptance evidence on `docs/Phase96_Memory_Overdue_Retention_Breach_Follow_Through_Verification_Outcomes_验收记录.md`
  - `Phase 96` is closed with `docs/Phase96_Memory_Overdue_Retention_Breach_Follow_Through_Verification_Outcomes_验收记录.md`
  - `P96-MEM-01` is complete on `codex/p96-mem-01-memory-overdue-retention-breach-follow-through-verification-outcomes` with additive overdue retention breach follow-through verification outcomes and highest-priority overdue-retention-breach-follow-through-verification-outcome rollups across supported scopes
  - The overdue-retention-breach follow-through sublane is complete
  - `P95-CLOSE-01` is complete on `codex/p95-closeout-next-plan` with Phase 95 acceptance evidence on `docs/Phase95_Memory_Overdue_Retention_Breach_Follow_Through_Verification_States_验收记录.md`
  - `Phase 95` is closed with `docs/Phase95_Memory_Overdue_Retention_Breach_Follow_Through_Verification_States_验收记录.md`
  - `P95-MEM-01` is complete on `codex/p95-mem-01-memory-overdue-retention-breach-follow-through-verification-states` with additive overdue retention breach follow-through verification states and highest-priority overdue-retention-breach-follow-through-verification rollups across supported scopes
  - `P94-CLOSE-01` is complete on `codex/p94-closeout-next-plan` with Phase 94 acceptance evidence on `docs/Phase94_Memory_Overdue_Retention_Breach_Follow_Through_Completion_States_验收记录.md`
  - `Phase 94` is closed with `docs/Phase94_Memory_Overdue_Retention_Breach_Follow_Through_Completion_States_验收记录.md`
  - `P94-MEM-01` is complete on `codex/p94-mem-01-memory-overdue-retention-breach-follow-through-completion-states` with additive overdue retention breach follow-through completion states and highest-priority overdue-retention-breach-follow-through-completion rollups across supported scopes
  - `P93-CLOSE-01` is complete on `codex/p93-closeout-next-plan` with Phase 93 acceptance evidence on `docs/Phase93_Memory_Overdue_Retention_Breach_Follow_Through_Outcomes_验收记录.md`
  - `Phase 93` is closed with `docs/Phase93_Memory_Overdue_Retention_Breach_Follow_Through_Outcomes_验收记录.md`
  - `P93-MEM-01` is complete on `codex/p93-mem-01-memory-overdue-retention-breach-follow-through-outcomes` with additive overdue retention breach follow-through outcomes and highest-priority overdue-retention-breach-follow-through-outcome rollups across supported scopes
  - `P92-CLOSE-01` is complete on `codex/p92-closeout-next-plan` with Phase 92 acceptance evidence on `docs/Phase92_Memory_Overdue_Retention_Breach_Follow_Through_Modes_验收记录.md`
  - `Phase 92` is closed with `docs/Phase92_Memory_Overdue_Retention_Breach_Follow_Through_Modes_验收记录.md`
  - `P92-MEM-01` is complete on `codex/p92-mem-01-memory-overdue-retention-breach-follow-through-modes` with additive overdue retention breach follow-through modes and highest-priority overdue-retention-breach-follow-through rollups across supported scopes
  - `P91-CLOSE-01` is complete on `codex/p91-closeout-next-plan` with Phase 91 acceptance evidence on `docs/Phase91_Memory_Overdue_Retention_Breach_Owner_Targets_验收记录.md`
  - `Phase 91` is closed with `docs/Phase91_Memory_Overdue_Retention_Breach_Owner_Targets_验收记录.md`
  - `P91-MEM-01` is complete on `codex/p91-mem-01-memory-overdue-retention-breach-owner-targets` with additive overdue retention breach owner targets and highest-priority overdue-retention-breach-owner-target rollups across supported scopes
  - `P90-CLOSE-01` is complete on `codex/p90-closeout-next-plan` with Phase 90 acceptance evidence on `docs/Phase90_Memory_Overdue_Retention_Breach_Lanes_验收记录.md`
  - `Phase 90` is closed with `docs/Phase90_Memory_Overdue_Retention_Breach_Lanes_验收记录.md`
  - `P90-MEM-01` is complete on `codex/p90-mem-01-memory-overdue-retention-breach-lanes` with additive overdue retention breach lanes and highest-priority overdue-retention-breach-lane rollups across supported scopes
  - `P89-CLOSE-01` is complete on `codex/p89-closeout-next-plan` with Phase 89 acceptance evidence on `docs/Phase89_Memory_Overdue_Retention_Breach_Actions_验收记录.md`
  - `Phase 89` is closed with `docs/Phase89_Memory_Overdue_Retention_Breach_Actions_验收记录.md`
  - `P89-MEM-01` is complete on `codex/p89-mem-01-memory-overdue-retention-breach-actions` with additive overdue retention breach actions and highest-priority overdue-retention-breach-action rollups across supported scopes
  - `P88-CLOSE-01` is complete on `codex/p88-closeout-next-plan` with Phase 88 acceptance evidence on `docs/Phase88_Memory_Overdue_Retention_Breach_Aging_验收记录.md`
  - `Phase 88` is closed with `docs/Phase88_Memory_Overdue_Retention_Breach_Aging_验收记录.md`
  - `P88-MEM-01` is complete on `codex/p88-mem-01-memory-overdue-retention-breach-aging` with additive overdue retention breach aging buckets and highest-priority overdue-retention-breach-aging rollups across supported scopes
  - `P87-CLOSE-01` is complete on `codex/p87-closeout-next-plan` with Phase 87 acceptance evidence on `docs/Phase87_Memory_Overdue_Retention_Breaches_验收记录.md`
  - `Phase 87` is closed with `docs/Phase87_Memory_Overdue_Retention_Breaches_验收记录.md`
  - `P87-MEM-01` is complete on `codex/p87-mem-01-memory-overdue-retention-breaches` with additive overdue retention breaches, breach due-at timestamps, and highest-priority overdue-retention-breach rollups across supported scopes
  - `P86-CLOSE-01` is complete on `codex/p86-closeout-next-plan` with Phase 86 acceptance evidence on `docs/Phase86_Memory_Overdue_Retention_Windows_验收记录.md`
  - `Phase 86` is closed with `docs/Phase86_Memory_Overdue_Retention_Windows_验收记录.md`
  - `P86-MEM-01` is complete on `codex/p86-mem-01-memory-overdue-retention-windows` with additive overdue retention windows, due-at timestamps, and highest-priority overdue-retention-window rollups across supported scopes
  - `P85-CLOSE-01` is complete on `codex/p85-closeout-next-plan` with Phase 85 acceptance evidence on `docs/Phase85_Memory_Overdue_Retention_Guidance_验收记录.md`
  - `Phase 85` is closed with `docs/Phase85_Memory_Overdue_Retention_Guidance_验收记录.md`
  - `P85-MEM-01` is complete on `codex/p85-mem-01-memory-overdue-retention-guidance` with additive overdue retention guidance, retention buckets, and highest-priority overdue-retention rollups across supported scopes
  - `P84-CLOSE-01` is complete on `codex/p84-closeout-next-plan` with Phase 84 acceptance evidence on `docs/Phase84_Memory_Overdue_Archive_Recommendations_验收记录.md`
  - `Phase 84` is closed with `docs/Phase84_Memory_Overdue_Archive_Recommendations_验收记录.md`
  - `P84-MEM-01` is complete on `codex/p84-mem-01-memory-overdue-archive-recommendations` with additive overdue archive recommendations and highest-priority overdue-archive rollups across supported scopes
  - `P83-CLOSE-01` is complete on `codex/p83-closeout-next-plan` with Phase 83 acceptance evidence on `docs/Phase83_Memory_Overdue_Closure_Decisions_验收记录.md`
  - `Phase 83` is closed with `docs/Phase83_Memory_Overdue_Closure_Decisions_验收记录.md`
  - `P83-MEM-01` is complete on `codex/p83-mem-01-memory-overdue-closure-decisions` with additive overdue closure decisions and highest-priority overdue-closure rollups across supported scopes
  - `P82-CLOSE-01` is complete on `codex/p82-closeout-next-plan` with Phase 82 acceptance evidence on `docs/Phase82_Memory_Overdue_Resolution_Outcomes_验收记录.md`
  - `Phase 82` is closed with `docs/Phase82_Memory_Overdue_Resolution_Outcomes_验收记录.md`
  - `P82-MEM-01` is complete on `codex/p82-mem-01-memory-overdue-resolution-outcomes` with additive overdue resolution outcomes and highest-priority overdue-resolution-outcome rollups across supported scopes
  - `P81-CLOSE-01` is complete on `codex/p81-closeout-next-plan` with Phase 81 acceptance evidence on `docs/Phase81_Memory_Overdue_Resolution_Checkpoints_验收记录.md`
  - `Phase 81` is closed with `docs/Phase81_Memory_Overdue_Resolution_Checkpoints_验收记录.md`
  - `P81-MEM-01` is complete on `codex/p81-mem-01-memory-overdue-resolution-checkpoints` with additive overdue resolution checkpoints and highest-priority overdue-resolution rollups across supported scopes
  - `P80-CLOSE-01` is complete on `codex/p80-closeout-next-plan` with Phase 80 acceptance evidence on `docs/Phase80_Memory_Overdue_Recovery_Paths_验收记录.md`
  - `Phase 80` is closed with `docs/Phase80_Memory_Overdue_Recovery_Paths_验收记录.md`
  - `P80-MEM-01` is complete on `codex/p80-mem-01-memory-overdue-recovery-paths` with additive overdue recovery paths and highest-priority overdue-recovery rollups across supported scopes
  - `P79-CLOSE-01` is complete on `codex/p79-closeout-next-plan` with Phase 79 acceptance evidence on `docs/Phase79_Memory_Overdue_Escalation_Lanes_验收记录.md`
  - `Phase 79` is closed with `docs/Phase79_Memory_Overdue_Escalation_Lanes_验收记录.md`
  - `P79-MEM-01` is complete on `codex/p79-mem-01-memory-overdue-escalation-lanes` with additive overdue escalation lanes and highest-priority overdue-escalation rollups across supported scopes
  - `P78-CLOSE-01` is complete on `codex/p78-closeout-next-plan` with Phase 78 acceptance evidence on `docs/Phase78_Memory_Overdue_Intervention_Hints_验收记录.md`
  - `Phase 78` is closed with `docs/Phase78_Memory_Overdue_Intervention_Hints_验收记录.md`
  - `P78-MEM-01` is complete on `codex/p78-mem-01-memory-overdue-intervention-hints` with additive overdue intervention hints and highest-priority overdue-intervention rollups across supported scopes
  - `P77-CLOSE-01` is complete on `codex/p77-closeout-next-plan` with Phase 77 acceptance evidence on `docs/Phase77_Memory_Overdue_Trend_Signals_验收记录.md`
  - `Phase 77` is closed with `docs/Phase77_Memory_Overdue_Trend_Signals_验收记录.md`
  - `P77-MEM-01` is complete on `codex/p77-mem-01-memory-overdue-trend-signals` with additive overdue trend signals and highest-priority overdue-trend rollups across supported scopes
  - `P76-CLOSE-01` is complete on `codex/p76-closeout-next-plan` with Phase 76 acceptance evidence on `docs/Phase76_Memory_Overdue_Visibility_Rollups_验收记录.md`
  - `Phase 76` is closed with `docs/Phase76_Memory_Overdue_Visibility_Rollups_验收记录.md`
  - `P76-MEM-01` is complete on `codex/p76-mem-01-memory-overdue-visibility-rollups` with additive overdue visibility counts and highest-priority overdue-visibility rollups across supported scopes
  - `P75-CLOSE-01` is complete on `codex/p75-closeout-next-plan` with Phase 75 acceptance evidence on `docs/Phase75_Memory_Overdue_Type_Rollups_验收记录.md`
  - `Phase 75` is closed with `docs/Phase75_Memory_Overdue_Type_Rollups_验收记录.md`
  - `P75-MEM-01` is complete on `codex/p75-mem-01-memory-overdue-type-rollups` with additive overdue memory-type counts and highest-priority overdue-type rollups across supported scopes
  - `P74-CLOSE-01` is complete on `codex/p74-closeout-next-plan` with Phase 74 acceptance evidence on `docs/Phase74_Memory_Overdue_Age_Buckets_验收记录.md`
  - `Phase 74` is closed with `docs/Phase74_Memory_Overdue_Age_Buckets_验收记录.md`
  - `P74-MEM-01` is complete on `codex/p74-mem-01-memory-overdue-age-buckets` with additive overdue age buckets and highest-priority overdue-age rollups across supported scopes
  - `P73-CLOSE-01` is complete on `codex/p73-closeout-next-plan` with Phase 73 acceptance evidence on `docs/Phase73_Memory_Follow_Up_Overdue_Flags_验收记录.md`
  - `Phase 73` is closed with `docs/Phase73_Memory_Follow_Up_Overdue_Flags_验收记录.md`
  - `P73-MEM-01` is complete on `codex/p73-mem-01-memory-follow-up-overdue-flags` with additive overdue flags and highest-priority overdue rollups across supported scopes
  - `P72-CLOSE-01` is complete on `codex/p72-closeout-next-plan` with Phase 72 acceptance evidence on `docs/Phase72_Memory_Escalation_Follow_Up_Windows_验收记录.md`
  - `Phase 72` is closed with `docs/Phase72_Memory_Escalation_Follow_Up_Windows_验收记录.md`
  - `P72-MEM-01` is complete on `codex/p72-mem-01-memory-escalation-follow-up-windows` with additive follow-up windows and highest-priority follow-up rollups across supported scopes
  - `P71-CLOSE-01` is complete on `codex/p71-closeout-next-plan` with Phase 71 acceptance evidence on `docs/Phase71_Memory_Pressure_Escalation_Recommendations_验收记录.md`
  - `Phase 71` is closed with `docs/Phase71_Memory_Pressure_Escalation_Recommendations_验收记录.md`
  - `P71-MEM-01` is complete on `codex/p71-mem-01-memory-pressure-escalation-recommendations` with additive escalation recommendations and highest-priority escalation rollups across supported scopes
  - `P70-CLOSE-01` is complete on `codex/p70-closeout-next-plan` with Phase 70 acceptance evidence on `docs/Phase70_Memory_Pressure_Action_Hints_验收记录.md`
  - `Phase 70` is closed with `docs/Phase70_Memory_Pressure_Action_Hints_验收记录.md`
  - `P70-MEM-01` is complete on `codex/p70-mem-01-memory-pressure-action-hints` with additive action hints and highest-priority operator rollups across supported scopes
  - `P69-CLOSE-01` is complete on `codex/p69-closeout-next-plan` with Phase 69 acceptance evidence on `docs/Phase69_Memory_Backlog_Pressure_Signals_验收记录.md`
  - `Phase 69` is closed with `docs/Phase69_Memory_Backlog_Pressure_Signals_验收记录.md`
  - `P69-MEM-01` is complete on `codex/p69-mem-01-memory-backlog-pressure-signals` with additive pressure classification and highest-pressure rollups across supported scopes
  - `P68-CLOSE-01` is complete on `codex/p68-closeout-next-plan` with Phase 68 acceptance evidence on `docs/Phase68_Memory_Review_Velocity_Signals_验收记录.md`
  - `Phase 68` is closed with `docs/Phase68_Memory_Review_Velocity_Signals_验收记录.md`
  - `P68-MEM-01` is complete on `codex/p68-mem-01-memory-review-velocity-signals` with additive recent review-throughput signals and latest review windows across supported scopes
  - `P67-CLOSE-01` is complete on `codex/p67-closeout-next-plan` with Phase 67 acceptance evidence on `docs/Phase67_Memory_Backlog_Aging_Signals_验收记录.md`
  - `Phase 67` is closed with `docs/Phase67_Memory_Backlog_Aging_Signals_验收记录.md`
  - `P67-MEM-01` is complete on `codex/p67-mem-01-memory-backlog-aging-signals` with additive backlog-aging signals for oldest pending memory and age buckets across supported scopes
  - `P66-CLOSE-01` is complete on `codex/p66-closeout-next-plan` with Phase 66 acceptance evidence on `docs/Phase66_Memory_Review_Governance_Signals_验收记录.md`
  - `Phase 66` is closed with `docs/Phase66_Memory_Review_Governance_Signals_验收记录.md`
  - `P66-MEM-01` is complete on `codex/p66-mem-01-memory-review-governance-signals` with additive governance signals for backlog and latest review activity across supported scopes
  - `P65-CLOSE-01` is complete on `codex/p65-closeout-next-plan` with Phase 65 acceptance evidence on `docs/Phase65_Cross_Scope_Memory_Operations_Overview_验收记录.md`
  - `Phase 65` is closed with `docs/Phase65_Cross_Scope_Memory_Operations_Overview_验收记录.md`
  - `P65-MEM-01` is complete on `codex/p65-mem-01-cross-scope-memory-operations-overview` with one combined API and CLI overview of queue health across repo-session, user, and tenant scopes
  - `P64-CLOSE-01` is complete on `codex/p64-closeout-next-plan` with Phase 64 acceptance evidence on `docs/Phase64_Cross_Scope_Memory_Queue_Summary_验收记录.md`
  - `Phase 64` is closed with `docs/Phase64_Cross_Scope_Memory_Queue_Summary_验收记录.md`
  - `P64-MEM-01` is complete on `codex/p64-mem-01-cross-scope-memory-queue-summary` with additive queue summary reads plus API and CLI parity across repo-session, user, and tenant scopes
  - `P63-CLOSE-01` is complete on `codex/p63-closeout-next-plan` with Phase 63 acceptance evidence on `docs/Phase63_Bulk_Memory_Review_Decisions_验收记录.md`
  - `Phase 63` is closed with `docs/Phase63_Bulk_Memory_Review_Decisions_验收记录.md`
  - `P63-MEM-01` is complete on `codex/p63-mem-01-bulk-memory-review-decisions` with scoped bulk memory confirm or expire controls plus applied/skipped/invalid parity across API and CLI
  - `P62-CLOSE-01` is complete on `codex/p62-closeout-next-plan` with Phase 62 acceptance evidence on `docs/Phase62_Scope_Aware_Memory_Review_Queue_验收记录.md`
  - `Phase 62` is closed with `docs/Phase62_Scope_Aware_Memory_Review_Queue_验收记录.md`
  - `P62-MEM-01` is complete on `codex/p62-mem-01-memory-review-queue` with shared repo, user, and tenant candidate-only memory queue reads plus API and CLI parity coverage
  - `P61-CLOSE-01` is complete on `codex/p61-closeout-next-plan` with Phase 61 acceptance evidence on `docs/Phase61_Cross_Scope_Memory_Review_Controls_验收记录.md`
  - `Phase 61` is closed with `docs/Phase61_Cross_Scope_Memory_Review_Controls_验收记录.md`
  - `P61-MEM-01` is complete on `codex/p61-mem-01-cross-scope-memory-review` with API and CLI review controls now extended across repo, user, and tenant memory scopes
  - `P60-CLOSE-01` is complete on `codex/p60-closeout-next-plan` with Phase 60 acceptance evidence on `docs/Phase60_Cross_Scope_Memory_Operator_Inventory_验收记录.md`
  - `Phase 60` is closed with `docs/Phase60_Cross_Scope_Memory_Operator_Inventory_验收记录.md`
  - `P60-MEM-01` is complete on `codex/p60-mem-01-user-tenant-memory-inventory` with shared repo, user, and tenant memory inventory reads plus API and CLI parity coverage
  - `P59-CLOSE-01` is complete on `codex/p59-closeout-next-plan` with Phase 59 acceptance evidence on `docs/Phase59_Memory_Source_Provenance_Readback_验收记录.md`
  - `Phase 59` is closed with `docs/Phase59_Memory_Source_Provenance_Readback_验收记录.md`
  - `P59-MEM-01` is complete on `codex/p59-mem-01-memory-source-provenance-readback` with deterministic `source` provenance now projected onto API and CLI session memory inventory rows
  - `P58-CLOSE-01` is complete on `codex/p58-closeout-next-plan` with Phase 58 acceptance evidence on `docs/Phase58_Memory_Lifecycle_Readback_And_Broader_Invalidation_验收记录.md`
  - `Phase 58` is closed with `docs/Phase58_Memory_Lifecycle_Readback_And_Broader_Invalidation_验收记录.md`
  - `P58-MEM-02` is complete on `codex/p58-mem-02-broader-stale-memory-invalidation` with refresh-target-driven stale invalidation for deterministic singleton repo memories across governance and procedure refresh families
  - `P58-MEM-01` is complete on `codex/p58-mem-01-session-memory-lifecycle-readback` with `last_review` lifecycle metadata now projected into API and CLI session memory inventory reads
  - `P57-CLOSE-01` is complete on `codex/p58-mem-01-session-memory-lifecycle-readback` with Phase 57 acceptance evidence on `docs/Phase57_Local_Memory_Lifecycle_And_Governance_Refresh_验收记录.md`
  - `Phase 57` is closed with `docs/Phase57_Local_Memory_Lifecycle_And_Governance_Refresh_验收记录.md`
  - `P57-MEM-15` is complete on `codex/p57-mem-02-memory-candidate-extraction` with automatic stale invalidation of confirmed doc-derived memory after full `AGENTS.md` refresh
  - `P57-MEM-14` is complete on `codex/p57-mem-02-memory-candidate-extraction` with duplicate confirm handling that expires redundant candidates and reports the matching confirmed memory id
  - `P57-MEM-13` is complete on `codex/p57-mem-02-memory-candidate-extraction` with type-aware review conflict handling so confirmed preferences can coexist while single-active memory types still supersede
  - `P57-MEM-12` is complete on `codex/p57-mem-02-memory-candidate-extraction` with `as_of`-aware freshness filtering for confirmed repo memory lookup
  - `P57-MEM-11` is complete on `codex/p57-mem-02-memory-candidate-extraction` with deterministic `preference` candidate extraction from explicit user message markers
  - `P57-MEM-10` is complete on `codex/p57-mem-02-memory-candidate-extraction` with deterministic `architecture_fact` candidate extraction from root `AGENTS.md` package-boundary rules
  - `P57-MEM-09` is complete on `codex/p57-mem-02-memory-candidate-extraction` with deterministic `project_rule` candidate extraction from successful root `AGENTS.md` reads
  - `P57-MEM-08` is complete on `codex/p57-mem-02-memory-candidate-extraction` with deterministic supersession of older confirmed memories during confirm review plus API/CLI parity coverage
  - `P57-MEM-07` is complete on `codex/p57-mem-02-memory-candidate-extraction` with typed confirmed-memory inputs, deterministic repo-memory ranking, normalized duplicate collapse, and type-aware stable prompt labels
  - `P57-MEM-06` is complete on `codex/p57-mem-02-memory-candidate-extraction` with confirmed repo memory retrieval and stable-section context injection wired across local harness execution paths
  - `P57-MEM-05` is complete on `codex/p57-mem-02-memory-candidate-extraction` with durable confirm and expire controls for session-scoped memory candidates over the local API and CLI
  - `P57-MEM-04` is complete on `codex/p57-mem-02-memory-candidate-extraction` with session-scoped memory inventory readback over the local API and CLI
  - `P57-MEM-03` is complete on `codex/p57-mem-02-memory-candidate-extraction` with deterministic `procedure` memory candidate persistence wired into the worker completion path
  - `P57-MEM-02` is complete on `codex/p57-mem-02-memory-candidate-extraction` with deterministic `procedure` memory candidate extraction from successful `command.run` and `tests.run` session events
  - `P57-MEM-01` is complete on `codex/p57-mem-01-memory-store-foundation` with typed memory models, a core store Port, and a local SQLite memory adapter without making Redis a kernel dependency
  - the next memory follow-up lane is scope-aware review queue and filtering so operators can triage candidate memory before review
  - `P56-CLOSE-01` is complete on `codex/p56-closeout-next-plan` with session resume execute phase-closure evidence on `docs/Phase56_Session_Resume_Execute_CLI_And_Operator_Parity_验收记录.md`
  - `P56-TEST-01` is complete on `codex/p56-test-01-session-resume-execute-contract-matrix` with resume execute parity coverage and CLI-local `database` normalization
  - `P56-CLI-01` is complete on `codex/p56-cli-01-session-resume-execute-parity` with CLI resume execute failure shaping aligned to API resume execution semantics
  - `Phase 56` is closed with `docs/Phase56_Session_Resume_Execute_CLI_And_Operator_Parity_验收记录.md`
  - `P55-CLOSE-01` is complete on `codex/p55-closeout-next-plan` with Phase 55 acceptance evidence and Phase 56 starter tasks
  - Phase 55 is closed with `docs/Phase55_Session_Inspect_CLI_And_Operator_Parity_验收记录.md`
  - `P55-TEST-01` is complete on `codex/p55-test-01-session-inspect-contract-matrix` with session inspect parity coverage and CLI-local `database` normalization
  - `P55-CLI-01` is complete on `codex/p55-cli-01-session-inspect-parity` with CLI inspect approval-context parity alignment
  - `P54-CLOSE-01` is complete on `codex/p54-closeout-next-plan` with Phase 54 acceptance evidence and Phase 55 starter tasks
  - Phase 54 is closed with `docs/Phase54_Session_Artifact_List_CLI_And_Operator_Parity_验收记录.md`
  - `P54-TEST-01` is complete on `codex/p54-test-01-session-artifact-list-contract-matrix` with artifact list parity coverage and CLI-local `database` normalization
  - `P54-CLI-01` is complete on `codex/p54-cli-01-session-artifact-list` with local artifact list inventory plus deterministic empty and missing-session results
  - `P53-CLOSE-01` is complete on `codex/p53-closeout-next-plan` with Phase 53 acceptance evidence and Phase 54 starter tasks
  - Phase 53 is closed with `docs/Phase53_Session_Control_CLI_And_Operator_Parity_验收记录.md`
  - `P53-TEST-01` is complete on `codex/p53-test-01-session-control-contract-matrix` with cancel and suspend parity coverage plus CLI-local normalization
  - `P53-CLI-01` is complete on `codex/p53-cli-01-session-cancel` with restored cancel control and local CLI cancel support
  - `P52-CLOSE-01` is complete on `codex/p52-closeout-next-plan` with Phase 52 acceptance evidence and Phase 53 starter tasks
  - Phase 52 is closed with `docs/Phase52_Session_Message_Append_CLI_And_Operator_Parity_验收记录.md`
  - `P50-CLI-01` is complete on `codex/p50-cli-01-approval-queue-read` with local `approval queue` and `approval inspect` read surfaces
  - `P50-TEST-01` is complete on `codex/p50-test-01-approval-queue-contract-matrix` with approval queue/detail parity coverage and CLI-local `database` normalization
  - Phase 50 is closed with `docs/Phase50_Approval_Queue_CLI_And_Operator_Parity_验收记录.md`
  - `P51-TEST-01` is complete on `codex/p51-test-01-approval-decision-contract-matrix` with approval decision parity coverage and CLI-local `database` normalization
  - Phase 51 is closed with `docs/Phase51_Approval_Decision_Cross_Surface_Parity_验收记录.md`
  - `P52-CLI-01` is complete on `codex/p52-cli-01-session-message-append` with local session message append support
  - `P52-TEST-01` is complete on `codex/p52-test-01-session-message-contract-matrix` with append parity coverage and CLI-local `database` normalization
- Phase 38 shared artifact access audit metadata helper is complete on `codex/p38-obs-01-artifact-access-audit-helper`, centralizing deterministic allow, deny, and prune audit metadata assembly in `agent-security` and reusing it across API read and prune audit paths
- Phase 38 API shared denial-response adoption is complete on `codex/p38-api-01-artifact-denial-response-adoption`, centralizing API read-side deny and unavailable response shaping while preserving the current operator-facing access contract
- Phase 38 is closed with `docs/Phase38_Shared_Artifact_Audit_Metadata_And_Denial_Response_Reuse_验收记录.md`
- Phase 39 CLI shared denial-response adoption is complete on `codex/p39-cli-01-artifact-denial-response-adoption`, extracting a CLI helper path for denied and unavailable artifact read responses while preserving CLI-local `database` context and prune behavior
- Phase 39 failure contract matrix expansion is complete on `codex/p39-test-01-artifact-failure-contract-matrix`, explicitly covering API and CLI parity for detail-denied and content failure envelopes after shared helper adoption
- Phase 39 is closed with `docs/Phase39_CLI_Shared_Denial_Response_Reuse_And_Failure_Contract_Parity_验收记录.md`
- Phase 40 API shared artifact control response adoption is complete on `codex/p40-api-01-artifact-control-response-adoption`, centralizing prune denied and unavailable response construction behind shared API helper paths while preserving current prune contracts
- Phase 40 CLI shared artifact control response adoption is complete on `codex/p40-cli-01-artifact-control-response-adoption`, centralizing prune denied and unavailable response construction behind shared CLI helper paths while preserving current prune contracts
- Phase 40 artifact prune contract matrix expansion is complete on `codex/p40-test-01-artifact-prune-contract-matrix`, explicitly covering API and CLI parity for prune denied and prune unavailable external-reference envelopes
- Phase 40 is closed with `docs/Phase40_Shared_Artifact_Control_Response_Reuse_And_Prune_Contract_Parity_验收记录.md`
- Phase 41 API shared artifact control success projection is complete on `codex/p41-api-01-artifact-control-success-projection`, centralizing prune success response projection behind a shared API helper path while preserving the current success contract
- Phase 41 CLI shared artifact control success projection is complete on `codex/p41-cli-01-artifact-control-success-projection`, centralizing prune success response projection behind a shared CLI helper path while preserving CLI-local `database` context
- Phase 41 artifact prune success contract matrix expansion is complete on `codex/p41-test-01-artifact-prune-success-contract-matrix`, explicitly covering API and CLI parity for `pruned` and `already_pruned` envelopes with stable lifecycle normalization
- Phase 41 is closed with `docs/Phase41_Shared_Artifact_Control_Success_Projection_And_Prune_Success_Parity_验收记录.md`
- Phase 42 shared artifact control audit metadata helper is complete on `codex/p42-obs-01-artifact-control-audit-helper`, centralizing prune denied, success, and unavailable audit payload assembly behind a shared `agent-security` helper boundary
- Phase 42 is closed with `docs/Phase42_Shared_Artifact_Control_Audit_Metadata_Helper_验收记录.md`
- Phase 43 shared artifact audit metadata convergence is complete on `codex/p43-obs-01-artifact-audit-convergence`, converging read-side and control-side audit helper semantics onto one shared lower-level builder while preserving current wrappers and adapter contracts
- Phase 43 is closed with `docs/Phase43_Shared_Artifact_Audit_Metadata_Convergence_验收记录.md`
- Phase 41 CLI shared artifact control success projection is complete on `codex/p41-cli-01-artifact-control-success-projection`, centralizing prune success response projection behind a shared CLI helper path while preserving CLI-local `database` context
- Phase 41 artifact prune success contract matrix expansion is complete on `codex/p41-test-01-artifact-prune-success-contract-matrix`, explicitly covering API and CLI parity for `pruned` and `already_pruned` envelopes with stable lifecycle normalization
- Phase 41 is closed with `docs/Phase41_Shared_Artifact_Control_Success_Projection_And_Prune_Success_Parity_验收记录.md`
- Phase 37 shared artifact access projection serializer is complete on `codex/p37-sec-01-shared-artifact-access-projection`, centralizing access explainability payload assembly and policy-rank evaluation in `agent-security`
- Phase 37 API shared access projection adoption is complete on `codex/p37-api-01-artifact-access-projection-adoption`, replacing API-local access explainability assembly with the shared security projection helper while preserving artifact access and prune contracts
- Phase 37 CLI shared access projection adoption is complete on `codex/p37-cli-01-artifact-access-projection-adoption`, replacing CLI-local access explainability assembly with the shared security projection helper while preserving CLI-only local context fields
- Phase 37 is closed with `docs/Phase37_Shared_Artifact_Access_Projection_And_Adapter_Reuse_验收记录.md`
- Phase 36 shared artifact projection serializer is complete on `codex/p36-sto-01-shared-artifact-projection-serializer`, centralizing payload lookup, lifecycle serialization, retrieval-state serialization, and base artifact envelope assembly in `agent-storage`
- Phase 36 API adapter adoption is complete on `codex/p36-api-01-artifact-projection-adoption`, replacing API-local artifact envelope assembly with the shared storage serializer while preserving access and audit behavior
- Phase 36 CLI adapter adoption is complete on `codex/p36-cli-01-artifact-projection-adoption`, replacing CLI-local artifact envelope assembly with the shared storage serializer while preserving CLI-only local context fields
- Phase 36 is closed with `docs/Phase36_Shared_Artifact_Projection_Serialization_And_Adapter_Reuse_验收记录.md`
- Phase 35 API success-envelope normalization is complete on `codex/p35-api-01-artifact-success-envelope-normalization`, making successful API artifact responses explicit instead of relying on implied 200 semantics
- Phase 35 CLI envelope consistency parity is complete on `codex/p35-cli-01-artifact-envelope-consistency-parity`, aligning inspect success payload shape and pruned-unavailable semantics with the normalized API artifact contract while keeping CLI-only `database` context explicit
- Phase 35 envelope contract matrix expansion is complete on `codex/p35-test-01-artifact-envelope-contract-matrix`, extending cross-surface regression from access parity into shared detail and unavailable envelope structure
- Phase 35 is closed with `docs/Phase35_Artifact_Envelope_Normalization_And_Surface_Consistency_验收记录.md`

## Completed

- `Phase 0 - Repo Bootstrap`
- `Phase 1 - Core Domain`
- `P2-RT-01 - LocalRuntime Process Execution`
- `P2-RT-02 - Workspace And Worktree Abstractions`
- `P2-TOOL-01 - Tool Contracts And Execution Results`
- `P2-TOOL-02 - Builtin File Read Path`
- `P2-TOOL-03 - Builtin Command Execution Path`
- `P2-TOOL-04 - Builtin Patch Apply Path`
- `P2-TOOL-05 - Builtin Validation Commands`
- `P2-IT-01 - Local Toolchain Integration Flow`
- `P2-GIT-01 - Readonly Git Inspection Tools`
- `P3-HAR-01 - Harness Loop Skeleton`
- `P3-MOD-01 - Mock Model Gateway`
- `P3-HAR-02 - Single Attempt Tool Orchestration`
- `P3-HAR-03 - Structured Run Output And Retry Skeleton`
- `P3-HAR-04 - Multi-Attempt Loop Driver`
- `P3-HAR-05 - Assistant Message And Tool Trace Projection`
- `P3-HAR-06 - Attempt Event Timestamp Refinement`
- `P3-HAR-07 - Planner And Verifier Hooks`
- `P3-HAR-08 - Session Event Builder Cleanup`
- `P3-HAR-09 - Tool Call Selection Strategy`
- `P3-HAR-10 - Explicit Harness Budgets`
- `P4-STO-01 - SQLite Event Store And Session Projection`
- `P4-STO-02 - Event Idempotency Protection`
- `P4-WKR-01 - Worker Recovery Entry`
- `P4-SCH-01 - SQLite Worker Leases`
- `P4-WKR-02 - Worker Claim And Resume Flow`
- `P4-GOV-01 - Core Event Schema Drafts`
- `P4-GOV-02 - Event Schema Enforcement`
- `P4-STO-03 - Incremental Event Replay`
- `P4-WKR-03 - Explicit Resume Entry`
- `P4-STO-04 - Tool Run Index`
- `P4-STO-05 - Model Call Index`
- `P5-CTX-01 - Context Compiler Bootstrap`
- `P5-CTX-02 - Related Files Recall And Ranking Split`
- `P5-CTX-03 - Conversation And Tool Output Compaction`
- `P5-CTX-04 - Prompt Layout And Cache Key Rules`
- `P5-CTX-05 - Trust Marking And Prompt-Injection Baseline`
- `P5-CTX-06 - Harness Context Input Wiring`
- `P5-CTX-07 - Runtime Evidence Context Injection`
- `P5-CTX-08 - Attempt Evidence Feedback Loop`
- `P5-CTX-09 - Structured Planner And Verifier Evidence`
- `P5-CTX-10 - Context-Aware Retry Plan Hint`
- `P5-CTX-11 - Context Compiler Acceptance Hardening`
- `P5-CTX-12 - Phase 5 Closeout Record`
- `P6-POL-01 - Local Policy Profiles`
- `P6-POL-02 - Command Risk Rules`
- `P6-POL-03 - Path Risk Rules`
- `P6-POL-04 - Sensitive Output Rules`
- `P6-POL-05 - Approval Request Model`
- `P6-POL-06 - Approval Event Wiring`
- `P6-POL-07 - Approval Decision Projection`
- `P6-POL-08 - Approval Service Entry`
- `P6-POL-09 - Phase 6 Closeout Record`
- `P7-OBS-01 - Observability Models Bootstrap`
- `P7-OBS-02 - Local Trace JSONL Store`
- `P7-OBS-03 - Local Replay Runner`
- `P7-EVAL-01 - Eval Case And Grader Bootstrap`
- `P7-EVAL-02 - Local Eval Runner`
- `P7-EVAL-03 - Baseline Eval Case Expansion`
- `P7-EVAL-04 - Local Release Gate Baseline`
- `P7-EVAL-05 - Eval Release Check Integration`
- `P7-EVAL-06 - Phase 7 Closeout Record`
- `P8-CLI-01 - CLI Command Skeleton`
- `P8-CLI-02 - CLI Run Local Session Creation`
- `P8-CLI-03 - CLI Inspect And Resume Session Read`
- `P8-CLI-04 - CLI Approve Local Decision`
- `P8-API-01 - API Health And Session Foundation`
- `P8-API-02 - API Route Adapter`
- `P8-CONFIG-01 - Local Settings Loader`
- `P8-CONFIG-02 - Entry Point Settings Wiring`
- `P8-API-03 - FastAPI Serving Foundation`
- `P8-API-04 - Session Stream Foundation`
- `P8-DOC-01 - Operator Runbook`
- `P8-API-05 - Local API Auth Foundation`
- `P8-MOD-01 - OpenAI-Compatible Model Gateway Adapter`
- `P8-MOD-02 - CLI Model Gateway Smoke`
- `P8-CLI-05 - CLI Durable Run Execution`
- `P8-API-06 - API Session Create And Execute`
- `P8-QUE-01 - Queued Session Bootstrap Events`
- `P8-WKR-04 - Worker Execute Ready Session`
- `P8-CLI-06 - CLI Resume Execute Trigger`
- `P8-API-07 - API Resume Execute Trigger`
- `P8-WKR-05 - Worker Ready Session Loop`
- `P8-INT-01 - Phase 8 Mainline Alignment`
- `P8-CLOSE-01 - Phase 8 Closeout Record`
- `P9-API-01 - Session Messages Entry`
- `P9-API-02 - Cancel And Suspend Entry`
- `P9-API-03 - Approval HTTP Entry`
- `P9-WKR-01 - Worker Continuous Loop Behavior`
- `P9-CLOSE-01 - Phase 9 Closeout And Phase 10 Planning`
- `P10-API-01 - Session Diff Read API`
- `P10-API-02 - Session Artifacts Read API`
- `P10-API-03 - Session Commit API`
- `P10-API-04 - Session Pull Request API`
- `P10-CLOSE-01 - Phase 10 Closeout And Phase 11 Planning`
- `P11-API-01 - Side Effect Idempotency Keys`
- `P11-OBS-01 - Delivery Audit Events`
- `P11-INT-01 - GitHub Pull Request Provider Skeleton`
- `P11-CLOSE-01 - Phase 11 Closeout And Phase 12 Planning`
- `P12-CONFIG-01 - SCM Provider Settings`
- `P12-INT-01 - Pull Request Gateway Selection`
- `P12-API-01 - Delivery Audit Read API`
- `P12-CLOSE-01 - Phase 12 Closeout And Phase 13 Planning`
- `P13-API-01 - API Composition Split`
- `P13-SEC-01 - SCM Credential Boundary Draft`
- `P13-INT-01 - Guarded GitHub Pull Request Execution`
- `P13-CLOSE-01 - Phase 13 Closeout And Phase 14 Planning`
- `P14-OBS-01 - SCM Execution Audit Hardening`
- `P14-SEC-01 - SCM Token Redaction Regression Gate`
- `P14-DOC-01 - Remote SCM Operator Safety Runbook`
- `P14-CLOSE-01 - Phase 14 Closeout And Next Planning`
- `P15-SEC-01 - Credential Capability Domain Model`
- `P15-SEC-02 - Credential Broker Port`
- `P15-INT-01 - SCM Broker Lookup Adapter`
- `P15-CLOSE-01 - Phase 15 Closeout And Next Planning`
- `P16-SEC-01 - Local Environment Credential Broker`
- `P16-APP-01 - API Credential Broker Composition`
- `P16-CLOSE-01 - Phase 16 Closeout And Next Planning`
- `P17-APP-01 - API Default Environment Broker Factory`
- `P17-INT-01 - SCM Env Fallback Boundary`
- `P17-DOC-01 - Broker-Backed SCM Operator Docs`
- `P17-CLOSE-01 - Phase 17 Closeout And Next Planning`

## Current Focus

- Phase 11 is now closed with idempotency, delivery audit, and GitHub PR provider skeleton complete
- remote SCM execution is still not wired to the API and remains an explicit future task
- Phase 12 is now closed with SCM settings, gateway selection, and delivery audit read API complete
- `apps/api/src/zebra_agent_api/app.py` has been reduced from 489 to 384 lines by moving read-only session APIs into `session_read.py`
- SCM credential boundary now separates token environment names from token values and provides deterministic redaction
- guarded GitHub PR execution now requires explicit GitHub provider, dry-run disablement, token availability, and full-access policy
- SCM execution audit metadata now normalizes provider, status, URL, commit SHA, dry-run flag, and unavailable reasons without token values
- SCM token redaction regression coverage now checks PR plans, API responses, delivery audit records, and settings snapshots
- remote SCM operator safety runbook now documents dry-run first, explicit opt-in, token rules, audit inspection, and rollback steps
- Phase 14 is closed with `docs/Phase14_SCM_Execution_Hardening_验收记录.md`
- credential capability domain model now covers provider, audience, scopes, expiry, and redacted serialization
- credential broker Port now defines SCM credential requests, in-memory test broker, and missing/denied/unavailable errors
- SCM gateway construction can use broker-issued capabilities for GitHub non-dry-run execution while preserving local-only and dry-run defaults
- Phase 15 is closed with `docs/Phase15_Credential_Broker_Foundation_验收记录.md`
- local environment credential broker can issue scoped capabilities from configured env var names without leaking token values in repr or redacted snapshots
- API pull-request composition can inject a broker and fake GitHub transport for broker-backed non-dry-run execution tests
- Phase 16 is closed with `docs/Phase16_Local_Credential_Backend_And_API_Wiring_验收记录.md`
- API composition now builds a default environment broker from GitHub SCM settings when explicit broker injection is not supplied
- direct SCM env fallback is now disabled by default and requires explicit `allow_env_token_fallback=True`
- broker-backed SCM operator docs now describe default environment broker execution, token handling, audit inspection, and fallback boundary
- Phase 17 is closed with `docs/Phase17_Credential_Backend_Hardening_验收记录.md`
- SCM delivery audit now records non-secret credential source and backend metadata for broker-backed and explicit fallback GitHub PR execution paths
- broker-missing failures now carry credential-source audit metadata without exposing token values
- SCM delivery audit now classifies credential_missing, credential_denied, credential_unavailable, and transport_failure for operator remediation
- Phase 18 is closed with `docs/Phase18_SCM_Audit_Observability_验收记录.md`
- secret-store Port and redaction contract now exist in `agent-security` for future non-environment broker backends
- local secret-store backend now reads per-handle secret documents through the Port and keeps raw values out of repr and redacted snapshots
- GitHub App credential broker skeleton now retrieves private-key material through `SecretStore` and preserves failure classification across integration and API audit paths
- Phase 19 is closed with `docs/Phase19_Secret_Store_And_Broker_Credentials_验收记录.md`
- deterministic network-profile contracts now exist in `agent-security`, including fail-closed defaulting and explicit validation for `domain-allowlist`
- GitHub PR execution now blocks direct remote transport by default and records `egress_policy` metadata when the configured network profile disallows the target host
- operator runbook now documents egress profiles, safe-default examples, and remediation paths that distinguish `egress_policy` from credential and transport failures
- Phase 20 is closed with `docs/Phase20_Egress_Control_Foundations_验收记录.md`
- SCM proxy transport contracts now exist in `agent-integrations`, including deterministic serializable request and response models separate from the direct GitHub HTTP path
- GitHub PR execution can now use a proxy-backed adapter selected by environment while preserving direct-path guards and failure classification
- MCP proxy starter contracts now exist for `mcp.<server>.<tool>` calls, along with policy-facing egress metadata that distinguishes local tool paths from proxy-routable MCP paths
- operator runbook now documents proxy-backed SCM transport selection, MCP proxy starter routing, proxy-specific remediation, and rollback to safe defaults
- Phase 21 is closed with `docs/Phase21_Proxy_Egress_Contracts_验收记录.md`
- `ToolExecutor` now supports MCP proxy gateway execution for `mcp.<server>.<tool>` calls without changing builtin local tool behavior
- proxy-backed SCM audit and MCP proxy tool execution now share stable `route`, `proxy_target`, and `proxy_transport` metadata fields
- local policy evaluation now classifies MCP tools into deterministic local, proxy-routed approval, or fail-closed blocked outputs
- approval request payloads now project route, target, and network-profile scope for proxy-aware operator decisions
- proxy gateway operator guidance is now split into `docs/proxy_gateway_operator_runbook.md`, and the main operator runbook links to it instead of growing beyond the markdown file-size limit
- Phase 22 is closed with `docs/Phase22_Proxy_Execution_And_Gateway_Wiring_验收记录.md`
- harness policy and approval events can now persist proxy route, target, network-profile, and scope metadata without changing existing local-only payloads
- operator-facing session reads and approval decision responses now expose proxy-safe `approval_context` derived from the latest `approval_requested` event
- harness trace projection and API trace serialization now normalize proxy approval metadata with the same `route`, `target`, `network_profile`, and `scope` vocabulary used by policy and execution layers
- Phase 23 is closed with `docs/Phase23_Proxy_Approval_Projection_And_Operator_Readback_验收记录.md`
- session projections and SQLite projection storage now persist durable `approval_context` state for proxy-aware approval requests
- operator-facing approval queue and approval detail reads are now projection-backed and no longer depend on raw event replay
- projection rebuild, durable SQLite projection rows, and repeated approval reads now hold the same `route`, `target`, `network_profile`, and `scope` vocabulary for proxy-aware approval context
- Phase 24 is closed with `docs/Phase24_Durable_Approval_Projection_And_Operator_Queue_验收记录.md`
- durable workspace projection state now persists `workspace_root`, `policy_profile`, lifecycle status, sequence, and last attempt number for later snapshot or resume wiring
- runtime contracts now model `provision`, `snapshot`, `restore`, `fork`, `suspend`, and `resume`, with `RuntimeSnapshot` carrying explicit local snapshot metadata
- worker recovery, resume, and execution now reuse durable workspace projection state and keep workspace lifecycle rows aligned with emitted worker events
- Phase 25 is closed with `docs/Phase25_Durable_Workspace_And_Snapshot_Foundations_验收记录.md`
- local runtime now supports filesystem-backed snapshot, restore, and fork flows for workspace-backed handles with deterministic per-handle retention
- local snapshot behavior is documented in `docs/local_snapshot_runtime.md`, including supported subset, storage layout, retention, and explicit unsupported paths
- session control now emits durable suspend and resume lifecycle events, persists snapshot metadata in workspace projections, and restores suspended local workspaces before worker execution resumes
- CLI `suspend`, API `POST /sessions/{id}/suspend`, and worker resume execution now share the same local snapshot-backed control-plane behavior
- Phase 26 is closed with `docs/Phase26_Local_Snapshot_Operator_Controls_验收记录.md`
- session read APIs now expose projection-backed workspace lifecycle state and snapshot metadata for operator inspection without replay-only fallback
- CLI inspect and resume-read surfaces now expose the same durable workspace lifecycle state and suspended snapshot metadata for local operators
- local snapshot inspect and cleanup now classify retained payloads as valid, missing, or incompatible through manifest-aware checks
- worker restore paths now fail closed on incompatible retained snapshots and explicitly clean consumed snapshot payloads after successful restore
- Phase 27 is closed with `docs/Phase27_Workspace_Lifecycle_Readback_And_Snapshot_Housekeeping_验收记录.md`
- durable local artifact payload storage now exists with SQLite-backed metadata, file-backed payload retention, and explicit missing-payload inspection
- worker execution now persists supported text tool outputs into the durable artifact payload store and rewrites local artifact refs to those retained payloads when no explicit artifact URI exists
- session artifact read APIs now expose artifact detail and base64 content retrieval with explicit `indexed_only`, `payload_available`, `payload_missing`, and `external_reference` semantics
- Phase 28 is closed with `docs/Phase28_Durable_Artifact_Storage_And_Retrieval_验收记录.md`
- CLI now exposes `artifact inspect` and `artifact read` commands with machine-readable retrieval-state and base64 content output for local artifact inspection
- artifact list and detail previews now expose explicit `preview_state`, and artifact detail/content reads now emit delivery-audit records keyed by session and artifact identifier
- durable artifact payload metadata now records explicit lifecycle state plus optional retention and prune timestamps
- durable artifact payload inspection now distinguishes `available`, `missing`, and `pruned` states without changing existing retrieval contracts
- Phase 29 is closed with `docs/Phase29_Artifact_Governance_And_Operator_Parity_验收记录.md`
- artifact retention policy contracts now exist in `agent-core`, and `agent-security` now maps policy profiles to deterministic local retention defaults plus `retained_until` calculation helpers
- artifact payload storage now supports deterministic expiry sweep and idempotent prune behavior for retained local payloads
- artifact list and detail reads now expose additive lifecycle metadata, and artifact content reads distinguish pruned payloads from generic missing payloads
- Phase 30 is closed with `docs/Phase30_Local_Artifact_Retention_Enforcement_验收记录.md`
- artifact access contracts now distinguish `operator_safe`, `sensitive`, and `restricted` classes, and security mapping now derives deterministic policy-facing defaults for local artifact controls
- API and CLI now expose manual artifact prune controls with idempotent managed-payload semantics and policy-aware handling for sensitive artifact classes
- Phase 31 is closed with `docs/Phase31_Artifact_Operator_Controls_And_Access_Foundations_验收记录.md`
- artifact detail and content reads now enforce access classes, CLI artifact actions now share the same access gates, and audit metadata now distinguishes allowed, denied, and unavailable artifact actions by class and result
- Phase 32 is closed with `docs/Phase32_Artifact_Access_Enforcement_And_Audit_Parity_验收记录.md`
- artifact API and CLI read surfaces now project additive access explainability metadata, and operator guidance now documents denied versus unavailable artifact remediation
- Phase 33 is closed with `docs/Phase33_Artifact_Access_Explainability_And_Operator_Guidance_验收记录.md`
- Phase 34 API consolidation is complete on `codex/p34-api-01-artifact-access-consolidation`, centralizing artifact access response assembly and audit metadata for API read surfaces while preserving the Phase 33 additive contract
- Phase 34 CLI shared projection reuse is complete on `codex/p34-cli-01-artifact-access-cli-shared-projection`, aligning denied and unavailable CLI artifact responses with the same additive access vocabulary used by the API
- Phase 34 cross-surface regression matrix is complete on `codex/p34-test-01-artifact-access-contract-matrix`, locking API and CLI access payload parity across allowed, denied, and unavailable paths
- Phase 34 is closed with `docs/Phase34_Artifact_Access_Consolidation_And_Contract_Hardening_验收记录.md`

## Next Unlocks

- Phase 125 merged through PR `#87`; `P125-CLOSE-01` records the closeout and unlocks one bounded Web Search Gateway slice
- `P126-WEB-01 - Bounded Web Search Gateway` is ready and is the only Phase 126 implementation lane
- Phase 123 merged through PR `#83`; `P123-CLOSE-01` records the closeout and unlocks one durable clarification HITL slice
- general, coding, and fixed Research child profiles now expose one typed, read-only, parallel-safe `files.search` primitive with literal content and filename modes, workspace-relative roots, optional glob filtering, and deterministic offset pagination
- workspace search rejects hidden or escaping roots and skips hidden, symlinked, binary, and oversized files while enforcing 20,000-file, 10,101-match, 500-character-line, 100-result, and 32 KiB output ceilings
- Phase 123 acceptance passed 52 focused tests, all 1,034 backend tests, Ruff, MyPy across 226 source files, the 8-case eval release gate, and one real `deepseek-v4-flash` `files.search -> files.read` run with a grounded final answer
- `P35-API-01 - Artifact Success Envelope Normalization` is complete on `codex/p35-api-01-artifact-success-envelope-normalization`
- `P35-CLI-01 - Artifact Envelope Consistency Parity` is complete on `codex/p35-cli-01-artifact-envelope-consistency-parity`
- `P44-TEST-01 - Artifact Audit Metadata Contract Coverage` is complete on `codex/p44-test-01-artifact-audit-contract-coverage`
- artifact delivery-audit regression coverage now locks one read-side denied path and one control-side success path, preserving the current `reason`, `retrieval_status`, `payload_artifact_id`, and `lifecycle_status` metadata boundaries while treating `created_at` as the only normalized non-deterministic field
- Phase 44 is closed with `docs/Phase44_Artifact_Audit_Metadata_Contract_Coverage_验收记录.md`
- `P45-CLI-01 - Delivery Audit CLI Read Surface` is complete on `codex/p45-cli-01-delivery-audit-read`
- CLI now exposes local session delivery-audit inspection with explicit `ok`, `not_found`, and empty-history semantics aligned to the existing API read surface
- `P45-TEST-01 - Delivery Audit Cross-Surface Contract Matrix` is complete on `codex/p45-test-01-delivery-audit-contract-matrix`
- delivery-audit parity rules are now locked through a shared contract matrix that normalizes CLI-local context fields while asserting stable API and CLI agreement on shared audit payload semantics
- Phase 45 is closed with `docs/Phase45_Delivery_Audit_CLI_And_Operator_Parity_验收记录.md`
- `P46-CLI-01 - Session Diff CLI Read Surface` is complete on `codex/p46-cli-01-session-diff-read`
- local operators can now inspect one session workspace diff from the CLI with explicit `ok`, `not_found`, and `diff_unavailable` semantics plus stable `clean`, `git_status`, and unified `diff` fields
- `P46-TEST-01 - Session Diff Cross-Surface Contract Matrix` is complete on `codex/p46-test-01-session-diff-contract-matrix`
- session diff parity rules are now locked through a shared contract matrix covering dirty, clean, missing-session, and non-git diff reads while treating CLI-local `database` context as a CLI-only field
- Phase 46 is closed with `docs/Phase46_Session_Diff_CLI_And_Operator_Parity_验收记录.md`
- `P47-CLI-01 - Session Stream CLI Read Surface` is complete on `codex/p47-cli-01-session-stream-read`
- local operators can now inspect one persisted session event stream from the CLI with explicit `ok` and `not_found` semantics plus ordered event payload replay
- `P47-TEST-01 - Session Stream Cross-Surface Contract Matrix` is complete on `codex/p47-test-01-session-stream-contract-matrix`
- session stream parity rules are now locked through a shared contract matrix covering populated replay, bootstrap-only replay, and missing-session reads while treating SSE framing and CLI-local `database` context as transport-specific fields
- Phase 47 is closed with `docs/Phase47_Session_Stream_CLI_And_Operator_Parity_验收记录.md`
- `P48-CLI-01 - Session Commit CLI Delivery Surface` is complete on `codex/p48-cli-01-session-commit-read`
- local operators can now create one session commit from the CLI with explicit committed, policy-blocked, unavailable, missing-session, invalid-request, and idempotent replay semantics
- `P48-TEST-01 - Session Commit Cross-Surface Contract Matrix` is complete on `codex/p48-test-01-session-commit-contract-matrix`
- session commit parity rules are now locked through a shared contract matrix covering committed success, policy-blocked, clean-workspace unavailable, missing-session, and cross-surface idempotent replay while treating CLI-local `database` context as transport-specific
- Phase 48 is closed with `docs/Phase48_Session_Commit_CLI_And_Operator_Parity_验收记录.md`
- `P49-CLI-01 - Session Pull Request CLI Delivery Surface` is complete on `codex/p49-cli-01-session-pull-request-read`
- local operators can now open one session pull request from the CLI with explicit dry-run, created, unavailable, policy-blocked, missing-session, invalid-request, and idempotent replay semantics
- `P49-TEST-01 - Session Pull Request Cross-Surface Contract Matrix` is complete on `codex/p49-test-01-session-pull-request-contract-matrix`
- session pull-request parity rules are now locked through a shared contract matrix covering dry-run, created, policy-blocked, unavailable, missing-session, and cross-surface idempotent replay while treating CLI-local `database` context as transport-specific
- Phase 49 is closed with `docs/Phase49_Session_Pull_Request_CLI_And_Operator_Parity_验收记录.md`
- `P50-CLI-01 - Approval Queue CLI Read Surface` is ready on `codex/p50-cli-01-approval-queue-read`
- `P50-TEST-01 - Approval Queue Cross-Surface Contract Matrix` is locked behind the CLI read surface
- `P50-CLOSE-01 - Phase 50 Closeout And Next Planning` is the documentation closeout lane for approval queue operator parity

## Active Documents

Read in this order for implementation work:

1. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
2. `docs/实施任务拆解与阶段验收.md`
3. `docs/02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
4. `docs/AGENT_TASKS.md`
5. `AGENTS.md`
6. `README.md`

## Validation Baseline

- Default commands:
  - `make sync`
  - `make test`
  - `make check`
- Phase 2 slices should also carry targeted `pytest`, `ruff`, and `mypy` evidence in `WORKLOG.md` or the merge commit context.

## Notes

- `WORKLOG.md` is the session log. It replaces the old lowercase `progress.md` name because macOS default filesystems are case-insensitive and cannot safely hold both `PROGRESS.md` and `progress.md`.

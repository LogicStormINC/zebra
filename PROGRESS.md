# Zebra Agent Project Status

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Current Mainline Snapshot

- Snapshot date: `2026-08-13`
- Wave 4 = CLOSED. Final pair: FinOS `6e84e23b22d11a1f89afa9d73e8f17c9e47382a5`
  / Zebra `da97dc3ac9ffe300076f4c68031b96a627e6dd58`, both ahead-only from
  `f839149` / `314e6be`, with `codex/finos-next` and `codex/finos-runtime-next`
  untouched. Independent audit: PASS with one P3 governance correction
  (`P3-GOV-01`), fixed by the Wave 4.5 docs-only commit.
- Wave 4.5 = GO, Phases 0 and 2 complete on `codex/znx-wave45-task-ui-foundation-v1`
  from exact base `da97dc3`; `ZNX-TEVID-01` is `Done` and
  `ZNX-UI-FOUNDATION-01` is registered (owned paths, non-goals, FinOS peer
  coordination). Phase 2 extracted the proven generic Task UI surface into the
  shared `@zebra-agent/task-ui@0.1.0` package (no Tauri dependency, no FinOS
  business types, one reducer per Task, extension slots) and rewired Zebra
  Desktop onto it with the old lib/component duplicates deleted. Contract
  commit `3a385d2` added public `approval_id` to raw `approval_requested`,
  pinned by fixture and acknowledged by the FinOS peer (Phase 1 landed at
  FinOS `84f81ba`). Desktop checks 21/21, build +0.2% vs base, E2E failures
  identical to exact base.
  Gate A runtime closure landed on the same branch: tool-capable model
  streams now emit deltas progressively (browsers render mid-stream), cancel
  stays authoritative (no late failed/completed), and provider failures are
  classified durably — non-retryable rejections -> `failed`, retryable
  HTTP 500/transport -> `suspended` with lease released and normalized-only
  payloads. Playwright E2E is now 8/8 (was 3/5 at base); full pytest
  `2199 passed, 8 failed, 9 skipped` (one inherited failure fixed, zero new);
  eval 10/10; bundle unchanged from Phase 2.
- Gate A is the Wave 5 start gate; Wave 5 remains frozen. No PR, merge, push,
  or deploy until the owner authorizes.
- Snapshot date: `2026-08-11`
- `Wave 2.5 / Goal-Plan v1 = Product Acceptance PASS`. The activation closure
  on `codex/znx-goal-plan-act-01` adds two independent, generic Stable Task
  contracts: strict default-false `plan_required`, and the existing
  `completion_contract.required_evidence`. A real DeepSeek two-round Goal
  produced Plan revisions before authoritative FinOS typed reads, closed the
  Plan, completed, then preserved the same Stable Task, stable Goal, evidence,
  and Plan revision continuity on follow-up. Terminal publication and worker
  lease release now share one SQLite completion transaction, so immediate
  follow-up no longer races a visible `SESSION_COMPLETED`. Post-hotfix targeted
  tests are `117 passed`; full pytest is `2110 passed, 9 failed, 9 skipped` with
  the exact-base failure set; eval is `10/10`, and static/file-size findings are
  unchanged inherited sets. Gate 2 real dual-repository E2E is `1 passed`.
  No Planner, fixed financial Plan, new permission, GUI, or deployment was added.
- `ZNX-GOALPLAN-01` closes the existing Plan lifecycle on
  `codex/znx-goal-plan-v1` from exact base `0a81c6d`, then combines cleanly with
  Gate 2 at `aa8c4d5`. Stable Task now projects its root Goal and latest mutable
  durable Plan, reconstructs both for continuation/retry/resume/worker paths,
  and rejects normal completion while Plan steps remain open. Closed Plans do
  not fabricate Goal success, and no-Plan one-shot tasks remain compatible.
  Goal/Plan plus Gate 2 targeted validation is `136 passed`; full pytest is
  `2085 passed, 9 failed, 9 skipped` with the exact-base failure set. Release
  eval is `10/10`; changed-path Ruff/compileall/diff-check pass. Full Ruff is
  11 inherited findings versus 13 at exact base, while Mypy and file-size retain
  the same 13 inherited findings. FinOS compatibility smoke is `23 passed`; no
  regression appeared in the real dual-repository Gate 2 E2E (`1 passed`). No
  FinOS source, stable branch, GUI, provider, or deployment change was made.
- AOR-DEF-01 follow-up review closes durable continuation evidence,
  shared capability preflight, and trusted skill scope/state/content-digest
  checks; focused follow-up tests are 70 passed and no deployment occurred.
- AOR-DEF-01 P0 validator evidence correction now uses only canonical,
  successful validator terminal evidence; focused P0/current regressions pass,
  with the same exact-base full-suite failures and static gates.
- Governance review correction: the exact base-to-HEAD union is 42 tracked
  paths (41 implementation/test/record paths plus the task-card path); the
  task card now names the API binding and skill catalog paths explicitly.
- Active local slice: `AOR-DEF-01` is implemented on
  `codex/agent-definition-completion-contract-20260802` from exact base
  `c5b814500bbeebea0d4a0307f9a58c903bd5320f`. It adds a versioned,
  provider-neutral AgentDefinition and typed completion-evidence gate, with
  trusted local context resolution and durable handoff propagation. Focused
  and relevant regressions pass; the exact-base full-suite failures and static
  gates remain recorded in its development-version record. No deployment or
  upstream synchronization was performed.
- Active unmerged slice: `MM-NATIVE-QWEN-PHASE1` is a docs-first generic
  model-media contract on `codex/qwen-native-multimodal` from
  `c3cc79c3a54f8a0be3a933bbcc43628bf82210ba`. It is limited to provider-neutral
  artifact references, fail-closed capability gates, Qwen's OpenAI-compatible
  adapter/configuration, and always-replay continuity. Deterministic validation
  is at the known baseline (`1870 passed, 9 inherited failures, 9 skipped`);
  the one authorized live Qwen smoke reached the configured private endpoint
  but returned normalized `authentication_failed`, so neither real-provider nor
  FinOS E2E acceptance is claimed. Legacy MiniMax remains available only when
  native media is not selected.
- Review stacked slice: `MDL-PROFILE-02` is implemented on
  `vinson1101/zebra:codex/generic-model-profile-v2` at `4533cf4`. It replaces
  the Phase 1 exact Qwen Flash model-name gate with an explicit verified profile
  selection while reusing the existing Core `ModelMediaCapabilities`.
  Implementation `cf0dff9` passes `46` focused tests and changed-source
  Ruff/Mypy; full pytest is `1900 passed, 9 skipped, 9 inherited failures`.
  It does not add a provider factory, automatic routing/fallback, UI, FinOS
  behavior, deployment, upstream push, or PR.
- Review stacked task: `HAR-CONV-01` is implemented on
  `codex/runtime-convergence-phase1`, based on PR `#198` plus current
  `origin/main`. It extends exact action repetition checks with stable evidence
  progress, bounded no-progress detection, and one tool-disabled terminal
  synthesis. Post-review repairs preserve mixed-batch work, ignore volatile
  artifact URIs, keep internal convergence instructions out of the user tail,
  propagate `tool_loop_no_progress`, and reject raw DSML tool requests as final
  answers. `70` focused regressions and touched-file Ruff/Mypy pass; full tests
  are `1763 passed, 9 inherited failures, 8 skipped`. A provider-neutral live
  replay now typed-suspends instead of looping or falsely completing, but it did
  not output the required transaction log; the Runtime guard passed while the A
  line business gate failed. FinOS image/MiniMax acceptance is separate. The
  branch is not authorized to merge directly to `main`.
- Review stacked task: `CTX-REHYDRATE-02` is the completed Phase 1.5
  completion slice on `codex/context-rehydrate-phase1-5`. It must reuse existing
  Capsule/ledger/projection/rehydration paths through the Core Port boundary,
  perform at most one recovered tool-disabled synthesis, and make the fixed text
  A line produce the complete log. The first pure A-line live replay exposed one
  additional P1 in the same phase: a correctly denied `web.fetch` URL containing
  a fragment was treated as terminal `retry_exhausted` instead of a correctable
  failed-tool observation. `HAR-CONV-01-POLICY-RECOVERY` therefore adds one
  explicitly classified, same-Attempt correction for read-only input validation;
  every unmarked, authority, side-effect, credential, boundary or human deny stays
  terminal/waiting. Local validation is `71` focused and `1773 passed, 9 inherited
  failures, 8 skipped` full-suite. The resulting live Segment now completes with an
  8,655-character structured log, but the confirmation follow-up exposed a separate
  `CTX-SEG-02-FOLLOWUP-REHYDRATE` P1: rollover succeeded, while the child received
  only the truncated checkpoint and returned 167 characters asking again for known
  trade details. Sync API/Worker active-Capsule parity and projection-first handoff
  were implemented locally, but the next isolated acceptance proved the content path
  still incomplete: the active 14,118-character Capsule compiled to only 427
  characters, with every required fact after character 12,000 absent. The source
  final was a non-self-contained 387-character completion notice, and the child
  falsely completed with a 311-character prefixed raw DSML tool request. The locked
  repair uses `max(task.context_token_budget,
  ModelContextWindow.compaction_reserve_tokens)` for active-projection continuity,
  removes fixed character limits and `plan`-as-conversation, strengthens the
  self-contained synthesis instruction, and rejects any unfenced DSML tool grammar.
  That repair passes `43` core and `36` API/Worker focused regressions, touched-file
  Ruff and Mypy, with the full suite at `1783 passed, 9 inherited failures, 8 skipped`.
  The next isolated live replay produced a 7,757-character initial structured log and
  proved the child compiled the complete 14,118-character active projection, including
  facts after character 12,000. After the exact user confirmation, however, the child
  still called `files.list`, repeated the already answered `agent.clarify`, and entered
  `waiting_input`. Pro therefore locked route A for the remaining P1: latest user
  follow-up must resolve the matching recovered pending clarification before new
  planning/tool exploration; ordinary follow-ups keep normal tool capability.
  Route A is now implemented only for active-projection terminal follow-ups and
  passes the final live gate: the clarification continuation produced an 8,536-character
  log, then the completed Task rolled over and its child produced a 6,686-character,
  261-line self-contained log in two model calls with no repeated clarification,
  waiting state, DSML or business write. Current validation is `80` related tests,
  touched-file Ruff, Mypy over `19` source files and `git diff --check`; the full suite
  is `1784 passed, 9 inherited failures, 8 skipped`. ChatGPT Pro marked Business and
  Runtime gates PASS. One harmless read-only `files.list` is optional P2 optimization.
  The A-line fixture is already recognized OCR text; Zebra image recognition remains
  outside this lane. Full Memory 2.0, Policy relaxation, new Worker architecture /
  Storage schema and direct merge to `main` remain out of scope.
- Review task: `CTX-MEM-01` is in PR `#198` and closes the valid parts of GitHub issue `#197` with
  an exact three-user-turn tail, complete tool groups, one strict retry from
  original history, recoverable context suspension, evidence-gated memory
  promotion, and repo-scoped SQLite FTS recall under a token budget. Local
  validation: `63` focused tests, changed-file Ruff, Mypy over `158` source
  files, and release eval `10/10` pass. Full suite: `1747 passed, 8 skipped`;
  the same nine failures reproduce on untouched `main`. `make check` is blocked
  only by two inherited file-size violations outside this task. PR CI run
  `30332213200` did not execute any step because GitHub reported an account
  payment/spending-limit gate.
- Verified implementation baseline: `f1e4965` (PR `#174`)
- Product posture: `embeddable Agent Runtime / feature-complete local Beta / single-host Phase A complete`
- Review task: `CTX-SEG-01` has delivered the stable Task, internal Segment,
  unified stream/routing, automatic safe rollover, and SQLite migration slice.
- `CTX-SEG-02` is merged for short terminal follow-ups and budget recovery; the
  long-context projection regression is reopened narrowly as
  `CTX-SEG-02-FOLLOWUP-REHYDRATE` under the active Phase 1.5 branch.
- Review task: `SUBAGENT-UX-01` makes Subagent use a model-native tool decision;
  simple work remains in the parent and every valid delegation records its reason.
- Active architecture task: ADR-013 replaces user-visible child Sessions with a
  stable Task boundary and backend-internal execution Segments.
- Desktop browser task: `QA-DESKTOP-E2E-01` is Done via PR `#161`
- Runtime blueprint: `ARCH-RT-BP-01` is complete on its local task branch
- Locked architecture tasks: ACP entry and optional code intelligence
- Open runtime issue: `#197` is under review in PR `#198`; the separate execution
  convergence gap is tracked by `HAR-CONV-01`. Product issue `#148` remains closed
  through PR `#156`.
- Review task: `WEB-UX-01` makes explicit `local + trusted-local` execution
  non-interactive across Desktop/API/CLI/Worker, including existing Tasks, while
  retaining fail-closed non-local defaults and hard Gateway/Runtime boundaries.
- Active extension task: `EXT-0` registers the Skill/MCP/Plugin extension
  control-plane contract (`ADR-014`, merged via PR `#180`); the **EXT-1 Skill v2
  epic is complete** — `EXT-SKILL-01..05` are `Done` (metadata v2,
  scope/namespace/digest, task-level skill-component snapshot +
  handoff/authority/recovery/API threading, the bounded admin surface with
  SQLite enable/disable state, and `skills.read` provenance + release-eval
  cases). **`EXT-MCP-01` is `Done`** — bounded protocol-version negotiation
  (`SUPPORTED_PROTOCOL_VERSIONS` with server-version validation) and a
  Streamable HTTP transport (`mcp_http.py`) with bearer-token-via-env,
  module-level SSRF guard, https enforcement, and stdio/http routing in the
  harness. **`EXT-MCP-02` is `Done`** — `McpSessionPool` with
  healthy/degraded/quarantined health classification, bounded backoff, and
  acquire/release/health/close wrapping `McpProxyTransport` (shared by stdio +
  http); `SessionState` dataclass exposed from `mcp_protocol`. **`EXT-MCP-06`
  is `Done`** — elicitation mapped onto the durable Clarification flow:
  `ClarificationContext`/`ClarificationRequestedPayload` gain optional
  `response_schema` + `elicitation_source` (existing flow byte-identical),
  `McpElicitationBridge` converts `elicitation/create` → ClarificationContext,
  and `ZEBRA_MCP_ELICITATION` gates it (default on). **This completes the EXT
  Phase A scope** (EXT-0 + SKILL-01..05 + MCP-01/02/06).
  Plugin/Hook/Marketplace remain `Locked` pending private-cloud GA. Elicitation
  is reconciled to durable HITL; sampling stays a hard non-goal.
- Existing harness baseline `HAR-TOOL-RECOVERY-01` enforces the durable contract
  that a single `ToolCallStatus.FAILED` (HTTP 4xx, missing file, timeout) must
  surface as a structured observation for model-selected correction rather than
  directly producing `session_failed`. Changes: repeated tool calls become
  observations with a threshold-gated `loop_guard_exhausted` hard stop (default
  3), sequential batches continue executing remaining tools after a mid-batch
  failure (matching concurrent-batch semantics), and a provider protocol
  firewall (`protocol_invariants.py`) validates tool-call/tool-result pairing
  before every model request to prevent `invalid_request` leakage. Its exact
  `tool + arguments` guard does not detect argument variants returning the same
  evidence; `HAR-CONV-01` owns that narrow follow-up.
- Model-response acceptance is now a separate provider-neutral boundary:
  malformed body/SSE/tool-call output becomes `ModelResponseRejectedError`,
  tool-capable stream deltas are committed only after validation, one bounded
  repair is allowed within the model-call budget, and exhaustion produces a
  recoverable `SESSION_SUSPENDED` rather than `session_failed`. Provider
  transport retries and semantic repairs have separate trace counters. The
  implementation and regression cases are present in the working tree; runtime
  validation has not been executed in this session.
- FinOS integration review `FINOS-RT-04` restores native Task JPEG/PNG
  attachments and adds a fixed eight-tool, Task-scoped read-only business
  provider on `codex/finos-runtime-alignment`. Its 81 focused/provider and
  settings-contract tests pass; the branch's two file-size, 13 MCP Mypy, and
  four MiniMax Ruff regressions are closed. The current full suite is `1792
  passed, 9 failed, 8 skipped`, matching `origin/main` with no FinOS-focused
  regression: eight existing functional failures plus the existing file-size
  test. Main still has two file-size, 13 Ruff, and four Mypy findings. CI jobs
  did not run because of the billing/spending limit; `make check`, container
  runtime, and production authentication/TLS gates remain open. This is a Draft
  candidate, not a mainline or release claim. See
  `docs/FinOS_Runtime_Integration_Status_2026-07-27.md`.
- Review follow-up `FINOS-RT-04-READONLY-AUTH` is merged locally on fixed fork
  deployment branch `codex/finos-runtime-alignment`; it narrows FinOS opt-in
  base-tool authority
  to an exact durable Task grant. It reuses the Task MCP allowlist plus a
  preapproved-readonly subset; Zebra Policy only auto-allows a name when the
  Task is read-only, uses MCP-proxy-only egress, and the classified route
  matches. The Policy is provider-neutral: no MiniMax/Qwen name is hard-coded.
  All other MCP and all write, Core, Shell, Git/PR, delete and publish paths
  retain existing approval/deny behavior. It has not been pushed or deployed,
  and is not authorized to merge directly to `main`.

## Current Capability

### Durable execution

- Event Store and projections are the durable source of truth.
- Harness and Worker execution is bounded, stoppable, resumable, and recoverable.
- SQLite leases, idempotency, tool/effect ledgers, snapshots, artifacts, and
  delivery audit cover the local execution lifecycle.
- Existing Session handoff safety contracts now back internal Segment rollover
  while the legacy ordinary-user mutation remains disabled by default.
- Stable Task persistence aggregates root and child Segments behind one identity,
  one monotonic event cursor, and active-Segment message/control routing.
- Completed-Task follow-up and cancelled/failed-Task recovery create internal Segments
  automatically; unsafe lifecycle boundaries pause or fail closed.
- Immediate terminal follow-ups inherit the previous user/Assistant checkpoint;
  internal rollover no longer drops the subject needed by short replies.

### Runtime and security

- Runtime classes are `trusted-local`, `os-sandbox`, `oci-rootless`, and `gvisor`.
- Production mode requires gVisor and a digest-pinned image and fails closed on
  missing runtime capability or authority drift.
- Hard runtime modes use a read-only root, non-root identity, dropped
  capabilities, no-new-privileges, default no-network, resource limits, and
  session-labelled cleanup.
- Policy, HITL, network profiles, MCP/Web gates, credential boundaries, and
  audit remain independent of model output.
- Explicit `local + trusted-local` mode uses effective `full-trusted-local`
  authority across Desktop/API/CLI/Worker, so new and existing Tasks execute model
  tools without per-call approval. One Agent Security resolver is the authority
  source for every execution entry point. System HTTPS proxies are honored for
  local Web execution; direct connections retain public-address DNS preflight.
  Core and non-local deployments remain default-deny and approval-gated.

### Context and model integration

- Every provider request crosses a model-aware context-window hard gate.
- Large tool outputs retain complete Artifact payloads while the model receives
  bounded, checksummed projections.
- Transparent Context Capsules support compaction, inspection, recovery, and
  deterministic provider-continuation fallback.
- DeepSeek stable Flash/Pro profiles, streaming/cache/TTFT/error telemetry, and
  default-off Beta capabilities are implemented without exposing private reasoning.
- Malformed provider JSON and Tool Call arguments are rejected before execution;
  one bounded model repair is attempted, then execution suspends recoverably.
- Explicit in-process DeepSeek thinking tool loops preserve and replay private
  `reasoning_content`; default executor profiles remain non-thinking, and missing
  continuation state fails before HTTP.

### Product surfaces

- Zebra owns Agent execution state and can run as an independent microservice;
  Desktop and CLI are optional operator surfaces over the same Runtime.
- Authelia/external identity owns authentication. Calling business systems own
  users, organizations, membership, business authorization, subscriptions, and billing.
- Zebra accepts signed Agent authority, opaque namespace, and technical limits;
  internal Policy may only preserve or narrow that authority.
- API, CLI, Worker, and Desktop read and mutate the same durable state.
- Desktop consumes replay-plus-tail SSE, renders truthful partial output, and
  supports approval, clarification, task plans, context, and artifacts without
  exposing internal child-Session or handoff controls.
- Real Chromium exercises the live Desktop/API/Worker/SQLite/SSE chain for long
  streams, reload recovery, cancellation, and invisible cross-Segment follow-up.
- Desktop composes Lobe UI `ThemeProvider` with Ant Design X and Zebra's durable
  event projection; Lobe UI does not replace session or chat state.
- The compact Ant Design X composer is merged; it does not change conversation
  or task-launch contracts.
- Typed local tools cover bounded file, command, patch, tests, Git, Web, Skill,
  MCP, and read-only Research paths according to the task profile.
- Failed tools return structured observations for model-selected correction or
  fallback, including bounded failure reason and detail when output is empty,
  while Policy, approval, protocol, effect, and budget stops remain hard.
- API and Harness model/tool call limits are optional and default to unlimited;
  an explicit caller ceiling remains strict. A batch that cannot fit starts no
  tools and suspends recoverably instead of becoming a generic Task failure.

## Latest Validation Baseline

Validated on `codex/ctx-seg-02-followup-recovery` on 2026-07-20:

- focused API/Core/Worker regression: `74 passed`
- `make test`: `1519 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `419` source files,
  and all `8/8` release Eval cases passed
- all `22` deterministic Desktop checks and the production Vite build passed;
  Tauri validation was intentionally omitted per explicit scope waiver

Validated on `codex/web-ux-01-trusted-local-auto-web` on 2026-07-19:

- final focused authority, failure-observation, proxy, API, Worker and runtime:
  `101 passed`
- `make test`: `1515 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `418` source files, and
  `8/8` release Eval cases passed
- every deterministic Desktop `check:*` script and production build passed
- real Chromium: `8/8`, covering the trusted-local launch default, automatic
  command execution, streaming, reload, cancellation, Segment and failure paths
- the original old Task completed a real OpenAI `web.fetch` via the configured
  macOS HTTPS proxy without approval or `private_network_blocked`
- real Zhipu Task `91fbddb3-d608-4e7c-a15b-694d6e55c9ae` recorded Policy
  `allow`, recovered from the site's expired TLS certificate, and gave the model
  the exact failure detail instead of a false allowlist explanation

Validated on `codex/subagent-delegation-model-native` on 2026-07-19:

- focused delegation and recovery regression: `39 passed`
- `make test`: `1509 passed, 5 skipped`
- `make check`: file-size `898`, Ruff, strict Mypy over `417` source files, and
  `8/8` release Eval cases passed
- isolated real-model API check answered `1+1` directly with `2`; trace and
  durable events contained no tool or Subagent activity

Validated on `codex/ctx-seg-01-task-runtime` on 2026-07-19:

- `make test`: `1501 passed, 7 skipped`
- `make check`: file-size, Ruff, strict Mypy over `417` source files, and `8/8`
  release Eval cases passed
- Desktop: every deterministic `check:*` script and production build passed
- real Chromium: `7/7` long-stream, reload, stop, invisible Segment follow-up,
  approval, and failure regressions passed
- terminal control state and approval identity now project through the stable Task
  boundary even while an internal Segment execution request is settling
- inherited workspace revision is fail-closed before the first Segment attempt;
  later approval continuations use current runtime authority instead of replaying
  the immutable creation-time revision check

Previous packaged mainline baseline:

Validated on `ARCH-RT-A4-E2E-01`, merged as `origin/main@d586a8f` / PR `#165`
on 2026-07-18:

- `make test`: `1484 passed, 7 skipped`
- file-size gate: `889` files, zero violations
- Ruff: passed
- strict Mypy: `412` source files, zero errors
- release Eval: `8/8`, `pass_rate=1.00`
- Desktop: deterministic checks, production build, and `7/7` real Chromium
  Runtime/streaming regressions passed
- Quality run `29645045918`: all seven jobs passed, including the packaged Ubuntu
  `.deb` WebDriver chain, real Linux gVisor, Workspace exhaustion, and real OS
  sandbox smoke on Ubuntu and macOS
- packaged evidence records `passed=true`, `runtime_class=os-sandbox`,
  `fallback_allowed=false`, cancellation, approval with real tool execution,
  failure visibility, and restart-durable-recovery; final screenshot shows the
  recovered failed session and Runtime Inspector value
- current main JavaScript chunk: about `1.47 MB` (`458 KB` gzip), Vite warning remains

The seven skips are opt-in real-provider/platform smokes. Linux CI runs the real
gVisor and native sandbox jobs instead of treating local skips as proof.

`UI-LOBE-01` validation additionally passes all Desktop checks, TypeScript,
Vite production build, and a real browser smoke without console warnings.

`UI-COMPOSER-01` additionally passes all `21` Desktop checks, TypeScript/Vite
build, and real Chromium desktop/mobile visual checks. The thread composer is
`117px` high instead of `183px`; the new-task and `390px` mobile variants are
`145px` and `113px`, with no horizontal overflow or browser console warnings.

The DeepSeek credentials-enabled focused run also passed all `39` contracts,
including a real thinking tool round trip.

## Governance State

- The Phase 0-8 implementation baseline is complete and historical.
- `docs/AGENT_TASKS.md` is the only executable task registry.
- All eight stale `Review` cards verified as merged are closed as `Done` by
  `QA-GOV-02` / PR `#144`.
- `QA-148-MDL-01`, `QA-DESKTOP-E2E-01`, and all Phase A Runtime tasks
  `ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01` are `Done`.
- `QA-HANDOFF-CLK-01`, `QA-PKG-E2E-02`, `QA-PKG-E2E-03`, and `UI-LOBE-01`
  are `Done` via PRs `#170`, `#171`, `#172`, and `#168`.
- `UI-COMPOSER-01` is `Done` via PR `#174`.
- `ARCH-129-ACP-01` and `ARCH-129-CTX-01` remain `Locked` until explicitly activated.

## Known Follow-Ups

1. Close `FINOS-RT-04` main-baseline gates (two file-size, 13 Ruff, four Mypy,
   eight functional failures plus the file-size test), CI billing/spending,
   fresh-container, and authenticated private-network/TLS acceptance before
   merge or release.
2. Add terminal/TTL cleanup for FinOS Task attachment workspaces without
   changing Journal, Note, Draft or Core lifecycle.
3. Decide explicitly whether to activate Phase B private-cloud single-tenant work;
   its database migration and recovery-model reviews remain required entry gates.
4. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
5. Add migration/backup evidence before any Phase B activation.
6. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
7. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, external-namespace isolation, and Kubernetes in
   dependency order.

## Runtime Blueprint

`ARCH-RT-BP-01` is complete on `codex/arch-runtime-deployment-blueprint` and
records the shared Runtime contract and the separate single-host and cloud
deployment profiles. It does not activate implementation or change the status
of locked architecture cards.

The maintainer activated single-host Phase A on 2026-07-18. Work is split into
`ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01`; all four tasks are merged and
every Phase A exit criterion is evidenced. Phase B and Phase C remain deferred
pending explicit activation; Phase B additionally requires database migration
and recovery-model review.

A1 now implements macOS Seatbelt and Linux bubblewrap `os-sandbox` with
capability probes, sanitized process environments, network denial, whole-process
boundaries, immutable authority, snapshots, and fail-closed platform selection.
A1 merged through PR `#160` after Ubuntu bubblewrap, macOS Seatbelt, gVisor,
Backend, and Desktop CI passed. A2 now owns Setup/Agent isolation.

A2 now implements exact external HTTPS GET egress, SHA-256 cache reuse, temporary
Credential revocation before Sandbox startup, no-network Setup execution,
lockfile verification, SPDX Setup Artifact, verified Snapshot handoff, and a new
no-network Agent handle. It reuses existing Artifact/Snapshot storage and adds no
durable state model. A2 merged through PR `#163` after all five Quality jobs
passed. A3 now enforces a dedicated capacity-limited Workspace mount in
production, kills timed-out process groups, normalizes runtime failures, and adds
real `ENOSPC`, 20-cycle native soak, long-stream, and gVisor machine-readable CI
evidence. Local validation passed `1483` tests plus all static/release gates; PR
`#164` merged after all six Quality jobs passed. A4 then delivered the final
packaged Tauri/Desktop Runtime E2E exit gate through PR `#165` / merge commit
`d586a8f`. Quality run `29645045918` passed all seven jobs. The Ubuntu `.deb`
artifact was driven through the real API, Worker, and `os-sandbox`; its retained
JSON and screenshot evidence cover no-fallback identity, cancellation, approval,
real tool execution, failure visibility, API restart, and durable recovery.

## Explicitly Deferred

- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- PostgreSQL/object-storage production control plane
- external authority adapter and namespace-isolated cloud control plane
- centralized Vault/KMS-backed credentials and production Egress
- ecosystem marketplace, cross-organization A2A, and autonomous production release

## Permanently External Business Responsibilities

- user registration, login credentials, MFA and identity lifecycle
- organization, membership, invitation, join/leave and account-disable workflows
- business RBAC, subscriptions, plans, billing, invoices and commercial quota

Authelia is the selected authentication provider. Zebra verifies external Agent
authority and enforces technical execution limits, but does not duplicate these
business domains. The durable decision is `ADR-012`.

## Document Responsibilities

| Document | Responsibility |
|---|---|
| `README.md` | stable product entry, setup, capability summary, boundaries |
| `PROGRESS.md` | concise current mainline snapshot and next decisions |
| `docs/AGENT_TASKS.md` | executable task status, owner, branch, paths, acceptance |
| `task_plan.md` | current task checklist only |
| `WORKLOG.md` | session-level execution history and handoff evidence |
| final architecture | target architecture and invariants |
| Phase 0-8 implementation document | historical dependency and acceptance baseline |

## Required Reading

1. `README.md`
2. `PROGRESS.md`
3. `docs/AGENT_TASKS.md`
4. `AGENTS.md`

Before architecture changes, also read the source-of-truth documents in the
precedence order defined by `AGENTS.md`.

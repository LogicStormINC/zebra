# Active task — CLOUD-PLAN-ACCEPTANCE-02 strict 100-point closure (2026-09-26)

1. `completed` — close SDK supply-chain gaps: pinned toolchain, package audit,
   tree-shaking proof and CI integration.
2. `completed` — add real-browser React and Trench acceptance for responsive,
   IME, attachment, session-transition, scroll, collapse and recovery flows.
3. `completed` — materialize executable fixtures, a real Zebra runner and
   independent verifiers; complete the current-version 180-attempt matrix.
4. `completed_local` — execute real-model Memory/result matrices and cache
   boundary reports; recovery/compaction cache percentages remain unmeasured.
5. `blocked_external` — local `runsc` is absent and the remote host rejects the
   available SSH credential, so one-digest gVisor/canary/rollback proof cannot run.
6. `completed_local` — rerun Zebra/Trench/SDK/browser/PostgreSQL gates and report
   implementation, strict acceptance, real-task and production evidence separately.

Detailed plan:
`docs/Zebra_Cloud_Agent_100分严格验收闭环计划_v1.0.md`.

Errors encountered:

- Ruby 2.6 `YAML.load_file(..., aliases: true)` rejected the unsupported keyword;
  use the compatible `YAML.load_file(path)` parser for workflow syntax checks.
- The first browser-matrix preparation used a repository-root path while the
  command already ran inside `sdks/typescript`; use SDK-relative paths there.
- The first Chromium focus assertion clicked an external lifecycle-control
  button, which correctly moved browser focus. Advance lifecycle state through
  a programmatic fixture action after attachment selection instead.
- Vite browser acceptance passed, but the first Next server command forwarded
  an extra `--` and never bound. Invoke `pnpm exec next start -H/-p` directly
  and retain child output for readiness diagnostics.
- The first Trench browser assertion assumed a fixed conversation id, but the
  product intentionally creates a random durable id. Assert the id captured
  from the real create-conversation request instead.
- The first live-eval reporting shell used `status`, which is a read-only zsh
  parameter. Use a task-specific exit variable for report commands.
- The 12-case real-model pilot exposed three truthful delivery-gate blocks:
  file and package deliverables retain publication requirements, while local
  memory-recovery fixtures now require an explicit write/read-back proof so
  they do not accidentally enter the artifact-publication path.
- The first browser scroll assertion sampled immediately after requesting
  smooth scrolling. Wait for the browser to settle at the bottom instead of
  changing production behavior to make an asynchronous animation synchronous.
- The first terminal-collapse and touch-target browser assertions sampled the
  React effect synchronously and included fixture-only navigation controls.
  Wait for the observable collapsed state and scope target sizing to the
  published `.zebra-agent-chat` surface.
- Failed commands originally exposed only `status=failed` to the model. Project
  bounded `stderr`, `exit_code`, timeout and failure reason so retries can correct
  the cause instead of repeating blind calls.
- Standard Git diff headers were validated after stripping `a/` and `b/` but the
  unnormalized patch was applied with `-p0`. Normalize once before both validation
  and execution, and reject hunk headers whose declared line counts do not match.
- The local policy rejected an absolute `command.run.cwd` even when it was the
  exact authorized workspace. Supply the workspace root to policy, allow only
  contained absolute cwd values, and retain the tool-level containment check.
- English `Create ... scheduled job` was classified as CREATE and invented an
  Artifact obligation. Scheduling is an OPERATE task and still requires fresh
  postcondition verification, not an unrelated file publication.

# Prior task — CLOUD-PLAN-CLOSURE-01 end-to-end plan closure (2026-09-26)

1. `completed` — Trench consumes the packaged React surface from reproducible vendored tarballs; the duplicate Composer implementation and source alias are gone.
2. `completed_implementation` — the fixed corpus contains 60 cases / 180 planned attempts and an independently verified runner/report path; the real campaign remains `0/180` until isolated fixtures, authority-backed verifiers and credentials are supplied.
3. `completed` — real package tarballs pass React 18 and 19 in Vite plus Next SSR/RSC consumers.
4. `partially_completed` — real PostgreSQL fault, Memory and application Compose gates pass; the no-gVisor composition tier passes fail-closed, while the seven gVisor execution scenarios and remote canary/rollback remain externally blocked.
5. `completed` — Zebra and Trench focused/full gates are reconciled, with implementation, local acceptance, real-task and production evidence reported separately.

# Prior task — CLOUD-RELIABILITY-02 reliability and release closure (2026-09-26)

1. `completed` — fail closed on missing/duplicate/out-of-order durable Task events and prove exact cursor recovery.
2. `completed` — replace an invalid persisted browser cursor with the authoritative Task tail, refresh pending effects, and stop reconnect loops when login/session authority expires.
3. `completed` — freeze exact source-matching React package versions with Zebra/Trench commits, image digests, migrations, protocols and configuration.
4. `completed` — bind the remaining reliability scenarios to candidate/rehearsal evidence without converting unavailable production evidence into PASS.
5. `completed` — run focused SDK/API/release suites and full repository gates, then report local, acceptance and production completion separately.

# Prior task — MEMORY-CONTEXT-02 memory, compaction and cache closure (2026-09-22)

1. `completed` — preserve completed actions, pending actions, rejected approaches and permission boundaries in durable Context Capsules and all recovery materialization paths.
2. `completed` — prove synonym recall, preference reversal, temporary-preference rejection, cross-project isolation, deletion suppression and irrelevant-memory bounds.
3. `completed` — segment cache evidence into cold start, warm loop, recovery, compaction and child wakeup without changing prompts, model or reasoning settings.
4. `completed` — run focused suites, full repository gates and record evidence-backed implementation coverage.

# Prior task — AGENT-QUALITY-04 result-level acceptance (2026-09-22)

1. `completed` — strengthen the typed acceptance contract with explicit response bounds and Host-verifiable goal terms without turning keyword classification into authority.
2. `completed` — make task-type outcomes require matching result evidence rather than treating any mutation or HTTP/tool success as completion.
3. `completed` — preserve recoverable parameter/read failures for correction while stopping evidence-free repeated actions and reconciling unknown writes.
4. `completed` — add deterministic result-level regressions for answer, research, change, create and operate tasks.
5. `completed` — rerun the failed real-model constraint smoke, focused suites and full repository gates, then record honest evidence.

# Prior task — AGENT-LIVE-EVAL-01 representative real-task evaluation (2026-09-22)

1. `completed` — define a live-eval case and attempt contract that cannot mix deterministic replay with real-model evidence.
2. `completed` — add 12 representative tasks across answer, research, code, file, operation and memory/recovery, split into development and holdout sets.
3. `completed` — aggregate first/final success, intervention, false-completion, recovery, citation, repeated-tool, latency and cost metrics only when 3 repetitions are complete.
4. `completed` — add a safe CLI report entry and deterministic contract tests.
5. `completed` — run the available real-model smoke, repository gates and record honest executed versus pending evidence.

# Prior task — REACT-UX-01 React task lifecycle experience (2026-09-22)

1. `completed` — define one typed public lifecycle contract for local submit, server acceptance, queue, execution, user wait, reconciliation, disconnect and distinct terminal outcomes.
2. `completed` — render lifecycle and recovery controls without exposing private reasoning or raw errors.
3. `completed` — prove reconnect, resume and retry remain distinct and unsafe unknown writes cannot be blindly replayed.
4. `completed` — prove new-session to active-chat rerenders retain the same controlled Composer node, input, attachments and focus boundary.
5. `completed` — run package, external-consumer and repository gates; document the S2 evidence and remaining Host-adapter boundary.

# Prior task — REACT-UI-01 React Agent composer foundation (2026-09-22)

1. `completed` — trace the Trench composer and identify its reusable behavior and Host-only dependencies.
2. `completed` — implement the finite public `AgentChat`, Composer, message, activity, approval, clarification, Artifact and Memory setting surfaces with explicit CSS variables.
3. `completed` — add interaction regressions for IME, submit/pause/continue, activity collapse, interrupts, resources, attachment removal and disabled state.
4. `completed` — build, pack and verify ESM/CJS/types/styles in isolated Vite and Next React consumers.
5. `completed` — review package API, run SDK and repository gates, and establish the stable Host-adapter boundary for later Trench migration.

# Prior task — REACT-PKG-01 TSDX package and consumer boundary (2026-09-21)

1. `completed` — save the complete Cloud Agent + React optimization plan under `docs/` and claim the task with explicit owned paths.
2. `completed` — validate TSDX 2.x against the existing pnpm workspace and correct the four SDK package boundaries.
3. `completed` — build and pack every SDK package; inspect exports, declarations and package contents.
4. `completed` — install the real tarballs into isolated Vite and Next.js React consumers and run production builds without source aliases.
5. `completed` — run SDK tests/type checks, document evidence and review the slice before component migration.

# Prior task — CLOUD-MEMORY-CLOSURE-01 PostgreSQL governed-Memory closure (2026-09-21)

Branch: `codex/cloud-memory-closure-01`, based on
`cloud-agent-trench@3fe23bbd`.

1. `completed` — bind Memory writes and reads to stable frozen Host principal
   and workspace scope without weakening Definition scope.
2. `completed` — add deterministic Chinese/English remember, update and forget
   directives with secret rejection and governed lifecycle mutations.
3. `completed` — add bounded Chinese-capable PostgreSQL recall and durable
   selected-Memory evidence.
4. `completed` — persist finalization outcomes for zero-candidate, created,
   updated, deleted and failed processing, and expose runtime status through the
   existing memory API surface.
5. `completed` — run focused, PostgreSQL, full repository and real composed
   cross-session acceptance; record evidence and implementation percentage.

Model and reasoning-effort settings remain unchanged. Redis Agent Memory stays
disabled while PostgreSQL remains the authoritative store.

Review follow-up closed five reproduced defects: Host visibility parity, safe
forget semantics, source-specific expiry, session metric scope parity, and older
relevant PostgreSQL recall. A real PostgreSQL acceptance now proves a confirmed
USER Memory written by one Session is automatically recalled by a later Session.
The second review closed four deeper boundary defects: every session Memory read
now freezes the complete Host workspace/principal/tenant/Definition scope and
fails closed without one principal; automatic expiry requires reconstructable
tool-event provenance; and PostgreSQL applies relevance before its bounded row
cutoff while retaining a stable preference/project-rule lane.

## Prior task — CLOUD-AGENT-PARITY-01 General capability and quality closure (2026-09-20)

Branch: `cloud-agent-trench`; Trench consumer:
`/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — remove Host-specific assistant identity/format constraints from generic modes and add typed task acceptance contracts.
2. `completed` — make completion, verification, retry and continuation state task-aware and durable.
3. `completed` — improve tool efficiency, evidence/claim quality and adaptive final-answer shaping.
4. `completed` — harden the reusable Agent UI boundary and process rendering for future npm extraction.
5. `completed` — add a representative multi-category quality suite and run focused/full/cross-repository acceptance.

Model and reasoning-effort settings remain unchanged. This task improves the
Cloud Agent runtime and reusable Host boundary; Trench is only the first Host.

Closure evidence: Zebra `make check` and `make test` pass (`4577 passed, 892
skipped`, deterministic eval `30/30`); TypeScript SDK check and `15/15` tests
pass. Trench complete gates pass (`136` API/model tests, `74` pipeline tests,
`91` ToC tests, lint, both production builds, migrations and diff check).
Logged-in browser conversation `conv_1789910351988_0397a0` completed with one
committed answer, one model call, no tools, no failed event and no irrelevant
Skill binding. Local Zebra API/Worker images were rebuilt and are healthy.

## Prior task — CLOUD-CAPABILITY-UI-01 Host-selectable agent modes (2026-09-20)

Branch: `cloud-agent-trench`; Trench consumer:
`/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — define a server-owned research/general/coding capability contract.
2. `completed` — bind capability changes to successor Zebra Tasks and durable Turns.
3. `completed` — expose the contract through the reusable composer boundary.
4. `completed` — verify API, runtime, frontend and cross-repository quality gates.

The host selects a product-level mode; clients never submit raw Tool, Policy,
network or budget profiles. Model and reasoning-effort behavior remains unchanged.

Follow-up closure: exploration, research and expert conversations again omit
model/tool call ceilings, as required by `CTX-SEG-03` and ADR-013. Explicit
administrative, scheduled and evaluation budgets remain strict, but Zebra now
validates them as positive integers without a magic maximum. Generation
`trench-native-v15` migrates existing conversations away from the regressed
snapshots. Focused Zebra API tests pass `22/22`; Trench runtime tests pass
`35/35`, and both complete repository gates pass. Existing browser conversation
`conv_1789911230325_53c036` migrated to v15 and completed; its successor Task
stores both model/tool call budgets as `null`.

## Prior task — AGENT-QUALITY-03 Real Answer Quality Closure (2026-09-20)

Branch: `cloud-agent-trench`; Trench consumer:
`/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — preserve structured failed Tool status through AG-UI and Trench.
2. `completed` — hide Host Tools that the current Grant cannot invoke.
3. `completed` — replace tool-count evidence with a durable, continuation-safe evidence ledger.
4. `completed` — require collected, matching citations for freshness-sensitive answers.
5. `completed` — reduce broad Trench retrieval churn and verify focused regressions.
6. `completed` — rebuild the local runtime and run real-model/API/browser acceptance.
7. `completed` — run complete Zebra and affected Trench quality gates and record evidence.

Model and reasoning-effort settings remain unchanged.

Closure evidence: Zebra `make test` passes `4573 passed, 892 skipped`; `make
check` passes the file-size gate, Ruff, strict Mypy over 968 source files and
deterministic Harness eval 10/10. Trench `make check` passes 129 Python tests,
74 cleaning tests, 89 ToC tests, lint, production builds, migration checks and
the diff gate. Real browser conversation `conv_1789903152657_6847d3` completed
with first public activity in 1.29 seconds, 6 model calls, 14 successful tools,
7 evidence-backed findings and 21 exact source links; reload restored the same
terminal timeline and committed answer.

## Prior task — AGENT-QUALITY-01 Evidence Closure And Skill-Guided Deliverables (2026-09-16)

## Current task — AGENT-QUALITY-02 Quality Loop Completion (2026-09-16)

Branch: `cloud-agent-trench`; Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — enforce selected Skill reads before final answers.
2. `completed` — bind freshness verification to resource evidence with opaque fallback.
3. `completed` — retain safe Host business-error diagnostics.
4. `completed` — add deterministic substantive-answer revision/warning gates.
5. `completed` — carry selected Skill components into bounded research children.
6. `completed` — validate and refresh Trench native source mutations.
7. `completed` — run static/focused/full checks and record remaining baseline failures.
8. `completed` — rebuild the live acceptance stack and verify service health; the
   source mutation path is covered by the focused Trench contract suite.

Branch: `cloud-agent-trench` (explicit user-requested in-place integration)
Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`

1. `completed` — bind selected Skills to the coordinator prompt and tool profile.
2. `completed` — add declared mutation/fresh-read evidence tracking and bounded
   completion verification.
3. `completed` — increase the bounded Cloud conversation history budget.
4. `completed` — project user subscription truth in Trench source reads.
5. `completed` — separate tool-loop progress prose from the final assistant answer.
6. `completed` — run focused and affected validation, then close durable records.

## Prior task — CTX-SEG-03 Host Budget Defaults And Truthful Suspension (2026-09-16)

Branch: `cloud-agent-trench` (explicit user-requested in-place integration)
Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`

1. `completed` — reproduce the incident from durable events and separate model-call
   exhaustion from tool-call exhaustion.
2. `completed` — remove Trench's implicit `6/16` limits from normal conversations.
3. `completed` — let the final permitted model request retain tool capability.
4. `completed` — project explicit budget suspension as a terminal AG-UI interrupt.
5. `completed` — run focused and affected repository validation, then close docs.

## Prior task — CLOUD-USER-SCHEDULE-DEPLOY-01 (2026-09-15)

Branch: `cloud-agent-trench` (explicit user-requested in-place integration)
Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`

1. `completed` — compose the independent API, Worker and Scheduler processes.
2. `completed` — expose user-scoped schedule CRUD and controls in Trench ToC.
3. `completed` — bind host workspace references and enabled Skills at the BFF.
4. `completed` — dispatch schedules through the standard RUN-command path.
5. `completed` — freeze one Skill and one MCP in the scheduled Turn snapshot.
6. `completed` — reconcile terminal Task state into durable Firing history.
7. `completed` — prove logged-in browser run-now and visible completed history.
8. `completed` — pass focused, PostgreSQL, type/lint/eval and frontend build gates.
9. `completed` — update durable project records for review handoff.

Implementation plan: `docs/Cloud_Agent用户级定时任务技术方案_v1.0.md`
(accepted and present in this worktree).

## Current task — Durable interactive execution and reconnect recovery (2026-09-21)

1. `completed` — preserve truthful non-budget suspension reasons.
2. `completed` — prove an unbudgeted Harness run exceeds the retired 24/64 ceilings.
3. `completed` — reconnect Trench after AG-UI idle timeout from the durable cursor.
4. `completed` — run focused Zebra and Trench regressions.
5. `completed` — run both repository quality gates and record durable evidence.
6. `completed` — verify the local composed runtime and browser path without changing
   model or reasoning settings.

## Prior task — RabbitMQ reliability (2026-09-05)

Approved isolated worktrees: `rabbitmq-reliability/zebra-agent` and
`rabbitmq-reliability/Trench`; original services remain unchanged.

1. Completed: stages 0/1 local contracts and broker evidence.
2. Completed: Stage 2 Trench Turn, 10/10 isolated acceptance.
3. Completed: Stage 3 Zebra command, 6/6 isolated acceptance; actual product,
   browser/file, broker restart, fallback/restore and process-fault evidence in
   `docs/rabbitmq_stage3_composition.md`.
4. Review: `RABBIT-SOURCE-SCOPE-01`, explicit source bindings and operator
   CAS backfill. Private/credential execution remains fail-closed.
5. Review: `RABBIT-SOURCE-SCHEDULE-01`, source-wide scheduling/fencing and
   atomic FetchCommand/source-Outbox admission; slice 6/6 and Stage 4 group 2
   accepted.
6. Review: `RABBIT-SOURCE-DELIVERY-01`, dedicated source relay/Inbox,
   bounded consumer/recovery/quarantine and opt-in restricted topology; Stage 4
   group 3 accepted. Stage 4 is now 2/7.
7. Review: `RABBIT-SOURCE-CUTOVER-01`, every old business fetch entry point now
   uses one default-off authority without double scheduling; Stage 4 group 4
   accepted. Stage 4 is now 3/7.
8. Review: `RABBIT-SOURCE-RESULT-01`, durable fenced fetch-result
   classification, safe diagnostics and bounded retry/recovery; Stage 4 group 5
   accepted. Stage 4 is now 4/7.
9. Review: `RABBIT-SOURCE-E2E-01`, real fixture HTTP fetch through
   PostgreSQL/Redis/RabbitMQ into authenticated history/timeline, including
   duplicate, Redis-rejection and cross-user isolation evidence; Stage 4 group 6
   accepted. Stage 4 is now 5/7.
10. Review: `RABBIT-SOURCE-COMPOSE-01`, default-off process composition,
    explicit cutover, actual-process fallback/restore/rollback and terminal
    database evidence; Stage 4 group 7 accepted. Stage 4 is now 6/7.
11. Review: `RABBIT-SOURCE-CREDENTIAL-REF-01`, existing credential identity,
    enabled state and platform validation with principal association and
    fail-closed drift; Stage 4 group 1 accepted. Stage 4 is now 7/7.
12. Review: `RABBIT-ROLLOUT-CAPACITY-01`, atomic admission/backlog bounds and
    frozen active-scope fair pickup accepted; Stage 5 is 1/8 (12.5%).
13. Review: Stage 5 group 2, default-off scope allowlist, physically separate
    side-effect-free bounded shadow lane and exact message/digest reconciliation;
    Stage 5 is 2/8 (25%).

Use `docs/AGENT_TASKS.md` for ownership and `docs/rabbitmq_completion.md` for
fixed acceptance counts. Implementation, isolated acceptance, commit/merge and
production activation remain separate. No commit or activation requested here.

## Prior task record — TRN-LINK (2026-08-26)

1. `completed` - P0 契约核对：7 项契合 / 5 项差距冻结
   （`docs/Zebra_Trench对接差距清单.md`）。
2. `completed` - G1 Host Grant Broker（`apps/host_grant_broker`）：
   RS256 签发（claim 集与 `HostSessionGrant` 精确一致，thread/run 经
   resource_refs 绑定）、JWKS 端点、Trench 会话验证（Cookie 只转发到
   `/api/trench-ai/me`）；8 个测试含真实验证器闭环。
3. `completed` - G2 Host 注册脚本（`scripts/register_trench_host.py`），
   已对真实 PostgreSQL host authority schema 冒烟。
4. `completed` - G3/G4 验收 operator sidecar（业务快照 + Worker 重启
   hook，token 保护，10 个测试）。
5. `completed` - G5 验收编排：`docker/compose.trench-acceptance.yml`
   （broker/sidecar/caddy TLS）+ `docker/trench-acceptance/bootstrap.sh`
   （密钥与本地 CA 生成，已实际执行）；`docker/Dockerfile` 增加 broker
   target。
6. `in_progress` - 全量回归验证与提交。
7. `blocked` - 应用镜像构建 + 完整栈拉起 + Trench `.env` 填值 +
   `EMB-TRN-READ-E2E-01` 16 输入执行（需 Trench 侧清场提交与真实
   部署输入，非代码缺口）。

下一步：等 Trench 侧提交清场后，按 `docs/Zebra_Trench对接实施方案_v1.0.md`
P1→P3 顺序拉栈、填配置、跑 runner。

## Current task — CLOUD-MEMORY-PROFILE-01 (2026-09-21)

1. `completed` — derive an inspectable user profile only from confirmed governed Memory.
2. `completed` — capture explicit background/goal self-statements as review-only candidates.
3. `completed` — balance bounded recall across preferences and task-relevant Memory types.
4. `completed` — expose principal-bound profile reads and exact governed deletion.
5. `completed` — enforce typed CHANGE/CREATE/OPERATE outcomes before answer commit.
6. `completed` — prove focused, API, real PostgreSQL, file-size, lint, type and eval gates.
7. `completed` — run the full suite and classify the sole live-provider-only failure.
8. `completed` — complete the real Trench Host surface with edit, source,
   scope and actual-recall transparency while keeping PostgreSQL authoritative.
9. `completed` — prove direct replacement, deletion suppression, cross-session
   recall and browser-visible governance in the composed local stack.
10. `completed` — review and harden fail-closed Host authority, PostgreSQL lock
    ordering, bounded source enrichment, blank input and overlapping UI requests.

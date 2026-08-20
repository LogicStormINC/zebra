# Zebra Agent Project Status

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Current Mainline Snapshot

- Mainline branch is `cloud-agent` (it carries the cloud product line and
  sits ahead of `origin/main`; PRs land on `cloud-agent` and main syncs
  on cut points).

- Second audit round closed on the durable delegation chain (2026-08-20,
  `cloud-agent`): the six P1 findings of the PR #248 review are fixed
  with real-PG evidence. Wakeup trust: only HARNESS-actor resume commands
  can wake a waiting parent (a USER resume neither resumes nor injects —
  restore fails closed without the trusted wakeup); every delivered
  child result is re-derived from the child's own terminal event inside
  the wakeup transaction AND re-verified by the Worker (terminal link +
  matching projection status + identical summary) before injection.
  Real answers: the wakeup reads `metadata.assistant_message`, not the
  lifecycle `summary`; the E2E's parent model can only finish after the
  child's real answer arrives in its conversation. Concurrency:
  admission idempotency claims keys with INSERT ... ON CONFLICT DO
  NOTHING (16 threads → 1 create + 15 identical replays); delegation
  losers roll their child back with the transaction and replay the
  winner's link (16 threads → 1 materialize + 15 winner replays, no
  orphans). Multi-child: the wakeup evaluates the durable
  ParentContinuation — parallel delegations keep the parent suspended
  until every epoch child is terminal, then one wakeup carries all
  results and the parent injects one real result per delegated call.
  Two-phase heal: a replayed create whose run command was lost re-
  submits it under the same command key and syncs the stored body. The
  wakeup append position derives from the event stream (MAX sequence),
  not the lagging projection. Validation: 2431 non-PG + 457 real-PG
  tests passed, `make check` green; new suites:
  `test_postgres_default_chain_scenarios.py` (forged resume,
  two-children join, replay requeue) and
  `test_postgres_concurrent_idempotency.py`, all registered in the
  compose runner. Known follow-ups unchanged: Host manifest/credential
  freeze at admission, Trench cutover inputs.

- Default-composition durable delegation proven end to end (2026-08-20,
  audit-fix branch on `cloud-agent`): the 2026-08-20 maintainer audit of
  PR #247 found all three "fixes" dead on the default path — the durable
  child could never materialize (fabricated `derived.local` parent
  binding + capability mismatch), the parent wrote SESSION_COMPLETED
  before SESSION_SUSPENDED with a contract-violating payload, and the
  idempotency hash diverged between API replay and PG admission (plus
  non-serializable attachment/UUID payloads). All closed on the real
  path: admission now freezes a binding for every cloud session
  (Host-bound pins the Host grant; internal sessions pin a
  deployment-authority binding) inside the atomic v25 transaction with a
  round-trippable snapshot; the tool loop suspends the parent on
  `suspend_after_turn` by freezing a `SUBAGENT_DELEGATED` join-state
  event (conversation, counters, tool-call identity) BEFORE any terminal
  event; the child runs READ_ONLY on a `research` tool profile (no
  `agent.research` — durable depth 1 is additionally enforced against
  the delegation link) with a binding narrowed to
  `{agent.execute, evidence.read}`; the wakeup command carries the
  child's terminal summary and the resumed parent injects it through the
  completed-tool continuation (`SESSION_RESUMED` now legal for logical
  resumes); idempotency uses ONE canonical hash computed by the API from
  the raw payload, stores the full 201 body atomically (run-command
  composition syncs it afterwards), replays it verbatim and 409s on
  hash conflict; child admission + delegation link commit in one
  transaction (no orphan children). Fixed three latent default-chain
  bugs the old component tests could not see: `load_task_binding` wrote
  a partial snapshot JSON no consumer could validate,
  `AttemptAuthorityEvidence.persist` recovered without the worker lease
  (cloud path always raised), and the workspace-projections CHECK
  rejected the `research` profile (v29 migration). New E2E
  `tests/agent_storage/test_postgres_default_chain_e2e.py` drives the
  REAL default API + Worker loop + `agent.research` over real
  PostgreSQL + MinIO with only the model transport scripted (registered
  in the compose runner). Validation: 2431 non-PG + 452 PG tests
  passed, `make check` green. Known follow-ups (explicitly not closed):
  Host-connector manifest/credential freeze at admission (Worker still
  discovers live at gateway build), and the Trench cutover chain.
- Agent Layer phases B–D executed (2026-08-18, PRs #208-#216): Phase B
  closed with `AL-TASK-BIND-CON-01` (immutable binding snapshots and
  capability intersection), `AL-CONNECTOR-PG-01` (v24 registry, immutable
  revisions, CAS bindings, real-PG evidence) and
  `AL-TASK-ADMISSION-PG-01` (v25; one-transaction admission across events,
  projections, task index, binding and idempotency with mid-transaction
  crash-injection rollback). Phase C closed with `AL-AUTH-WORKER-01`
  (P0.4: `BoundHostExecutionAuthorityResolver` derives Attempt authority
  from the frozen binding with fail-closed drift/expiry and narrowing-only
  revalidation), `AL-HOST-EGRESS-01` (P0.2 implementation side: pinned
  immutable connector profiles with memory-only ephemeral credentials) and
  `AL-HOST-EFFECT-01` (uncertain write receipts reconciled through the
  pinned profile path; blind retries structurally absent). Phase D's
  in-repo portion closed with `AL-QUERY-API-V1-01` (task-level AG-UI
  cursors survive rollover) and `AL-HOST-CONFORMANCE-01` (two-vocabulary
  fake hosts pass one shared 18-test suite over the real admission and
  effect paths; zero-branch gates). 14/16 cards Done:
  `AL-API-DECOUPLE-01` (#217) additionally moved
  `agent-runtime`/`zebra-agent-worker` out of the API's core dependencies
  into a `[local]` extra with lazily imported seams, so a cloud-only
  deployment packages the API without Worker or Runtime execution. The
  remaining two (`AL-TRENCH-CUTOVER-01`, `AL-LEGACY-REMOVAL-01`) are
  hard-gated on `EMB-TRN-READ-E2E-01` real-stack acceptance evidence and
  stay Locked until the maintainer provisions the deployment inputs
  (Trench/Zebra HTTP endpoints, both stacks' PG/Redis/object-store health,
  Grant exchange, Worker restart hook, and the Trench session cookie).
- Agent Layer Phase A executed (2026-08-18, PRs #204-#207 on `cloud-agent`):
  `AL-BOUNDARY-CON-01` lands the `agent-control-plane` workspace package
  (core-only dependency, boundary gate, `AgentAction` route vocabulary);
  `AL-HOST-CONTRACT-V1-01` freezes the capability/grant-scope separation,
  single-segment JSON-pointer resource binding rules, digest-canonical
  manifest v1, uncertain effect receipts and the ephemeral credential seam;
  `AL-WORKER-GENERIC-01` deletes the Worker's Trench tool/argument/resource
  branches — resolution now runs generically from manifest binding rules,
  legacy manifests are enriched by the Host adapter in integrations, and a
  vocabulary gate forbids Host names in Worker production code;
  `AL-CONNECTOR-CON-01` freezes immutable outbound connector profiles
  (bare-HTTPS origins, secret-free credential refs) and namespace bindings
  with published/deprecated/revoked lifecycle plus the operator-only
  registry Port. Phase B implementation cards (`AL-CONNECTOR-PG-01` from
  migration v24, `AL-TASK-BIND-CON-01`, `AL-TASK-ADMISSION-PG-01`) remain
  `Locked` awaiting activation.
- Agent Layer direction ratified (2026-08-18, `AL-PLAN-01` `Done`): Zebra
  Agent Layer = Agent Control Plane + Host Integration Plane, landing first
  as a logical `agent-control-plane` application package inside `apps/api`
  (no new microservice yet), with the Runtime untouched. The five
  architecture decisions are recorded in ADR-017; the authoritative
  engineering plan is `docs/cloud-agent构建实施方案.md` (review baseline
  `main@bb3a1bce`, key claims re-verified on ratification day). Sixteen
  `AL-*` implementation cards are registered `Locked` in four phases
  (boundary/protocol, connector/task-binding, execution authority/egress,
  API/conformance/migration); highest-leverage starters are
  `AL-HOST-CONTRACT-V1-01`, `AL-WORKER-GENERIC-01` and
  `AL-CONNECTOR-CON-01`, which together free the Worker from all Trench
  vocabulary and enable zero-branch second-Host onboarding.

- Snapshot date: `2026-08-16`
- 非产品决策收口（maintainer directive "除接入 Trench 外相关的功能全部
  做完，多租户也要开发完毕，用户体系是外挂的"）：多租户三切片全部落地——
  v23 迁移把租户 namespace 持久化到 session 投影（TASK_PREPARED host
  context 绑定一次），API 会话/任务/审批/流/AG-UI/users/tenants 内存读面
  全部按调用方租户隔离（跨租户 404，未绑定会话保持 operator 域），默认
  Cloud Worker 经 `TenantScopedAuthorityResolver` 在每次 Attempt 前持久化
  `execution_authority_resolved`（issuer 钉定、租户 namespace per-scope、
  外来 issuer fail closed）；顺带修复 `validate_event_payload` 的
  python-mode dump 泄漏 datetime 到 PostgreSQL Jsonb 的缺陷。扩展体系
  `EXT-PLUGIN-01`/`EXT-HOOK-01` 与 `ARCH-129-ACP-01`/`ARCH-129-CTX-01`
  按 blanket activation 全部实现并登记 `Done`。剩余 `Locked` 均为治理性
  门控而非工程缺口：`EXT-MARKETPLACE-01`（私有云 GA 前置）、Mem0 消费链
  （Provider admission: DENIED）、`AGENT-DEF-STO-01`（本地 SQLite Registry，
  云端产品定位推迟）。rig E2E 在 authority 事件入流后仍 `PASS` 11/11。
- Agent Definition chain closed: the full runtime chain
  REG（`AGENT-DEF-PG-01`，v19 迁移 + `PostgresAgentRegistry` + draft/version/
  release/eval evidence）→ DRAFT（`AGENT-DEF-DRAFT-01`，物化服务 + API）→
  BIND（`AGENT-DEF-BIND-01`，`AgentDefinitionSnapshot` + TASK_PREPARED +
  投影镜像 + 恢复校验）→ MEM（`AGENT-DEF-MEM-01`，Definition 域 governed
  Memory，v21 迁移）→ TRUST（`AGENT-DEF-TRUST-01`，内容信任与威胁模型）→
  EVAL（`AGENT-DEF-EVAL-01`，`AgentVersionPublicationGate`）→
  PUB（`AGENT-DEF-PUB-01`，受控发布 API + enforcement_mode，v22 迁移）全部
  `Done`；真实 PostgreSQL 矩阵 437 passed，本地套件 1290 passed，`make check`
  （file sizes/ruff/mypy 649/eval gate 10/10）全绿。`AGENT-DEF-STO-01`（本地
  SQLite Registry）按产品定位继续推迟。
- Durable positioning (2026-08-16, maintainer): the product is the cloud
  agent; the local agent exists to develop and prove the agent runtime and
  is not an independent product goal. Recorded explicitly in `AGENTS.md`
  (Product Positioning) and the `README.md` introduction; mainline
  prioritization follows cloud product value per ADR-012.
- Maintainer batch closeout: the entire 2026-08-10 to 2026-08-12 cloudline
  stack (`CLOUD-INTEGRATION-REG-01`, `CLOUD-TRN-NEXT-PLAN-01`, the three
  `QA-CLOUDLINE` quality baselines, the three `ARCH-CONFIG` boundary cards,
  `CLOUD-DEPLOY-PROFILE-CON/01`, the three `CLOUD-COMMAND` cards, the three
  `CLOUD-LIVE` cards, `CLOUD-REC-PROD-CON/PG-PITR/S3`, `CLOUD-DEPLOY-HELM-01`,
  `CLOUD-REAL-SVC-CI-01`, `CLOUD-K8S-GVISOR-E2E-01`, the `EMB-AUTH`,
  `EMB-AGUI`, `EMB-HOST-GW` and `EMB-HOST-RUNTIME` cards) was fast-forward
  merged into `zebra-cloud-trench` at `ca88aeba`, and the rebased
  `CLOUD-EFFECT-COMP-CLOSE-01` implementation merged as `bbd6108d`. All of
  these cards are recorded `Done`; per-card prose in
  `docs/AGENT_TASKS.md` is preserved as historical evidence. The preserved
  dirty-mainline handoff snapshot was kept on
  `codex/cloudline-worktree-snapshot` (removed 2026-08-17 during branch
  cleanup; superseded by mainline history). Follow-up correction
  (2026-08-17): the post-review gaps the card owner had reopened on
  `codex/cloud-effect-comp-close-01` — unknown Memory commit recovery
  (`cloud_memory_recovery`), fail-closed execution preflight
  (`execution_preflight`), receipt read validation, and the real-PostgreSQL
  compose runner under `tests/compose/cloud_effect_composition/` — were
  merged back into `zebra-cloud-trench`; `CLOUD-EFFECT-COMP-CLOSE-01` is
  `In Progress` again until its focused test acceptance criterion is
  re-verified. Verification closeout (2026-08-18): the real-PostgreSQL
  compose runner passes `19 passed` with
  `ZEBRA_CLOUD_EFFECT_COMPOSITION_TEST_RESULT=PASS` (isolated PostgreSQL +
  MinIO); one contract gap found and fixed — cross-session receipt lookups
  now raise a session-scoped `GovernedMemoryConflictError` instead of the
  generic identity-reuse message. The card is `Done`.
  Registry hygiene (2026-08-18): stale cards whose PRs merged in July
  (`CTX-SEG-01` #176, `FINOS-HAR-03` #169, `SUBAGENT-UX-01` #177,
  `WEB-UX-01` #178) and `CLOUD-WORKSPACE-CP-PLAN-01` (all seven successors
  `Done`) are closed; the registry now reflects reality with
  `EMB-TRN-READ-E2E-01` as the only open engineering item.
  `ARCH-RUNTIME-V2-PLAN-01` is `Done` (2026-08-18): the proposal's §2/§10
  were delta-aligned to the post-#194 `main` — the review confirmed the
  v2 direction was validated by implementation (Gate B–G cards all `Done`;
  every originally-missing symbol exists in code), and residual increments
  must be activated as new path-bounded cards.
  PR #194 merged 2026-08-18 (`91251fa5`): `main` again carries the full
  cloud mainline; branching returns to main-based flow.
  `EMB-TRN-READ-E2E-01` was re-attempted on the merged main and correctly
  produces the structured `BLOCKED` result (all 16 deployment inputs
  enumerated); it remains
  `In Progress` and fail-closed pending isolated cross-service inputs.
  Host cleanup follow-up (`QA-RIG-SCRATCH-VOL-01`, `Done` 2026-08-18): the
  2026-08-18 Desktop cleanup found seven leaked zebra RAM volumes — five
  `ZEBRACPE2E*` rig scratch volumes (the effect-default E2E fixture only
  detached on mount failure) plus workspace-CP probe mounts; all were
  ejected and their mount points removed, and the rig fixture now owns its
  scratch volume through a context manager that force-detaches on every exit
  path, so repeated rig runs no longer accumulate volumes on the host.
  `In Progress` and fail-closed pending isolated cross-service inputs.
- `CLOUD-EFFECT-DEFAULT-E2E-01` is `Done` with the full 10-scenario matrix
  passing on the rig: the two 2026-08-16 fault-injection scenarios verify
  that killing the Worker during the post-tool model turn recovers to a
  deterministic suspension with zero re-execution, and that rotating the
  control-plane epoch mid-execution rejects the stale terminal mutation
  while the effect reaches deterministic uncertain reconciliation. The
  completed-tool continuation recovery (`recover_approved_continuation`
  completed adjudication plus the `continue_completed_tool` harness path,
  covering executed and failed terminal outcomes) and command-consumption
  skip logging shipped with regression tests; the suspended-command-lane
  recovery follow-up is closed: the rig failure was a fixture bug (killing
  only the `uv` wrapper orphaned the worker, which suspended the session
  itself via model-call timeout); the scenario now kills the whole process
  tree and the killed session recovers through the completed-tool
  continuation to `session_completed` with zero re-execution.
  `CLOUD-WORKSPACE-CP-E2E-01` is `Done`: the automated
  `workspace_cp_provisioned_side_effect` scenario passes on the gVisor rig
  and the full runner returns `ZEBRA_EFFECT_DEFAULT_E2E=PASS` (11/11
  scenarios). The macOS APFS chmod fixture blocker is fixed by applying the
  mode change from inside the colima VM plus a guest-side write probe.
  `CLOUD-WORKSPACE-CP-PLAN-01` is registered as `Planning` for the P0.3
  Workspace Control Plane, splitting seven path-bounded successor cards
  (contract, PostgreSQL authority, provisioning provider, API command
  surface, Worker runtime wiring, GC/reconcile, default-entrypoint E2E).
  Previously `In Progress` with its execution tier
  validated on a test-only gVisor rig: the default Worker executed a real,
  policy-approved `command.run` side effect inside a gVisor sandbox through
  the durable command lane; PostgreSQL holds exactly one `succeeded` Effect
  with terminal Event and payload binding, MinIO holds both finalized
  versioned payloads, restart cycles do not duplicate the side effect, and a
  no-tool session reaches `COMPLETED` with governed Memory finalization.
  `lease_loss_uncertain_reconcile` stays skipped pending a fault-injection
  design. Composition tier (no engine) still closes green with `BLOCKED`
  (2). Recorded findings: inline execution never populates outbox
  `claim_fencing_token` (dispatch-consumer lane owns that). The
  post-approval wedge was root-caused by an instrumented rig experiment
  and fixed on 2026-08-15: `accept_persisted_event` drove guard-committed
  events through the legacy `index_event`/`upsert` path that the cloud
  Event-derived adapters forbid, aborting before projections advanced and
  leaving the event store ahead of the projection row, which made every
  terminal append conflict. The fix mirrors the recorder's transaction
  path (advance the view, index through fenced `index_worker_event`,
  save projections) and carries a regression test; the approved
  side-effect session now completes with a final model turn on the rig
  and the E2E matrix asserts it. The post-start fail-closed resume
  defense intentionally stays; genuine mid-execution Worker death
  checkpointing, the lease-loss fault-injection scenario and
  command-consumption failure logging remain on the successor card. The
  suspended-command-lane item closed on 2026-08-16: a local reproduction
  with a real hanging gateway proved that the exact durable death shape
  (completed approved tool plus a dangling model request from the killed
  Worker) already recovers through the completed-tool continuation to
  `completed` with zero re-execution — locked by a regression test — and
  the earlier `suspended` observation was rig-specific; the E2E death
  scenario now asserts completion. The worker loop additionally skips
  poisoned ready sessions with a logged reason instead of crashing the
  whole Worker on `WorkerExecutionError`. Previously: the repository now carries a fail-closed runner
  (`tests/compose/effect_default_e2e/`) that drives real PostgreSQL 17.5,
  MinIO, the committed API application object, the default Worker entrypoint
  and a provider-shaped OpenAI-compatible stub model. The composition
  scenarios (infrastructure, session acceptance, worker fail-closed with zero
  Effect side effects across repeated cycles, handoff Effect read) pass and
  are recorded in `docs/CLOUD-EFFECT-DEFAULT-E2E-01.md`. Source review and a
  host prototype proved runtime provisioning precedes the first model call,
  so the six execution-tier scenarios stay explicitly
  `gvisor_engine_absent`: the runner reports
  `ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED` (exit 2) and never derives a PASS from
  composition-tier evidence. The execution tier needs a runsc-capable engine
  and its implementation slice; the local colima `zebra-gvisor` VM's runsc
  sandbox does not start under nerdctl yet.
- `CLOUD-EFFECT-COMP-CLOSE-01` is `Done` after maintainer activation and
  rebase onto the merged cloudline. It is a narrow application-composition
  gate: the default Cloud Worker now composes the typed
  `CloudWorkerComposition` (Effect dispatch, projection transaction,
  deployment namespace, cloud Artifact and Provider Continuation factories)
  instead of an unsafe `ControlPlaneStores` cast, the API handoff reads the
  narrow `EffectStateReadPort`, and cloud Memory finalization commits through
  the governed aggregate. It does not make the platform production-ready.
- `CLOUD-TRN-NEXT-PLAN-01` is in `Review` on
  `codex/cloud-trench-next-plan-01`, intentionally stacked after the regression
  fix. The inspected next-step plan is recorded in
  [Zebra Cloud 与 Trench 下一阶段执行计划 v1.0](./docs/Zebra%20Cloud与Trench下一阶段执行计划_v1.0.md).
  It makes the first product milestone the production Trench read-only vertical
  slice, but first gates it on a green cloud mainline, coherent PostgreSQL +
  gVisor production composition, stateless command-only API, durable replay plus
  Redis live tail, real-service CI, production recovery and deployment evidence.
  `EMB-HOST-RUNTIME-01` and the Trench-side `TRN-HOST-READ-AUTH-01` successor
  are now activated in isolated worktrees; no P4+, Memory runtime or Agent
  Definition runtime work is activated.
- `QA-CLOUDLINE-PY-01` is `Review` on
  `codex/qa-cloudline-py-01`. It owns the Python size/Ruff/Mypy gate after the
  Lease/API regression fix. The integrated Zebra line now passes Mypy over
  `617` source files and the full backend is `2210 passed, 275 skipped`; the
  existing concurrent PostgreSQL/Memory size and export fixes were validated
  as an isolated handoff snapshot, and the dirty `zebra-cloud-trench`
  worktree is preserved unchanged.
- `QA-CLOUDLINE-DESKTOP-01` is in `Review` on
  `codex/qa-cloudline-desktop-01`. It split the remaining Desktop stylesheet
  size violation without changing the composer CSS contract and made the
  long-stream/stop assertions event-driven. Node 22 build, all Desktop static
  checks, file-size validation, and the eight Playwright tests pass. The default
  Tauri check remains environment-blocked by the global USTC Cargo mirror;
  direct rsproxy Cargo validation passed with `--locked`. A macOS packaged
  `.app` build also passed, while packaged WebDriver execution remains a
  Linux CI concern because `tauri-driver` reports that macOS is unsupported.
- `QA-CLOUDLINE-CI-01` is in `Review` on `codex/qa-cloudline-ci-01`. It keeps
  the canonical Quality jobs intact, adds loopback proxy bypass to Desktop and
  packaged jobs, and updates the packaged driver helper to the durable
  cancellation and suspended-state contracts. The local Gate 0 matrix is
  green; the previous PR #194 failures are confirmed stale and predate the
  Lease, atomicity, stylesheet, and event-driven assertion fixes. Real OS
  sandbox smoke and the 20-cycle soak pass locally; canonical remote workflow
  evidence is still outstanding.
- `ARCH-CONFIG-BOUNDARY-01` is in `Review` on
  `codex/arch-config-boundary-01`. ADR-021 freezes the provider-neutral
  configuration boundary and the dependency contract passes: reusable packages
  cannot import `apps/*` composition roots, and the five current config imports
  are tracked as exact successor inventory for Integrations/Security.
- `ARCH-CONFIG-INTEGRATIONS-01` is in `Review` on
  `codex/arch-config-integrations-01`. Model, DeepSeek beta, SCM and credential
  builders now accept typed provider settings; `agent-integrations` no longer
  imports or depends on `zebra_agent_config`. App roots perform the mapping and
  preserve environment, retry, credential and network behavior.
- `ARCH-CONFIG-SECURITY-01` is in `Review` on
  `codex/arch-config-security-01`. Security credential policy now accepts only
  the minimal provider/token reference and has no `zebra_agent_config` import;
  redaction and provider validation remain unchanged. The package dependency
  inventory is now empty.
- `CLOUD-DEPLOY-PROFILE-CON-01` is in `Review` on
  `codex/cloud-deploy-profile-con-01`. ADR-022 and executable settings
  validation freeze the deployment/storage/runtime axes: local is lazy SQLite,
  cloud/production require PostgreSQL + gVisor + quota, and invalid mixes fail
  closed.
- `CLOUD-DEPLOY-PROFILE-01` is in `Review` on
  `codex/cloud-deploy-profile-01`. API, Worker, Storage, migration and
  application Compose now consume the validated storage/runtime axes; full
  Python validation is green, Compose config passes, and the actual image build
  is currently blocked by a Docker Hub authorization timeout.
- `CLOUD-COMMAND-API-CON-01` is in `Review` on
  `codex/cloud-command-api-con-01`. ADR-023 and the core contract freeze the
  durable command envelope, stable idempotency/revision admission and accepted
  Event payload; route/Worker execution remains reserved for its successors.
- `CLOUD-COMMAND-RUN-01` is `Review` on `codex/cloud-command-run-01`. Its owned
  slice adds the stateless API command submission seam and Worker
  run/resume/message wake-up without Runtime side effects in API. Full Python
  validation is green: `2128 passed, 271 skipped`; `make check` is green.
- `CLOUD-COMMAND-CTRL-01` is `Review` on `codex/cloud-command-ctrl-01`. Cloud
  stop/cancel/suspend/resume now use the durable command seam and Worker-side
  control service; local operator behavior remains compatible. Full validation
  is green: `2134 passed, 271 skipped`; `make check` passes.
- `CLOUD-LIVE-WIRE-CON-01` is `Review` on `codex/cloud-live-wire-con-01`. ADR-024
  and the shared post-commit publisher seam freeze durable-first ordering,
  duplicate tolerance and replay-barrier degradation before Redis composition.
  Full validation is green: `2138 passed, 271 skipped`; `make check` passes.
- `CLOUD-LIVE-PUBLISH-01` is `Review` on `codex/cloud-live-publish-01`. Cloud
  API/Worker now compose one namespace-bound Redis publisher around direct Event
  appends; SSE consumption remains next. Full validation is green:
  `2145 passed, 271 skipped`; `make check` and the real Redis runner pass.
- `CLOUD-LIVE-SSE-01` is in `Review` on `codex/cloud-live-sse-01`. HTTP SSE now
  captures a Redis replay barrier, drains durable Events, then tails Redis with
  duplicate filtering and durable polling fallback. Full validation is green:
  `2147 passed, 271 skipped`; `make check` is green.
- `CLOUD-REC-PROD-CON-01` is in `Review` on
  `codex/cloud-rec-prod-con-01`. Its recovery contract freezes PG physical/WAL,
  immutable object copies, restore epoch and identity rotation, machine-readable
  drill evidence, and the read-only → single Worker → ingress sequence. Full
  validation is green: `2147 passed, 271 skipped`; `make check` is green.
- `CLOUD-REC-PG-PITR-01` is in `Review` on
  `codex/cloud-rec-pg-pitr-01`. Its isolated physical base-backup/WAL runner
  restores to a named point, excludes a post-target Event, rebuilds Projection,
  rotates Lease epoch and records cleanup. Real runner and full validation are
  green: `2147 passed, 271 skipped`; `make check` is green. Measurements remain
  local-only (`RPO 0.077309s`, `RTO 6.462744s`).
- `CLOUD-REC-S3-01` is in `Review` on `codex/cloud-rec-s3-01`. Its independent
  versioned MinIO backup-copy/delete/restore runner verifies the PostgreSQL
  Artifact ref, checksum, metadata, namespace and cleanup without reading a
  Worker-local payload. Real runner and full validation are green:
  `2147 passed, 271 skipped`; `make check` is green. Evidence remains local-only.
- `CLOUD-DEPLOY-HELM-01` is in `Review` on
  `codex/cloud-deploy-helm-01`. Its fail-closed chart renders migration/API/
  Worker, Service, Secret refs, non-root/read-only pods, resources, PDBs and
  gVisor RuntimeClass. `helm lint/template` and static tests pass. A real
  isolated Helm install now proves migration hook ordering, API/Worker `2/2`,
  production `/health`, gVisor `/proc/version`, UID `65532`, Worker recovery,
  and cleanup; managed rollout evidence is still not claimed.
- `CLOUD-REAL-SVC-CI-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Its canonical workflow now runs separate
  application, Redis live, PITR, S3 and fresh-restore matrix runners with
  bounded timeouts and always-retained evidence. The integrated Zebra line
  `741a471f` also re-ran application Compose after seeding a valid test-only
  Host registry; the local Docker matrix is green. `actionlint` now passes the
  canonical quality workflow after removing duplicate proxy keys, and the
  Linux container quota smoke reports real `ENOSPC`. No remote Actions or
  managed rollout is claimed.
- `CLOUD-K8S-GVISOR-E2E-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. The fail-closed Kubernetes runner and dedicated
  workflow are implemented. An isolated Linux `colima-zebra-gvisor` cluster
  now passes the full runner (`WORKER_RESTART_RESUME`, quota, NetworkPolicy and
  cleanup); this is local task evidence, not remote canonical CI or managed
  production rollout evidence.
- `EMB-TOOL-CON-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. `ToolContract`/`ToolResult` now carry Host
  execution location, scopes, risk, bounds, idempotency and typed receipt
  metadata; transport, JWT and Trench implementation remain separate tasks.
- `EMB-AUTH-CON-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. The provider-neutral Host Grant/JWT contract
  pins algorithms, issuer/JWKS, exact origins, clock skew and bindings; JWT
  decoding, HTTP and PostgreSQL replay remain separate adapters.
- `EMB-AUTH-PG-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Migration v17, namespace-bound Host registry,
  secret-free Grant audit and atomic PostgreSQL `jti` replay now pass the real
  Compose runner (`4 passed`) and the existing control-plane migration runner
  (`11 passed`); HTTP/JWT and Trench remain out of scope.
- `EMB-AUTH-HTTP-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Cloud/production HTTP now requires an injected
  Host Grant authorizer before route dispatch, and CORS uses normalized exact
  HTTPS origins without reflection; focused auth/HTTP (`5 passed`) and existing
  HTTP/command/live/stream (`52 passed`) matrices are green.
- `EMB-AUTH-01` is in `Review` on `codex/cloud-real-svc-ci-01`. A signed RS256
  PyJWT decoder with bounded injectable JWKS resolution now composes with the
  PostgreSQL registry/replay authorizer; the production HTTP factory wires that
  authorizer by default for the concrete cloud store bundle, while explicit
  injection remains available for tests and alternate roots. The real Host
  PostgreSQL/API matrix is `5 passed`, with no raw token in HTTP/audit evidence.
- `EMB-AGUI-CMD-01` is `Review` on `codex/cloud-real-svc-ci-01`. The bounded
  `run`/`resume`/`stop` envelope resolves `threadId` to the active durable
  Segment and calls only the existing command service; focused command tests
  pass (`5`), with no Worker execution import or construction.
- `EMB-AGUI-STREAM-01` is `Review` on `codex/cloud-real-svc-ci-01`. The AG-UI
  SSE route validates exact durable cursors, replays and live-tails the Event
  Store, and emits official projected events with a lossless polling fallback.
  Replay/reconnect/live-tail tests pass in the combined matrix.
- `EMB-AGUI-API-01` is `Review` on `codex/cloud-real-svc-ci-01`. Command-only
  API composition, durable AG-UI replay/live tail and existing Host Grant HTTP
  gating pass together; it remains a parent review gate until this branch is
  merged and mainline gates are repeated.
- `EMB-HOST-GW-01` is `Review` on `codex/cloud-real-svc-ci-01`. The typed Host
  gateway verifies manifest digest and workload identity, intersects scopes,
  validates resource/idempotency/SSRF boundaries and returns bounded receipts;
  focused tests pass (`7`) and the Integrations package is `143 passed,
  3 skipped`.
- `EMB-TRN-READ-E2E-01` is `In Progress` on `codex/emb-trn-read-e2e-01`.
  Zebra now owns a fail-closed real-service runner for Trench/BFF/Zebra
  read-only acceptance, with nine named scenarios, secret-free evidence and a
  business-table snapshot invariant. Its contract tests pass (`4`), Ruff and
  targeted Mypy pass; the integrated Trench branch passes the focused backend
  (`66` API, `49` cleaning), migration SQL, frontend build/test/lint, and the
  Zebra branch passes the full quality gate (`2209 passed, 275 skipped`). The
  five local Cloudline runners (application, Redis fan-out, PITR, S3 recovery,
  and fresh restore) are green. The real cross-service run is still `BLOCKED`
  because this machine has no isolated Trench/Zebra HTTP, PG, Redis,
  object-store, Grant exchange or Worker-restart inputs; no cross-service pass
  is claimed. The previously recorded Worker composition seam is now closed by
  the active `EMB-HOST-RUNTIME-01` successor: `build_worker_tool_gateway`
  discovers the Host manifest, exposes its typed tools and routes Host calls
  without local fallback. The Trench-side `TRN-HOST-READ-AUTH-01` successor
  verifies the signed workload binding and preserves read-only scope/resource
  filtering. Both successors are in review on the integrated branches; the
  real cross-service runner remains fail-closed until isolated services and
  credentials are provisioned.
- `EMB-HOST-RUNTIME-01` is in `Review` on `codex/emb-host-runtime-01`. Zebra
  now carries an optional, expiry-aware HostContext from authorized API request
  through TASK_PREPARED persistence and Worker recovery; Worker discovery is
  manifest-first and fail-closed, and Host read tools are routed through the
  typed Host gateway with resource/idempotency binding. Full `make test` passes
  (`2207 passed, 275 skipped`), and `make check` plus the focused API/Core/
  Worker/Integrations/Effect Guard matrix pass. The branch does not claim
  deployment or a real Trench call.
- Gate 3 combined API/Integrations matrix is `204 passed, 3 skipped`; no Trench
  business Tool or Kubernetes gVisor E2E completion is claimed.
- `CLOUD-INTEGRATION-REG-01` is in `Review` on
  `codex/cloud-integration-regressions-01`. It fixes two regressions found on
  `zebra-cloud-trench`: Worker heartbeat now starts from the recovery-renewed
  Lease checkpoint, and local/test API Store composition is lazy again while
  explicit cloud startup remains fail closed. The focused matrix passes `33
  passed, 1 skipped`; the full backend suite is `2104 passed, 271 skipped, 1
  failed`, with only four out-of-scope repository size violations remaining.
- Cloud mainline status is recorded in
  [Zebra Cloud 主线当前状态与后续工作](./docs/Zebra%20Cloud%20主线当前状态与后续工作.md):
  PostgreSQL adapters, API/Worker PostgreSQL composition, application Compose,
  isolated Redis live fan-out and local migration/recovery evidence are complete;
  production recovery and the CopilotKit/Trench production slice remain gated.
  `CLOUD-CONTROL-PLANE-PG-01`
  implementation and focused validation are complete on the isolated branch;
  sidebar closeout is approved and the task is recorded as `Done`; its API/Worker
  mapping remains a later gate. `CLOUD-DELIVERY-TXN-PG-01` is also merged to the
  cloud mainline at `9ec52b16` and recorded as `Done`; its API/Worker wiring,
  runtime selection and external execution remain out of scope.
- Sidebar review of the requested API/Worker PostgreSQL switch returned
  `ACTIVATE-BLOCKED`: the defect is confirmed, but implementation is not authorized
  while the explicit profile contract and dependency registry are incomplete.
  The follow-up contract review returned `CONTRACT-ACCEPTED` and closed
  `CLOUD-PROFILE-COMPOSITION-CON-01` as `Done`; its `CLOUD-LIVE-01` dependency was
  removed because the contract has no live-runtime scope. `CLOUD-API-WORKER-PG-01`
  and `CLOUD-COMPOSE-APP-01` are now `Done` on the cloud mainline. Local SQLite
  remains the default and cloud must fail closed rather than fall back to SQLite.
- `CLOUD-API-WORKER-PG-01` completed its authorized implementation slice and is
  now `Done` after independent Review and fast-forward merge of `d9fd0419` into
  `zebra-cloud-trench`. Focused API/HTTP/Worker and real PostgreSQL Compose
  evidence is green. It owns only shared profile selection,
  PostgreSQL stores injection and the model/tool projection compatibility seam;
  it does not activate application Compose, Redis live, `CLOUD-LIVE-01`, or any
  aggregate gate.
- Context fencing conformance child `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01` is
  now `Done` on its governance worktree. Its Store-level semantic gap was closed
  by `CLOUD-AGG-FENCE-CTX-SEMANTIC-01`, which is also `Done` after sidebar
  `CLOSEOUT-OK`, three zero-write regressions and a real PostgreSQL `18/18`
  focused matrix. The parent `CLOUD-AGG-FENCE-01` is now `Done` as a governance
  gate; the Model/Tool revision successor is now closed as `Done`.
- `CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01` is now `Done` with audit result
  `PASS`; its reserve/abort successor is `Done`, and the dispatch successor
  `CLOUD-AGG-FENCE-DISPATCH-01` is fast-forward merged and closed as `Done`.
  The mainline PostgreSQL runners pass `15/15` and `14/14` with
  `ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=PASS` and
  `ZEBRA_HANDOFF_DISPATCH_POSTGRES_TEST_RESULT=PASS`.
- `CLOUD-LIVE-01` is `Done` after completing and fast-forward merging the
  separately owned Redis live event fan-out slice at `cfbebcf7`. It remains
  limited to a provider-neutral Port, a
  bounded Redis Streams adapter and isolated evidence; the local Core/adapter
  matrix is `24/24` (including the non-blocking read and namespace validation
  regressions), the full integrations package is `127 passed, 3 skipped`,
  and the pinned `redis:8.2.1-alpine` host runner passes `1/1` with
  `ZEBRA_LIVE_FANOUT_REDIS_TEST_RESULT=PASS`. The detailed matrix is recorded
  in `docs/CLOUD-LIVE-01.md`. It does not authorize API/Worker startup wiring,
  application Compose, Runtime selection or any Redis authority.
- `CLOUD-COMPOSE-APP-01` is now `Done` on
  `codex/cloud-compose-app-01`. It owns only the non-root multi-target Zebra
  image, the application-only migration/API/Worker Compose overlay and isolated
  smoke evidence; host-side cloud composition already proves API health,
  `PostgresControlPlaneStores` and one Worker PostgreSQL cycle. The production
  `--no-dev` image now declares `uvicorn` as an API runtime dependency, and the
  complete three-container smoke passes with a temporary mirror-only Python
  base override (runtime UID `65532`) and now through the Application Compose
  default mirror with `ZEBRA_APPLICATION_COMPOSE_TEST_RESULT=PASS`. The
  Dockerfile keeps the official Docker Hub digest as its standalone default;
  that direct build remains an external review gap. The base dependency Compose
  remains a separate lifecycle.
- `CLOUD-AGG-FENCE-01` is now `Done` as a governance gate after the aggregate
  review's `PASS` evidence and maintainer continuation closeout. This unlocks
  only the recovery evidence sequence; Runtime/API/Worker selection and
  production rollout remain separate gates.
- `CLOUD-REC-01` is now `Done` as the local recovery evidence gate:
  `CLOUD-PG-MIG-01`, `CLOUD-REC-BACKUP-01`, `CLOUD-REC-RESTORE-01` and
  `CLOUD-REC-DRILL-01` are all independently validated and merged. The local
  drill proves rollback, fenced claim/reconcile races and zero-loss Event
  counts; no production RPO/RTO, PITR or DR claim is made from Compose.
- `CLOUD-PG-MIG-01` is now `Done` on `codex/cloud-pg-mig-01`. The completed
  slice provides canonical read-only SQLite snapshots, migration v16 cutover
  fencing, restricted Event-first import, Session/Workspace/Task rebuild,
  Event-derived Model/Tool projection replay, Context capsule/pointer
  verification, and fenced Handoff operation/envelope/dispatch replay with
  rebuilt-lineage checks, plus namespace-scoped idempotency and governed Memory
  replay, and rowid-evidenced Delivery Audit replay through snapshot v2. The
  PostgreSQL 17.5 runner passes `29/29` with
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS` and deterministic cleanup. New
  zero-write regressions reject legacy Artifact, Effect and Provider
  continuation tables before Event writes; their cloud authority mappings are
  closed as explicit quarantine contracts and runtime ACTIVE write wiring remains
  gated. The PostgreSQL 17.5 runner passes `29/29` with
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS` and deterministic cleanup.
- `CLOUD-PG-MIG-LEGACY-CON-01` is now `Done` as the governance parent after all
  three path-bounded children were explicitly activated, independently
  validated and merged.
  `CLOUD-PG-MIG-LEGACY-ARTIFACT-01` is now `Done` after merge commit `bed02e4a`
  from `codex/cloud-pg-mig-legacy-artifact-01`. Its deterministic
  Artifact legacy quarantine/export contract and evidence runner pass the local
  focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5 runner (`5 passed`,
  `ZEBRA_PG_MIG_LEGACY_ARTIFACT_TEST_RESULT=PASS`) with cleanup.
  `CLOUD-PG-MIG-LEGACY-EFFECT-DELIVERY-01` is now `Done` after merge commit
  `62d2e601` from `codex/cloud-pg-mig-legacy-effect-delivery-01`. Its
  deterministic Effect/Delivery quarantine/export contract and evidence runner
  pass the local focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5
  runner (`5 passed`,
  `ZEBRA_PG_MIG_LEGACY_EFFECT_DELIVERY_TEST_RESULT=PASS`) with cleanup.
  `CLOUD-PG-MIG-LEGACY-PROVIDER-01` is now `Done` after merge commit
  `5f275d4b` from `codex/cloud-pg-mig-legacy-provider-01`. Its deterministic
  Provider Continuation quarantine/export contract and evidence runner pass the
  local focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5 runner
  (`5 passed`, `ZEBRA_PG_MIG_LEGACY_PROVIDER_TEST_RESULT=PASS`) with cleanup.
  No cloud Artifact/Effect/Provider authority write or runtime wiring is implied.
- The current cloud governance slice
  `CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01` is now `Done` with audit result `PASS`.
  Its direct Task authority gap is implemented by `CLOUD-AGG-FENCE-TASK-01` at
  `6a31929a`; the focused Task PostgreSQL regression passes `23/23` and
  Handoff/dispatch regression passes `24/24`. The repository-owned
  `CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01` runner is also `Done` at
  `49a8c026`, passing `36/36` on PostgreSQL `17.5-alpine3.21` with deterministic
  cleanup. The parent `CLOUD-AGG-FENCE-01` is now `Done` and no Runtime or
  application Compose activation is implied.
- `CLOUD-AGG-FENCE-MODEL-TOOL-01` is `Done` at implementation commit
  `31347989`. The PostgreSQL adapter now binds a Worker Model/Tool projection
  Event to `expected_stream_revision` and the current stream; its dedicated
  runner passes `8/8` with `ZEBRA_MODEL_TOOL_POSTGRES_TEST_RESULT=PASS`, while
  the existing Control Plane runner passes `11/11`. Both runners clean their
  resources. The parent gate is now `Done` and no runtime activation is
  implied.
- `CLOUD-AGG-FENCE-PROVIDER-01` is `Done` at implementation commit
  `816a1ae0`. `delete_for_worker` now binds the current LeaseFence and
  `expected_stream_revision` to the locked Session stream before soft-delete;
  its reproducible PostgreSQL 17.5 runner passes `4/4` with
  `ZEBRA_PROVIDER_CONTINUATION_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources. The parent `CLOUD-AGG-FENCE-01` is now `Done`.
- `CLOUD-AGG-FENCE-ARTIFACT-01` is `Done` as an evidence-only conformance
  slice. The repository-owned PostgreSQL 17.5 runner passes `13/13` with
  `ZEBRA_ARTIFACT_PAYLOAD_POSTGRES_TEST_RESULT=PASS` and cleans all resources;
  the existing v9 transitions already use the shared namespace, LeaseFence,
  stream CAS and lifecycle revision guards. No adapter or migration changed;
  the parent gate is now `Done`.
- `CLOUD-AGG-FENCE-EFFECT-PAYLOAD-01` is `Done` as an evidence-only
  conformance slice. Its repository-owned PostgreSQL 17.5 runner passes `7/7`
  with `ZEBRA_EFFECT_PAYLOAD_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources; existing payload-aware Effect transitions bind Worker authority
  and atomically coordinate Event, Artifact and outbox state. No adapter or
  migration changed; the parent gate is now `Done`.
- `CLOUD-AGG-FENCE-DELIVERY-01` is `Done` as Delivery boundary evidence.
  Delivery is intentionally an API command claim/receipt lane, not a Worker
  Lease aggregate; its corrected PostgreSQL 17.5 runner passes `12/12` with
  `ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources. No adapter or runtime wiring changed; the parent gate is now
  `Done`.
- `CLOUD-AGG-FENCE-REVIEW-01` is `Done` with result `PASS`. All registered
  path-bounded aggregate evidence is green: Context `18/18`, Handoff
  auth/dispatch `15/15` and `14/14`, Workspace/Task `36/36`, Model/Tool `8/8`,
  Provider `4/4`, Artifact `13/13`, Effect/Artifact `7/7` and Delivery `12/12`.
  The parent `CLOUD-AGG-FENCE-01` is now `Done` after maintainer continuation
  closeout; this does not authorize runtime or application Compose activation.
- `CLOUD-PROVIDER-CONT-PG-PLAN-01` is formally `Done` after sidebar
  architecture review. `CLOUD-PROVIDER-CONT-PG-01` is now `Done` on the isolated
  `codex/cloud-provider-cont-pg-01` worktree, based on `f6c8a926`, with its Core
  contract, PostgreSQL v13 adapter/migration, cloud Worker aggregate seam,
  focused tests, Compose evidence and review fixes committed as `39bbe444` and
  `abd7a7f0`. The sidebar closeout accepted the evidence, and the next storage
  composition card `CLOUD-CONTROL-PLANE-PG-01` is now `Done` after sidebar
  closeout on its isolated implementation branch. Runtime,
  API/Provider HTTP, Desktop, local SQLite, Redis, Mem0 and application Docker
  remain excluded.
- Review task: `CTX-MEM-01` is in PR `#198` and closes the valid parts of GitHub issue `#197` with
  an exact three-user-turn tail, complete tool groups, one strict retry from
  original history, recoverable context suspension, evidence-gated memory
  promotion, and repo-scoped SQLite FTS recall under a token budget. Local
  validation: `63` focused tests, changed-file Ruff, Mypy over `158` source
  files, and release eval `10/10` pass. Full suite: `1747 passed, 8 skipped`;
  the same nine failures reproduce on untouched `main`. The current file-size
  gate is blocked by four inherited violations outside this task. PR CI run
  `30332213200` did not execute any step because GitHub reported an account
  payment/spending-limit gate.
- Verified implementation baseline: `f1e4965` (PR `#174`)
- Product posture: `embeddable Agent Runtime / feature-complete local Beta / single-host Phase A complete`
- Review task: `CTX-SEG-01` has delivered the stable Task, internal Segment,
  unified stream/routing, automatic safe rollover, and SQLite migration slice.
- Active repair task: `CTX-SEG-02` preserves the latest bounded conversation
  checkpoint across terminal follow-up Segments, removes implicit low call
  ceilings, and converts explicit hard-budget exhaustion into recoverable pause.
- Review task: `SUBAGENT-UX-01` makes Subagent use a model-native tool decision;
  simple work remains in the parent and every valid delegation records its reason.
- Active architecture task: ADR-013 replaces user-visible child Sessions with a
  stable Task boundary and backend-internal execution Segments.
- Desktop browser task: `QA-DESKTOP-E2E-01` is Done via PR `#161`
- Runtime blueprint: `ARCH-RT-BP-01` is complete on its local task branch
- Completed Embedded architecture task: `EMB-PLAN-01` on `zebra-cloud-trench`
  replaces the conflicting draft with one CopilotKit/AG-UI target, ADR-015, and
  a dependency-ordered task roadmap. Formal review closed it as `Done`; it is
  documentation-only and does not activate Phase B or any Trench implementation
  card.
- Compatibility task `EMB-AGUI-SPIKE-01` is formally `Done` on the test-only
  closeout branch. It pins `ag-ui-protocol==0.1.19`, validates the canonical SSE,
  interrupt/resume and forward-compatibility boundaries with `11/11` focused
  tests, and adds no production API/Worker, CopilotKit, React SDK or UI wiring.
- Trench `TRN-CPK-SPIKE-01` is merged to Trench `main` at `5c59b22`; its
  focused/full checks, frontend builds, Alembic checks and `git diff --check`
  pass. `EMB-HOST-CON-01` is `Done` on `codex/emb-host-con-01` at
  `ca59753b`: provider-neutral Core Host authority claims, context derivation,
  bounded limits and fail-closed validation pass `16/16` focused and `386/386`
  `agent_core` tests. JWT/JWKS, API/AG-UI, Trench and runtime wiring remain
  separately gated.
- `EMB-AGUI-CON-01` is `Done` on `codex/emb-agui-con-01` at `5485fc2e` after
  Host authority closeout. Its pure, replayable AG-UI projection passes `5/5`
  focused and `132 passed, 3 skipped` package tests; API/Worker routes, Redis
  live fan-out, Trench/CopilotKit runtime and Host transport remain separately
  gated.
- Completed storage composition task: `CLOUD-STO-SEAM-01` on `codex/cloud-sto-seam-01` is the
  first Zebra-foundation task after the maintainer reprioritized durable storage
  and memory ahead of further Trench work. It injects existing control-plane Store
  Ports while preserving the local SQLite profile and adds no cloud dependency.
  Formal review closed it as `Done`; PostgreSQL, Redis, S3 and backend selection
  remain separate gates.
- Completed authoritative storage task: `CLOUD-STO-AUTH-01` on
  `codex/cloud-sto-auth-01` extends that same flat bundle across every durable
  API/Worker collaborator that advances Session state, gates effects or governs
  memory. A/B regressions prove the legacy path is not created; no cloud backend,
  migration or Mem0 integration is selected by this task. Formal review closed
  it as `Done`; Compose, PostgreSQL and Memory Gateway remain separate gates.
- Memory contract task `MEM-GW-CON-01` is formally `Done` on `codex/mem-gw-con-01`; it defines
  provider-neutral confirmed-memory publish, search and delete outcomes. Remote
  hits contain only a Zebra `MemoryId` for mandatory Store revalidation; no Mem0
  adapter, credential, Docker or runtime wiring is part of this slice.
- Completed dependency-container task: `CLOUD-COMPOSE-INFRA-01` on
  `codex/cloud-compose-infra-01` creates the base Docker Compose dependency stack
  and a separate optional Mem0 boot-smoke overlay. Its pinned image, migrations,
  health and anonymous-request rejection are verified locally. Mem0 remains
  derived and replaceable; Zebra application containers stay locked until real
  cloud adapters exist. Formal review closed the dependency baseline as `Done`;
  no Docker-socket operation or runtime selection was made here.
- PostgreSQL Event/Projection storage: `CLOUD-PG-01` is formally `Done` with
  isolated adapters, migration checksums, CAS/idempotency, namespace isolation
  and replay-safe projections. Recorded real PostgreSQL evidence is accepted;
  it is not runtime-selected. `CLOUD-LEASE-PG-01` separately covers
  epoch-scoped, database-clock Lease fencing.
- Lease/fencing contract plan: `CLOUD-LEASE-PLAN-01` is formally `Done`; it
  freezes epoch ownership, database-time TTL, fenced aggregate boundaries and
  uncertain external-effect recovery, while its implementation children retain
  independent gates and no runtime selection.
- Memory storage implementation: `MEM-GW-PG-NATIVE-01` is formally `Done` as a
  PostgreSQL-native, storage-only Memory Gateway with migration v12 and accepted
  isolated evidence. The native admission is `PASS`; Mem0 remains
  denied/deferred and all Runtime/Worker/provider paths stay locked.
- Effect Outbox task in Review: `CLOUD-EFFECT-OUTBOX-01` now has typed Core
  dispatch states and a PostgreSQL aggregate for fenced schedule, `SKIP LOCKED`
  claim, terminal commit, uncertain reconciliation and explicit retry. Its isolated
  Docker Compose PostgreSQL 17.5 matrix passes `49/49`, including fault rollback,
  concurrency, restore epoch, namespace and response-loss cases. It is not runtime-
  selected; Worker integration and any cloud-readiness claim remain locked.
- Integrated Effect consumer task: `CLOUD-EFFECT-CONSUMER-01` runs Lease heartbeat
  on a background thread before recovery, checks ownership at Event and external
  Effect boundaries, and releases through one fenced lifecycle exit. Explicitly
  injected cloud runtimes can now schedule, claim and terminalize durable Effect
  intents; expired claims become `uncertain` for reconciliation and never auto-
  replay. The local SQLite profile still uses its existing ledger, and no backend
  selector or production cutover is included. Its isolated Docker Compose
  PostgreSQL 17.5 consumer matrix passes `58/58`, including heartbeat, stale-fence,
  crash, response-loss and reconciliation cases; dedicated containers, volumes and
  network were removed after the run. Deterministic and full-suite gates retain
  only the confirmed inherited failures.
- Local microservice integration: the reviewed Lease contract, PostgreSQL Lease,
  Effect Outbox and Worker consumer cards are fast-forwarded onto the isolated
  `zebra-cloud-trench@2759345c`. `CLOUD-LEASE-01` is formally `Done` with its
  combined evidence record; it does not select PostgreSQL at runtime or claim
  full aggregate fencing, production cutover or exactly-once external execution.
- Completed aggregate-fencing inventory: `CLOUD-AGG-FENCE-PLAN-01` traces the
  authoritative Context, Handoff, Workspace/Task, Model/Tool, provider-history,
  Artifact and delivery-audit paths and splits them into dependency-ordered cards.
  It keeps Event-derived/read-only models out of the authority layer and API
  commands outside Worker Lease fencing. It is documentation-only and unlocks only
  `CLOUD-AGG-FENCE-CON-01`; the parent gate and adapter cards remain Locked.
- Context fencing conformance is now explicitly split into a governance audit and
  a minimal semantic successor. The audit matrix covers Worker compaction,
  administrative recovery, v7 constraints, fail-closed legacy methods and
  read-only Context Materialization. It records accepted stale-fence, namespace,
  pointer and rollback evidence, but keeps the audit card open until the semantic
  successor's review closes the former Event type and capsule binding gap. The
  successor adds only Store validation, focused tests and a PostgreSQL Compose
  runner; no migration or runtime composition is changed.
- Completed authority-contract task: `CLOUD-AGG-FENCE-CON-01` adds strict
  `WorkerMutationAuthority` and `AdministrativeMutationCAS` types. It reuses the
  existing LeaseFence, permits the empty-stream revision `-1`, rejects noncanonical
  namespaces and keeps aggregate-specific revisions out of the shared type. Its
  focused `19/19`, Core `270/270`, Ruff, strict Mypy and Eval `10/10` gates pass;
  it does not implement PostgreSQL, change Store selection or touch Desktop. Its
  local acceptance unlocks only `CLOUD-AGG-WORKSPACE-PG-01`.
- Added the sole current cloud `Ready` card, `CLOUD-SCOPE-CON-01`, to freeze the
  external opaque `(authority_issuer, namespace_id)` plus bounded
  `allowed_session_ids` read scope. The contract deliberately maps to the
  injected deployment namespace in trusted composition and adds no Tenant model,
  SQL, Runtime selection, Provider HTTP, Desktop, Redis or Mem0 behavior. Its
  successors are the still-locked Provider Continuation and Session History
  adapters.
- `CLOUD-SCOPE-CON-01` is now `Done`: `OpaqueAuthorityScope` is immutable,
  rejects malformed or over-broad allow-lists, preserves the full-scope versus
  deny-all distinction, and leaves external-to-deployment namespace mapping to
  trusted composition. Focused Core `9/9`, full Core `347/347`, relevant
  regressions `32/32` and Eval `10/10` pass; only the two inherited file-size
  violations keep `make check` red. Provider Continuation and Session History
  remain independently locked pending explicit adapter activation.
- `CLOUD-SESSION-HISTORY-PG-01` is now `Done`. It adds only a namespace-scoped
  PostgreSQL read adapter, JSONB row decoding, parity/isolation tests and an
  isolated Compose runner. Local focused validation is `13 passed, 3 skipped`,
  host PostgreSQL Compose validation is `3 passed` with
  `ZEBRA_SESSION_HISTORY_POSTGRES_TEST_RESULT=PASS`, changed static checks and
  Eval `10/10` pass. Provider Continuation, complete Store composition, Runtime
  selection and external Host verification remain out of scope.
- `CLOUD-CONTEXT-CON-01` is now `Done`. ADR-020 and the Core-only
  `ContextMaterializationPort` freeze a read-only, rebuildable generation across
  Session History, the active Context Capsule and confirmed governed Memory.
  Focused contract coverage is `3/3`, related scope/Capsule coverage is `16/16`,
  full Core is `350/350`, changed static checks and Eval `10/10` pass. The
  `CLOUD-CONTEXT-PG-01` is now `Done`: its read-only PostgreSQL adapter and
  isolated Compose runner are implemented, with local Storage `149 passed, 172
  skipped`, Core `350/350`, Eval `10/10`, and host Compose `4 passed` with
  `ZEBRA_CONTEXT_MATERIALIZATION_POSTGRES_TEST_RESULT=PASS`. No Runtime,
  Worker, API, Desktop, SQLite, Redis or Mem0 path is unlocked.
- Completed and formally closed Workspace adapter task: `CLOUD-AGG-WORKSPACE-PG-01`
  adds the additive
  PostgreSQL v4 projection schema and an injected Worker transaction that validates
  current Lease authority and Event-derived Session/Workspace content before
  committing all three primary records atomically. Replay remains monotonic and
  namespace-scoped; Model Call/Tool Run indexes remain replayable follow-up views.
  Lost-response retries now adopt the canonical stored Event and projections
  rather than the regenerated request envelope. Focused Ruff, Core/Storage strict
  Mypy, microservice file-size over `907` tracked and new files, `467 passed, 64
  skipped` backend regressions and Eval `10/10` pass. The final host PostgreSQL
  17.5 matrix passes `80/80`, including stale authority, rollback, semantic
  derivation and canonical lost-response retry paths. Formal review of the
  integrated implementation and its sole `Done` dependency closed the card as
  `Done`; it unlocks only `CLOUD-AGG-TASK-PG-01`. `CLOUD-CONTROL-PLANE-PG-01`,
  not this card, owns the cloud Worker composition root and runtime backend
  selection.
- Completed and formally closed Task/Segment adapter task:
  `CLOUD-AGG-TASK-PG-01` adds PostgreSQL v5,
  a namespace-scoped Task read model, deterministic explicit rebuild and a
  connection-scoped rollover primitive. Reads never write; rebuild and rollover
  share a Task advisory lock, Handoff Event pairs are validated by common identity,
  and composite foreign keys prevent cross-Task ownership. Ruff, strict Mypy over
  `166` files, the `911`-file microservice size gate, `473 passed, 77 skipped`
  related regressions and Eval `10/10` pass. The real PostgreSQL 17.5 matrix passes
  `32/32`; formal review of the integrated implementation and its `Done` authority
  dependency closed the card as `Done` and unlocks only
  `CLOUD-MODEL-TOOL-PG-01` for the next serialized migration. Context and Handoff
  continue planning in separate sidebar tasks without writing the migration hotspot.
- Completed and formally closed Model/Tool projection task:
  `CLOUD-MODEL-TOOL-PG-01` adds replayable PostgreSQL v6 Event-derived
  projections. Its focused Worker tests pass `7/7` and its isolated PostgreSQL
  migration/projection matrix passes `7/7`; the card is `Done` after dependency
  and path review. `CLOUD-AGG-CTX-PG-01` is now also formally closed as `Done`
  after its recorded isolated PostgreSQL `14/14` and SQLite/Worker `11/11`
  evidence; Context administrative recovery remains a separate Review card and
  neither selects the cloud runtime.
- Completed and formally closed Artifact contract task: `CLOUD-ART-OBJ-CON-01` freezes provider-neutral Artifact
  object/metadata authority before any SDK or adapter. ADR-017 separates stable
  `artifact://` identity from temporary access URLs and opaque external references,
  freezes staged/finalize/compensate recovery plus fenced Worker and management
  authority, and leaves provider, key encoding, API delivery and runtime selection
  unchosen. It unlocks planning for `CLOUD-ART-PAYLOAD-PG-01`; Artifact lifecycle,
  object and payload adapters remain separately gated. `CLOUD-AGG-HANDOFF-CON-01`
  is now formally closed as `Done`: it adds a tokenized Lease-fenced SQLite
  dispatch receipt before the PostgreSQL Handoff aggregate, with `290` recorded
  related tests and a current-HEAD focused `22/22` regression check. SQLite work
  stops at this compatibility contract. `CLOUD-AGG-HANDOFF-PG-01` remains the
  next v8 migration Review gate, while Artifact payload implementation remains
  locked.
- Completed and formally closed Context follow-up: `CLOUD-AGG-CTX-ADMIN-PG-01` reuses the v7
  administrative CAS only for historical capsule recovery in an explicitly injected
  PostgreSQL store. API recovery consumes the canonical Event/Session/Workspace result
  without a second projection write; the transaction rejects missing or changed
  projections and updates the active pointer with recovery Event time. Its isolated
  PostgreSQL 17.5 matrix passes `19/19`. It does not add PostgreSQL manual compact,
  Desktop behavior or runtime backend selection. Formal dependency/path review
  closed the card as `Done`; the dedicated PostgreSQL recovery adapter and matrix
  test are now explicitly recorded in its Owned paths.
- Completed and formally closed Handoff v8 aggregate slice preserves the exact v1-v7 migration names and
  checksums while splitting migration types, execution and the v8 catalog into focused
  files. The real PostgreSQL 17.5 migration matrix passes `6/6`; v8 adds only
  namespace-scoped operation, database-guarded immutable envelope and fenced dispatch
  tables, reusing
  the v5 Task/Segment index instead of creating a second lineage authority. A canonical
  request digest binds reserve, fresh commit and lost-response replay; the atomic
  transaction covers parent/child Events, projections, Task rollover, Envelope,
  dispatch and operation state. Child Workspace state remains fully Event-rebuildable.
  Dispatch uses database-time expiry, `FOR UPDATE SKIP LOCKED`, rotated tokens and exact
  full-fence ACK; Worker recovery now threads the acquired fence and cloud drift writes
  use the existing fenced projection transaction. The isolated PostgreSQL aggregate
  matrix passes `20/20`; Core/Storage/API/Worker pass `822/822` with `102` skips.
  Formal dependency/path review closed `CLOUD-AGG-HANDOFF-PG-01` as `Done`; no
  runtime, provider, Desktop or application Compose selection was made.
- Artifact v9 preflight confirmed that the local `ArtifactPayloadStorePort` lacks
  namespace/fence/staged lifecycle semantics. The v9 card requires the reviewed
  fenced cloud lifecycle Port and reserve -> object verification -> Event ->
  finalize/compensate ordering; its object boundary is direct botocore with MinIO
  bucket versioning and exact object-version evidence. It explicitly excludes SQLite,
  Desktop, runtime selection, Effect linkage and API read composition.
- Completed and formally closed Artifact v9 review slice starts from integrated Handoff v8 at
  `cfe40713`. `CLOUD-ART-PAYLOAD-PG-01` owns the PostgreSQL lifecycle metadata,
  provider-neutral object orchestration, Worker Event binding and isolated
  PostgreSQL/MinIO fault matrix; it does not select a runtime backend or add Desktop.
  The v9 migration foundation now adds one authoritative lifecycle metadata table,
  non-authoritative mutation/audit ledgers, exact Event/stream/fence bindings and
  reconcile/retention indexes. Core supplies one canonical reservation digest, while
  `(namespace, artifact_id)` remains the logical object locator and only the S3 adapter
  derives its private key. The PostgreSQL adapter now implements the complete fenced
  Worker lifecycle, canonical Event JSON binding, DB-owned transition timestamps,
  safe compensation, audited management recovery and Session-scoped reconcile reads.
  Isolated PostgreSQL 17.5 migration/lifecycle tests pass `19/19`. Worker orchestration
  now uses a default-off injection seam with strict reserve -> versioned put/head ->
  receipt -> Event -> finalize ordering. Managed URI spoofing fails closed, external
  references remain opaque, and uncertain outcomes remain staged for management
  reconcile. The real
  PostgreSQL+MinIO matrix passes `30/30`, including lost put/Event acknowledgements,
  sequence drift, finalize failure and concurrent retention prune. Worker/Runtime
  pass `260/260` with `16` environment-gated skips; Storage passes `131/131` with
  `114` environment-gated skips. Formal dependency/path review closed
  `CLOUD-ART-PAYLOAD-PG-01` as `Done`; Effect linkage, read composition and
  Runtime/provider selection remain separate gates.
- Completed and formally closed Effect/Artifact review slice `CLOUD-EFFECT-PAYLOAD-ATOMIC-01` starts from
  `zebra-cloud-trench@b87760b6`. Its dependencies are integrated; it owns the narrow
  transaction that binds the verified Effect request Artifact to the intent Event and
  Effect outbox row. Stable request identity, finalized-only cross-Worker reads and
  terminal result Artifact binding are implemented without migration v10. Real
  PostgreSQL+MinIO tests pass `53/53`; Tools/Worker/Runtime pass `418/418` and Storage
  passes `131/131`. Formal dependency/path review closed it as `Done`; it excludes
  SQLite, Desktop, runtime selection and delivery APIs.
- Completed and formally closed Artifact read-composition review slice `CLOUD-ART-READ-COMP-01` starts from
  `zebra-cloud-trench@4480ca66` after both PostgreSQL Model/Tool v6 and Artifact
  payload v9 dependencies were integrated. It adds one-snapshot namespace-scoped
  reads over those existing facts and injects a separate required payload-read
  capability through the current API store boundary. Canonical URI, exact Event
  binding, finalized lifecycle, recorded object version and verified bytes are all
  required; cloud composition disables legacy prune. The real PostgreSQL+MinIO matrix
  passes `39/39`, full tests pass `1943` with `145` gated skips, and no Artifact table
  or migration, SQLite feature, Desktop path or runtime backend selector was added.
  Formal dependency/path review closed it as `Done`; delivery APIs and complete
  Control Plane remain separate gates.
- Completed governed-memory planning slice `CLOUD-MEMORY-PG-PLAN-01` starts from
  `zebra-cloud-trench@f9568e34`. Audit confirmed the cloud branch still has only a
  SQLite `MemoryStorePort`; Mem0 is correctly derived but its future delivery ledger
  would otherwise depend on a local fact source. This docs-only card is formally
  `Done` and freezes the
  PostgreSQL Memory authority and atomic review boundary before migration or delivery
  implementation. The reviewed plan assigns v10 to governed facts/operation receipts,
  then v11 to Mem0 delivery; final review found no open P0/P1. Session History remains
  Locked on trusted Host scope.
- Completed governed-memory Core slice `CLOUD-MEMORY-CON-01` is formally `Done` and starts from integrated
  plan `2c43af0f`. It adds provider-neutral revision/CAS, content-free operation
  receipts and tombstones, plus pure candidate/promotion/review planning while
  preserving local wrapper behavior. Worker/Admin requests bind Session CAS and
  canonical payloads without coupling retry identity to LeaseFence or regenerated
  IDs/timestamps. Core tests pass `320/320`, API/Worker pass `411` with `14` gated
  skips, strict Core Mypy and changed-path Ruff pass, and release Eval is `10/10`.
  Full tests are `1971 passed, 145 skipped` with the sole inherited 561/500 Desktop
  file-size violation reproduced on the untouched cloud mainline.
  PostgreSQL v10, Mem0 v11, runtime selection, SQLite feature work and Desktop remain
  outside this task.
- Completed PostgreSQL governed-memory slice `CLOUD-MEMORY-PG-01` is formally `Done` and starts from integrated
  Core contract `4bda7f72`. It adds v10 authority/receipt storage, exact namespace reads,
  restart-safe content-free scans, Worker/Admin aggregate transactions and repeatable
  read-only SQLite import tooling. The isolated PostgreSQL 17.5 matrix passes `29/29`;
  full tests pass `1977` with `162` gated skips and only the inherited Desktop size
  failure. Runtime wiring was deliberately removed after review exposed terminal-event,
  active-set and mixed-store recovery gaps; it remains gated on one coherent cloud
  composition. Mem0 delivery, Desktop/SQLite feature work and production cutover remain
  excluded.
- Completed and formally closed Artifact contract slice: `CLOUD-ART-LIFECYCLE-CON-01` separates the
  provider-neutral cloud lifecycle Port/domain from the unchanged local
  `ArtifactPayloadStorePort`. It can proceed in Core without touching Handoff v8,
  PostgreSQL, MinIO, SQLite, Worker composition or Desktop, and becomes the explicit
  contract dependency for Artifact v9. The Core contract now freezes exact
  Event/object evidence, Worker versus management authority, safe cleanup evidence
  and staged/finalized/compensated/pruning/pruned shapes without changing local
  behavior. Its provider-neutral contract gate is `Done`; object, payload, Effect,
  read-composition and Runtime cards remain separate.
- Completed and formally closed object adapter slice: `CLOUD-ART-OBJECT-S3-01` implements the immutable
  S3-compatible bytes boundary and MinIO versioning against the reviewed Core Port.
  Conditional put, canonical retry, digest/size verification, exact-version read and
  delete, namespace-private keys and typed provider failures pass an isolated real
  MinIO cross-client matrix (`15/15`). All storage tests pass `130` with `87` gated
  skips and strict storage Mypy passes `49` files. PostgreSQL metadata, lifecycle
  orchestration, runtime selection, signed delivery, SQLite and Desktop remain
  untouched. Its object boundary is `Done`; PostgreSQL metadata, lifecycle
  orchestration, Effect linkage, reads and Runtime remain separate gates.
- Business-baseline recovery is active before cloud-stack integration. Exact replay
  on `zebra-cloud-trench@375dca92` reproduces all `9/9` remaining failures. Four
  path-bounded microservice cards own provider expectations, SCM credential
  fixtures, Worker cancellation convergence and Core Event contract
  extraction. All four microservice repair cards are locally integrated after the
  provider, SCM, cancellation, Core file-size, backend and Eval gates pass. Desktop
  is explicitly outside the new Zebra microservice mainline.
- Agent Definition architecture task `AGENT-DEF-ADR-01` is Done: ADR-016 records
  accepted Definition control-plane decisions and updates the final architecture.
  It separates Task-level Definition configuration from Attempt-level execution
  authority and preserves ADR-012's opaque external namespace. `AGENT-DEF-CON-01`
  is now Done: its frozen provider-neutral Definition/Version/Release models,
  deterministic digest/reference validation and Registry Port are merged, with
  `355/355` focused Core tests and changed static checks passing. The follow-up
  `AGENT-AUTH-SNAPSHOT-01` is now Done on
  `zebra-cloud-trench@50ad8d1c`: it owns only the schema, resolver Port, durable
  pre-Attempt event and narrowly injected Worker seam, with recoverable
  latest-snapshot revalidation. Focused authority `6/6`, Core `355/355` and
  Worker `93 passed, 13 skipped` are green; the full suite's single failure is
  the two inherited file-size violations outside this task. No implementation
  task is currently active; the cloud mainline is waiting for maintainer
  activation of a registered successor. Local SQLite Registry work is
  intentionally deferred on this cloud microservice mainline, while storage,
  API and runtime wiring remain locked.
  The implementation order is
  `CON -> AUTH`, then `{DRAFT,AUTH} -> BIND -> MEM -> TRUST -> EVAL -> PUB`;
  PostgreSQL Registry remains a separately gated adapter.
- Web Intelligence planning: `WEB-INT-PLAN-01` is a documentation-only review
  slice defining a provider-neutral native `web.*` surface over a replaceable
  wigolo Provider, Zebra-owned orchestration/security, and durable Watch. Its
  implementation cards remain Locked; no wigolo runtime or new native Tool is
  delivered.
- Locked architecture tasks: Web Intelligence implementation, ACP entry and
  optional code intelligence
- Open product issue: none; `#148` closed with PR `#156`
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
- Completed documentation task: `EXT-PLAN-01` records the Skill, MCP, and Plugin
  extension upgrade architecture, authority boundaries, phased task map, and
  acceptance gates. It changes no product capability and does not activate the
  deferred marketplace or remote MCP work.
- Active harness task: `HAR-TOOL-RECOVERY-01` enforces the durable contract
  that a single `ToolCallStatus.FAILED` (HTTP 4xx, missing file, timeout) must
  surface as a structured observation for model-selected correction rather than
  directly producing `session_failed`. Changes: repeated tool calls become
  observations with a threshold-gated `loop_guard_exhausted` hard stop (default
  3), sequential batches continue executing remaining tools after a mid-batch
  failure (matching concurrent-batch semantics), and a provider protocol
  firewall (`protocol_invariants.py`) validates tool-call/tool-result pairing
  before every model request to prevent `invalid_request` leakage.
- Model-response acceptance is now a separate provider-neutral boundary:
  malformed body/SSE/tool-call output becomes `ModelResponseRejectedError`,
  tool-capable stream deltas are committed only after validation, one bounded
  repair is allowed within the model-call budget, and exhaustion produces a
  recoverable `SESSION_SUSPENDED` rather than `session_failed`. Provider
  transport retries and semantic repairs have separate trace counters. The
  implementation and regression cases are present in the working tree; runtime
  validation has not been executed in this session.

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
- `EMB-PLAN-01`, `EMB-AGUI-SPIKE-01`, `CLOUD-STO-SEAM-01`, and
  `CLOUD-STO-AUTH-01` are formally Done for their architecture, protocol and
  local Store-composition slices. Production AG-UI, Trench and cloud backend
  selection remain separately gated.
  `MEM-MEM0-ADP-01` is formally Done as a disabled-safe integration contract;
  it is not runtime-selected. `MEM-MEM0-SPIKE-01` is formally Done for its
  pinned OSS contract evidence; the provider-neutral
  Memory Gateway contract, Core delivery-certainty contract, PostgreSQL-native
  admission Spike, PostgreSQL-native storage gateway, and PostgreSQL v11
  delivery ledger are formally Done with isolated evidence; none selects a
  Runtime backend. Mem0 remains a derived, degraded-safe index;
  PostgreSQL Event/Projection and epoch/Lease Adapters have real-service
  restore and concurrency evidence.
  The local CI-billing waiver does not satisfy merge, runtime composition, release
  or production gates. The reviewed Effect and Artifact foundations are not runtime-
  selected; full aggregate fencing, Redis, production AG-UI, Trench, analysis,
  writeback, Memory delivery/runtime wiring and GA remain `Locked` pending explicit
  gates. `MEM-GW-DEL-PLAN-01` is formally `Done` on
  `codex/mem-gw-del-plan-closeout-01`; it keeps `MEM-GW-DEL-01` locked and
  registers the Core certainty, scoped reset Spike, PostgreSQL v11 ledger and
  runtime/rebuild child cards. `MEM-GW-DEL-CON-01` is formally `Done` after its explicitly activated,
  provider-neutral Core implementation slice. `MEM-MEM0-RESET-SPIKE-01` is now
  `Blocked` on `codex/mem0-reset-spike-01`: its isolated Compose run proved the
  pinned Mem0 list endpoint has no documented bounded pagination, so exact scoped
  enumeration cannot be accepted. `top_k` is not pagination. `MEM-GW-DEL-PG-01`
  is formally `Done` on `codex/mem-gw-del-pg-01` for the metadata-only v11
  ledger, atomic v10 enqueue and PostgreSQL claim/revalidation slice. Its host
  Compose runner passes `24` real PostgreSQL tests covering fresh/v1-v10 upgrade,
  checksum, migration rollback, replay, atomic enqueue, stale ACK, namespace
  isolation, unknown and in-flight quarantine, and batch search admission. The
  parent ledger and runtime wiring remain locked by the scoped-reset gate.

`MEM-MEM0-RESET-ALT-01` is formally `Done` as a zero-production-code validation
of whether v11 `scope/generation` plus confirmed provider mappings can replace
provider-wide enumeration for logical reset. Its isolated runner passes `2`
tests with verdict `B/PARTIAL`: logical reset and known mapping deletion are
bounded, but unknown provider orphans remain unrecoverable from the ledger. The
existing reset Spike remains `Blocked`; the partial verdict does not unlock the
runtime consumer. The focused delivery runner remains `24 passed`, and the full
storage matrix remains `295 passed, 1 skipped`.

`MEM-PROVIDER-DEL-COMPLIANCE-01` is now `Done` on
`codex/mem-provider-del-compliance-01`. This docs/specification-only slice adds
ADR-018 and a test-only admission matrix for deterministic recovery, physical
deletion and complete scoped coverage. The current Mem0 verdict is logical
fencing `PASS`, ledger mapping deletion `PASS`, ambiguous-create recovery
`FAIL/UNPROVEN`, complete scoped deletion `FAIL/UNPROVEN`, and Runtime admission
`BLOCKED`. Mem0 is therefore `Provider admission: DENIED` and
`Mainline candidate: DEFERRED`; `MEM-GW-DEL-RUN-01`, the parent ledger and
Runtime composition remain `Locked`. No production code, Provider HTTP, Worker,
Desktop or SQLite composition is changed.
The focused contract suite passes `2`; changed-path Ruff, format, Mypy,
compilation and `git diff --check` pass. `make check` remains blocked by two
unrelated file-size violations: Desktop stylesheet `561/500` and PostgreSQL
storage test `765/700`.

`MEM-PG-NATIVE-ADMISSION-SPIKE-01` is formally `Done`. Its isolated PostgreSQL
17.5 profile proves the ADR-018-compatible native boundary with `8 passed` and
emits `ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS`; the full storage matrix passed
`303 passed, 1 skipped` (`295` predecessor cases plus `8` admission cases).
The result admitted the candidate architecture, after which
`MEM-GW-PG-NATIVE-01` was explicitly activated for storage-only work. Worker,
Provider HTTP, Desktop, SQLite, Redis and Runtime remain `Locked`.

`MEM-GW-PG-NATIVE-01` is formally `Done`. Production PostgreSQL migration v12
and the provider-neutral `PostgresNativeMemoryGateway` are covered by `10`
focused Compose cases; the full `tests/agent_storage` matrix passes `313 passed,
1 skipped`, and the existing delivery runner remains `24 passed`. The card does
not select a Runtime backend or add Provider HTTP, Worker, Desktop, SQLite or
Redis composition.

## Known Follow-Ups

1. Keep the completed Embedded architecture and AG-UI/Trench Spikes parked while
   the storage branches follow their recorded merge order.
2. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
3. Preserve merge order from `CLOUD-STO-SEAM-01` through `CLOUD-STO-AUTH-01`,
   `CLOUD-PG-PLAN-01` (now `Done`), `CLOUD-PG-01`, and the Lease contract/Adapter chain; do not
   select PostgreSQL until every authoritative Store can move as one profile.
4. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
5. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, external-namespace isolation, and Kubernetes in
   dependency order.
6. Review the dependency Compose baseline and Mem0 contract/Adapter chain. Preserve
   its duplicate, expired-search, timeout and error-classification findings; do not
   claim real-provider compatibility or make Mem0 authoritative.
7. Preserve the PostgreSQL/Lease order: `CLOUD-PG-PLAN-01 -> CLOUD-PG-01 ->
   CLOUD-LEASE-PLAN-01 -> CLOUD-LEASE-CON-01 -> CLOUD-LEASE-PG-01`; only then may
   fenced Effect Outbox and Worker consumer cards be activated.
8. Activate Object Storage, Redis live state, recovery and Memory delivery/runtime
   wiring one path-bounded card at a time; no production claim precedes complete
   composition, migration, restore and failover evidence.
9. Continue the memory lane one path-bounded child at a time. The Core and
   PostgreSQL delivery children, provider-neutral gateway, PostgreSQL-native
   admission and storage slices are Done. The scoped reset child is `Blocked`
   on bounded enumeration; keep the Mem0 consumer, parent ledger and Runtime
   locked until their own explicit gates are reviewed.
10. Keep `WEB-INT-PLAN-01` in review until its document evidence is accepted;
    do not activate Web Intelligence contracts, Provider, security, tools,
    orchestration or Watch cards out of dependency order.

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

- Zebra AG-UI production adapter and HostSessionGrant verifier
- Trench CopilotKit Runtime/BFF, read-only panel, frontend tools and writeback
- Memory delivery runtime wiring: `MEM-GW-DEL-01` remains `Locked`; its Core
  certainty and PostgreSQL ledger children are Done, while scoped reset/rebuild
  is Blocked and the Mem0 consumer remains gated.
- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- complete PostgreSQL runtime composition and object-storage adapters
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
| `docs/Zebra Embedded 生产级目标架构.md` | Embedded/Trench target and invariant boundaries |
| `docs/Zebra Embedded与Trench实施任务拆解_v1.0.md` | dependency, ownership and phase gates for Embedded delivery |
| Phase 0-8 implementation document | historical dependency and acceptance baseline |

## Required Reading

1. `README.md`
2. `PROGRESS.md`
3. `docs/AGENT_TASKS.md`
4. `AGENTS.md`

Before architecture changes, also read the source-of-truth documents in the
precedence order defined by `AGENTS.md`.

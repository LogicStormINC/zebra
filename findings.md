# Findings

## CLOUD-PG-01 - 2026-07-28

- The first PostgreSQL slice can implement and test Event/Projection Adapters,
  but cannot enter `ControlPlaneStores`: the other authoritative Ports still
  have only SQLite implementations, so partial wiring would create two facts.
- `event.sequence - 1` is the existing expected-version contract. A dedicated
  `session_streams` row performs SQL CAS in the same transaction as Event insert;
  insert failure rolls the stream version back without a gap.
- Existing SQLite idempotency treated any matching key as a successful retry.
  The shared business fingerprint now excludes newly assigned Event ID, sequence
  and timestamp while rejecting different type, actor, payload or provenance.
- Projection may lag Event and replay, but may never lead or exist without its
  Event stream. PostgreSQL saves check the authoritative stream version, reject
  stale writes and reject divergent content at the same applied sequence.
- Explicit migrations use one advisory lock plus recorded name/checksum. Adapter
  construction never runs DDL, so future runtime identities need no schema rights.
- The separately owned Compose PostgreSQL service is sufficient for real local
  tests; this task does not duplicate Compose, add testcontainers or claim that
  the dependency branch is already merged.
- A custom-format logical backup restored into a fresh temporary database and
  passed the full PostgreSQL contract before exact cleanup. This is development
  evidence, not production PITR/RPO/RTO approval.

## CLOUD-PG-PLAN-01 - 2026-07-28

- PostgreSQL may replace SQLite only as one complete control-plane authority;
  implementing adapters in slices does not permit Store-by-Store cutover or
  SQLite/PostgreSQL dual-write.
- Event append is the durable fact transaction. Projection is deliberately
  allowed to lag and must converge by stream version; existing context and
  handoff aggregate Ports retain ownership of their multi-table transactions.
- The cutover state machine is `PREPARED -> VERIFIED -> ACTIVE`. `ACTIVE` is the
  sole authority boundary and is not undone by an application rollback; the old
  SQLite snapshot remains read-only migration evidence.
- PostgreSQL and object payload recovery share a versioned manifest. Immutable
  object versions/checksums and database recovery watermarks prevent a PITR
  database from silently referencing a mismatched object set.
- Restore must create a fresh random control-plane epoch before traffic opens.
  Protected Lease, Effect and Outbox writes compare epoch, token and ownership
  in the same SQL transaction so stale workers affect zero rows.
- RPO, RTO, retention and drill cadence remain `TBD`; any missing approval or
  measurement blocks production traffic without blocking local adapter work.
- The maintainer's GitHub Actions billing waiver authorizes local continuation
  only. It does not satisfy merge, release, production or real PostgreSQL gates.

## CLOUD-STO-AUTH-01 - 2026-07-24

- The first five-store seam could not safely select a cloud backend: context
  lifecycle, handoff/dispatch, idempotency, effect replay, governed memory,
  artifact indexes, provider continuations, session history and delivery audit
  still reconstructed SQLite adapters from `database_path` inside API/Worker flows.
- One flat `ControlPlaneStores` is sufficient. The missing boundaries were
  existing cohesive storage responsibilities, so focused Core Ports and adapter
  conformance remove the split without a backend hierarchy or new dependency.
- Context lifecycle and handoff are aggregate transaction boundaries. Keeping
  their event/projection/dispatch coordination behind one Port lets a future
  PostgreSQL adapter provide atomicity without leaking database tables upward.
- Distinct A/B regressions now exercise idempotency, attachments/SSE, context
  compaction/recovery, handoff/dispatch, effect replay, memory review, artifact
  and model/tool indexes, provider continuation and scoped session history. Each
  asserts that the legacy SQLite path does not exist before the test inspects it.
- With an injected bundle, `database_path` is compatibility configuration for
  local-only collaborators such as skills state and derived web caches; it is no
  longer an authority locator for durable API/Worker flows.
- Governed memory review currently persists the Memory fact and its Event/
  Projection through separate Store calls. This task guarantees one backend,
  not cross-call atomicity; the PostgreSQL/outbox design must close that failure
  window before production selection.
- `MemoryStorePort` retains candidate/review/supersession/deletion authority.
  Mem0 or another semantic-memory provider remains a separately gated derived
  Gateway and does not alter this composition contract.

## CLOUD-STO-SEAM-01 - 2026-07-23

- API and Worker construct the same SQLite control-plane adapters repeatedly;
  SSE also bypasses `ZebraAgentApi`, so changing only `create_app` would leave a
  false seam that cannot support a PostgreSQL adapter end to end.
- Existing Event, Projection, Workspace, AgentTask and Lease Ports are sufficient
  for the first bundle. Context lifecycle, idempotency, effect ledger, handoff
  dispatch, artifact indexing and some approval reads need later focused Ports.
- `MemoryStorePort` is Zebra's governed lifecycle projection: candidate,
  confirmed, superseded, expired and deleted states retain provenance and review
  semantics that Redis Agent Memory does not model. The remote service therefore
  remains a separate derived Gateway with outbox/receipts and fail-open reads.
- Redis Agent Memory is Public Preview and the old open-source V0 server is not a
  production fallback. A managed-service compatibility Spike precedes its Adapter.
- The storage seam has no technical dependency on Host/AG-UI contracts. The
  maintainer explicitly activated it as a local stacked task while PR `#194`
  remains the mandatory merge predecessor.
- Independent review reproduced event-stream splits when context lifecycle or
  handoff used a different SQLite path from injected control-plane Ports. The
  first seam therefore records local database identity and rejects partial
  split-backend composition before any write; it does not claim PostgreSQL readiness.
- Existing SQLite adapters open a fresh connection per operation, so `:memory:`
  cannot represent one coherent control-plane database. The local bundle rejects
  that mode instead of advertising a composition that loses schema and state.
- Approval listing cannot emulate its former SQL predicate with an unbounded
  `list_recent_sessions` call. `ProjectionStorePort.list_waiting_approval_sessions`
  preserves database-side filtering and oldest-first ordering for future adapters.
- Remaining authoritative collaborators are not optional infrastructure details:
  context lifecycle, handoff/dispatch, idempotency, effect ledger, governed
  memory, Artifact and continuation state must enter composition before `CLOUD-PG-01`.

## EMB-AGUI-SPIKE-01 - 2026-07-23

- The maintainer explicitly activated the Zebra-side compatibility Spike. The
  Trench CopilotKit Spike remains out of this repository and stays Locked.
- The architecture dependency is locally reviewed but not merged. To preserve
  one-task/one-branch isolation, the Spike is a stacked branch based on the
  architecture commit and carries a hard merge-order constraint.
- The task owns only a development dependency, isolated protocol fixtures/tests,
  one compatibility record, and governance files. Production imports and wiring
  are forbidden by task scope.

## EMB-PLAN-01 - 2026-07-23

- `docs/Zebra Embedded 生产级目标架构.md` concatenates two incompatible target
  designs. The later half reintroduces a custom React SDK and Postgres/pgvector
  memory after the opening decisions replace that memory design with Redis Agent
  Memory.
- The repository is still on the local SQLite profile. Private-cloud Phase B is
  deferred and requires an explicit activation decision plus migration, backup,
  recovery, and rollback review before production claims are valid.
- The minimum frontend boundary is Trench React -> CopilotKit React v2 -> a
  Trench-hosted Copilot Runtime/BFF -> Zebra AG-UI. Browser UI state and
  CopilotKit-managed threads are not Zebra durable truth.
- Zebra keeps generic host authority through an opaque `namespace_id` and a
  short-lived `HostSessionGrant`; Trench keeps business users, organizations,
  RBAC, and authoritative tool-side authorization.
- CopilotKit replaces only the proposed React integration layer. Zebra still
  owns AG-UI mapping, durable interrupts, Surface Lease, semantic frontend tool
  receipts, replay, Policy, and Artifact access contracts.
- Redis Agent Memory remains an optional, replaceable, degraded-safe adapter and
  is not on the first read-only Trench slice's critical path.
- The draft is 4,288 lines because a second complete architecture starts at line
  1,692. Replacing it with one bounded authoritative document is safer than
  trying to patch both contradictory halves.
- CopilotKit's current v2 boundary is `@copilotkit/react-core/v2` with
  `<CopilotKit runtimeUrl=...>`, `useAgent`, `useAgentContext`,
  `useFrontendTool`, and `useInterrupt`. The supported production topology keeps
  Copilot Runtime in the Host application server; `agents__unsafe_dev_only` is
  explicitly a development-only direct connection.
- AG-UI wire values use `EventType` constants such as `RUN_STARTED`,
  `TEXT_MESSAGE_START`, `TOOL_CALL_START`, and `STATE_SNAPSHOT`. Architecture
  examples should name both the SDK class and exact wire value to avoid the
  draft's CamelCase/uppercase ambiguity.
- Current AG-UI interrupts finish a Run with an interrupt outcome, require state
  and message snapshots before that boundary, and resume on the same `threadId`
  through an idempotent `resume[]` response covering every open interrupt.

## CTX-SEG-02 - 2026-07-20

- Task `d3206b32-fcb2-435a-9bca-34143cb3072f` failed without any Policy,
  network, or tool error. Its terminal follow-up Envelope had no Capsule or
  completed work, so “分析一下资金流向” lost the preceding stock context and the
  model searched the Zebra repository instead.
- The shared automatic Handoff builder is the smallest correct repair point.
  It now projects the latest non-automation user message and Assistant response
  into a bounded, low-trust checkpoint whenever automation has no explicit
  completed-work or Capsule summary.
- API and Harness defaults (`4/3` and `8/6`) were the systemic source of ordinary
  work being stopped despite ongoing progress. Omitted limits now remain `None`.
- Caller-supplied limits remain strict: a batch larger than the remaining hard
  allowance starts nothing and suspends recoverably instead of becoming a Task failure.
- A batch that exactly consumes an explicit tool allowance may use one remaining
  tools-disabled model turn to summarize its actual results; another tool request pauses.
- `tests_completed` with `summary=verifier hook skipped` is NoopVerifier plumbing,
  not real validation. Desktop hides only that exact no-op event and retains real
  verifier outcomes.


## WEB-UX-01 - 2026-07-19

- The reported failure was not a model tool-call protocol defect: DeepSeek
  emitted `web.fetch`, then durable `network_profile=none` caused Policy denial.
- Existing `domain-allowlist` authority still forced `require_approval`, so no
  configuration-only switch could remove the interruption.
- The smallest coherent boundary is one shared Policy change: authorized
  `WEB_GATEWAY` routes return `allow`; `MCP_PROXY` continues to return
  `require_approval`; blocked routes remain denied.
- `full-trusted-local` already existed in the core network enum but Web routing
  and Desktop launch controls did not consume it. Reusing it avoids a new mode.
- Existing Desktop localStorage retained the old `none` default, so changing the
  constant alone would not repair current installations. A one-time marker
  migrates that legacy value; the local API independently normalizes every new
  Task to trusted authority, so stale or explicit client values cannot weaken
  the operator-selected local execution mode.
- Direct Web execution needs a multi-response model regression because the same
  Worker attempt now executes the tool and performs final synthesis instead of
  splitting those model calls across approval continuation attempts.
- Desktop defaults only affect new Tasks. Existing Tasks and automatic internal
  Segments persist the prior `network_profile=none`, so the Worker must derive an
  effective local authority at execution time instead of rewriting history.
- API, CLI, and Worker now call the same effective-network resolver. This is the
  execution source of truth; UI defaults and durable Task values are evidence,
  not independent Policy switches inside `local + trusted-local` mode.
- This macOS host uses a system HTTPS proxy at `127.0.0.1:7890`; Clash Fake-IP DNS
  maps public names to reserved `198.18.0.0/15`. Disabling proxies and resolving
  locally therefore produced a false `private_network_blocked`. Trusted local Web
  transport now delegates DNS/routing to the configured HTTPS proxy; direct mode
  keeps the public-address preflight.
- Real old-Task validation separates failures correctly: OpenAI `/news/` returns
  upstream HTTP 403 and its RSS exceeds the bounded response limit, while
  `https://openai.com/robots.txt` executes and the Task completes without approval.
- A real Zhipu request exposed a separate recovery defect: the trace retained a
  TLS certificate error in metadata, but an empty tool output became only
  `Tool failed.` in the provider conversation. The shared model-step formatter
  now projects bounded `status`, `reason`, and `detail`, preventing the model
  from guessing that a transport error was a Policy or allowlist denial.

## UI-COMPOSER-01 - 2026-07-19

- The oversized composer had two independent causes: fixed `126px` / `180px`
  minimum heights and an attachment surface that always consumed its own row.
- Reusing the existing Ant Design X `Sender` remains sufficient. Moving the
  existing attachment surface into the footer and sharing one size contract
  removes the extra row without changing task-launch or submission behavior.
- Real Chromium measured the thread composer at `117px`, down from `183px`.
  The idle variant is `145px`; at `390px` viewport width the composer is `113px`,
  the send action remains visible, and no horizontal overflow occurs.
- The compact layout adds no dependency and leaves the production bundle within
  the established Lobe UI baseline.

## CTX-SEG-01 - 2026-07-19

- The durable root Session UUID can serve as the initial Task UUID without a
  destructive identifier migration; existing lineage is rebuilt lazily into
  `agent_tasks`, `execution_segments`, and `task_event_index` projections.
- Rollover correctness depends on updating the active Segment in the same SQLite
  transaction that commits the handoff child and outbox. A separate post-commit
  Task update would permit a visible stale active Segment after a crash.
- Completed-Task follow-up uses an automation checkpoint message, then appends the
  real user message to the new Segment. This keeps handoff metadata out of the
  public stream and preserves ordinary text attachment semantics.
- Desktop fallback creation was the remaining source of user-visible identity
  churn. Removing it and routing all core calls through `/tasks` keeps the
  conversation key, sidebar count, and SSE cursor stable.
- The internal lifecycle controller treats model or authority uncertainty as
  fail-closed and pending tools, approvals, clarifications, or unknown effects as
  pause conditions; an Agent hint is only an input signal.

## UI-LOBE-01 - 2026-07-18

- Lobe UI 5 is ESM-only and its current peer line requires React 19, Ant Design
  6, antd-style 4, Motion 12, Lobe Icons 5, and Fluent Emoji 4.
- Zebra's existing Ant Design X 2.8 already required Ant Design 6, so upgrading
  the stale Ant Design 5 pin closes an existing peer mismatch instead of creating
  a separate migration solely for Lobe UI.
- `ThemeProvider` is mounted at the existing root theme boundary and receives
  Zebra's current token configuration; durable chat/event state remains custom.
- The package still exposes an upstream Emoji Mart React 19 peer warning. It is
  not suppressed, does not appear in the mounted provider path, and production
  TypeScript/Vite/browser validation passes.
- Direct ThemeProvider subpath import plus TypeScript Bundler resolution keeps
  the dependency boundary explicit. The resulting `1.43 MB` / `454 KB` gzip
  chunk does not regress the mainline `1.47 MB` / `458 KB` record.

## QA-GOV-02 - 2026-07-18

- PR `#144` was based on `882c955`, while current main is `667627a`.
- The PR's Context and DeepSeek proposal commits were superseded by merged
  implementation PRs `#145`, `#147`, `#146`, and the staged handoff series.
- Mechanical conflict resolution would risk replacing current implementation
  truth with old proposal-era README, PROGRESS, task, and architecture claims.
- The safe reconciliation is a force-with-lease rebuild from current main that
  preserves only governance intent.
- Eight `Review` cards have verified merge evidence and can be closed: PRs
  `#135`, `#136`, `#137`, `#139`, `#140`, `#141`, `#145`, and `#147`.
- The remaining executable registry state is two locked tasks: ACP entry and
  optional code intelligence. No task is currently Ready or In Progress.

## CTX-LC-01 - 2026-07-17

- The user split DeepSeek specialization into a separate Codex task. This task
  now owns only provider-neutral context lifecycle work; DeepSeek request and
  telemetry edits were removed before either implementation branch committed them.

- Current same-session conversation compaction is correctly placed before
  follow-up model calls, but the initial call bypasses it and
  `within_budget=false` is not a hard outbound gate.
- Context and conversation budgets are fixed and character-estimated; they do
  not reserve provider output, reasoning, tool schema, or continuation overhead.
- `command.run` and `tests.run` return complete stdout/stderr directly, so the
  first implementation rung is one shared bounded output projector backed by
  the existing Artifact boundary rather than provider-native compaction.
- Provider-native compaction is an optional continuation optimization. Session
  events plus a transparent Zebra Capsule remain recovery and cross-model truth.
- The implemented hard gate counts serialized messages and tool schemas against
  a model context window after output/reasoning/compaction/protocol reserves.
  A configured conversation target remains a soft progressive-compaction target;
  only the model-profile hard input limit fails the request.
- `command.run` covers arbitrary build commands, so no separate build tool or
  duplicate output-persistence path was added.
- The final implementation uses one request planner and hard gate for initial,
  follow-up, approval, clarification, recovery, and final-synthesis paths. Token
  counting is provider-pluggable; the neutral fallback records its estimate method.
- All large-output tool families cross one `ToolOutputEnvelope` boundary. Complete
  payloads remain retrievable by Artifact URI while model-visible evidence is a
  bounded head/tail projection with size, digest, checksum, and provenance.
- Active projection preserves protected user constraints and recent exact
  assistant/tool pairs, folds completed evidence into typed tombstones, and permits
  only budgeted, policy-checked, provenance-checked Artifact rehydration.
- Capsule Artifact persistence, `ContextCompacted`, `ContextCapsuleCreated`, and
  active-pointer CAS execute in one SQLite transaction. Worker recovery prefers the
  active Capsule and can restore a user-selected exact event tail.
- Provider-native continuation remains an optional capability contract with
  provider/model/version/TTL scoping. Missing, expired, incompatible, deleted, or
  cross-provider state deterministically falls back to the Zebra Capsule.
- Full acceptance evidence: `1379 passed, 1 skipped`; file-size and Ruff passed;
  strict Mypy passed across `379` source files; all `8` release Evals passed.

## 2026-06-18

- 当前最重要的设计基线仍然是 `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
- 仓库已经完成 `uv workspace` 和 `apps/ + packages/` 的基础重构，适合进入按阶段推进的实施模式
- 现有 `PROGRESS.md` 更像状态摘要，还缺一份明确的“任务拆解 + 阶段验收”文档
- 对这个项目来说，阶段划分应围绕核心依赖链组织：
  `core -> runtime/tools -> harness -> control plane -> context -> security -> eval -> productization`
- Phase 1 到 Phase 3 是最关键的连续闭环，如果这里没有打通，后面的 API、云端和安全服务都没有稳定依托

## 2026-07-19 CTX-SEG-P0-01 Invisible Internal Execution Segments

- The visible “阶段性新线程” form was intentional legacy product behavior, not a
  transient rendering bug: the old architecture required users to preview an
  Envelope and explicitly create a child Session at a safe boundary.
- Backend feature disablement did not hide the card because Desktop rendered it
  from terminal Session status and never consumed the backend feature flag.
- The minimum safe correction is to remove the ordinary Desktop creation surface
  and its client call chain while retaining disabled backend lineage, authority,
  recovery, and no-replay contracts for later internal Segment rollover.
- ADR-013 makes stable Task identity the user boundary. Automatic rollover needs
  Task/Segment persistence and a backend lifecycle controller before it can be
  truthfully claimed; P0 intentionally does not emulate that behavior in React.

## 2026-07-19 SUBAGENT-UX-01 Model-Native Delegation

- `agent.research` was already model-invoked; the missing product contract was
  stable selection guidance and diagnostic evidence, not a new task router.
- A keyword, length, score, frontend switch, or router-model classifier would add
  hidden policy and latency. The parent model now chooses direct answer, parent
  tool, or bounded child through its ordinary advertised-tool decision.
- `HarnessModelStep` is the smallest correct prompt owner because it sees the
  effective manifest. Guidance is appended to the existing compiled System Prompt
  when present, preserving Context, attachment, memory, CLI, and Worker contracts.
- Invalid `delegation_reason` calls return bounded structured validation output
  and create no child. Successful results return reason and child usage in their
  JSON output as well as audit metadata.
- A failed tool is evidence, not an automatic task terminal: the model may correct
  or choose another tool while budgets remain. Policy, approval, clarification,
  protocol, repeated-effect, and budget stops remain deterministic.
- The task branch was rebuilt from `origin/main`; the unmerged Web branch no longer
  acts as a hidden branch dependency.

## CLOUD-LEASE-PLAN-01 - 2026-07-28

- The original `CLOUD-LEASE-01` is not one safe implementation slice. It spans
  Core ownership types, PostgreSQL Lease/epoch state, Effect/Outbox aggregate
  transactions and Worker/tool execution lifecycle, so it remains Locked.
- Current `WorkerLease` has no epoch/token; heartbeat and release compare only
  `worker_id`. A stale process reusing that ID can mutate a successor Lease.
- `checkpoint` is execution progress, but handoff facts currently expose it as a
  fencing token. The two concepts must become separate typed fields before any
  PostgreSQL Lease Adapter is safe.
- PostgreSQL must decide expiry from database time and retain each Session's
  highest fencing generation after release. A get-before-update check or row
  deletion cannot enforce ownership under races.
- Worker recovery currently precedes acquire, no production path calls heartbeat,
  and ordinary Event/Effect writes carry no Lease. A focused fenced Worker
  mutation Port is required; the general `EventStorePort` should remain usable by
  API/System writers that do not hold a Worker Lease.
- Effect started Event, ledger transitions, provider call and terminal Event are
  separate transactions. The minimum correction is a narrow Effect dispatch
  aggregate that atomically writes Event + reservation + Outbox intent, not a
  generic Unit of Work.
- PostgreSQL Outbox is the v1 durable queue. With no broker or external consumer,
  a generic inbox is YAGNI. An expired executing claim becomes uncertain and is
  reconciled; it never returns automatically to pending.
- The executable order is `CLOUD-LEASE-CON-01 -> CLOUD-LEASE-PG-01 ->
  CLOUD-EFFECT-OUTBOX-01 -> CLOUD-EFFECT-CONSUMER-01`.
- Reader review caught and closed three initial P0 contract gaps: PITR can reset
  a raw token so authorization uses the full epoch/token/owner tuple; expired or
  old-epoch claims need a new-owner reconciliation CAS; and this parent cannot
  claim full Worker aggregate safety. `CLOUD-AGG-FENCE-01` now owns that later gate.
- Background heartbeat uses an independent connection and lost flag. An in-flight
  provider call may finish after lease loss, but its terminal mutation is fenced.
- Failed-no-effect retry has an explicit monotonic attempt/retry-key transaction;
  uncertain execution never returns automatically to pending.

# Findings

## CLIENT-ADR-01 - 2026-08-25

- AG-UI `RunAgentInput` already parses `state` / `tools` / `context` /
  `forwardedProps` (`apps/api/src/zebra_agent_api/ag_ui_command.py`), but
  they remain command payload only: no durable client binding exists and
  the worker-recovered task never sees them. `CLIENT-AGUI-ADMISSION-01`
  and `CLIENT-CONTEXT-01` own the conversion into persisted client run
  bindings and state snapshots.
- `ToolExecutionLocation`
  (`packages/agent-core/src/agent_core/domain/tools.py`) currently
  enumerates only `ZEBRA` / `HOST` / `SANDBOX`. Adding `CLIENT` is owned
  by `CLIENT-EFFECT-CON-01`, which also requires `ToolContract` scope for
  both `HOST` and `CLIENT`.
- The worker loop still constructs the Host Connector Registry, Subagent
  Delegation Store and Wakeup Service directly from the DSN; new client
  stores must not copy this composition pattern —
  `CLIENT-PLATFORM-COMP-01` introduces the shared
  `AgentPlatformControlPlane` bundle for API and Worker instead.
- Existing boundaries the client plane must preserve: the
  `agent-control-plane` architecture gate (no Worker / Runtime / FastAPI /
  storage adapter imports), the AG-UI Projector's pure-projection seam
  (State Snapshot / State Delta / Tool Call / Interrupt already
  projected), the Orchestrator `system/orchestrator@1`
  `orchestration.*`-only capability set, and the Host Effect
  outbox / reconciliation as the backend business-write authority.
- Baseline note: the planning document pins `main@efd4e293` as the sync
  point, but the working mainline is `cloud-agent` (PRs land there per
  `PROGRESS.md`); this card branches from `cloud-agent@2319da7f`, which
  contains `main@efd4e293` as an ancestor.

## CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01 - 2026-08-03

- The Context Worker path is fenced at the PostgreSQL transaction boundary:
  `WorkerMutationAuthority` carries the complete `LeaseFence`, the store checks
  namespace/session/revision, and `assert_current_lease_fence` runs before any
  Event, Capsule, pointer or projection write. Pointer and stream CAS plus
  transaction rollback are covered by the recorded focused PostgreSQL matrix.
- Administrative Context recovery is a separate `AdministrativeMutationCAS`
  path. It locks the Session stream and active pointer, compares the current
  Session/Workspace projections, and returns the canonical aggregate result
  without a second projection save. Context Materialization remains read-only and
  must not be used as mutation authority.
- A Store-level semantic gap remains: `commit_administrative_activation` does not
  reject a non-`CONTEXT_COMPACTED` Event or verify that the recovery payload's
  `capsule_id` equals the requested capsule. The current API caller supplies both
  correctly, but direct composition/Port use can bypass that caller contract.
- Sidebar decision: `BLOCK-GAP`; keep the conformance audit `In Progress`, keep
  `CLOUD-AGG-FENCE-01` `Locked`, and register the minimal adapter/test successor
  `CLOUD-AGG-FENCE-CTX-SEMANTIC-01`. No production code or migration belongs in
  the audit card.

## CLOUD-CONTEXT-PG-01 - 2026-08-03

- The PostgreSQL materialization adapter keeps one `READ ONLY` transaction for
  Session projection revision, safe Session History, active Capsule pointer and
  confirmed governed Memory. Calling the existing adapters separately would
  create independent snapshots and is intentionally avoided.
- Session and active Capsule expectations are exact: a missing/changed
  projection raises a typed conflict rather than returning a partial envelope.
  Memory rows are decoded as revisioned `GovernedMemoryEntry` values and the SQL
  path excludes deleted, candidate and expired records before Core validation.
- Existing governed-Memory query ordering was preserved through a shared row
  helper; the new expiry predicate is additive and transaction-local. No
  migration, write, cache authority, Store selector or runtime path changed.
- Local validation is `149 passed, 172 skipped` Storage, `350/350` Core, changed
  Ruff/format/strict Mypy and Eval `10/10`. Host Compose verification passed
  `4/4` with `ZEBRA_CONTEXT_MATERIALIZATION_POSTGRES_TEST_RESULT=PASS`; the
  isolated runner cleaned its container, network and volume.
- The first host attempt exposed a fixture-only conflict with the existing
  confirmed repo/type singleton index. The expired record now uses a distinct
  Memory type, preserving real expiry filtering without weakening the schema.

## CLOUD-CONTEXT-CON-01 - 2026-08-03

- Context Materialization is an ephemeral read envelope, not a fourth source of
  truth. Session History answers what happened, the active Context Capsule holds
  resumable state, and PostgreSQL governed Memory supplies only confirmed,
  unexpired facts.
- The Core request pins the opaque deployment read scope, exact Session revision,
  expected active Capsule ID, explicit Memory visibility query and read timestamp.
  A result fails closed on stale revisions, deny-all scope, unordered History,
  duplicate Memory IDs, expiry or non-confirmed Memory.
- Generation identity is deterministic: Session revision plus active Capsule ID
  plus sorted `(MemoryId, revision)` entries. Rebuild must reread authority; the
  envelope is never a new Event, Capsule, Memory or database revision.
- ADR-020 and `ContextMaterializationPort` deliberately stop before PostgreSQL
  composition; the successor was activated only after the contract closed.
  Runtime, Worker/API selection, Desktop, SQLite, Redis and Mem0 stay outside
  scope.

## CLOUD-MEMORY-CON-01 - 2026-07-29

- Cloud mutation requests now freeze namespace, Session identity and expected stream
  revision. Worker LeaseFence remains execution authority and intentionally does not
  alter the durable operation digest.
- Creation and content hashes describe semantic Memory/provenance, so a response-loss
  retry may regenerate public Memory/Event IDs and event bookkeeping while changed
  content, scope or lifecycle intent still conflicts.
- Pydantic `model_copy(update=...)` does not rerun validators; aggregate
  `validate_for()` therefore rechecks canonical creation evidence and the full request
  digest at the Port boundary.
- The compatibility extraction wrapper must issue one bounded legacy query per refresh
  target before deduplicating by Memory ID. Combining targets under one `limit=100`
  changes existing SQLite behavior and loses eligible records.
- The Core Port deliberately has no SQL or runtime composition. PostgreSQL v10 remains
  the next authority slice; Mem0 delivery stays locked behind it.

## CLOUD-MEMORY-PG-PLAN-01 preflight - 2026-07-29

- `MemoryStorePort` is injected across API and Worker, but only
  `SQLiteMemoryStore` implements it. No PostgreSQL table or adapter currently owns
  governed Memory facts on the cloud branch.
- Mem0 is already behind a provider-neutral Gateway and correctly returns references
  that require `MemoryStorePort` revalidation. Its missing delivery ledger must not
  be built on top of the remaining local SQLite authority.
- Current review is a multi-write sequence: read candidate/scope, update reviewed and
  superseded records, append review Event, then save Session projection. Blind
  last-writer-wins `upsert` cannot make this crash- or concurrency-safe in PostgreSQL.
- The next implementation must preserve the rich repo/user/tenant inventory/query
  surface while distinguishing opaque deployment namespace isolation from business
  visibility labels. Zebra does not become a tenant directory.
- Review exposed and closed six implementation blockers: Gateway certainty owned
  paths, durable multi-row replay receipt, no-text tombstones, pure pre-write mutation
  plans, deleted SQL/FTS constraints and canonical replay independent of later record
  revisions. Final review found no remaining P0/P1.


## MEM-MEM0-ADP-01 - 2026-07-28

- The installed `httpx` client is sufficient; no Mem0 SDK or new dependency is
  needed for the proven REST surface.
- A default-disabled Adapter can preserve local behavior without runtime wiring.
  Enabled plain HTTP requires an explicit local-only opt-in, and implicit
  environment proxy discovery stays off to avoid credential leakage or localhost
  interception.
- Mem0 provider refs in the pinned OSS version are UUIDs. Canonical UUID parsing
  at publish, search and delete closes path traversal and schema-drift ambiguity.
- The Adapter cannot own delete identity: a namespace-aware provider-ref lookup
  is required, while durable mapping/idempotency remains `MEM-GW-DEL-01`.
- A provider lookup outage is degraded, not not-found. Only a successful lookup
  miss or provider `404` is not-found, preserving deletion retry/audit semantics.
- Response bytes and hit counts are bounded. Whole-response drift or an entirely
  invalid non-empty hit set counts toward the circuit; partial is reserved for a
  response with at least one revalidatable hit.
- The process-local circuit admits one half-open probe. Multi-Worker coordination
  remains a later operational gate rather than hidden shared state in this Adapter.
- The Adapter itself passes publish/search/delete against the pinned isolated
  Compose Mem0 server. Real provider, TLS/proxy and production SLO remain unverified.

## MEM-MEM0-SPIKE-01 - 2026-07-28

- Pinned Mem0 OSS accepts authenticated `infer=false` writes through a local
  embedding-only provider; the successful path never calls chat completion.
- Identical delivery creates distinct Mem0 UUIDs. Zebra therefore needs its own
  durable `MemoryId -> provider_ref` mapping and idempotent delivery ledger.
- Hashed `user_id` scopes isolate the tested searches, but Mem0 is not the Host
  authorization boundary and every returned Zebra reference still needs Store
  revalidation.
- Expired records can be listed with `show_expired=true` but cannot be searched
  with the same flag in the pinned version.
- Provider 503 becomes `502/provider_unavailable`; bad dimensions become
  `502/unknown`; a stalled provider blocks until the caller deadline. All three
  belong to the Adapter's degraded path.
- Restart preserves vector and history data in their isolated volumes. Both are
  derived evidence only; `MemoryStorePort` remains Zebra's fact source.
- The deterministic provider proves the OSS REST/pgvector path, not real-provider
  credentials, rate limits, proxy/TLS behavior or production SLO.

## MEM-GW-CON-01 - 2026-07-28

- The safest remote-memory contract does not return text. A hit carries only the
  governed Zebra `MemoryId`, an opaque provider reference and a separately named
  provider score, forcing lifecycle/content revalidation through `MemoryStorePort`.
- Confirmed-only publication belongs at the typed trust boundary. Candidate,
  superseded, expired and deleted records cannot be represented as publications.
- Degraded, disabled and partial provider behavior are ordinary typed outcomes;
  they are not reasons to fail an Agent Run.
- Mem0 and Redis names, SDK types, identities and transport details stay outside
  Core so the derived index remains replaceable.

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
## CLOUD-COMPOSE-INFRA-01 - 2026-07-24

- The repository has no existing Dockerfile or Compose asset to reuse; only
  runtime configuration and architecture references exist.
- Mem0 OSS is a better self-hosted candidate than Redis Agent Memory V0 for this
  Compose-first phase, but it is still an auxiliary semantic service rather than
  a governed-memory database. Its official Compose is a development example and
  the published API image exposes only a mutable old `latest`, so the boot smoke
  builds from release commit `ca2abca2b884e038d3e525070e79d3057ef2012c` and pins
  `mem0ai==2.0.13` instead of claiming a production artifact.
- Zebra `MemoryStorePort` already models candidate, confirmed, superseded,
  expired and deleted states with provenance. Mem0 must not replace those states:
  publish only confirmed memory with `infer=false`, carry a Zebra memory ref, and
  revalidate every hit against the authoritative Store before prompt admission.
- Mem0's isolated pgvector PostgreSQL and SQLite history volume are derived and
  rebuildable. They share neither data nor authority with Zebra PostgreSQL or
  erasable `redis-live`.
- The slim Python image needs the self-contained `psycopg-binary` distribution;
  installing only upstream's pure-Python `psycopg` package leaves no `libpq`.
  A separate runtime input preserves exact upstream comparison while the combined
  hash lock, no-index direct-input check and `pip check` close dependency drift.
- Mem0 imports create `~/.mem0` even with telemetry disabled. `MEM0_DIR` therefore
  points to tmpfs so the API can retain a read-only root filesystem; this generated
  identity config is operational scratch data, not governed or semantic memory.
- `/auth/setup-status` is request-audited, so using it every 10 seconds as a
  health probe would itself add about 8,640 persistent rows per day. The final
  check uses an audit-skipped HTTP path for process liveness and a direct SQL
  query for application-database readiness.
- A successful boot applies only the REST server's relational migrations. The
  `vector` extension and semantic collection are intentionally not initialized by
  the sentinel-key smoke and must be observed during the credentialed contract Spike.
- Container boot does not prove write/search contracts. Exact REST shapes,
  duplicate delivery, restart, deletion, provider failure, embedding changes and
  namespace behavior require `MEM-MEM0-SPIKE-01` with disposable credentials.
- Building Zebra API/Worker images before cloud adapters exist would create a
  misleading SQLite-backed main stack. Application containers therefore remain
  a separate locked task.

## CLOUD-STO-SEAM-01 - 2026-07-23

- API and Worker construct the same SQLite control-plane adapters repeatedly;
  SSE also bypasses `ZebraAgentApi`, so changing only `create_app` would leave a
  false seam that cannot support a PostgreSQL adapter end to end.
- Existing Event, Projection, Workspace, AgentTask and Lease Ports are sufficient
  for the first bundle. Context lifecycle, idempotency, effect ledger, handoff
  dispatch, artifact indexing and some approval reads need later focused Ports.
- `MemoryStorePort` is Zebra's governed lifecycle projection: candidate,
  confirmed, superseded, expired and deleted states retain provenance and review
  semantics that an external semantic index does not model. The remote service therefore
  remains a separate derived Gateway with outbox/receipts and fail-open reads.
- The current Mem0 candidate remains replaceable. A self-hosted contract and
  operations Spike precedes its Adapter.
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
- PyPI currently resolves `ag-ui-protocol==0.1.19`; the exact version and wheel
  hash are pinned in `pyproject.toml` and `uv.lock`.
- The official encoder emits blank-line-terminated `data:` SSE records with
  camelCase JSON. Eleven focused tests now cover bounded independent decoding,
  the canonical run/text/tool/state stream, interrupt/resume, and extension drift.
- A test directory named `ag_ui` must remain a non-package. Adding
  `__init__.py` shadows the installed official SDK during pytest collection.
- The SDK union rejects unknown event discriminators, preserves extra fields on
  known events, and provides explicit `CUSTOM`/`RAW` exits.
- SDK validation is structural only: it does not enforce same-thread resume,
  full open-interrupt coverage, RFC 3339 expiry, or response JSON Schema. The
  future Zebra adapter must validate those facts against durable state.
- Focused completion evidence is 11 passing tests plus clean task-owned Ruff,
  formatter, lock, diff, file-size, and production-import checks.
- Full validation collected 1,763 tests with nine failures. The exact failure
  set reproduces on the architecture baseline without this dependency or test
  directory. The same comparison confirms two file-size, 13 Ruff, and four
  Mypy findings are pre-existing; all ten release Eval cases pass.

- Formal closeout accepts `ag-ui-protocol==0.1.19` with `11/11` focused tests;
  this does not activate production AG-UI, CopilotKit/Trench, React SDK or UI.

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
- External semantic memory remains optional, replaceable and degraded-safe; the
  later Mem0 candidate is not on the first read-only Trench slice's critical path.
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
# CTX-MEM-01 Findings - 2026-07-28

- Issue `#197` is partially valid. The worker process does not crash, but a
  `ContextWindowExceededError` currently falls through to terminal `FAILED`.
  Same-session user instructions are preserved by the protected ledger, while
  older assistant/tool detail is reduced by a fixed 240+240-token summary.
- Completed Sessions already extract memory candidates, but no automatic
  candidate-to-confirmed path exists. Confirmed repo injection sorts by type and
  recency, takes eight records, and does not consider the current user request.
- Existing primitives are sufficient: `ContextCapsule`, protected ledger,
  active projection/tombstones, `MemoryReviewService`, `MemoryQuery`, SQLite and
  `sessions.search`. A second memory framework or vector dependency is YAGNI.
- Codex separates memory generation from memory use and treats provider
  compaction items as opaque continuation state. Claude recommends server-side
  compaction/tool-result clearing. Pi preserves a token-sized exact tail at turn
  boundaries and appends a durable compaction entry. Hermes uses normal and
  emergency thresholds plus structured summaries, but its documented summary
  failure can silently discard middle context.
- Zebra should keep three different truths separate: active same-Task context
  comes from Event Store + Capsule; cross-Task hints come only from confirmed
  governed Memory; exact older evidence remains available through durable
  Session/Event search and Artifact retrieval.
- `MEM-GW-CON-01` is a local stacked Review task for a future provider-neutral
  semantic gateway. `CTX-MEM-01` must not touch that Port or depend on its branch.
- Implementation evidence confirms the smallest shared-path fix: one compaction
  recovery function serves every model request, one governed promotion service
  reuses the existing review state machine, and FTS remains an index over the
  authoritative MemoryStore rather than a parallel memory truth.
- Final local gates: `63` focused tests, changed-file Ruff, relevant Mypy over
  `158` source files and release eval `10/10` pass. The full suite's nine
  failures reproduce on untouched `main`; `make check` only reports the two
  inherited out-of-scope file-size violations.


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

## CLOUD-LEASE-CON-01 - 2026-07-28

- Ownership is now one immutable `LeaseFence(epoch, token, owner)`; checkpoint is
  recovery progress only and is never promoted into handoff authorization.
- SQLite release retains the row and generation. Acquire, heartbeat and release
  decide ownership with current epoch plus full-fence CAS; `get()` exposes only
  a current, unexpired, unreleased lease and cannot revive diagnostic rows.
- Upgrade migration must be row-state-driven rather than gated by one column.
  Partial legacy rows are idempotently fail-closed with token zero, while
  token-positive rows survive concurrent constructors unchanged.
- Worker claims must acquire before recovery and then CAS checkpoint to the
  recovered Event sequence before returning. Recovery or that CAS failing causes
  a fenced cleanup attempt and never exposes a false successful claim.
- TTL is bounded by a configurable maximum at both the caller and Adapter trust
  boundaries; the caller validates the integer before constructing `timedelta`.
- Two final independent reviews closed partial-schema, incomplete handoff tuple,
  checkpoint advancement, TTL overflow and old direct-caller gaps with
  `0 P0 / 0 P1 / 0 P2` remaining.
- Background heartbeat, PostgreSQL/database-clock proof, fenced aggregate writes,
  Effect Outbox and production composition remain later cards.

## CLOUD-LEASE-PG-01 - 2026-07-28

- Restore rotation and Lease mutation require a shared lock order: every fenced
  mutation first holds the namespace epoch row `FOR SHARE`, then mutates the Lease;
  rotation updates that epoch row with a conflicting exclusive lock. Without this,
  an old heartbeat could return success after rotation had already completed.
- The PostgreSQL Adapter uses only `transaction_timestamp()` for acquisition,
  heartbeat, expiry and release. TTL is a duration parameter; session timezone and
  caller clocks cannot decide ownership.
- Migration v2 is additive and does not bootstrap authority. Bootstrap is strict,
  restore rotation generates its own UUID, and Adapter construction performs no DDL.
- Lease rows retain the highest visible generation after release. Expiry, release
  and epoch mismatch takeovers increment that token; active same-owner reacquire is
  still a conflict and checkpoint remains monotonic recovery progress only.
- Real PostgreSQL tests prove same/different owner races, clock-skew independence,
  namespace isolation, full-fence rejection, retained generations and deterministic
  heartbeat-versus-rotation ordering.
- Python module separation is not a database permission boundary. Migration/restore
  identities and runtime read-only epoch privileges remain composition/cutover work;
  this card makes no production-safe or full multi-worker-safe claim.

## CLOUD-EFFECT-OUTBOX-01 - 2026-07-28

- `execution_session_id` and `root_session_id` are different authorities: the
  former selects the Lease and Event stream, while the latter is only the durable
  cross-handoff Effect dedupe scope. A child must never write with the root fence.
- One aggregate `effect_outbox` row is sufficient for v1 because PostgreSQL itself
  is the durable queue. Splitting Effect and Outbox tables adds a synchronization
  invariant without adding a broker or independent delivery lifecycle.
- Every mutation locks the namespace epoch, then the current Session Lease, then
  the Effect row and Event stream. Restore rotation therefore cannot complete while
  an old fenced transaction remains capable of committing.
- A claimed operation that loses its receipt never returns to pending. Expiry or
  epoch replacement only permits a CAS transition to `uncertain`; a current owner
  must resolve provider evidence or dead-letter it explicitly.
- Same-key schedule and retry APIs are idempotent only when durable meaning matches.
  Failed-no-effect may create one monotonic next attempt; uncertain execution cannot
  be replayed automatically.
- The isolated PostgreSQL 17.5 matrix passes `49/49`, proving Compose-backed
  concurrency, rollback, restore epoch and namespace behavior for this slice.
- PostgreSQL trigger injection is the smallest faithful way to test rollback after
  an Event insert but before the aggregate row commit. Namespace-scoped trigger
  predicates avoid changing production code or adding a generic failure hook.

## CLOUD-AGG-FENCE-PLAN-01 - 2026-07-29

- Full aggregate fencing is not a table-by-table SQLite port. The authority map
  separates Event-derived projections and read models from additional payload or
  command authorities before choosing PostgreSQL schemas.
- Model Call, Tool Run, Workspace and Task remain replayable projections. Session
  History and Artifact list remain read composition. Creating separate authority
  tables for the latter two would add conflicting sources of truth.
- Context, Handoff/dispatch, Provider continuation payload and Artifact payload
  contain durable state outside the Session Event stream. Their PostgreSQL writes
  require transaction-local namespace and Lease-fence validation.
- API delivery/idempotency is not a Worker Lease problem. It needs a command claim,
  durable external Effect and atomic receipt/audit semantics under API authority.
- `postgres/migrations.py` and Store composition are coordination hotspots. Cards
  that otherwise own separate aggregate modules must integrate migrations in DAG
  order instead of editing those shared files concurrently.

## CLOUD-AGG-FENCE-CON-01 - 2026-07-29

- Reuse `LeaseFence` rather than `WorkerLease`: checkpoint and timestamps are
  observations, while epoch/token/owner are the identity the transaction must
  revalidate against database time.
- Worker authority and API administrative CAS are distinct frozen types. A nullable
  fence would allow a Worker write without authority and blur the security boundary.
- Expected stream revision allows `-1` for an empty stream. Capsule pointer,
  Workspace binding and other aggregate-specific revisions stay in their focused
  command types rather than a universal union.
- A generic Unit of Work in Core would leak infrastructure mechanics and add no
  safety. The proven Effect pattern remains the target: a coarse-grained Adapter
  validates authority and performs all writes on one connection transaction.

## CLOUD-SCOPE-CON-01 - 2026-08-03

- `ADR-012` already accepts `(authority_issuer, namespace_id)` as the opaque
  durable isolation key and explicitly forbids a Zebra Tenant domain. The
  missing implementation boundary is the typed read scope, not a new identity
  system.
- The existing `SessionHistoryPort.scoped(allowed_session_ids)` and
  `MAX_HISTORY_SCOPE_SESSIONS=20` provide the compatible allow-list vocabulary.
  The new contract preserves `None` as trusted full-scope and an empty tuple as
  explicit deny-all; it rejects duplicates and malformed UUIDs before storage.
- External authority-to-`deployment_namespace` mapping stays in trusted
  composition. No adapter may derive a namespace from DSN, credentials, or
  unscoped database queries.
- This card is intentionally Core/documentation-only. Provider Continuation and
  PostgreSQL Session History remain separate locked implementation gates.
- Implementation evidence: `OpaqueAuthorityScope` is frozen/extra-forbid,
  canonicalizes UUIDs through the existing history bound, and exposes explicit
  full-scope/deny-all predicates. Core `347/347` and focused `9/9` pass; no
  storage or runtime path consumes it yet.
- Formal review on 2026-08-03 accepted the implementation and left both adapter
  successors locked. The scope contract is a prerequisite, not a backend
  selection or a claim that external Host authority verification is complete.

## CLOUD-SESSION-HISTORY-PG-01 - 2026-08-03

- Session History is a read composition over the existing namespace-scoped
  `session_projections` and `session_events` tables. It does not create a second
  authority table, write aggregate, migration or recovery source.
- Every query carries the injected `deployment_namespace`; the opaque Core scope
  supplies the optional canonical UUID allow-list. `None` is trusted full-scope,
  while an empty tuple is an explicit deny-all. External membership and namespace
  mapping remain trusted composition responsibilities.
- PostgreSQL JSONB rows are decoded through one small row helper. Only user and
  model message event types are exposed; tool and arbitrary payload fields stay
  out of snippets and message content. Browse/search/read order, bounds and
  pagination mirror the existing SQLite behavior.
- Local focused validation passes `13 passed, 3 skipped`; changed Ruff/format,
  strict Mypy for the new adapter/row modules, shell syntax, diff and Eval `10/10`
  pass. The three PostgreSQL tests are skipped without a DSN.
- The first host Compose run failed in the test fixture before adapter assertions:
  `TOOL_EXECUTION_COMPLETED` was missing required contract fields. The fixture
  now supplies the existing valid payload shape; no production or adapter code
  changed. The clean host rerun passed `3/3` and returned
  `ZEBRA_SESSION_HISTORY_POSTGRES_TEST_RESULT=PASS`; the runner removed its
  container, volume and network.
- Formal review accepted the card as `Done` with local focused `13 passed,
  3 skipped`, host `3 passed`, changed static checks and Eval `10/10`. No
  ControlPlaneStores, API/Worker, Runtime/Desktop, Redis, Mem0 or Provider
  Continuation path changed.

## CLOUD-AGG-WORKSPACE-PG-01 - 2026-07-29

- Workspace remains an Event-derived read model. Fenced Worker commits therefore
  compare the supplied Session and Workspace with projections computed from the
  currently stored rows plus the Event; matching sequence numbers alone are not
  sufficient authority.
- The smallest safe primary transaction is Event + Session + Workspace. Model Call
  and Tool Run indexes can be reconstructed from Events and remain outside this
  card's transaction until their focused PostgreSQL adapter card.
- An idempotent retry may regenerate Event ID, sequence metadata and timestamp.
  Storage must return the first canonical Event plus its canonical projections;
  otherwise a lost response can make Recorder memory diverge from PostgreSQL even
  though the business operation is idempotent.
- Lease epoch, token, owner, expiry, namespace and expected stream revision are
  validated inside the same PostgreSQL transaction. Trigger-injected faults after
  Event insertion prove rollback leaves all three primary records unchanged.
- The Worker keeps the legacy Store write path unless both the transaction Port and
  deployment namespace are injected. This card exposes the injection seam but
  deliberately does not select a backend or modify Desktop/local-agent composition;
  the complete cloud composition root belongs to `CLOUD-CONTROL-PLANE-PG-01`.

## CLOUD-AGG-TASK-PG-01 - 2026-07-29

- AgentTask is an Event/Handoff-derived index. PostgreSQL reads must never repair
  or create it; `ensure_for_session()` and `rebuild_all()` are explicit write paths.
- Rebuild and rollover use the same namespace/Task advisory transaction lock.
  Rebuild replaces derived Segment/Event rows from sequence zero, so stale rows
  cannot survive as contradictory secondary facts.
- A child Handoff belongs to a lineage only when received and committed Events
  uniquely match target Session, handoff id, stage, checksum and artifact id.
  Ambiguous, orphaned or mismatched pairs fail closed before index mutation.
- The caller-owned rollover primitive uses a savepoint and mapping-row cursor, so
  it works inside the future Handoff transaction and translates expected uniqueness
  races into a stable storage conflict without aborting the caller transaction.
- Composite ownership foreign keys keep active Segment, predecessor and indexed
  Event Segment inside the same Task. The active constraint is deferred so a
  deterministic delete/reinsert rebuild remains one valid transaction.
## CLOUD-ART-OBJ-CON-01 - 2026-07-29

- ADR-017 is the sole detailed cloud Artifact payload contract. PostgreSQL
  metadata and verified object bytes jointly form authority; `artifact://` is
  stable identity, while object locators and temporary access URLs stay internal.
- Model/Tool external `artifact_uri` remains an opaque external reference. Replay
  and read composition cannot fetch, sign, copy or convert it into managed bytes.
- The contract freezes staged/finalize/compensate and pruning recovery before any
  object SDK, provider, key encoding, migration, API route or Worker profile is
  chosen. `CLOUD-ART-PAYLOAD-PG-01` owns the later shared implementation.

## CLOUD-ART-PAYLOAD-PG-01 preflight - 2026-07-29

- `agent-storage` currently depends only on `agent-core` and `psycopg`; neither the
  workspace lock nor package manifests contain boto3, botocore, MinIO or another S3
  SDK. The base Compose already provides pinned MinIO plus idempotent bucket creation.
- Direct synchronous `botocore>=1.42.97,<1.43.0` is the minimum SDK: its low-level
  S3 model exposes conditional put, checksum metadata, version-aware head/get/delete
  and presigning without boto3's unused `s3transfer`. Existing `httpx` must not be
  expanded into a hand-written SigV4, credential, retry and error-mapping client.
- The MinIO bucket bootstrap currently creates the bucket but does not enable
  versioning. v9 must enable it and prove real MinIO `VersionId` behavior; ETag cannot
  substitute for Zebra's SHA-256/size or exact deletion evidence.
- The local `ArtifactPayloadStorePort` has no deployment namespace, Lease fence,
  expected revision or staged lifecycle. Adding optional cloud authority to it would
  let callers accidentally execute an unfenced cloud write, so v9 needs a focused
  cloud lifecycle Port while the existing Port remains a local compatibility surface.
- `ToolOutputProjector` persists bytes before it constructs Event metadata, which is
  the correct cloud seam once its persistence callback implements staged reserve and
  verified object upload. `ToolRunIndexer` currently has a post-Event fallback that
  creates payload bytes; that fallback must not become the cloud authority path.
- `EffectExecutionGuard` also persists payload before scheduling its durable Event and
  outbox intent. Atomic Effect-to-payload linkage remains owned by
  `CLOUD-EFFECT-PAYLOAD-ATOMIC-01`; v9 supplies the finalized cross-Worker payload
  primitive but must not broaden itself into the Effect aggregate.
- Migration v8 is actively owned by Handoff. Artifact can refine contracts and tests,
  but cannot claim or edit migration v9 until v8 is integrated.
- The minimum v9 metadata row needs namespace/artifact/session identity, intended
  Event sequence, idempotency key and canonical request hash; payload kind/type/name,
  SHA-256/size/retention; internal locator and exact object version; lifecycle status
  and revision; reservation fence; finalized Event identity; verification and
  transition timestamps. Composite foreign keys bind Session and finalized Event.
- Lifecycle checks make finalized/pruning/pruned rows require Event identity, object
  version and verification evidence; compensated rows cannot retain a finalized Event.
  State changes additionally lock the row and compare lifecycle revision because SQL
  checks alone cannot serialize concurrent transitions.
- Fault acceptance must cover response loss after reserve/Event/finalize, unknown put
  and Event outcomes, Lease takeover, object mismatch/permission/transport failures,
  exact-version compensation, management reconcile, cross-namespace access and
  concurrent prune/sweep. Unknown outcomes remain staged and fail closed.

## CLOUD-ART-PAYLOAD-PG-01 Worker orchestration review - 2026-07-29

- Stable Artifact identity and complete bytes are captured in memory during parallel
  Tool execution. PostgreSQL reserve waits until the terminal draft reaches the
  sequential Event sink, so its intended sequence is authoritative without creating
  a SessionEvent before reserve.
- Inline Worker deletion after object I/O is unsafe with the v9 state model: S3 delete
  cannot precede fence validation, while holding a PostgreSQL transaction across S3
  would violate the provider boundary. Therefore prepare/Event/finalize uncertainty
  remains staged with receipt evidence for management reconcile; no single empty read
  is treated as proof that an Event transaction cannot commit later.
- Existing external Artifact URIs are opaque and bypass managed capture. Conversely,
  an `artifact://` URI absent from the coordinator's pending map fails closed before
  canonical Event append.
- Cloud Tool-output composition and fenced Effect dispatch cannot yet share the Event
  path because Effect commits its terminal Event outside this coordinator. The two
  configurations fail fast until `CLOUD-EFFECT-PAYLOAD-ATOMIC-01` owns that aggregate.

## CLOUD-EFFECT-PAYLOAD-ATOMIC-01 - 2026-07-29

- No v10 migration is needed. The v9 Artifact metadata and existing Effect outbox can
  share the canonical Event transaction; a second Artifact ID column or FK would not
  prove finalized lifecycle or object availability and would add duplicate identity.
- Effect request Artifact IDs derive from root Session plus canonical Effect identity,
  not the attempt-specific ToolCall ID. Schedule acknowledgement loss therefore reuses
  the exact object even when recovery creates a new ToolCall ID, while
  `same_schedule` now rejects a changed payload reference instead of leaking an orphan.
- Object I/O remains outside PostgreSQL locks. Reserve, conditional put/verification
  and receipt recording precede one transaction that appends the Event, finalizes
  Artifact metadata and mutates the Effect outbox. Unknown outcomes remain staged for
  management recovery; the Worker never guesses by deleting inline.
- Cross-Worker reads require finalized metadata plus exact verified object evidence.
  Unknown managed terminal URIs fail closed. Effect terminal outputs captured by the
  projector use the same Event/finalize/outbox transaction as request payloads.
- The local SQLite payload path remains unchanged. Cloud composition is accepted only
  when the dispatch exposes all payload-aware atomic methods.
- An initially stale fence fails at reserve before object I/O. If authority is lost
  after a verified object exists, inline deletion is unsafe without a pre-delete claim;
  the receipt remains `STAGED`, absent from Event/outbox, and visible to management
  reconcile. Unknown commit outcomes follow the same replay/reconcile rule.

## CLOUD-ART-READ-COMP-01 preflight - 2026-07-29

- The existing API already reads through `ControlPlaneStores.artifacts` and applies
  one shared access, redaction, ordering and lifecycle serialization path. A separate
  cloud route would duplicate policy and is unnecessary.
- PostgreSQL v6 already stores every field required by the current Model/Tool read
  Ports, but its adapter exposes only fenced indexing and management replay. Adding
  namespace-scoped read methods is sufficient; no schema migration is required.
- Artifact payload v9 deliberately uses a cloud-only lifecycle Port. API composition
  must adapt its finalized/pruned metadata plus verified object bytes to read concerns
  without weakening the local payload Port or inventing a second Artifact authority.
- A read identity is the Tool projection's source Event plus the v9 binding, not only
  an Artifact UUID. Cloud aliases (`file://`, query/fragment variants) and same-Session
  swapped references must fail closed even if the target bytes otherwise exist.
- Exact-version GET is necessary because a HEAD followed by a generic latest-version
  read has a race and does not prove the bytes belong to the finalized v9 receipt.
- Read and control capabilities remain separate. Injecting a cloud reader must disable
  the legacy one-step SQLite prune path until a management-authorized cloud command
  transaction is implemented.

## CLOUD-ART-LIFECYCLE-CON-01 - 2026-07-29

- A separate cloud contract is required because the local payload Port cannot express
  namespace, fence, staged lifecycle, exact object version or management recovery.
  The old Port/domain/SQLite files remain unchanged rather than gaining optional
  cloud arguments.
- Provider-neutral object primitives bind namespace, Artifact ID, Zebra SHA-256,
  size and opaque version evidence. Put validates exact bytes; verification separates
  not-found/mismatch from unavailable errors; cleanup proves either exact-version
  deletion or verified absence.
- Lifecycle records retain the full object receipt and Event binding rather than only
  caller-supplied IDs. Finalized/pruning/pruned states validate namespace, Session,
  intended sequence, canonical `artifact://` URI, digest, size and version; all five
  states reject contradictory evidence.
- Worker and management writes use different mandatory signatures. Management reuses
  `AdministrativeMutationCAS` for the Session/revision boundary and adds immutable
  operation/operator/reason audit context instead of weakening or faking a Worker
  fence.
- Initial review caught weak management authority, incomplete finalized proof and
  contradictory lifecycle evidence despite green tests. Those P1 gaps were fixed and
  regression cases added before the card moved to Review.

## CLOUD-ART-OBJECT-S3-01 - 2026-07-29

- MinIO returns opaque non-`null` `VersionId` values once bucket versioning is enabled;
  two independent clients can observe the same canonical conditional write and read
  the exact version. Deleting that version preserves idempotent absence semantics.
- S3 response data is a trust boundary. Blank, padded, oversized or `null` versions,
  naive timestamps, malformed bodies and conflicting digest/size evidence must map to
  Zebra typed failures instead of escaping botocore, attribute or Pydantic errors.
- A dedicated Compose project plus explicit network override is required for safe
  `down --volumes`; relying on the base Compose network name would collide with the
  long-lived dependency stack and reproduce network-ownership warnings.

## CLOUD-AGG-HANDOFF-PG-01 migration foundation - 2026-07-29

- PostgreSQL Handoff must reuse `agent_tasks`, `execution_segments` and
  `task_event_index`; adding a `session_lineage` table would create a second authority.
- v8 needs only reservation/operation, immutable envelope and fenced dispatch tables.
  Every key and foreign key is namespace-scoped, while claim token plus the complete
  LeaseFence are all-present only in the claimed state.
- The legacy batch claim/ACK methods cannot prove token and full fence. Cloud Worker
  recovery must use `HandoffDispatchStorePort` and pass the fence acquired for the
  current execution instead of rediscovering authority by owner name.
- PostgreSQL claim/ACK must use `transaction_timestamp()` for expiry decisions even
  though the compatibility Port carries caller timestamps. Caller time is validated
  for shape only and never becomes cloud lease authority.
- Reusing an owner name is not authority: release plus reacquire increments the Lease
  generation, and an ACK carrying the earlier token/fence must affect zero rows.
## CLOUD-MEMORY-PG-01 durable findings (2026-07-30)

- PostgreSQL governed Memory can be authoritative before runtime cutover: v10 owns
  current rows, canonical operation receipts and temporary no-text scan membership;
  Mem0 remains a rebuildable derived index.
- A safe cloud Worker cutover cannot be expressed as an optional Memory Store alone.
  `SESSION_COMPLETED`, Memory planning/mutations/Events and Session/Workspace projections
  need one recoverable finalization boundary, and planning must validate its active
  scope set under the commit lock. The composition root must also prove all participating
  Stores share the same PostgreSQL namespace. Keep runtime wiring deferred until those
  three conditions are represented together.
- Legacy SQLite import is an explicit offline operation: open with `mode=ro`, preflight
  the complete source before PostgreSQL writes, lock and revalidate the target in one
  transaction, and emit only identifiers/codes/digests in quarantine evidence.

## CLOUD-AGG-CTX-ADMIN-PG-01 durable findings (2026-07-30)

- A preflight Workspace read in the API is not an authority check: another writer can
  change or remove the projection before commit. Administrative aggregate transactions
  must lock the Session stream and compare both current projections inside PostgreSQL.
- Historical activation must keep two times distinct: Artifact identity and content
  come from the selected capsule's creation Event, while active-pointer `updated_at`
  comes from the new canonical recovery Event.
- Keep cloud recovery opt-in through an explicit composition namespace. Inferring the
  backend or namespace from a concrete adapter would couple API code to infrastructure;
  adding it to the full Store bundle before cloud composition is complete would spread
  an unfinished runtime selector.

## MEM-GW-DEL-PLAN-01 durable findings (2026-08-02)

- The sidebar ChatGPT review confirmed that `MEM-GW-DEL-01` is a cross-layer gate,
  not a safe single implementation card. Keep it `Locked` until Core certainty,
  PostgreSQL atomic enqueue and provider reset/rebuild are separately proven.
- Mem0 `POST` is not idempotent. A timeout, disconnect, 5xx or malformed success
  response is `unknown`, must quarantine the scope generation and must never be
  retried automatically. Parsing a free-form Gateway detail string is forbidden.
- Delivery operations must be metadata-only. The v11 ledger stores Memory ID,
  revision, content digest, scope/generation, provider ref and typed error codes;
  Memory text, provider bodies and credentials remain outside the ledger.
- Search admission is a batch authority check over active mapping, provider ref,
  scope/generation and current confirmed/unexpired PostgreSQL state. A provider hit
  is never authoritative and never carries Memory text into the prompt path.
- Provider reset/rebuild is management-only: scan v10 confirmed facts, drain a
  delivery high-watermark, atomically switch generation, then purge the old generation
  only after a bounded scoped reset is proven. A global Mem0 `/reset` does not satisfy
  the contract.
- The cloud mainline clone had missing reachable Git objects because it was created
  from a deleted temporary alternate. The missing objects were restored from the
  local Zebra checkout before creating the planning worktree; this is repository
  repair evidence, not an implementation dependency.
- On 2026-08-02 the maintainer explicitly activated `MEM-GW-DEL-CON-01` only. Its
  implementation is restricted to Core values, transitions, Ports and tests; the
  reset Spike, PostgreSQL v11 ledger and runtime consumer remain locked successors.
- The Core contract now keeps `MemoryDeliveryCertainty` independent from legacy
  Gateway status strings. `MemoryGatewayMutationResult.detail` is explicitly
  diagnostic; legacy Adapter calls receive conservative defaults until the runtime
  child supplies explicit certainty.
- `claimed` and `in_flight` are intentionally distinct: a claim can return to
  `pending`, while an expired in-flight network request becomes `uncertain` and
  cannot be automatically retried. Terminal `completed`, `uncertain` and
  `dead_letter` states have no outgoing transition.
- Core delivery records contain only Memory ID, revision, SHA-256 digests,
  operation, scope/generation, idempotency key, attempt, state and certainty. No
  provider body, Memory text, credential or storage type enters the contract.

## MEM-MEM0-RESET-SPIKE-01 activation and implementation (2026-08-02)

- The sidebar ChatGPT review activated only the test-only reset probe. The exact
  owned paths are `docker/compose.mem0.test.yml`, focused `docker/mem0/` helpers,
  `tests/spikes/mem0/` and the Mem0 compatibility evidence doc; Core, PostgreSQL
  delivery, Worker, Adapter and local SQLite composition remain out of scope.
- The probe uses an isolated Compose project with a response-loss proxy that commits
  the first `POST /memories` upstream and closes the client response. It enumerates
  only documented pagination parameters, deletes each exact generation object, and
  uses read-only PostgreSQL payload queries as an oracle. It never calls a global
  `/reset`, mutates provider tables, or retries an unknown publish.
- Static Ruff, Python compilation, Compose config validation and the gated test
  collection pass. The real Compose run failed closed at the bounded-enumeration
  gate: OpenAPI parameters were only `agent_id`, `run_id`, `show_expired`, `top_k`
  and `user_id`; `page/page_size` and `offset/limit` were absent. The child is
  therefore `Blocked`, `top_k` is not pagination, and no reset/rebuild success is
  claimed.

## MEM-GW-DEL-PG-01 activation (2026-08-02)

- The maintainer activated `codex/mem-gw-del-pg-01` after the Core certainty
  contract was integrated. This child owns the metadata-only PostgreSQL v11
  ledger, atomic v10 authority enqueue, independent claim/CAS and batch search
  revalidation paths listed in `docs/AGENT_TASKS.md`.
- The scoped Mem0 reset child is independently `Blocked` because its provider
  list contract has no bounded pagination. That management-only result does not
  block this PostgreSQL authority slice; the parent ledger, Worker consumer and
  Mem0 runtime remain `Locked`.
- No default Worker composition, provider HTTP call or local SQLite behavior is
  authorized by this activation.

## MEM-GW-DEL-PG-01 implementation (2026-08-02)

- Added migration v11 with `memory_delivery_scopes`,
  `memory_delivery_operations` and `memory_provider_mappings`. All three tables
  are metadata-only; provider response bodies, Memory text, raw scope labels and
  credentials are absent. Different opaque scope digests may coexist, while one
  active generation is allowed per digest.
- `PostgresMemoryDeliveryLedger` implements idempotent enqueue, `SKIP LOCKED`
  claims, random tokens, DB-time expiry, distinct claimed/in-flight recovery,
  typed certainty CAS, mapping updates and batch authority revalidation. An
  unknown outcome quarantines its scope and therefore cannot be automatically
  claimed again.
- `PostgresGovernedMemoryStore(delivery_scope=...)` composes enqueue into the
  same v10 authority transaction. Existing construction without that explicit
  scope remains unchanged and does not activate Worker, Mem0 or SQLite paths.
- The isolated host runner `tests/spikes/memory_delivery/run-postgres-tests.sh`
  passes `24` tests, including fresh/v1-v10 upgrade/checksum, migration rollback,
  replay, atomic enqueue, stale ACK, namespace isolation, unknown/in-flight quarantine and one-shot
  search admission. The full `tests/agent_storage` PostgreSQL matrix also passed
  `295` tests with one pre-existing skip.

## MEM-GW-DEL-PG-01 review handoff (2026-08-02)

- The PostgreSQL child is moved to `Review` with its owned paths, focused tests,
  migration evidence and host Compose runner recorded above. The parent ledger
  remains `Locked` because the scoped reset/rebuild gate is still `Blocked`.

## MEM-MEM0-RESET-ALT-01 activation (2026-08-02)

- The sidebar ChatGPT planning result selected this as the single next task after
  the v11 merge. It is intentionally a zero-production-code Spike: use the
  PostgreSQL ledger and deterministic in-memory provider stand-in to test
  generation fencing, mapping-only deletion and the unknown-publish orphan
  boundary.
- The task is independent of the blocked provider pagination result but cannot
  unlock the runtime consumer by assumption. A complete physical reset must
  still be proven, or the provider must be explicitly rejected from this path.

## MEM-MEM0-RESET-ALT-01 implementation and review handoff (2026-08-02)

- Added a dependency-only PostgreSQL Compose profile and two test-only cases:
  known mapping deletion plus generation fencing, and an upstream-committed
  unknown publish whose provider ref is intentionally absent from the ledger.
- The isolated runner passed `2` tests with verdict `B/PARTIAL`. Logical reset is
  safe for search admission and known mappings, but an unknown provider orphan
  cannot be recovered or physically deleted from mapping-only evidence.
- The existing delivery focused runner passed `24`; the full storage matrix passed
  `295` with one pre-existing skip. No Provider HTTP, Worker, Desktop or local
  SQLite composition started. The task is moved to `Review`; runtime remains
  `Locked` pending a deletion-compliance decision.

## MEM-PROVIDER-DEL-COMPLIANCE-01 activation (2026-08-02)

- The sidebar ChatGPT review selected this as the only legal Ready successor after
  the alternative reset returned `B/PARTIAL`. The task is docs/specification-only
  on `codex/mem-provider-del-compliance-01`; no production path is activated.
- ADR-018 defines three mandatory capabilities: deterministic recovery after a
  lost response, deterministic physical deletion with a postcondition, and
  complete scoped coverage by bounded enumeration, deterministic lookup or an
  atomic namespace drop. Best effort and `top_k` are explicitly insufficient.
- The current Mem0 admission is fail-closed: logical fencing `PASS`, ledger-only
  known mapping deletion `PASS`, ambiguous-create recovery `FAIL/UNPROVEN`,
  complete scoped physical deletion `FAIL/UNPROVEN`, Runtime `BLOCKED`.
- `MEM-MEM0-RESET-SPIKE-01` remains `Blocked`; `MEM-GW-DEL-RUN-01`, the parent
  ledger and Runtime composition remain `Locked` until a future provider version
  supplies and proves the missing capabilities.

## MEM-PROVIDER-DEL-COMPLIANCE-01 review handoff (2026-08-02)

- ADR-018 is the provider-neutral deletion contract. Its specification matrix
  passes `2` focused tests and records a contract `PASS` without implying Mem0
  Runtime admission.
- Changed-path Ruff, format, Mypy, Python compilation and `git diff --check` pass.
  `make check` is blocked at the file-size gate by two untouched baseline files:
  Desktop stylesheet `561/500` and PostgreSQL storage test `765/700`.
- Mem0 remains Experimental/Research only; no task status was changed for the
  blocked reset Spike or locked delivery consumer. No production code changed.

## MEM-PROVIDER-DEL-COMPLIANCE-01 closeout (2026-08-02)

- ADR-018 is accepted as the deletion/recovery admission boundary. The task is
  `Done`; Mem0 is explicitly `Provider admission: DENIED` and
  `Mainline candidate: DEFERRED`. Future re-entry requires new upstream
  capability evidence and a new admission run.

## MEM-PG-NATIVE-ADMISSION-SPIKE-01 implementation (2026-08-02)

- The sidebar ChatGPT review selected this as the only legal Ready successor. It
  is a test-only PostgreSQL-native admission slice on
  `codex/mem-pg-native-admission-spike-01`; the blocked Mem0 reset/consumer cards
  are not dependencies and remain locked/deferred.
- Added a per-test PostgreSQL schema with namespace/scope generation authority,
  deterministic operation identity, content-bearing retrieval projection and
  content-free operation audit. No production migration or package changed.
- Eight real PostgreSQL cases cover deterministic replay, response-loss recovery,
  atomic projection/rollback, stale-generation write fencing, complete scoped
  deletion, namespace isolation and minimum recall semantics. The isolated
  Compose runner starts only PostgreSQL 17.5 and emits
  `ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS`.

## MEM-PG-NATIVE-ADMISSION-SPIKE-01 review handoff (2026-08-02)

- ADR-019 is accepted with architecture verdict `PASS`. The focused runner passes
  `8` cases on PostgreSQL `17.5-alpine3.21`; the full `tests/agent_storage` matrix
  passes `303 passed, 1 skipped` (`295` predecessor cases plus `8` new cases).
- Changed-path Ruff, format, Mypy, compilation and `git diff --check` pass.
  `make check` remains blocked by the two untouched file-size baseline
  violations (`561/500` Desktop stylesheet and `765/700` PostgreSQL test).
- The result admits only the test-proven PostgreSQL-native architecture. It does
  not unlock `MEM-GW-PG-NATIVE-01`, Runtime, Worker, Provider HTTP, Desktop,
  SQLite or Redis. Mem0 remains denied/deferred.

## CLOUD-AGG-FENCE-CTX-SEMANTIC-01 implementation (2026-08-03)

- The PostgreSQL `commit_administrative_activation` boundary now validates the
  existing strict `ContextCompactedPayload` contract before opening any write
  path: the Event must be `CONTEXT_COMPACTED`, its nested capsule must match the
  requested `capsule_id`, and `recovered_from_capsule_id` must be absent or match
  that same capsule. Invalid input raises the existing conflict type and leaves
  the Event stream and active pointer unchanged.
- Three focused regressions cover wrong Event type, nested capsule mismatch and
  recovery binding mismatch. The isolated PostgreSQL Compose runner passes
  `18/18` (Context lifecycle plus API recovery) on PostgreSQL
  `17.5-alpine3.21`; no migration, API contract or runtime composition changed.
- Sidebar ChatGPT returned `CLOSEOUT-OK`, moved the implementation card from
  `Review` to `Done`, and allowed the parent Context conformance audit's
  `BLOCK-GAP` to close. The aggregate fencing gate remains `Locked` because
  other aggregate cards are still pending.

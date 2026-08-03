# Zebra Agent Project Status

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Current Mainline Snapshot

- Snapshot date: `2026-08-02`
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
- Agent Definition architecture task in Review: `AGENT-DEF-ADR-01` records accepted
  Definition control-plane decisions and updates the final architecture. It
  separates Task-level Definition configuration from Attempt-level execution
  authority and preserves ADR-012's opaque external namespace. Code audit also
  confirmed that external Attempt authority snapshots and immutable Skill content
  snapshots are not yet implemented; dedicated locked tasks now own those gaps.
  This integration records the decision only; implementation remains governed by
  the registered dependency DAG and explicit task activation.
  The implementation order is `CON -> STO -> {PG,DRAFT}`, `CON -> AUTH`, then
  `{DRAFT,AUTH} -> BIND -> MEM -> TRUST -> EVAL -> PUB`.
- Locked architecture tasks: ACP entry and optional code intelligence
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

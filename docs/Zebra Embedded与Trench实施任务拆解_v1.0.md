# Zebra Embedded 与 Trench 实施任务拆解 v1.1

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-24 |
| 架构基线 | `Zebra Embedded 生产级目标架构.md`、ADR-015 |
| 当前可执行任务 | 无；等待已完成任务按依赖顺序评审、合并与重新激活 |
| Review 任务 | `EMB-PLAN-01`、`EMB-AGUI-SPIKE-01`、`CLOUD-STO-SEAM-01`、`CLOUD-STO-AUTH-01`；Trench Spike 保持本地待处理 |
| 其他任务 | `Locked`，等待依赖和 maintainer 逐卡激活 |
| 第一业务验收 | Trench Event Detail 的生产只读链路 |

## 1. 执行规则

1. 一个任务、一个 owner、一个 branch、一个 worktree、一个主 PR。
2. Zebra 与 Trench 的修改必须拆成不同仓库任务，不创建跨仓库巨型 PR。
3. 合并顺序固定为 ADR/Contract → Domain/Ports → Adapter → App Wiring → E2E。
4. 下列 Owned paths 是锁定前的候选边界；任务变为 `Ready` 前必须在对应仓库
   的任务注册表中落实到精确文件或子目录。
5. Shared files、root config、`PROGRESS.md` 和 contracts 是协调热点，不与功能
   Adapter 混入同一 PR，除非任务明确拥有。
6. 所有 Zebra 实现任务先运行 `make sync`，完成 focused tests，并以
   `make check` 收口。Trench 命令在该仓库任务卡激活时固定。
7. `Locked` 不代表可以提前编码；依赖必须已经合并到最新 `main`。

## 2. 总依赖

```mermaid
flowchart TD
    PLAN["P0 架构收敛"] --> SPIKE["P0 双仓库 Spike"]
    PLAN --> SEAM["Zebra Storage Composition Seam"]
    SEAM --> AUTH["Authoritative Store Composition"]
    AUTH --> CLOUD["P2 Cloud Durable Foundation"]
    CLOUD --> MEMORY["Memory Gateway + Mem0 Gate"]
    SPIKE --> CONTRACT["P1 Host / AG-UI / Surface Contracts"]
    CONTRACT --> READ["P3 Trench Read-only Slice"]
    CLOUD --> READGATE["Production Read-only E2E"]
    READ --> READGATE
    READGATE --> FRONTEND["P4 Frontend Collaboration"]
    FRONTEND --> ANALYSIS["P5 Deterministic Analysis"]
    ANALYSIS --> WRITE["P6 Controlled Writeback"]
    WRITE --> GA["P8 Multi-tenant GA"]
    MEMORY --> GA
```

Storage Seam 使用现有通用 Store Ports，不依赖 Host/AG-UI/Surface 契约。当前调度
优先完成 Zebra durable foundation 和 Agent Memory Gateway，再恢复 Trench 实施；
Memory 仍是可降级增强能力，不进入 Run 或 read-only E2E 的必需运行时依赖。Cloud
与 Host 协议两条线只有在真实环境汇合并通过恢复/安全门禁后，才可称为 production
read-only。

## 3. P0：架构与兼容性

### EMB-PLAN-01 — Embedded architecture consolidation

- Status/branch: `Review` / `zebra-cloud-trench`；Zebra repo。
- Depends on: ADR-012、ADR-013、Runtime blueprint、maintainer 的 CopilotKit 决策。
- Owned paths: 目标架构、ADR-015、本任务拆解、任务注册表和治理记录。
- Deliverable: 一份无冲突目标架构，删除 React SDK 和 pgvector/Graphiti 方案。
- Acceptance: 文档、链接、任务依赖和项目状态一致；不修改生产代码。

### EMB-AGUI-SPIKE-01 — Zebra AG-UI protocol spike

- Status: `In Progress`；branch `codex/emb-agui-spike-01`；Zebra repo。
- Depends on: `EMB-PLAN-01`；maintainer 已明确激活 stacked local branch，合并仍等待依赖进入 `main`。
- Owned paths: `pyproject.toml`, `uv.lock`, `tests/spikes/ag_ui/`, focused compatibility note and governance records。
- Deliverable: pin `ag-ui-protocol`；验证 encoding、SSE、interrupt/resume、unknown event。
- Acceptance: golden stream 可被官方 Python client decode；不接入 API/Worker production wiring。

### TRN-CPK-SPIKE-01 — Trench CopilotKit v2 runtime spike

- Status: `Locked`；Trench repo only。
- Depends on: `EMB-PLAN-01` merged。
- Candidate paths: Trench isolated spike route/page/test fixture；精确路径由 Trench 注册。
- Deliverable: `<CopilotKit>` → Runtime v2 handler → `HttpAgent` → fake Zebra AG-UI。
- Acceptance: text、tool、interrupt、resume、reload、Header policy 全通过；记录版本和许可证边界。

### P0 gate

- 两个 Spike 固定同一协议版本矩阵和升级策略。
- 生产不使用 `agents__unsafe_dev_only`。
- 未确认 OSS/Enterprise 边界的功能不得成为 required dependency。

## 4. P1：协议冻结

### EMB-HOST-CON-01 — Generic Host authority contracts

- Status: `Locked`；Zebra repo；depends on both P0 Spikes。
- Candidate paths: `packages/agent-core/src/agent_core/domain/host_authority.py`, contract tests。
- Deliverable: HostSessionGrant claims、HostContextEnvelope、ResourceRef、namespace、scope、limits、errors。
- Acceptance: no Trench imports；invalid issuer/origin/expiry/scope/resource fixtures fail closed。

### EMB-AGUI-CON-01 — Durable AG-UI projection contract

- Status: `Locked`；Zebra repo；depends on `EMB-HOST-CON-01`。
- Candidate paths: `packages/agent-integrations/src/agent_integrations/ag_ui/`, contract tests。
- Deliverable: Task/thread、Segment attempt/run、event、cursor、interrupt/resume mapping。
- Acceptance: golden fixtures cover text/tool/state/error/reconnect；mapping is a pure projection。

### EMB-SURFACE-CON-01 — Frontend surface and shared-state contracts

- Status: `Locked`；Zebra repo；depends on `EMB-AGUI-CON-01`。
- Candidate paths: focused `agent-core` domain/port modules and contract tests。
- Deliverable: FrontendCapability、SurfaceLease、ActionReceipt、state partition/version/patch。
- Acceptance: expiry、unmount、duplicate action、version conflict and resync are deterministic。

### EMB-TOOL-CON-01 — Host tool contract extension

- Status: `Locked`；Zebra repo；depends on `EMB-HOST-CON-01`。
- Candidate paths: focused modules under `packages/agent-tools/`, contract tests。
- Deliverable: execution location、scope、risk、timeout、size、idempotency、receipt schema。
- Acceptance: reuses existing ToolDefinition/Result contracts; no parallel tool model。

### P1 gate

- Python/JSON/TypeScript fixtures share versioned schemas and canonical examples。
- Unknown fields/events have explicit forward-compatibility behavior。
- 相关 Domain/Port contract 必须先于对应 Adapter；Host/AG-UI/Surface 契约只阻塞
  Host transport、Trench 和 UI Adapter，不阻塞复用现有 Store Ports 的 composition seam。

## 5. P2：Cloud durable foundation

### CLOUD-STO-SEAM-01 — Storage composition seam

- Status: `Review`；Zebra repo；branch `codex/cloud-sto-seam-01`；owner `Codex`。
- Depends on: locally reviewed `EMB-PLAN-01` baseline、completed Runtime Phase A and
  maintainer activation on 2026-07-23；stacked branch must not merge before `EMB-PLAN-01`。
- Owned paths: API storage wiring, Worker composition/execution wiring,
  `agent-storage` composition, focused API/Worker tests and task governance records。
- Deliverable: one typed control-plane Store bundle and local SQLite builder; inject the
  existing Event/Projection/Workspace/Task/Lease Ports through API, SSE and Worker flows。
- Acceptance: target Store constructors appear only in the local SQLite builder; same-path
  spies prove injection and distinct-path use fails closed before a split write; local SQLite
  behavior remains unchanged; no PostgreSQL、Redis、S3、migration、backend enum or new dependency。

### CLOUD-STO-AUTH-01 — Complete authoritative Store composition

- Status: `Review`；Zebra repo；branch `codex/cloud-sto-auth-01`；owner `Codex`。
- Depends on: maintainer explicitly activated local stacked implementation on
  2026-07-24；branch is based directly on local `CLOUD-STO-SEAM-01` and must not
  merge before `EMB-PLAN-01 -> CLOUD-STO-SEAM-01`。
- Owned paths: focused Core Store Ports、SQLite adapter conformance、API/Worker
  storage composition、authoritative A/B regressions and governance records。
- Deliverable: compose context lifecycle、handoff/dispatch、idempotency、effect ledger、
  governed memory、Artifact payload/index、provider continuation、session history and
  delivery-audit authorities before backend selection；remove the legacy path guard。
- Acceptance: compaction/recovery/handoff/memory/effect A/B tests keep one authoritative
  stream and prove the unused path is not created；API/SSE/Worker contain no target
  SQLite constructor；`:memory:` remains rejected；focused/full/quality blockers are recorded。

### CLOUD-PG-01 — PostgreSQL event and projection storage

- Status: `Review`；branch `codex/cloud-pg-01-events-v1`；depends on locally
  reviewed `CLOUD-STO-AUTH-01` plus the approved `CLOUD-PG-PLAN-01` model。
- Candidate paths: `packages/agent-storage/.../postgres/`, migrations, storage tests。
- Deliverable: Event Store、Projection、monotonic sequence、expected-version CAS、replay。
- Acceptance: concurrent append/idempotency/rebuild tests plus real PostgreSQL CI pass。

### CLOUD-PG-PLAN-01 — PostgreSQL migration and recovery model review

- Status: `Review`；branch `codex/cloud-pg-plan-01`；docs-only local task。
- Depends on: local reviewed `CLOUD-STO-AUTH-01` and maintainer waiver to continue
  local evidence while GitHub Actions billing is blocked；merge/release gates remain。
- Candidate paths: one focused decision document and governance records only。
- Deliverable: authoritative scope、offline cutover、backup/PITR、restore validation、
  fencing/outbox recovery and rollback boundaries。
- Acceptance: unlock criteria for `CLOUD-PG-01` are executable and no unapproved
  RPO/RTO、dual-write、Adapter、migration script or production claim is introduced。

### CLOUD-LEASE-PLAN-01 — Lease, fencing and Effect dispatch contract

- Status: `Review`；branch `codex/cloud-lease-plan-01`；docs-only local task。
- Depends on: locally reviewed `CLOUD-PG-01` and the temporary local-evidence waiver。
- Deliverable: separate checkpoint from fencing、freeze DB-clock Lease semantics、define
  atomic Effect/Outbox and uncertain-effect recovery、split the oversized parent card。
- Acceptance: one reviewed contract and four path-bounded implementation cards；the parent
  remains Locked and no Python、migration SQL、generic UoW/inbox or production claim is added。

### CLOUD-LEASE-CON-01 — Core Lease and fencing contract

- Status: `Review`；branch `codex/cloud-lease-con-01`；maintainer explicitly
  activated local stacked implementation on 2026-07-28；merge still requires
  `CLOUD-LEASE-PLAN-01` first。
- Implemented paths: Core Lease domain/Port/errors、SQLite Lease conformance、handoff
  fence facts、Worker claim ordering and focused compatibility tests。
- Deliverable: typed epoch/token/owner fence、monotonic checkpoint、full-CAS errors、
  idempotent legacy migration and bounded TTL validation。
- Acceptance: reacquire/takeover token monotonicity、stale fence rejection and checkpoint
  independence pass without PostgreSQL、background heartbeat or Effect dispatch。

### CLOUD-LEASE-PG-01 — PostgreSQL epoch and Lease Adapter

- Status: `Review`；branch `codex/cloud-lease-pg-01`；maintainer explicitly
  activated local stacked implementation on 2026-07-28；merge still requires
  `CLOUD-LEASE-CON-01` and `CLOUD-PG-01` first。
- Evidence: additive migration v2、strict epoch bootstrap/restore rotation、DB-clock
  full-fence CAS、retained generation and real PostgreSQL races pass；Store selection、
  runtime DB roles、Worker wiring and production cutover remain excluded。
- Candidate paths: PostgreSQL migration、epoch/Lease modules、exports and real-service tests。
- Deliverable: DB-clock expiry、retained generations、concurrent acquire and restore rotation。
- Acceptance: two-worker race、same-worker-instance collision、takeover、wrong namespace and
  old-epoch writes fail or succeed exactly as the Core contract requires。

### CLOUD-EFFECT-OUTBOX-01 — Fenced Effect dispatch aggregate

- Status: `Locked`；depends on merged `CLOUD-LEASE-PG-01`。
- Candidate paths: focused Core dispatch Port/types、PostgreSQL Effect/Outbox modules,
  migration and real-service tests。
- Deliverable: atomic Event/Effect/Outbox schedule and terminal transactions、SKIP LOCKED
  claim、uncertain/reconciliation lifecycle。
- Acceptance: injected write failures leave no half-state；duplicate schedule/claim and stale
  fences cannot duplicate an external-effect intent；no generic Unit of Work or inbox。

### CLOUD-EFFECT-CONSUMER-01 — Worker fenced consumer integration

- Status: `Locked`；depends on merged `CLOUD-EFFECT-OUTBOX-01`。
- Candidate paths: Worker claim/recovery/heartbeat/Event lifecycle、agent-tools Effect
  integration and focused Worker tests。
- Deliverable: acquire-before-recover、periodic heartbeat、lost-Lease stop、fenced release and
  provider reconciliation。
- Acceptance: long-run lease loss stops new model/Event/Effect work；crash after provider
  success never auto-replays an uncertain Effect；terminal replay returns durable result。

### CLOUD-LEASE-01 — Lease, fencing and Event/Effect delivery parent gate

- Status: `Locked`；depends on the four implementation cards above。
- Deliverable: close Session Lease and fenced Event/Effect execution、atomic effect dispatch
  and at-least-once discovery using combined real PostgreSQL evidence。
- Acceptance: two-worker race、restore epoch、crash matrix and duplicate-delivery gates all
  pass；the result is neither exactly-once external execution nor full Worker aggregate safety。

### CLOUD-AGG-FENCE-01 — Full Worker aggregate fencing gate

- Status: `Locked`；depends on PostgreSQL Adapters for every authoritative Worker-owned
  aggregate and merged `CLOUD-LEASE-01`。
- Candidate scope: ContextLifecycle、Handoff/dispatch、Workspace/Task、Model/Tool run、
  provider continuation/history、Artifact and delivery-audit aggregate transactions。
- Deliverable: split path-bounded conformance cards only after the PostgreSQL Adapter
  inventory exists；each aggregate validates the current Lease fence inside its own transaction。
- Acceptance: stale epoch/token/owner tests pass per aggregate on real PostgreSQL；before this
  gate no document may claim complete multi-Worker safety。

### CLOUD-ART-01 — Object storage

- Status: `Locked`；depends on `CLOUD-PG-01`；may parallel `CLOUD-LEASE-01` by subpath。
- Candidate paths: `agent-storage` object adapter, Artifact/Snapshot composition, tests。
- Deliverable: S3/MinIO payload、PostgreSQL manifest、checksum、signed access、retention。
- Acceptance: missing/deleted object, cross-namespace access and restore are covered。

### CLOUD-LIVE-01 — Redis live fan-out

- Status: `Locked`；depends on `CLOUD-PG-01`、`CLOUD-LEASE-01` and
  `CLOUD-AGG-FENCE-01`。
- Candidate paths: Redis adapter, outbox publisher, API stream composition, integration tests。
- Deliverable: replay-plus-tail without per-client SQLite polling；Redis remains ephemeral。
- Acceptance: Redis restart/gap falls back to PostgreSQL cursor with no lost/duplicated public event。

### CLOUD-RT-01 — Kubernetes gVisor profile

- Status: `Locked`；depends on `CLOUD-ART-01` and existing Phase A Runtime。
- Candidate paths: runtime Kubernetes adapter, Helm manifests, real-cluster CI fixtures。
- Deliverable: gVisor RuntimeClass、bounded volume、Snapshot restore、default-deny network。
- Acceptance: real cluster executes/cancels/restores and fails closed without gVisor。

### CLOUD-REC-01 — Migration, backup and recovery gate

- Status: `Locked`；depends on all prior P2 cards。
- Candidate paths: migration/recovery tests, runbook, acceptance evidence only。
- Deliverable: SQLite export/import policy、PostgreSQL PITR、S3 restore、rollback and failover drill。
- Acceptance: measured RPO/RTO and repeatable commands; no production claim without evidence。

### P2 gate

- PostgreSQL and S3 are truth; Redis can be erased without Task loss。
- Multi-worker fencing and duplicate suppression are proven on real services。
- Migration/backup/rollback review is signed before production traffic。

## 6. P3：Trench read-only vertical slice

### EMB-AUTH-01 — Host registry and Grant verifier

- Status: `Locked`；Zebra repo；depends on `EMB-HOST-CON-01` and `CLOUD-PG-01`。
- Candidate paths: `agent-security` verifier/registry, config, API auth middleware, tests。
- Deliverable: issuer/JWKS/aud/jti/origin/namespace/resource/scope validation and exact CORS。
- Acceptance: forged, expired, replayed and cross-namespace grants fail closed; local profile remains compatible。

### EMB-AGUI-API-01 — Production AG-UI endpoint

- Status: `Locked`；Zebra repo；depends on `EMB-AGUI-CON-01`, `EMB-AUTH-01`, `CLOUD-LIVE-01`。
- Candidate paths: AG-UI integration package, API route/composition, focused tests。
- Deliverable: run、stream、stop、resume、replay-tail and RFC 9457 failures。
- Acceptance: API only writes commands/reads projections; Harness never executes in API process。

### EMB-HOST-GW-01 — Typed Host Tool Gateway

- Status: `Locked`；Zebra repo；depends on `EMB-TOOL-CON-01` and `EMB-AUTH-01`。
- Candidate paths: `agent-integrations/.../host_tools/`, security transport helpers, tests。
- Deliverable: manifest discovery/invoke、workload identity、scope intersection、SSRF、receipt。
- Acceptance: timeout/4xx/5xx/invalid body are structured recoverable results; secrets never reach model/Sandbox。

### TRN-READ-01 — Trench read Tool API

- Status: `Locked`；Trench repo only；depends on P1 contracts。
- Candidate paths: Trench internal Zebra tool controller/service/schema/tests。
- Deliverable: get_event/evidence/related_events/entity_timeline/topic。
- Acceptance: authoritative Trench RBAC/resource checks, bounded payloads and idempotent reads。

### TRN-CPK-BFF-01 — Trench production Copilot Runtime/BFF

- Status: `Locked`；Trench repo only；depends on `TRN-CPK-SPIKE-01` and `EMB-AUTH-01` contract。
- Candidate paths: Trench server runtime route, auth/grant exchange and tests。
- Deliverable: Runtime v2 handler registers Zebra HttpAgent and server-side Header allowlist。
- Acceptance: no browser service secret/direct agent; refresh/expiry and origin policy tested。

### TRN-PANEL-01 — Read-only Copilot panel

- Status: `Locked`；Trench repo only；depends on `TRN-CPK-BFF-01` and `TRN-READ-01`。
- Candidate paths: Event Detail panel, CopilotKit hooks/renderers, frontend tests。
- Deliverable: current event context、streamed messages、tool/result and Artifact references。
- Acceptance: no Zebra SDK package; reload resumes same thread/Task without duplicating message。

### EMB-TRN-READ-E2E-01 — Production read-only acceptance

- Status: `Locked`；Zebra acceptance repo paths only；depends on all P2/P3 cards。
- Candidate paths: root cross-service integration tests and focused acceptance record。
- Deliverable: real Trench Event Detail → BFF → Zebra → Trench Tool chain。
- Acceptance: stream/reload/cancel/resume, forged grant, namespace denial, worker/Redis restart all pass。

### P3 gate

- This is the first production business milestone。
- No analysis, frontend mutation, writeback or remote memory is required for exit。
- Failures report truthful structured evidence; no silent fallback to unauthenticated/local behavior。

## 7. P4：Frontend collaboration

### EMB-SURFACE-01 — Surface lease and action dispatch

- Status: `Locked`；Zebra repo；depends on `EMB-SURFACE-CON-01` and P3 gate。
- Candidate paths: focused core/storage/API modules and tests。
- Deliverable: register/renew/revoke surface、presence、capability snapshot、Action Receipt。
- Acceptance: expired/unmounted surface rejects dispatch; retries are idempotent and auditable。

### TRN-STATE-01 — CopilotKit shared state integration

- Status: `Locked`；Trench repo only；depends on `EMB-SURFACE-01` contract。
- Candidate paths: Trench panel state bridge and tests。
- Deliverable: `/agent` `/host` `/shared` ownership, versioned patch and resync UI。
- Acceptance: stale base version cannot overwrite newer state; large data remains referenced。

### TRN-FRONTEND-TOOLS-01 — Semantic frontend tools

- Status: `Locked`；Trench repo only；depends on `TRN-STATE-01`。
- Candidate paths: Event Detail capability registry/handlers/renderers/tests。
- Deliverable: highlight/select/open/compare/show-analysis actions via `useFrontendTool`。
- Acceptance: no DOM/eval/arbitrary navigation; presence/schema/receipt enforced。

### EMB-TRN-FRONTEND-E2E-01 — Collaboration failure matrix

- Status: `Locked`；depends on all P4 cards。
- Candidate paths: Zebra integration/E2E fixtures and acceptance record。
- Deliverable: disconnect、unmount、duplicate action、state conflict and reconnect scenarios。
- Acceptance: no stale action and deterministic snapshot/resync across browser/API restart。

## 8. P5：Deterministic analysis

### DATA-CON-01 — Analysis contracts

- Status: `Locked`；Zebra repo；depends on P3 gate。
- Candidate paths: focused `agent-core` analysis domain/port modules and tests。
- Deliverable: DatasetRef、AnalysisManifest、JobRef、Metric、Finding、lineage schemas。
- Acceptance: immutable IDs/checksum/version/resource limits and serialization fixtures pass。

### TRN-DATASET-01 — Trench dataset snapshot API

- Status: `Locked`；Trench repo only；depends on `DATA-CON-01` fixtures。
- Candidate paths: Trench snapshot service/object writer/auth/tests。
- Deliverable: authorized immutable dataset snapshot or signed reference。
- Acceptance: exact query/time range/version/checksum recorded; expiry and revocation tested。

### DATA-RUNTIME-01 — Approved DuckDB/Polars runtime

- Status: `Locked`；Zebra repo；depends on `DATA-CON-01`, `TRN-DATASET-01`, `CLOUD-ART-01`。
- Candidate paths: focused data runtime adapter under `agent-runtime`, tool wiring, tests。
- Deliverable: inspect/estimate/submit/cancel approved operators with CPU/memory/time limits。
- Acceptance: no arbitrary Python/package/network; deterministic replay and cancellation pass。

### DATA-PHASE-01 — Event propagation phase detection

- Status: `Locked`；Zebra repo；depends on `DATA-RUNTIME-01`。
- Candidate paths: focused deterministic analysis module and tests/fixtures。
- Deliverable: versioned phase algorithm with evidence, counter-evidence and confidence inputs。
- Acceptance: same manifest/data/version yields same Finding; model prose cannot alter fact fields。

### TRN-ANALYSIS-UI-01 — Analysis rendering

- Status: `Locked`；Trench repo only；depends on `DATA-PHASE-01` output contract。
- Candidate paths: CopilotKit renderers, PhaseTimeline/cards and frontend tests。
- Deliverable: metric/finding/lineage rendering and semantic panel actions。
- Acceptance: every claim links to DatasetRef/evidence/algorithm version; no raw large data in chat state。

### EMB-TRN-ANALYSIS-E2E-01 — Reproducible analysis gate

- Status: `Locked`；depends on all P5 cards and `CLOUD-RT-01`。
- Candidate paths: Zebra real-service E2E and acceptance evidence。
- Deliverable: snapshot → compute → Finding → UI trace with retry/cancel/restart。
- Acceptance: output is reproducible, bounded, lineage-complete and recoverable after worker loss。

## 9. P6：Controlled writeback

### EMB-APPROVAL-01 — AG-UI durable approval adapter

- Status: `Locked`；Zebra repo；depends on P4 gate and existing durable Policy/Approval。
- Candidate paths: AG-UI adapter projection/resume modules and regression tests。
- Deliverable: persisted approval → interrupt outcome → same-thread idempotent resume。
- Acceptance: expiry/deny/cancel/reload/crash never bypass Policy or lose pending state。

### TRN-WRITE-01 — Trench save_report/create_watch tools

- Status: `Locked`；Trench repo only；depends on `EMB-APPROVAL-01` contract。
- Candidate paths: Trench command controllers/services/idempotency/RBAC/tests。
- Deliverable: only save_report and create_watch with Business Receipt。
- Acceptance: re-authorize at execution time; duplicate idempotency key returns same outcome。

### EMB-CALLBACK-01 — Signed callback and reconciliation

- Status: `Locked`；Zebra repo；depends on `TRN-WRITE-01` and `CLOUD-LEASE-01`。
- Candidate paths: host callback adapter, delivery ledger/storage, worker wiring, tests。
- Deliverable: signed callback、outbox retry、receipt correlation、reconciliation。
- Acceptance: crash/retry/out-of-order callback is auditable and cannot create double write。

### EMB-TRN-WRITE-E2E-01 — Writeback safety gate

- Status: `Locked`；depends on all P6 cards。
- Candidate paths: Zebra cross-service E2E and acceptance record。
- Deliverable: approve/deny/expire/duplicate/crash/reconcile matrix on real services。
- Acceptance: each success has Zebra Effect Receipt + Trench Business Receipt; zero double writes。

## 10. P7：Provider-neutral Memory Gateway + Mem0

### MEM-GW-CON-01 — AgentMemoryGateway contract

- Status: `Review`；branch `codex/mem-gw-con-01`；depends on local reviewed
  `CLOUD-STO-AUTH-01` and explicit maintainer continuation；merge remains blocked
  until the authoritative Store chain lands。
- Candidate paths: new focused core Port/domain models and contract tests。
- Deliverable: confirmed-memory publish、search、delete and degraded-response contracts。
- Acceptance: `MemoryStorePort` remains authoritative；no Mem0/provider SDK type enters core；
  opaque namespace and Zebra memory ref are mandatory；outage cannot fail a Run。

### MEM-MEM0-SPIKE-01 — Mem0 OSS contract and operations probe

- Status: `Review`；branch `codex/mem0-contract-spike-01`；stacked on local
  reviewed `CLOUD-COMPOSE-INFRA-01`、`CLOUD-STO-AUTH-01` and `MEM-GW-CON-01`。
- Candidate paths: isolated REST fixtures/tests, Spike configuration and compatibility evidence only。
- Deliverable: pin exact self-hosted OSS paths/shapes for `infer=false`、metadata filters、
  expiration、search、update、history、delete、restart and error behavior。
- Acceptance: observe duplicate delivery、timeout、provider failure and embedding-dimension
  changes；persist no credential；a deterministic local provider may validate OSS semantics,
  while real provider compatibility remains a separate credentialed gate。
- Observed: duplicate delivery creates distinct provider IDs；provider stall reaches the
  caller deadline；provider 503 maps to `502/provider_unavailable`；dimension mismatch maps
  to `502/unknown`；expired records remain absent from search even with `show_expired=true`。

### MEM-MEM0-ADP-01 — Mem0 Gateway adapter

- Status: `Review`；branch `codex/mem0-adapter-01`；stacked on local reviewed
  `MEM-MEM0-SPIKE-01` after explicit maintainer continuation on 2026-07-28。
- Candidate paths: `agent-integrations/.../mem0/`, configuration and tests。
- Deliverable: feature flag、opaque mapping、`infer=false`、redaction、timeout、rate limit、
  circuit breaker and provider-version evidence。
- Acceptance: only confirmed Zebra memories are published；remote score never changes Zebra
  confidence/lifecycle；local profile remains compatible。
- Observed: fixed `infer=false` and opaque namespace mapping pass against the pinned real
  Compose service；timeout、429、5xx、schema drift and lookup outage degrade；provider refs
  are canonical UUIDs；disabled mode performs no network I/O。

### MEM-GW-DEL-01 — Memory delivery and deletion ledger

- Status: `Locked`；depends on `MEM-MEM0-ADP-01` and `CLOUD-LEASE-01`。
- Candidate paths: delivery storage/worker adapter, delete audit and tests。
- Deliverable: outbox/idempotency/reconciliation/retention/deletion evidence and rebuild path。
- Acceptance: retry cannot duplicate governed memory；search hits are revalidated through
  `MemoryStorePort`；delete is traceable without retaining deleted content。

### MEM-GW-GATE-01 — Contract drift and fault gate

- Status: `Locked`；depends on all P7 cards。
- Candidate paths: daily contract tests, fault injection and acceptance record。
- Deliverable: schema/version drift、outage、rate-limit、timeout、stale-hit and deletion scenarios。
- Acceptance: Memory outage never fails Run；Mem0's isolated pgvector is rebuildable derived data；
  no second Zebra fact source or Graphiti fallback appears。

## 11. P8：Namespace isolation and GA

### CLOUD-NS-01 — Opaque namespace isolation

- Status: `Locked`；Zebra repo；depends on P3 gate and production storage adapters。
- Candidate paths: storage/security filters, Redis/S3 conventions, isolation tests。
- Deliverable: namespace propagation and deny-by-default across data/log/trace/metric/backup。
- Acceptance: zero cross-namespace reads/writes under API, worker, tool, artifact and recovery paths。

### CLOUD-BROKER-01 — Credential and Egress Brokers

- Status: `Locked`；depends on `CLOUD-NS-01`。
- Candidate paths: `agent-security`, `agent-integrations`, runtime wiring and security tests。
- Deliverable: Vault/KMS-backed short credentials, exact destination egress and revocation。
- Acceptance: no long-lived secret enters model/Sandbox; rotation/revoke/crash behavior proven。

### CLOUD-KATA-01 — Optional stronger tenant isolation

- Status: `Locked`；depends on multi-tenant threat model and `CLOUD-BROKER-01`。
- Candidate paths: runtime/admission/Helm/real-cluster tests only。
- Deliverable: Kata/node-pool profile only if documented threats exceed gVisor boundary。
- Acceptance: explicit go/no-go decision; no mandatory Kata complexity without evidence。

### CLOUD-GA-01 — Production GA evidence

- Status: `Locked`；depends on every required prior gate。
- Candidate paths: Helm/Terraform/GitOps, load/chaos/DR tests, runbooks and evidence。
- Deliverable: quotas、SLO、PITR、DR、canary、rollback、on-call and capacity plan。
- Acceptance: real cluster passes load/chaos/security/recovery; maintainer explicitly declares GA。

## 12. Activation order

Maintainer 在 2026-07-23 将执行优先级改为“先完成 Zebra 本体，再恢复 Trench”。
当前顺序固定为：

1. `CLOUD-STO-SEAM-01`：只建立既有 Store Ports 的 composition seam；
2. `CLOUD-STO-AUTH-01`：补齐所有会推进 Session、治理记忆或约束副作用的 durable
   Store 边界，并以跨库回归证明不会分裂事件真相；
3. 评审 migration/backup/recovery/rollback 后，完成 PostgreSQL Event/Projection；
   Lease/Outbox 先冻结合同，再依次完成 Core fencing、PostgreSQL Lease、Effect Outbox
   和 Worker consumer，之后才进入 Object Storage、Redis live 和 Cloud recovery gate；
4. 依次完成 `MEM-GW-CON-01`、`MEM-MEM0-SPIKE-01`、`MEM-MEM0-ADP-01`、delivery
   ledger 和 fault gate；
5. 再恢复 Host/AG-UI contract 和 Trench read-only lane；P3 production E2E 必须等待
   P2 gate，但 Mem0 故障或关闭不得阻塞 Run；
6. 后续 Frontend、Analysis、Writeback 和 GA 仍逐阶段激活。

`EMB-AGUI-SPIKE-01` 和本地 Trench Spike 的既有证据保留，不在 Cloud Store 任务中
继续扩展或合并。

## 13. Global release blockers

任一条件成立时不得宣称完成：

- 只有 mock，没有真实 PostgreSQL/Redis/S3/Kubernetes/Trench 链路；
- migration、backup、restore 或 rollback 未演练；
- auth failure 被误报为零数据、空结果或成功；
- CopilotKit UI state 被当作 durable Task/Approval truth；
- Redis 丢失会丢 Task、Effect 或 Artifact metadata；
- Tool、callback 或 resume 重试会重复业务写入；
- namespace 未贯穿 storage/cache/object/log/trace；
- Memory Preview 故障会使 Run 失败；
- 跨仓库任务没有各自 owner、branch、validation 和 version evidence。

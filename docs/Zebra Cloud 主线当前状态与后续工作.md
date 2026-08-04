# Zebra Cloud 主线当前状态与后续工作

> 快照日期：2026-08-04
> 分支：`zebra-cloud-trench`
> 当前基线：`31347989`

## 结论

Zebra Cloud 已完成 PostgreSQL 云端事实存储、API/Worker 存储组合和主要聚合能力，
但尚未完成可部署的应用 Compose、在线事件 fan-out 和 Trench 业务接入。当前状态是
“API/Worker 已能按显式 cloud profile 选择 PostgreSQL，主容器组装、运行时业务选择
和 Trench 接入尚未完成”。

任务注册表是当前状态的权威来源；本文件是面向项目协作的汇总，不替代
[`docs/AGENT_TASKS.md`](./AGENT_TASKS.md) 中的任务卡、Owner、Branch 和依赖。

## 已完成

### Core 与本地基线

- Event Store、Task/Segment、Harness、Tool、Policy、Approval、Context、恢复、
  Sandbox 和本地 Runtime 基线已完成。
- `ControlPlaneStores` 已统一 Event、Projection、Task、Lease、Context、Handoff、
  Effect、Memory、Artifact、Provider Continuation、Session History 和 Delivery
  Audit Port。
- 本地 SQLite profile 仍保持可用，并拒绝 `:memory:` 组合，避免多连接产生伪事实源。

### PostgreSQL 云端基础

- PostgreSQL 迁移目录已覆盖 v1-v15：Event/Projection、Epoch/Lease、Effect
  Outbox、Workspace、Task/Segment、Model/Tool、Context、Handoff、Artifact、
  Governed Memory、Memory Delivery、Native Memory Gateway、Provider Continuation、
  cloud control-plane shared records 和 Delivery Transaction。
- 已完成并有独立测试证据的主要 Adapter 包括：Event/Projection、Lease、Effect
  Outbox/Consumer、Workspace、Task、Context、Handoff、Model/Tool、Artifact、
  Session History 和 Governed Memory。
- Handoff v8、Artifact v9、Governed Memory v10、Memory Delivery v11 和 Native
  Memory v12、Provider Continuation v13 和 cloud control-plane v14 均已进入当前
  分支的实现记录。
- 已记录的宿主 PostgreSQL Compose 矩阵包括 Session History `3/3`、Context
  Materialization `4/4`、Task `32/32`、Workspace `80/80`、Effect Outbox `49/49`
  和 Effect Consumer `58/58`。
- `CLOUD-DELIVERY-TXN-PG-01` 已 fast-forward 合并到当前云端主线
  `9ec52b16`，并由侧边栏批准关闭为 `Done`。v15 Delivery transaction store
  将 receipt、audit 和 `COMMITTED` 状态放在同一 PostgreSQL transaction；API/
  应用 Compose、Runtime selector 和外部动作仍未接线。

### Memory

- Zebra PostgreSQL Governed Memory 是权威事实源，负责候选、确认、过期、删除、
  来源和作用域生命周期。
- PostgreSQL Native Memory Gateway 已完成准入验证。
- Mem0 OSS Spike、Gateway Adapter、Compose 依赖和替代 reset 方案已完成验证，
  但 Mem0 仍只允许作为可降级的派生索引。

### Agent Definition v2

- `AGENT-DEF-ADR-01`、`AGENT-DEF-CON-01` 和 `AGENT-AUTH-SNAPSHOT-01` 已完成。
- 已冻结 Definition/Version/Release 模型、Registry Port、Definition digest、
  Attempt authority snapshot、解析和可恢复重验证事件。
- `AGENT-AUTH-SNAPSHOT-01` 已合并到 `zebra-cloud-trench`，不保存凭证、Token 或
  可重放密钥。

### Docker 与协议边界

- `docker/compose.dependencies.yml` 管理 PostgreSQL、Redis、MinIO 和初始化容器。
- Mem0 使用独立可选 Compose overlay；Mem0 数据明确是派生、可替换的存储。
- Embedded 架构已经确定 CopilotKit/AG-UI 方向，取消自研 Zebra React SDK；AG-UI
  目前只完成协议兼容 Spike，没有生产路由或 Trench 接线。

## 尚未完成

### PostgreSQL 运行时组合

`CLOUD-API-WORKER-PG-01` 已完成并以 `d9fd0419` fast-forward 合并到
`zebra-cloud-trench`（治理收口提交为 `635b6960`）。API 和 Worker 使用同一个
profile composer：只有显式 `ZEBRA_PROFILE=cloud` 才选择
`PostgresControlPlaneStores`；缺少 DSN、namespace、签名密钥、authority scope 或
S3 object reader 配置时启动 fail closed；local、unset 和 test profile 继续使用
SQLite。Worker 同时注入 PostgreSQL workspace transaction 和 deployment namespace
fence，`model_calls`/`tool_runs` 只是 Event-derived `model_tool_projections` 的
兼容 facade，不产生第二事实源。

该任务的 focused API/HTTP/Worker 回归为 `41 passed`，control-plane PostgreSQL
17.5 Compose runner 为 `11 passed`，结果标记为
`ZEBRA_CONTROL_PLANE_POSTGRES_TEST_RESULT=PASS` 且资源已清理。此项只完成存储组合，
不等于应用 Compose、Runtime 业务选择或在线事件路由已完成；现有
`CLOUD-COMPOSE-APP-01` 仍为实现 `Blocked`，不能被隐式激活。

此前完成的云端主线任务是
`CLOUD-DELIVERY-TXN-PG-01`。其实施边界见
[`Cloud Delivery Transaction PostgreSQL Plan`](./architecture/cloud-delivery-txn-pg-plan.md)。
`CLOUD-PROVIDER-CONT-PG-PLAN-01` 和实现卡均已由侧边栏接受并关闭为
`Done`；Delivery 迁移目标为 v15，API/Worker 接线仍是后续门禁。

当前主线后续任务：

1. `CLOUD-PROFILE-COMPOSITION-CON-01`：已由侧边栏接受并关闭为 `Done`，仅登记显式
   cloud/local profile contract、API/Worker stores 注入边界和 model/tool
   compatibility seam；sidebar 未授权任何生产代码或运行时选择。
2. `CLOUD-CONTROL-PLANE-PG-01`：已由侧边栏批准并完成 `Done`，交付
   cloud-only `CloudControlPlane`、`PostgresControlPlaneStores` 存储组合、迁移和
   聚焦验证；现有本地 `ControlPlaneStores` 不变，API/Worker 接线与 Runtime 选择
   仍是后续门禁。
3. `CLOUD-API-WORKER-PG-01`：已由侧边栏批准实施、独立 Review 并以 `d9fd0419`
   fast-forward 合并为 `Done`；完成 API/Worker 的 cloud PostgreSQL profile
   组合、fail-closed 配置和 model/tool compatibility facade，不包含应用 Compose
   或 Runtime 业务切换。
4. `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01`：Context lifecycle 的治理/审计型
   fencing conformance card，已由侧边栏批准关闭为 `Done`。
5. `CLOUD-AGG-FENCE-CTX-SEMANTIC-01`：修复行政 Context activation 的
   Event type 与 capsule binding Store-level 缺口，已由侧边栏批准关闭为
   `Done`；Store guard、三类零写入回归和真实 PostgreSQL `18/18` 矩阵均已
   完成。
6. `CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01`：Handoff/dispatch 的治理型
   conformance 审计已完成并为 `Done`，审计结果为 `PASS`。reserve/abort authority
   与 dispatch revision/replay/race/namespace 缺口均由独立 successor 处理，两个
   PostgreSQL runner 分别通过 `15/15` 与 `14/14`。
7. `CLOUD-AGG-FENCE-HANDOFF-AUTH-01`：已由侧边栏批准激活，在
   `codex/cloud-agg-fence-handoff-auth-01` 完成 reserve/abort authority
   Store seam、零写入回归和真实 PostgreSQL runner；当前为 `Done`，实现提交
   `6a04f1cd`，并已由独立 sidebar closeout 以 `CLOSEOUT-OK` 关闭。

8. `CLOUD-AGG-FENCE-DISPATCH-01`：AUTH-01 合并后由侧边栏批准以
   `zebra-cloud-trench@4a10883a` 激活，现已完成并关闭为 `Done`；实现提交为
   `6c1ceffa`，治理收口为 `48bb942a`，仅覆盖 dispatch claim/ACK 的 operation、
   revision、LeaseFence、claim-token、replay/race/namespace/rollback/zero-write
   语义，不重做 reserve/abort。
9. `CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01`：当前为 `Done`，审计结果为
   `PASS`；其 direct Task authority 缺口已由
   `CLOUD-AGG-FENCE-TASK-01` 在 `6a31929a` 实现，Task focused PostgreSQL 回归为
   `23/23`；当前 checkout 的 Workspace/Task PostgreSQL runner 由独立 evidence
   successor `49a8c026` 提供，`36/36` 通过并完成清理。
10. `CLOUD-AGG-FENCE-MODEL-TOOL-01`：已完成 Model/Tool projection 的
   `expected_stream_revision`、stream drift、rollback 和 zero-write 校验；专用
   PostgreSQL 17.5 runner 通过 `8/8`，现有 Control Plane runner 通过 `11/11`，
   实现提交为 `31347989`。
11. `CLOUD-AGG-FENCE-PROVIDER-01`：已完成 Provider Continuation lifecycle
   conformance。`delete_for_worker` 现已绑定 expected stream revision 与锁定的
   Session stream；专用 PostgreSQL 17.5 runner 通过 `4/4`，提交为 `816a1ae0`，
   不改 v13 schema 或本地 SQLite。
12. `CLOUD-AGG-FENCE-ARTIFACT-01`：已完成 Artifact lifecycle conformance
   evidence。v9 Worker transitions 已共用 namespace、LeaseFence、stream CAS 与
   lifecycle revision；仓库自有 PostgreSQL 17.5 runner 通过 `13/13`。
13. `CLOUD-AGG-FENCE-EFFECT-PAYLOAD-01`：已完成 Effect-to-Artifact
   conformance evidence。payload-aware schedule/terminal 已绑定 Worker authority
   并原子协调 Event、Artifact 与 outbox；专用 PostgreSQL 17.5 runner 通过 `7/7`。
14. `CLOUD-AGG-FENCE-DELIVERY-01`：已完成 Delivery command boundary
   conformance。Delivery 使用 command claim/receipt token，而非 Worker Lease；
   修正后的 PostgreSQL 17.5 runner 通过 `12/12`，不改变 adapter 或 runtime。
15. `CLOUD-AGG-FENCE-REVIEW-01`：已完成总门禁证据复核，结果 `PASS`；已汇总所有
   path-bounded aggregate PASS 与清理证据。
16. `CLOUD-AGG-FENCE-01`：已从 `Locked` 转为 `Review`，仅表示证据待维护者批准；
   不授权 runtime/application Compose、successor 或生产切换。

当前 `CLOUD-CONTROL-PLANE-PG-01`、`CLOUD-API-WORKER-PG-01` 与
`CLOUD-DELIVERY-TXN-PG-01` 均为 `Done`；
Context conformance 审计及其 semantic successor 均为 `Done`，
`CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01` 已完成并为 `Done`，审计结果为
`PASS`；`CLOUD-AGG-FENCE-HANDOFF-AUTH-01` 已完成授权实现并由独立 sidebar
以 `CLOSEOUT-OK` 关闭为 `Done`。父 fencing gate 仍为 `Locked`，因为其他 aggregate
 fencing cards 尚未闭合；`CLOUD-AGG-FENCE-DISPATCH-01` 已完成并关闭为 `Done`，
`CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01` 已完成并为 `Done`，其
`CLOUD-AGG-FENCE-TASK-01` 与 `CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01`
 均已完成，不能顺带激活
 Runtime selector 或应用 Compose。`CLOUD-AGG-FENCE-MODEL-TOOL-01` 已完成并
 关闭为 `Done`，补齐了 Model/Tool projection 的 `expected_stream_revision`
 PostgreSQL 写入校验；`CLOUD-AGG-FENCE-PROVIDER-01` 也已完成，补齐了
 Provider Continuation soft-delete 的同事务 stream CAS；`CLOUD-AGG-FENCE-ARTIFACT-01`
 已完成证据补齐，不改变 v9 adapter；`CLOUD-AGG-FENCE-EFFECT-PAYLOAD-01` 已完成
 事务证据补齐，不改变已实现事务；`CLOUD-AGG-FENCE-DELIVERY-01` 已完成
 command boundary 证据，不改变 command transaction；API/Worker 存储组合已由
`CLOUD-API-WORKER-PG-01` 完成；应用
`CLOUD-COMPOSE-APP-01` 当前仍为实现 `Blocked`，等待应用 Compose、Runtime 业务
selector 和在线事件路由的单独授权；本次组合任务关闭不改变任何 runtime gate。

### Docker 应用层与在线事件

- `docker/compose.application.yml` 目前不存在；其登记卡
  `CLOUD-COMPOSE-APP-01` 当前为 `Blocked`，不能作为 API/Worker 接线授权。
- Zebra migration、API、Worker 三类主容器尚未建立。
- Redis 目前只有依赖容器，没有 replay-plus-tail 的 live fan-out Adapter。
- PostgreSQL/MinIO/Redis 的备份、PITR、恢复、回滚、RPO/RTO 和多 Worker 故障演练
  尚未形成完整 GA 证据。

### Mem0 运行准入

Mem0 当前 Provider admission 为 `DENIED`，原因是 ambiguous-create 恢复和完整
scoped deletion 仍未得到可靠证明。`MEM-GW-DEL-RUN-01`、Memory parent gate 和
Runtime consumer 均保持 `Locked`。Mem0 不得成为 Zebra 的第二事实源，也不能阻塞
Agent Run。

### Agent Definition 后续链

下列任务仍未实施：

- Registry 存储 Adapter（SQLite/私有云 PostgreSQL）
- Draft/Version materialization
- Task-level Definition binding
- Definition-scoped governed Memory
- Trust/Ingress coverage
- Version publication Eval gate
- Gated publication API

当前任务图存在一个需要维护者重新确认的依赖问题：`AGENT-DEF-PG-01` 依赖本地
`AGENT-DEF-STO-01`，而云端主线又明确推迟 SQLite Registry。因此 Definition 云端
存储链不能自行跳过依赖启动。

### CopilotKit / Trench 生产链路

以下仍为 `Locked`：

- HostSessionGrant 和外部 authority verifier
- Zebra 生产 AG-UI endpoint
- Host Tool Gateway
- Trench read Tool API
- Trench CopilotKit Runtime/BFF
- Event Detail 只读 Copilot panel
- 跨服务 read-only E2E
- 后续 frontend collaboration、deterministic analysis、controlled writeback 和 GA

Zebra 继续拥有 Task/Event/Approval/Receipt/Artifact/Policy authority；CopilotKit
Thread、Redis live state 和前端 state 不能成为持久事实源。

## 当前质量状态

当前实现分支的 `make test` 结果：

```text
2255 collected
2037 passed
217 skipped
1 failed
```

当前失败是仓库文件大小门禁，包含四个已知超限文件：

- `UI/desktop/src/components/CodexConversationPane.styles.ts`：561/500
- `apps/api/src/zebra_agent_api/app.py`：513/500
- `packages/agent-storage/src/agent_storage/postgres/context_lifecycle.py`：502/500
- `tests/agent_storage/test_postgres_governed_memories.py`：765/700

这不是当前 Cloud Adapter 的功能失败，但会使全仓库质量门保持红色。Desktop 文件
属于当前云端主线之外；Governed Memory 测试文件需要后续拆分或由维护者批准明确的
云端质量门策略。

## 后续实施顺序

以下顺序沿用现有任务注册表；Delivery 已完成，Context conformance 审计与
语义缺口修复均已完成，当前先进行 Handoff/dispatch conformance 审计，父门禁
仍受依赖约束：

1. [x] 关闭 `CLOUD-PROVIDER-CONT-PG-PLAN-01`，冻结 authority identity、
   `WorkerMutationAuthority`、PostgreSQL 事务和生命周期合同。
2. [x] 实施并关闭已激活的 `CLOUD-PROVIDER-CONT-PG-01`（迁移 v13、PostgreSQL
   adapter、云端 Worker aggregate seam 和真实 Compose 证据）。实现提交为
   `39bbe444`，复核修复为 `abd7a7f0`，sidebar closeout 已接受。
3. [x] 完成并关闭 `CLOUD-PROFILE-COMPOSITION-CON-01`，冻结 explicit
   cloud/local profile、fail-closed 和 model/tool compatibility seam；不授权
   API/Worker 实现或 runtime activation。
4. [x] 完成 cloud-only `CloudControlPlane` / `PostgresControlPlaneStores` 存储组合，
   并由独立 `CLOUD-API-WORKER-PG-01` 任务实现 SQLite/Cloud profile 选择；实现提交
   为 `d9fd0419`，治理收口为 `635b6960`。
5. 完成 `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01` 审计，并由
   `CLOUD-AGG-FENCE-CTX-SEMANTIC-01` 修复已确认的 Store 语义缺口；两张卡
   均已由侧边栏 closeout 为 `Done`。
6. [x] 完成 `CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01` 治理审计；初始 sidebar
   closeout 为 `BLOCK-GAP`，后续 AUTH-01、DISPATCH-01 及两个 PostgreSQL runner
   已闭合缺口，本地收口结果为 `PASS`，父门继续 `Locked`。
7. [x] 完成 `CLOUD-AGG-FENCE-HANDOFF-AUTH-01` 的独立 sidebar closeout；结果为
   `CLOSEOUT-OK`、`Review -> Done`，父门继续 `Locked`。
8. [x] 已实施已激活的 `CLOUD-AGG-FENCE-DISPATCH-01`：claim/ACK
   已绑定 operation、stream/pointer revision、WorkerMutationAuthority、LeaseFence
   与 token，补齐 replay、race、namespace、rollback 和 zero-write 回归；专用
   PostgreSQL 17.5 runner 已 `14/14` 通过并完成清理，实现提交为 `6c1ceffa`，
   治理收口为 `48bb942a`，已快进合并并完成本地 closeout；父门继续 `Locked`。
9. [x] 完成 `CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01` 审计；结果为 `PASS`，
   Task authority 与 Workspace/Task runner successor 均已完成。
10. [x] 完成 `CLOUD-AGG-FENCE-TASK-01` direct rollover authority；实现提交
   `6a31929a` 已通过 Task `23/23`、Handoff/dispatch `24/24` 和本地
   `REVIEW-OK`，当前为 `Done`。
11. [x] 完成 `CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01`；固定提交
   `49a8c026` 的 PostgreSQL `17.5-alpine3.21` runner 通过 `36/36` 并完成清理，
   本地 `REVIEW-OK` 已记录；再完成其余 aggregate fencing conformance，评估
   `CLOUD-AGG-FENCE-01` 激活。
12. [x] 实施并关闭 `CLOUD-AGG-FENCE-MODEL-TOOL-01`；专用 PostgreSQL 17.5
   runner 通过 `8/8`，现有 Control Plane runner 通过 `11/11`，补齐
   expected stream revision、stream drift、rollback 和 zero-write 证据。
13. [x] 完成 Artifact、Effect/Artifact linkage、Delivery 等剩余 aggregate
   fencing conformance；Artifact `13/13`、Effect `7/7`、Delivery `12/12`，
   所有 runner 均完成清理。
14. [x] 完成 `CLOUD-AGG-FENCE-REVIEW-01`；汇总全部矩阵为 `PASS`，
   `CLOUD-AGG-FENCE-01` 从 `Locked` 转为 `Review`，不授权实现或 runtime。
15. 接入 Redis live fan-out，创建独立的 Zebra application Compose overlay。
16. 完成迁移、备份、恢复、回滚和多 Worker E2E 门禁。
17. 再激活 Host/AG-UI/Trench read-only vertical slice。
18. 之后才进入 Frontend、Analysis、Writeback 和 GA。

## 当前治理门

`CLOUD-PROVIDER-CONT-PG-01` 与 `CLOUD-DELIVERY-TXN-PG-01` 已完成独立实施与
closeout：Owner、Branch、Worktree、Owned paths 和 v13/v15 迁移所有权均已登记。
当前 `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01` 与
`CLOUD-AGG-FENCE-CTX-SEMANTIC-01` 均已完成；
`CLOUD-AGG-FENCE-01` 的 path-bounded evidence 已全部闭合，当前可进入 `Review`；
在维护者批准前不授权实现、successor 或 runtime/application Compose 激活。
`CLOUD-CONTROL-PLANE-PG-01` 已在所有 aggregate PostgreSQL adapter/read-composition
依赖闭合后由侧边栏批准激活，并在实现、Compose 验证和 closeout 后登记为 `Done`；
其 v14 shared records 与 cloud-only composition 已交付。其余
SQLite Registry、Runtime backend selection、Provider HTTP、Desktop、Redis live、
Mem0 consumer 和应用 Compose 仍保持隔离。

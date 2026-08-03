# Cloud Control Plane PostgreSQL 组合计划

## 状态

- 任务：`CLOUD-CONTROL-PLANE-PG-01`
- 状态：`Done`
- 目标分支：`codex/cloud-control-plane-pg-01`
- 实现提交：`1611fb5e`
- 决策来源：侧边栏 ChatGPT 技术评审已选择方案 B

## 决策

云端 PostgreSQL 组合使用新的 Core `CloudControlPlane` 合同和 Storage
`PostgresControlPlaneStores` 实现。现有本地 `ControlPlaneStores` 及其 SQLite
默认组合保持不变，不能通过增加 cloud-only 字段、backend selector 或可选参数
来兼容两种 profile。

`CloudControlPlane` 只表达已经完成的云端事实边界：Event、Session/Workspace
Projection、Task、Lease、Context、Handoff、Effect、Governed Memory、Artifact
payload、Event-derived Model/Tool projection、Session Artifact read、Provider
Continuation、Session History、Idempotency 和 Delivery Audit。组合接收可信的
`deployment_namespace`，并分别接收 History 与 Provider Continuation 的
`OpaqueAuthorityScope`，避免将两个外部 authority scope 意外合并。

## 存储边界

`PostgresControlPlaneStores` 只负责实例化 namespace-bound adapters，不执行 DDL、
不创建连接池，也不从 DSN 推断 namespace。迁移仍由统一的 checksum-verified
runner 执行。v14 只补齐之前缺失的共享记录：

- `control_plane_idempotency_records`：按 namespace/action/key 唯一，保存请求
  hash、HTTP-neutral status 和 JSON object receipt；重复 key 的不同 hash 必须
  抛出冲突。
- `control_plane_delivery_audit_records`：按 namespace 追加审计记录，并以
  `(namespace, session_id, audit_id)` 提供稳定读取顺序。

Model/Tool 读写仍以 canonical Event 和既有 v6 replayable projections 为权威；
Artifact 读取仍由 PostgreSQL lifecycle metadata 与已验证对象证据组合，不能再
创建第二套 Artifact 或 Event authority。

## 验收边界

1. 缺少内存 cursor signing key 或 cloud object reader 时，组合在返回 bundle 前
   fail closed。
2. 迁移在同一 schema 重复执行时保持 checksum/name 不变并且无副作用。
3. 两个 deployment namespace 的 idempotency、audit、projection reads 互不泄漏。
4. 本地 SQLite profile 的构造和测试不变。
5. 真实 PostgreSQL Compose 测试通过后进入 sidebar closeout；随后才可拆分
   API/Worker profile selection、Delivery transaction 和 aggregate fencing 任务。

本实现已通过 sidebar closeout；`CLOUD-CONTROL-PLANE-PG-01` 仅关闭本存储组合门，
不自动解锁 API/Worker、Runtime 或应用层任务。

## 明确非目标

本任务不修改 `apps/api/`、`apps/worker/`、`packages/agent-runtime/`、Provider
HTTP、Desktop、Redis、Mem0、CopilotKit/Trench 应用运行时或 application Compose，
也不进行生产 backend cutover。Runtime 选择和 API/Worker 接线必须由后续拥有独立
Owned paths 的任务完成。

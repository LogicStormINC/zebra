# Zebra Cloud Workspace Control Plane 立项方案 v1.0

- 方案编号：`CLOUD-WORKSPACE-CP-PLAN-01`
- 状态：`Planning`，仅冻结方案与任务拆分，不激活实现任务
- 基线：`zebra-cloud-trench`（2026-08-16，CLOUD-EFFECT-DEFAULT-E2E-01 全矩阵 PASS 之后）
- 输入：[周期性审查20260812.md](./周期性审查20260812.md) P0.3、
  [CLOUD_Effect默认接线与应用组合收口方案_v1.0.md](./CLOUD_Effect默认接线与应用组合收口方案_v1.0.md)
- 明确不适用：Runtime 隔离改造、Trench、多租户计费、Kubernetes 调度

## 1. 决策摘要

P0.3 是 2026-08-12 审查认定的"当前最缺失的基础能力"，也是 Cloud Agent
与本地 Agent 最大的基础设施差异。当前 cloud profile 下 API 直接把宿主
绝对路径写入 Task/Workspace 投影，Worker 假设该路径在本机存在；应用
Compose 的 API/Worker 容器之间没有共享 Workspace 卷、没有 Git
clone/checkout、没有 volume provisioner、没有回收与 quota controller。
现有 E2E 的 test-only 双视图挂载明确不是 provisioning 证据。

目标状态：Workspace 成为 Control Plane 管理的一等资源，具备确定的生命
周期与权威存储，同时不引入第二事实源（沿用 PostgreSQL Event/Projection
权威 + S3 对象存储边界）。

## 2. 证据与边界

已成立的基础：

- `WorkspaceProjection` 已是 Event-derived 权威投影（含 quota evidence）。
- Artifact 对象边界（S3/MinIO 版本化 + fenced metadata）已闭环。
- 迁移/备份/恢复与 aggregate fencing 治理已完成。
- E2E rig 证明了"专用挂载点 + quota 检查 + 沙箱 bind"的可执行链路。

缺口（审查 P0.3 原文归纳）：

```text
WorkspaceSource   git repository / uploaded archive / snapshot / Trench ref
WorkspaceInstance workspace_id / source_revision / volume_ref / owner
                  namespace / active attempt / writable lease / quota / state
Lifecycle         provision → clone/materialize → seal → snapshot → restore
                  → handoff → release → garbage collect → orphan reconcile
```

## 3. 原则

1. Workspace 权威状态放 PostgreSQL（新迁移），字节放对象存储；Volume
   引用是部署细节，不是事实源。
2. API 只提交 provisioning 命令并读投影；克隆/物化由 Worker 或专用
   provisioner 在 Lease 下执行。
3. revision fencing：物化结果绑定 source revision + 内容 digest；attempt
   续跑必须校验 workspace revision。
4. quota 沿用现有 dedicated-mount 检查，由 provisioner 保证挂载形态。
5. 单机 Docker 与未来 Kubernetes 共用同一 Port 语义，适配器分开。
6. 本地 SQLite profile 不引入 Workspace CP；`workspace_write` 本地行为
   不变。

## 4. 任务拆分（默认 Locked）

### CLOUD-WORKSPACE-CP-CON-01 — 领域与 Port 合同

冻结 `WorkspaceSource`/`WorkspaceInstance`/生命周期状态机、
`WorkspaceProvisionerPort`、`WorkspaceVolumePort`、snapshot/restore 语义
与 quota/回收合同。Core-only，零迁移。

### CLOUD-WORKSPACE-CP-PG-01 — PostgreSQL 权威存储

新迁移：workspace 实例表（namespace-bound、revision/digest、lease 关联、
quota、lifecycle 状态）+ Event 绑定 + 幂等 provision/release 操作收据。
真实 PostgreSQL 矩阵 + namespace 隔离回归。

### CLOUD-WORKSPACE-CP-PROV-01 — Git/Archive 物化 Provider

受 Lease 保护的 clone/checkout（浅克隆 + revision pin + digest 校验）与
archive 解包物化；输出 snapshot 引用；失败进入确定 retry/uncertain 状态。
单机 volume 布局由本卡交付（目录式 + 专用挂载点满足 quota 门）。

### CLOUD-WORKSPACE-CP-API-01 — API provisioning 命令面

cloud profile 下 create-session 接受 `workspace_source` 替代裸路径；
command-only 提交 provision 命令、读 workspace 投影；本地路径模式保持
本地 profile 兼容。

### CLOUD-WORKSPACE-CP-RT-01 — Worker 运行时接线

Worker 从 Workspace CP 解析 volume/mount 并 provision 运行时；attempt
revalidation 校验 workspace revision；失联 workspace fail-closed。

### CLOUD-WORKSPACE-CP-GC-01 — 回收、quota 与孤儿对账

release/GC、quota controller、崩溃孤儿 reconcile（对齐 Lease/Epoch 失效
路径）；演练 runner 证据。

### CLOUD-WORKSPACE-CP-E2E-01 — 默认入口验收

扩展 effect_default E2E：以 git 源物化 workspace → 审批副作用 → 完成收
尾，全程无 test-only 挂载；断言 revision fencing 与回收。

## 5. 依赖顺序

```text
CON → PG → PROV → API → RT → GC → E2E
```

CON 与 PG 可先行；PROV 依赖 PG 的操作收据；E2E 复用现有 rig 文档并替换
其 test-only 挂载段。

## 6. 里程碑

| 里程碑 | 成功标准 |
| --- | --- |
| M1 合同+存储 | CON/PG 合并，真实 PG 矩阵绿 |
| M2 物化+命令面 | git 源经 API 命令物化，revision/digest 落库 |
| M3 运行时+回收 | Worker 经 CP provision；GC/孤儿对账演练绿 |
| M4 默认入口 E2E | 无 test-only 挂载的全链路 PASS |

## 7. 风险

| 风险 | 控制 |
| --- | --- |
| 与单机 Docker 卷语义耦合过深 | Volume 布局只在 PROV 卡；Port 保持中立 |
| 大仓库物化超时/膨胀 | 浅克隆 + digest + quota + 确定重试，不静默重放 |
| 引入第二事实源 | 字节只进对象存储；PostgreSQL 为唯一权威 |
| 与 Workspace quota 门冲突 | provisioner 负责专用挂载形态，quota 语义不变 |

## 8. 激活前检查清单

- [ ] CLOUD-EFFECT-DEFAULT-E2E-01 的执行层证据被维护者接受
- [ ] 首张卡在 docs/AGENT_TASKS.md 登记 owner/branch/Owned paths
- [ ] 首个实现任务先留下当前主线失败的 regression test

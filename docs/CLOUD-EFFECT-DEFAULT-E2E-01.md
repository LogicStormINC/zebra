# CLOUD-EFFECT-DEFAULT-E2E-01 - Default Entrypoint Real Side-Effect Acceptance

- 状态：`Done`（2026-08-16：10/10 场景通过并落盘）
- Owner: `lukeding`
- 基线：`zebra-cloud-trench`（2026-08-14 maintainer batch closeout 之后）
- 输入：[CLOUD_Effect默认接线与应用组合收口方案_v1.0.md](./CLOUD_Effect默认接线与应用组合收口方案_v1.0.md)
- Runner：`tests/compose/effect_default_e2e/run_default_e2e.py`

## 目的

在真实 PostgreSQL、真实 MinIO/S3 兼容对象存储、真实默认 Worker
entrypoint 和 OpenAI 兼容 stub 模型下，验收默认 cloud composition 的
Effect 执行边界。该 gate 是收口方案第 4.6 节定义的最终验收。

## 两层矩阵

源码审查与宿主机原型确认：Runtime provisioning 发生在第一次模型调用
之前。因此只要引擎没有 gVisor（runsc），任何会话——包括纯文本会话——
都无法进入执行。执行层与组合层被显式拆开。

### 组合层（任意 Docker 引擎可复现）

| 场景 | 断言 | 结果 |
| --- | --- | --- |
| infrastructure | 迁移应用、epoch 引导、run root 零 SQLite 文件 | pass |
| session_acceptance | 经真实 API 应用对象入队、projection 为 ready | pass |
| worker_fail_closed | 默认 Worker entrypoint 在 runtime provisioning 处确定性失败；重复周期后 `effect_outbox` 为 0；会话保持 ready；无 TOOL 事件；零 SQLite | pass（无引擎时执行） |
| handoff_effect_read | `PostgresEffectDispatchStore` 的 `terminal_keys()`/`has_uncertain()` 干净返回 | pass |

无引擎时运行 `ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED`（exit 2），执行层场景
以 `gvisor_engine_absent` 显式跳过。

### 执行层（gVisor 引擎 + 专用 workspace 挂载）

| 场景 | 断言 | 结果 |
| --- | --- | --- |
| side_effect_schedule_claim_complete | approval → resume 命令 → 真实 gVisor 沙箱执行 `command.run`；outbox 恰 1 行 `succeeded`，terminal Event 与 payload 绑定；workspace 出现精确内容 | pass |
| worker_restart_no_duplicate | 多次 Worker 周期后 outbox 仍恰 1 行、副作用文件内容不变 | pass |
| replay_consistency | started/completed 事件与 outbox 终态一致、terminal_event_id 绑定 | pass |
| payload_object_binding | 请求与结果 payload 均进入版本化 MinIO，metadata `finalized` | pass |
| session_completed_governed_memory | 无工具会话真实 COMPLETED，governed Memory 收尾经聚合（空计划不伪造提交） | pass |
| worker_death_mid_continuation_recovers | 工具完成后、最终模型轮中被杀 Worker；TTL 到期触发恢复；断言确定性挂起、零重复执行、outbox 恰 2（含前一场景） | pass |
| lease_loss_uncertain_reconcile | 工具执行中轮转 control-plane epoch；断言陈旧 terminal 被拒、效果进入确定 uncertain 归还、零重放 | pass |

2026-08-16 本机全矩阵记录（见"复现"）：10 个场景全 pass，
`ZEBRA_EFFECT_DEFAULT_E2E=PASS`（exit 0）；无引擎时仍为 `BLOCKED`（2）。

## 执行层语义备注（证据驱动）

- 工具名以 provider 序列化形式（`command__run`）往返；stub 从 offered
  名单取原名回发。
- cloud profile 下 `command.run` 走 HITL：`tool_call_proposed →
  policy_decision_made → approval_requested`；驱动器经
  `/approvals/{id}/approve` 批准并提交带 revision 的 resume 命令。
- 默认执行流在会话 Lease 下内联完成 schedule → execute → complete；
  `claim_fencing_token` 仅由独立分发消费通道（`claim_next`）填充，内联
  路径为 NULL 是预期行为，不是缺口。
- **已修复的楔死根因（2026-08-15）**：受控实验加编排器/提交双端插桩
  把根因钉到 `DurableHarnessEventRecorder.accept_persisted_event`——
  fenced guard 原子提交的事件经该方法同步时走了 legacy
  `index_event`，而 cloud 的 Event-derived 投影适配器禁止 `upsert`
  （`cloud tool runs are Event-derived; use fenced worker indexing`）。
  异常在投影推进之前抛出，导致事件流领先投影行一个序列，finalize
  写终态事件时触发
  `session projection does not precede the canonical Event`，会话楔死
  在 `running`，后续 resume 再被
  `approved tool continuation has uncertain prior execution state`
  fail-closed。修复让 `accept_persisted_event` 与 `append_event` 的
  事务路径一致：先推进视图、经 `index_worker_event(authority=...)`
  走 fenced 索引、再保存投影。回归测试固定该序列（cloud recorder 上
  legacy upsert 必须不可达，投影必须前进）。
- **修复后的完整链路（本机 rig 实测）**：批准 → resume 命令 → gVisor
  真实副作用 → 最终模型轮 → `session_completed`（final answer）。
  E2E 的 `side_effect_schedule_claim_complete` 断言已收紧为会话必须
  `completed`；全矩阵保持 PASS。
- **2026-08-16 successor 交付**：已完成的工具调用（含 failed 终态）
  现在可从事件账本确定性恢复续跑而不重执行
  （`recover_approved_continuation` completed 裁决 +
  `continue_completed_tool`，回归测试锁定"cloud recorder 上 legacy
  upsert 不可达 + 单次 started/completed"）；命令消费 skip 的 reason
  落 stderr；两个故障注入场景进入矩阵。
- **唯一遗留**：Worker 死亡后经命令通道把 suspended 会话推进到完成
  （命令被接受但消费者越过投影后闲置）——精确记录于
  `worker_death_mid_continuation_recovers` 的 detail，属 suspended
  resume 语义 successor。

## 复现

组合层（任意 Docker 引擎）：

```bash
uv run python tests/compose/effect_default_e2e/run_default_e2e.py
echo $?  # 0=PASS 1=FAIL 2=BLOCKED(等待 gVisor)
```

执行层（本机 rig 记录的搭建步骤，test-only）：

1. colima `zebra-gvisor` profile（Ubuntu 24.04 VM，`/usr/bin/runsc`
   已存在）；`sudo apt-get install -y docker.io`。
2. `/etc/docker/daemon.json` 注册 `{"runtimes":{"runsc":{"path":"/usr/bin/runsc"}}}`；
   systemd drop-in 覆盖 `ExecStart=/usr/bin/dockerd -H unix:///var/run/docker.sock -H tcp://127.0.0.1:2375`。
3. 宿主机经 colima ssh 控制套接字转发 2375。
4. 256Mi APFS RAM 盘挂载在 `~/zebra-effect-ws`（宿主侧专用挂载点满足
   quota 门；home 经 virtiofs 双视图进入 VM 供引擎 bind），`chmod 777`。
5. digest-pinned 运行时镜像载入 VM dockerd。
6. 运行：

```bash
DOCKER_HOST=tcp://127.0.0.1:2375 \
ZEBRA_EFFECT_E2E_ENABLE_EXECUTION_TIER=1 \
ZEBRA_EFFECT_E2E_WORKSPACE=$HOME/zebra-effect-ws \
ZEBRA_EFFECT_E2E_RUNTIME_IMAGE=python@sha256:<digest> \
uv run python tests/compose/effect_default_e2e/run_default_e2e.py
```

依赖容器始终运行在本地默认引擎；仅 Worker 的沙箱引擎指向 rig。该
test-only 挂载不是 Workspace provisioning、租户隔离或生产跨容器证据
（P0.3 Workspace Control Plane 仍未实现）。

## 契约测试

`tests/compose/effect_default_e2e/test_effect_default_e2e_contract.py`
固定：组合层场景顺序、执行层 fail-closed 常量、零副作用断言、durable
验证只走 PostgreSQL 权威路径、种子走已提交 API 应用对象、stub 保持
provider 形状且从 offered 名单取工具名。

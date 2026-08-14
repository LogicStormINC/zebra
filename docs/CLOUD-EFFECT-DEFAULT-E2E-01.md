# CLOUD-EFFECT-DEFAULT-E2E-01 - Default Entrypoint Real Side-Effect Acceptance

- 状态：`In Progress`（8/9 场景通过并落盘；lease-loss 故障注入待设计）
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
| lease_loss_uncertain_reconcile | 待故障注入设计 | skipped |

2026-08-14 本机全矩阵记录（见"复现"）：9 个场景 8 pass + 1 显式
skip，`ZEBRA_EFFECT_DEFAULT_E2E=PASS`（exit 0）。

## 执行层语义备注（证据驱动）

- 工具名以 provider 序列化形式（`command__run`）往返；stub 从 offered
  名单取原名回发。
- cloud profile 下 `command.run` 走 HITL：`tool_call_proposed →
  policy_decision_made → approval_requested`；驱动器经
  `/approvals/{id}/approve` 批准并提交带 revision 的 resume 命令。
- 默认执行流在会话 Lease 下内联完成 schedule → execute → complete；
  `claim_fencing_token` 仅由独立分发消费通道（`claim_next`）填充，内联
  路径为 NULL 是预期行为，不是缺口。
- **发现的恢复缺口（精确根因，2026-08-14 受控实验）**：批准续跑是一次
  性交接。`recover_approved_continuation` 只接受
  `requested + granted + 未开始执行` 状态；一旦出现
  `TOOL_EXECUTION_STARTED`，任何后续 resume 都因
  `approved tool continuation has uncertain prior execution state`
  fail-closed（防副作用重放的正确防御）。但配套的进程内续跑在实验中
  未完成：工具 `succeeded` 后 attempt 不再发起最终模型轮、不写任何
  终态事件，会话楔死在 `running`；观察到双重 `TOOL_EXECUTION_STARTED`
  事件（`mark_approved_continuation_started` 一枚 + 批执行器又一枚），
  是隔离异常还是预期双记需 successor 确认。此外命令消费通道把失败
  `skipped` 的 reason 吞在循环内部（不打日志），且命令事件随投影推进
  变为不可重试。需要 successor 卡同时处理：批准续跑的 durable
  checkpoint 化、孤儿 `running` 会话的恢复通道、以及命令消费失败的
  可观测与重试语义。

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

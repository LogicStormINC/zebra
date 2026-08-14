# CLOUD-EFFECT-DEFAULT-E2E-01 - Default Entrypoint Real Side-Effect Acceptance

- 状态：`Blocked`（执行层等待 gVisor 基础设施；组合层证据已闭合）
- Owner: `lukeding`
- 基线：`zebra-cloud-trench`（2026-08-14 maintainer batch closeout 之后）
- 输入：[CLOUD_Effect默认接线与应用组合收口方案_v1.0.md](./CLOUD_Effect默认接线与应用组合收口方案_v1.0.md)
- Runner：`tests/compose/effect_default_e2e/run_default_e2e.py`

## 目的

在真实 PostgreSQL、真实 MinIO/S3 兼容对象存储、真实默认 Worker
entrypoint 和 OpenAI 兼容 stub 模型下，验收默认 cloud composition 的
Effect 执行边界。该 gate 是收口方案第 4.6 节定义的最终验收。

## 两层矩阵

源码审查与宿主机原型确认了一个收口方案未预见的时序事实：**Runtime
provisioning 发生在第一次模型调用之前**。因此只要引擎没有 gVisor
（runsc），任何会话——包括纯文本会话——都无法进入执行，Effect 层根本
不会被触达。执行层与组合层因此被显式拆开：

### 组合层（任意 Docker 引擎可复现）

| 场景 | 断言 | 本机结果 |
| --- | --- | --- |
| infrastructure | 迁移应用、epoch 引导、run root 零 SQLite 文件 | pass |
| session_acceptance | 经真实 API 应用对象入队、projection 为 ready | pass |
| worker_fail_closed | 默认 Worker entrypoint 在 runtime provisioning 处确定性失败；两个重复周期后 `effect_outbox` 仍为 0 行；会话保持 ready 可恢复；无 TOOL 事件；零 SQLite authority 文件 | pass |
| handoff_effect_read | `PostgresEffectDispatchStore` 上 `terminal_keys()`/`has_uncertain()` 干净返回 | pass |

本机执行记录（OrbStack/Docker 29.4.0，无 runsc）：

```text
scenario infrastructure: pass
scenario session_acceptance: pass
scenario worker_fail_closed: pass
scenario handoff_effect_read: pass
ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED  (exit 2)
```

### 执行层（需要 gVisor 引擎 + 专用 workspace 挂载）

以下场景在无 runsc 引擎时以 `gvisor_engine_absent` 显式跳过，runner
绝不允许从组合层证据推导 PASS：

1. `side_effect_schedule_claim_complete` — 走 schedule/claim/complete，从不调用 legacy `reserve`
2. `payload_object_binding` — 请求 payload 进入对象存储并在 terminal Event 事务中绑定 metadata
3. `replay_consistency` — Event/Projection/outbox 重放一致
4. `worker_restart_no_duplicate` — Worker 重启不重复已成功副作用
5. `lease_loss_uncertain_reconcile` — Lease 丢失后陈旧 terminal 写被拒并进入确定 uncertain 路径
6. `session_completed_governed_memory` — 会话真实 COMPLETED 且 governed Memory 走 fenced aggregate

执行层启用条件：引擎具备 runsc（`ZEBRA_EFFECT_E2E_ENABLE_EXECUTION_TIER=1`）
且实现合入。本机 `colima` 的 `zebra-gvisor` profile 含 `/usr/bin/runsc`，
但 nerdctl 下 sandbox 无法启动（`runsc did not terminate successfully`），
尚未形成可用引擎证据。

## 明确不声称

- 组合层 PASS 不构成执行层或生产就绪声明
- test-only 宿主机进程组合不替代应用容器 entrypoint 证据
  （`tests/compose/application/run-smoke.sh` 单独覆盖容器链路）
- HTTP Host Grant 鉴权链路不在本 gate（trench E2E 覆盖）
- Workspace Control Plane（P0.3）仍未实现，执行层的专用挂载是
  test-only fixture，不是 provisioning 证据

## 复现

```bash
uv run python tests/compose/effect_default_e2e/run_default_e2e.py
echo $?  # 0=PASS 1=FAIL 2=BLOCKED(等待 gVisor/执行层)
```

证据写入 `$ZEBRA_EFFECT_DEFAULT_E2E_EVIDENCE_DIR`（默认
`/tmp/zebra-effect-default-e2e/result.json`）；容器、卷、网络与 stub
进程无论成败均被清理。

## 契约测试

`tests/compose/effect_default_e2e/test_effect_default_e2e_contract.py`
固定：组合层场景顺序、执行层 fail-closed 常量、零副作用断言、durable
验证只走 PostgreSQL 权威路径、种子走已提交 API 应用对象、stub 保持
provider 形状且按 prompt 分流。

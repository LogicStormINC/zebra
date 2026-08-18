# ADR-022：Deployment Profile 矩阵与权威轴合同

- 状态：Accepted for Gate 1
- 日期：2026-08-10
- 相关任务：`CLOUD-DEPLOY-PROFILE-CON-01`、`CLOUD-DEPLOY-PROFILE-01`

## 决策

Profile 不是任意字符串分支，而是三个显式轴的解析结果：

| Profile | Deployment | Storage authority | Runtime isolation | 允许的数据库 |
| --- | --- | --- | --- | --- |
| `local` / `ci` / `test` | `local` | `sqlite` | `trusted-local`（可显式选择受控本地 sandbox） | SQLite path |
| `cloud` | `cloud` | `postgresql` | `gvisor` | PostgreSQL DSN |
| `production` | `cloud` | `postgresql` | `gvisor` | PostgreSQL DSN |

`ZebraAgentSettings` 仍是唯一 environment-backed aggregate；它暴露只读的
`deployment`、`storage_authority` 和 `runtime_isolation` 轴视图，不再创建第二套
全量 Settings。API、Worker、migration 和 Compose 必须消费这三个轴的同一解析结果。

## Fail-closed 不变式

- `cloud`/`production` 必须使用 PostgreSQL DSN，不能以 SQLite fallback 启动。
- `cloud`/`production` 必须明确 `ZEBRA_RUNTIME_CLASS=gvisor`、digest-pinned
  runtime image 和 storage-enforced workspace quota。
- `cloud + trusted-local` 与 `production + SQLite` 在 config load 阶段拒绝。
- `local` 保留惰性 SQLite 兼容；构造 API 或无效命令不得提前创建数据库。
- runtime isolation、storage authority 和 deployment 由 app composition 读取，
  adapter 不自行从 profile 字符串推断权威层。

## 责任边界

`apps/config` 只解析输入和校验矩阵；`CLOUD-DEPLOY-PROFILE-01` 将同一解析结果
接入 API/Worker storage composition、migration 和 Compose。`agent-storage` 只实现
SQLite/PostgreSQL adapters，不读取 environment，也不决定 production fallback。

## 验证

`tests/config/test_profile_contract.py` 覆盖 local compatibility、axis projection、
valid PostgreSQL + gVisor production input，以及 rejected SQLite/trusted-local
combinations。组合根的实际 store/runtime wiring由后续实现卡验证。

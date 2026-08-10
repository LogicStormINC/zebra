# ADR-021：配置边界与 Provider-neutral 输入合同

- 状态：Accepted for Gate 1 implementation
- 日期：2026-08-10
- 相关任务：`ARCH-CONFIG-BOUNDARY-01`、`ARCH-CONFIG-INTEGRATIONS-01`、
  `ARCH-CONFIG-SECURITY-01`

## 决策

`apps/config` 是环境和部署配置的唯一 composition 输入。它可以构造
`ZebraAgentSettings` aggregate，但 `packages/*` 不得反向依赖 `apps/*`、API/Worker
composition root 或另一个“总配置对象”。应用层负责把 aggregate 映射成每个
adapter 所需的最小、不可变、provider-neutral 输入。

依赖方向固定为：

```text
environment/files -> apps/config -> apps/* composition -> packages/* ports/adapters
```

`agent-core` 只定义领域类型和 Port；它不读取环境变量，也不导入
`zebra_agent_config`。`agent-integrations` 和 `agent-security` 后续只能接收自身
所需的 typed settings：

| Adapter area | 最小输入 | 禁止携带 |
| --- | --- | --- |
| Model | provider、base URL、model、API-key environment name、retry/profile knobs | 全量 `ZebraAgentSettings`、运行时/数据库 |
| SCM | provider、owner/repo、API base URL、token environment name、dry-run | Model、Runtime、Session handoff |
| Mem0/Memory | endpoint、namespace、credential reference、timeout | API/Worker app object、SQLite/PG store |
| Credential/Security | SCM credential reference 与 redaction policy | 明文 secret、环境读取、API settings |

这些输入只表达 adapter 合同，不表达部署权威。Profile（local/cloud/production）、
storage authority（SQLite/PostgreSQL）和 runtime isolation（trusted-local/gVisor）
由后续 Profile composition task 一次解析；adapter 不得根据字符串 profile 自行
推断权威层。

## 可执行边界

`tests/config/test_package_dependency_boundaries.py` 扫描所有 package source：

1. 任何对 `apps`、`zebra_agent_api` 或 `zebra_agent_worker` 的导入立即失败；
2. 当前 5 个 `zebra_agent_config` 导入被精确列入 successor inventory，新增导入
   立即失败；
3. Integrations/Security successor 完成后，inventory 必须变为空集合，并把测试
   收紧为禁止所有 package 对 `zebra_agent_config` 的导入。

这份 allowlist 是迁移台账，不是永久豁免，也不允许通过动态导入或字符串反射
绕过边界。应用 mapping 和 adapter 输入应在 focused contract tests 中保留兼容的
环境变量语义。

## 不变式

- 不新增第二个全局 Settings aggregate。
- 包可以依赖 `agent-core`，但 `agent-core` 不依赖其他 `agent-*` 包。
- API/Worker 只负责 composition；业务规则、策略与 adapter 校验留在 package。
- 未通过 Profile contract 的生产组合 fail closed，不能回退到 SQLite 或 trusted-local。

## 后续迁移顺序

1. `ARCH-CONFIG-INTEGRATIONS-01` 为 Model/SCM/Mem0 建立 typed provider settings，并
   从 5 个 inventory entry 移除 integrations imports。
2. `ARCH-CONFIG-SECURITY-01` 建立 credential/redaction 输入并移除 Security import。
3. `CLOUD-DEPLOY-PROFILE-CON-01` 固化 deployment/storage/runtime 矩阵；之后由
   `CLOUD-DEPLOY-PROFILE-01` 在 API、Worker、migration 和 Compose 统一解析。

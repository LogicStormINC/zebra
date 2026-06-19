---
title: "Codex-like 工程 Agent 平台：多人协作任务分配与 RACI"
subtitle: "适用于人类团队 + Codex 并行开发的组织、所有权与交接规范"
author: "Project Architecture Office"
date: "2026-06-18"
---

> Status: Active collaboration reference.
> This file is valid only when used together with `实施任务拆解与阶段验收.md`, `AGENT_TASKS.md`, `../AGENTS.md`, and `../PROGRESS.md`.

# 目录

1. 文档说明
2. 推荐团队结构
3. RACI 规则与决策权
4. 模块所有权与备份 Owner
5. Phase 0 具体任务分配
6. Phase 1 任务分配
7. Phase 2-3 任务分配
8. 人类 + Codex 协作协议
9. 交接标准
10. Review 与合并规则
11. 冲突管理与合并顺序
12. 沟通节奏与状态报告
13. Blocker 与升级机制
14. 人员替换与 Bus Factor
15. CODEOWNERS 模板
16. 最终执行准则

# 文档说明

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 配套文档 | `实施任务拆解与阶段验收.md`、`AGENT_TASKS.md` |
| 适用团队 | 3-10 人研发团队；Phase 0-1 推荐 5 人，Phase 2 推荐 6-8 人 |
| 核心原则 | 一项任务一个人类 Owner、一个主工作区、一个最终责任人；Codex 不作为 RACI 角色 |

# 1. 推荐团队结构

## 1.1 角色定义

| 代码 | 角色 | 主要责任 | 不应承担 |
|---|---|---|---|
| PO | Product Owner / 项目负责人 | 范围、优先级、业务验收、风险接受、阶段 Go/No-Go | 直接决定底层安全实现 |
| TL | 技术负责人 / 架构师 | 架构、合同、ADR、依赖顺序、集成、技术 Gate | 长期包揽所有实现和 Review |
| CORE | 控制平面与 Harness 工程师 | Domain、Event Store、Projection、Scheduler、Recovery、Harness | 直接操作 Docker/K8s 细节 |
| RUNTIME | Runtime 与安全工程师 | Worktree、Docker/K8s、Policy、Approval、Credential、Egress | 绕过核心合同实现私有协议 |
| CTX | Context / Model / Tools 工程师 | Model Gateway、Context Compiler、Repo Map、Typed Tools、SCM/MCP | 将厂商 SDK 泄漏进 agent-core |
| APP | CLI / API / Web / IDE 工程师 | CLI、Control API、SSE、Web、ACP、用户审批与 Diff 体验 | 在 UI 层复制业务状态机 |
| QA | QA / Eval / Observability / Release 工程师 | Fixture、自动化、故障注入、安全回归、Eval、Trace、发布证据 | 只在开发结束后“补测试” |
| SRE | 平台/SRE（Phase 2-3 可独立） | CI/CD、Postgres、对象存储、K8s、监控、容量、DR | 变更 Policy 或领域合同而不评审 |

## 1.2 推荐人员规模

### 3 人精简型

| 人员槽位 | 合并角色 | 适用范围 |
|---|---|---|
| A | PO + TL + CORE | 架构、合同、控制平面、集成 |
| B | RUNTIME + SRE | Docker、Worktree、安全、CI/CD |
| C | CTX + APP + QA | Model/Context/Tools、CLI、测试/Eval |

仅建议完成 Phase 0 和受限的 Phase 1。Phase 2 Web/IDE、Credential Broker 与多 Worker 会形成明显瓶颈。

### 5 人推荐型（Phase 0-1）

| 槽位 | 角色组合 |
|---|---|
| 1 | PO/TL（TL 为主，PO 可 0.5 人） |
| 2 | CORE |
| 3 | RUNTIME/Security/SRE |
| 4 | CTX/Model/Tools |
| 5 | APP/QA/Eval（发布前 QA 权限独立） |

### 7-8 人扩展型（Phase 2-3）

拆分 APP、QA、SRE，并为安全高风险模块增加独立 Reviewer。推荐：PO、TL、CORE、RUNTIME/Security、CTX/Model/Tools、APP/Web/IDE、QA/Eval、SRE/Platform。

# 2. RACI 规则与决策权

- **R - Responsible**：实际完成工作，可以多人；
- **A - Accountable**：对结果最终负责，必须且只能有一个；
- **C - Consulted**：变更前必须征求意见；
- **I - Informed**：结果完成后同步。

Codex 只能作为执行工具，不进入 RACI。任务 Owner 对 Codex 生成的代码、测试、文档和风险承担完整责任。

## 2.1 关键决策 RACI

| 决策/工作流 | A | R | C | I |
|---|---|---|---|---|
| 产品范围、非目标、发布优先级 | PO | PO | TL、QA | 全体 |
| 总体架构、Ports、模块边界 | TL | TL、CORE | RUNTIME、CTX、APP、QA | PO |
| Event/Tool/Policy Contract 版本 | TL | CORE | RUNTIME、CTX、APP、QA | PO |
| Sandbox、Policy、凭证与网络安全 | RUNTIME | RUNTIME | TL、QA/Security、SRE | PO、CORE、CTX |
| Model/Context/Tool 设计 | CTX | CTX | TL、CORE、RUNTIME、QA | APP |
| CLI/API/Web/IDE 产品实现 | APP | APP | PO、TL、CORE、QA | 全体 |
| Eval、故障注入、阶段 Gate | QA | QA | TL、模块 Owner、PO | 全体 |
| CI/CD、容量、备份与 DR | SRE | SRE | TL、RUNTIME、QA | PO |
| 技术 Gate 通过 | TL | QA、各模块 Owner | RUNTIME/Security、SRE | PO |
| 业务发布 Go/No-Go | PO | PO、TL、QA | 全体模块 Owner | 全体 |

# 3. 模块所有权与备份 Owner

| 路径/模块 | Primary Owner | Backup Owner | 强制 Reviewer |
|---|---|---|---|
| `packages/agent-core/domain`、`application`、`harness`、`ports` | CORE | TL | TL；涉及 Policy 时 RUNTIME |
| `packages/agent-storage` | CORE | SRE | QA；Schema 变更 TL |
| `packages/agent-runtime`、`sandbox/`、`services/sandboxd` | RUNTIME | SRE | QA/Security、TL |
| `packages/agent-security`、Credential/Egress | RUNTIME | TL | QA/Security；接口变更 CORE |
| `packages/agent-context` | CTX | CORE | TL、QA |
| `packages/agent-tools` | CTX | RUNTIME | CORE、QA；命令工具 RUNTIME 必审 |
| `packages/agent-integrations/models`、SCM、MCP/ACP | CTX | APP | TL、RUNTIME、QA |
| `apps/cli`、`apps/api`、`apps/web` | APP | CORE | QA；权限相关 RUNTIME |
| `apps/worker` | CORE | SRE | RUNTIME、QA |
| `packages/agent-observability`、`evals/`、`tests/` | QA | SRE | 对应模块 Owner |
| `contracts/`、`docs/adr/` | TL | CORE | 所有受影响模块 Owner |
| `infra/` | SRE | RUNTIME | QA/Security、TL |

每个 Primary Owner 必须培养至少一个 Backup Owner。连续两个阶段只有一人能维护的模块，不允许进入 GA。

# 4. Phase 0 具体任务分配

| Task ID | Primary（R） | Accountable（A） | Backup | Reviewer / Consulted |
|---|---|---|---|---|
| P0-GOV-01 | TL | TL | QA | CORE、RUNTIME、CTX |
| P0-CON-01 | CORE | TL | CTX | RUNTIME、QA |
| P0-STO-01 / P0-STO-02 | CORE | TL | QA | RUNTIME |
| P0-RT-01 / P0-RT-02 | RUNTIME | RUNTIME | SRE/QA | TL、CORE |
| P0-SEC-01 | RUNTIME | RUNTIME | TL | CORE、QA |
| P0-HAR-01 | CORE | TL | CTX | RUNTIME、APP、QA |
| P0-RES-01 | QA + CORE | QA | RUNTIME | TL |
| P0-GATE-01 | QA | TL | PO | 全体 |

## 4.1 Phase 0 并行泳道

```text
Lane A - CORE:    Contracts -> Event Store -> Projection -> Harness
Lane B - RUNTIME: Worktree -> Docker -> Policy
Lane C - QA:      Test harness -> Failure injection -> Acceptance report
Lane D - TL:      Governance -> ADR -> Daily integration -> Gate
```

P0-HAR-01 是唯一强汇合点。它开始前，Event/Tool Contract、Event Store、Docker Runtime 和 Policy 最小链路必须有已合并版本，不能依赖未提交的个人分支。

# 5. Phase 1 任务分配

| 工作包 | 主要 Task IDs | R | A | Backup | 必审角色 |
|---|---|---|---|---|---|
| 工程治理与合同 | P1-GOV-*, P1-CON-* | TL、CORE | TL | QA | RUNTIME、CTX、APP |
| Session/Event/Projection | P1-CORE-01, P1-STO-* | CORE | TL | QA | RUNTIME |
| Scheduler/Recovery/Harness | P1-SCH-01, P1-RES-01, P1-HAR-* | CORE | TL | CTX | RUNTIME、QA |
| Runtime/Worktree/Artifact | P1-RT-*, P1-ART-01 | RUNTIME、CORE | RUNTIME | SRE/QA | TL、QA |
| Typed Tools | P1-TOOL-* | CTX；Command 由 RUNTIME 协作 | CTX | CORE | RUNTIME、QA |
| Policy/Approval/Audit | P1-SEC-* | RUNTIME、QA | RUNTIME | TL | CORE、CTX |
| Model/Context | P1-MDL-*, P1-CTX-* | CTX | CTX | CORE | TL、QA |
| CLI/API | P1-CLI-01, P1-API-01 | APP | APP | CORE | PO、QA、RUNTIME |
| Observability/Eval/E2E | P1-OBS-01, P1-EVAL-*, P1-E2E-01 | QA | QA | APP/SRE | 全部模块 Owner |
| Release Gate | P1-GATE-01 | QA、TL | TL | PO | 全体 |

## 5.1 Phase 1 推荐迭代排布

| Sprint | 主要目标 | 并行工作 | 集成 Gate |
|---|---|---|---|
| S1 | Monorepo、Contracts、Domain、Runtime Port | GOV/CON；Fake Runtime；Fixture 设计 | 合同与依赖方向通过 |
| S2 | Event Store、Projection、Docker、Guidance/Model Mock | CORE 与 RUNTIME/CTX 并行 | 一个只读 Tool 纵切 |
| S3 | Scheduler/Recovery、Policy、Read/Patch Tools | 三泳道并行 | 可中断恢复的 Patch |
| S4 | Model Provider、Context Compiler、Typed Command/Test | CTX/Runtime/Core | Mock + Live model 双路径 |
| S5 | Harness、CLI/API、Approval、Trace | 核心汇合 | 本地 E2E Alpha |
| S6 | Compaction、Eval、Security、Failure Injection | QA 主导 | 30-50 cases 基线 |
| S7-S8 | 稳定、文档、Gate、v0.1.0 | 缺陷修复，不接新范围 | Phase 1 Gate |

# 6. Phase 2-3 任务分配

## 6.1 Phase 2

| 工作包 | R | A | C |
|---|---|---|---|
| PostgreSQL、多 Worker、S3 | CORE、SRE | CORE | TL、QA |
| API、SSE、Web、ACP | APP | APP | PO、CORE、QA |
| Credential Broker、Egress | RUNTIME、SRE | RUNTIME | TL、QA/Security、CTX |
| GitHub/GitLab、Repo Map、LSP | CTX | CTX | RUNTIME、APP、QA |
| Snapshot/Suspend/Resume | RUNTIME | RUNTIME | CORE、SRE、QA |
| Research/Reviewer Subagent | CTX、QA | TL | CORE、RUNTIME |
| Phase 2 Gate | QA、TL | TL | PO、所有 Owner |

## 6.2 Phase 3

| 工作包 | R | A | C |
|---|---|---|---|
| K8s Sandbox、强隔离、Warm Pool | RUNTIME、SRE | SRE | TL、QA/Security |
| Tenant、RBAC、组织 Policy | CORE、APP、RUNTIME | TL | PO、QA |
| Vault/KMS、Capability、Network | RUNTIME、SRE | RUNTIME | QA/Security、TL |
| Temporal、跨节点恢复 | CORE、SRE | CORE | RUNTIME、QA |
| Cost、SLO、DR、Chaos | SRE、QA | SRE | TL、PO、RUNTIME |
| GA Gate | QA、TL、PO | PO | 全体 |

# 7. 人类 + Codex 协作协议

## 7.1 一任务一 Owner、一线程、一 Worktree

每个任务必须遵守：

```text
1 个 Task ID
= 1 个人类 Owner
= 1 个短生命周期分支
= 1 个 Git Worktree
= 1 个主要 Codex Thread
= 1 个最终 PR
```

禁止两个人或两个 Codex 写同一 Worktree。Codex Subagent 默认只做只读探索、测试分析或 Review；需要并行写入时必须使用独立 Worktree，并由人类协调合并顺序。

## 7.2 分支与 Worktree 命名

```text
codex/p1-ctx-02-context-compiler
codex/p1-rt-02-container-cleanup
codex/p1-res-01-failure-injection
codex/p1-gate-01-release-evidence
```

Worktree：`.worktrees/<task-id>-<short-name>`。分支从最新 `main` 创建，任务超过 3 天须每日 rebase 或合并主线，避免大规模漂移。

## 7.3 任务开始流程

1. Owner 将任务状态改为 `In Progress` 并填写姓名、分支、Worktree、预计完成日；
2. Codex 首先读取 `AGENTS.md`、当前阶段文档、`AGENT_TASKS.md` 对应任务和当前 `PROGRESS.md`；
3. 使用 Plan mode 生成不超过 8 步的计划，由 Owner 核对边界；
4. 合同或 ADR 不明确时，只允许产出分析，不允许猜测实现；
5. 先补测试或最小失败用例，再写实现；
6. 每个可验证增量运行局部测试，结束前运行任务全部验收命令。

## 7.4 PR 尺寸与拆分规则

- 推荐净改动 300-800 行；超过 1,000 行（生成文件/锁文件除外）必须说明为何不可拆；
- 一个 PR 不同时引入新 Contract、新 Adapter、新 UI 和数据迁移；应按 `Contract -> Core Port -> Adapter -> App wiring -> E2E` 分批；
- 数据库迁移、Policy、Credential、Runtime、Contract 变更不得与无关重构混在同一 PR；
- Codex 生成代码必须由 Owner 逐文件 Review，不能只看最终摘要。

# 8. 交接标准

## 8.1 上游向下游交接包

| 交接类型 | 必须提供 |
|---|---|
| Contract -> Adapter | Schema、Python 类型、Golden fixtures、错误码、兼容性测试 |
| Core -> App | 用例接口、状态/错误模型、Mock、示例调用、API 合同 |
| Runtime -> Tools | RuntimeSpec、能力矩阵、限制、超时/stream 语义、契约测试 |
| Security -> Feature | Permission profile、Policy 示例、审批条件、威胁场景、审计字段 |
| Feature -> QA | 需求/非目标、自动命令、fixtures、已知边界、风险和 trace |
| Phase -> Operations | 部署/回滚、监控、告警、数据迁移、容量、故障处理 runbook |

## 8.2 HANDOFF 记录

每个跨 Owner 交接须在 PR 或任务中记录：

```markdown
## Handoff
- Producer:
- Consumer:
- Contract/version:
- Files/Artifacts:
- Commands verified:
- Known limitations:
- Open decisions:
- Rollback path:
```

消费者确认合同和证据后才能将任务关闭。仅发送“已完成，请看代码”不构成交接。

# 9. Review 与合并规则

| 风险级别 | 示例 | 最低 Review |
|---|---|---|
| L1 低 | 文档、测试数据、非行为性重构 | 1 名非作者 Reviewer |
| L2 中 | 普通功能、Context 排序、CLI/API | CODEOWNER + QA 自动 Gate |
| L3 高 | Event Contract、Event Store、Recovery、Tool 执行 | TL/CODEOWNER + QA |
| L4 关键 | Sandbox、Policy、Credential、Egress、Tenant、RBAC | RUNTIME/Security + TL + QA/Security，至少 2 名人类批准 |

`main` 必须保护，禁止直接 push；合并要求 lint/type/unit/integration/contract/security checks 全绿。发布分支只允许缺陷修复，不允许新增范围。

# 10. 冲突管理与合并顺序

## 10.1 高冲突文件

以下路径为高冲突区，由 Primary Owner 控制合并窗口：

```text
packages/agent-core/domain/events.py
packages/agent-core/ports/*
contracts/**
configs/schemas/**
apps/*/composition.py
pyproject.toml / uv.lock
```

修改高冲突文件前必须在任务看板登记。多任务需要同一合同变更时，先创建单独的 Contract PR，合并后下游分支再更新。

## 10.2 推荐合并顺序

```text
ADR / Contract
  -> Domain / Ports
  -> Storage / Runtime / Integration Adapter
  -> Tool / Policy / Context
  -> CLI / API / Web wiring
  -> E2E / Eval / Docs
```

# 11. 沟通节奏与状态报告

| 节奏 | 参与者 | 输出 |
|---|---|---|
| 每日 15 分钟 | 全体工程成员 | 昨日证据、今日 Gate、阻塞和高冲突文件 |
| 每周 2 次集成会 | TL、各泳道 Owner、QA | 主线集成状态、合同变更、失败用例 |
| 每周一次风险评审 | PO、TL、RUNTIME、QA/SRE | P0-P2、成本、安全、进度范围 |
| Sprint 结束 Demo | 全体 | 从干净环境执行验收命令，不使用本机隐藏状态 |
| 阶段 Gate | PO、TL、QA、Owner | Go / Conditional Go / No-Go 与证据包 |

状态更新必须包含：当前 Task ID、已验证内容、未完成项、阻塞原因、是否需要合同/范围决策。禁止只报告“完成 80%”。

# 12. Blocker 与升级机制

- 阻塞超过 4 个工作小时：Owner 在任务中标记 `Blocked`，写明所需决策；
- 涉及 Contract、架构边界或安全假设：立即升级 TL/RUNTIME，不得由 Codex自行决定；
- 预计延期超过 1 天：拆分可交付增量或调整范围，不能以大 PR 隐藏进度；
- 发现 P0/P1：暂停相关泳道，创建复现和证据，先修复/隔离再继续；
- 同一 Codex 错误重复两次：更新 `AGENTS.md`、测试或 Skill，不再仅靠重复提示。

# 13. 人员替换与 Bus Factor

每个关键模块必须有 Primary + Backup，并满足：

1. Backup 每月至少 Review 或共同完成一个该模块任务；
2. 模块 runbook 能让新成员在半天内完成本地启动和测试；
3. 合同、部署、故障恢复和安全假设有 ADR/文档；
4. 不允许只存在于某个人的 Codex 线程、终端历史或本机配置；
5. Phase 2 退出前，CORE、RUNTIME/Security、CTX 至少各有 2 人可维护。

# 14. CODEOWNERS 模板

```text
/contracts/                         @tech-lead @team-core
/packages/agent-core/               @team-core @tech-lead
/packages/agent-storage/            @team-core @team-platform
/packages/agent-runtime/            @team-runtime @team-platform
/packages/agent-security/           @team-runtime @security-reviewers
/packages/agent-context/            @team-context @team-core
/packages/agent-tools/              @team-context @team-runtime
/packages/agent-integrations/       @team-context @team-app
/packages/agent-observability/      @team-quality @team-platform
/apps/cli/                          @team-app @team-quality
/apps/api/                          @team-app @team-core
/apps/web/                          @team-app @team-quality
/services/sandboxd/                 @team-runtime @team-platform
/services/credential-broker/        @team-runtime @security-reviewers
/services/egress-proxy/             @team-runtime @security-reviewers
/evals/                             @team-quality @tech-lead
/tests/security/                    @team-quality @security-reviewers
/infra/                             @team-platform @team-runtime
/docs/adr/                          @tech-lead @team-core
```

# 15. 最终执行准则

多人协作时，速度来自**低耦合并行和高质量交接**，不是让更多人或更多 Codex 同时编辑相同代码。最优组织方式是：

```text
PO 管范围
TL 管边界和集成
模块 Owner 管实现
QA 管证据和 Gate
RUNTIME/Security 管不可绕过的安全边界
Codex 在独立 Worktree 中执行小而清晰的任务
```

只要坚持一任务一 Owner、合同先行、Worktree 隔离、RACI 单一 A、证据化交接和阶段 Gate，这个项目可以由 3 人启动、5 人高效完成 Phase 1，并在 Phase 2-3 平滑扩展到更大的团队。

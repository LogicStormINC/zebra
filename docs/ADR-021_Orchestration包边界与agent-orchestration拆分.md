# ADR-021：Orchestration 包边界与 agent-orchestration 拆分

- 状态：`Accepted`
- 日期：2026-08-22
- 决策人：maintainer（lukeding）
- 关联：ADR-017（Agent Layer 边界与多 Host 接入）、
  `docs/Zebra_Agent_Orchestrator与Subagent重构实施方案_v1.0.md`
  （Orchestrator Agent 与 Orchestration Control Plane 的正式定义，
  第一、5.1 节）

## 背景

Orchestration 已经形成独立于通用执行底座的 bounded context：确定性的
Plan/Budget 合同、DAG 校验与调度、Child Task 物化协调、五层 Completion
Gate、worktree 合并门与 Review Fix Loop、Agent Team 合同，以及作为普通
Definition 发布的 `system/orchestrator@1`。但代码仍散落在四处：

1. `agent-core` 的 domain/application（九个模块，约 1900 行）；
2. `agent-storage/postgres`（orchestration 投影与迁移）；
3. `agent-integrations/ag_ui`（orchestration 状态投影）；
4. Worker 组合层的续体派发。

其中存在一个已核实的层次泄漏：
`agent_core.domain.orchestrator_definition` 反向导入
`agent_tools.contracts`，且 `agent-core` 的 pyproject 从未声明该依赖——
它只是靠 workspace 环境全包可见才得以运行。一旦有人"补上"声明，
`agent-core ⇄ agent-tools` 即成循环依赖。这直接违反"core 不依赖其他
agent 包"的仓库规则，说明拆分是在修复真实泄漏，不是形式优化。

同时，Agent Layer 的第一个应用包 `agent-control-plane`（ADR-017、
AL-BOUNDARY-CON-01）已建立并受架构门保护。若再引入一个笼统的
`agent-layer` 包，只会制造新的逻辑堆放区；按 DDD bounded context 拆
稳定职责，而不是按"Agent"名称拆部署单元。

## 决策

1. **新增 workspace 包 `agent-orchestration`**，作为 Orchestration
   Control Plane 的代码载体。依赖集冻结为 `agent-core` +
   `agent-tools`（`ToolContract`/`ToolRisk` 留在 `agent-tools`，由
   orchestration 正向依赖，无环）。允许未来单向调用
   `agent-control-plane` 应用服务（Child Task 物化经 admission）；
   当前无实际导入，故不声明，方向由架构门固化：orchestration →
   control plane，永不反向。

2. **九个模块以纯 `git mv` + 导入改写迁入**，行为零变化：

   | 原位置（`agent_core`） | 新位置（`agent_orchestration`） |
   |---|---|
   | `domain/orchestration.py` | `domain/orchestration.py` |
   | `domain/orchestration_budget.py` | `domain/orchestration_budget.py` |
   | `domain/orchestrator_definition.py` | `domain/orchestrator_definition.py` |
   | `domain/worktree_orchestration.py` | `domain/worktree_orchestration.py` |
   | `domain/agent_team.py` | `domain/agent_team.py` |
   | `application/orchestration_validation.py` | `application/orchestration_validation.py` |
   | `application/orchestration_scheduling.py` | `application/orchestration_scheduling.py` |
   | `application/completion_gate.py` | `application/completion_gate.py` |
   | `application/review_fixloop.py` | `application/review_fixloop.py` |

   对应的九个测试文件从 `tests/agent_core/` 移至
   `tests/agent_orchestration/`。

3. **`subagents.py` 留在 `agent-core`**：Focused Subagent 是三种多
   Agent 模式中的模式 1，协调者是 Parent Agent，不是 Control Plane
   职责；其 `SubagentRole`、`CompletionGateReceipt` 作为普通 core
   合同被 orchestration 消费（依赖方向合法）。

4. **adapter 留在原包，只改导入**：PostgreSQL orchestration 投影留在
   `agent-storage`，AG-UI orchestration 状态投影留在
   `agent-integrations`；二者 pyproject 声明对 `agent-orchestration`
   的 workspace 依赖。编排决策仍在 orchestration 包，adapter 不拥有
   状态机。

5. **三道架构门**（`tests/architecture/`）：
   - 新增 core 门：`agent-core` 禁止导入任何其他 `agent_*` 包、
     `zebra_agent_worker`、FastAPI 或 `apps.`——正是能拦住原泄漏的门；
   - control-plane 门增加禁止 `agent_orchestration`（含 pyproject
     依赖声明）；
   - 新增 orchestration 门：禁止导入 Worker、Runtime、storage、
     integrations、HTTP 框架与 `apps.`，pyproject 钉死 core+tools
     依赖集。

6. **不拆独立微服务**：Orchestration 仍由 `apps/api` 与 `apps/worker`
   组合部署，共享现有 Runtime 与 durable store（与 ADR-017"逻辑边界
   先行"一致）。`Orchestrator Agent` 本身只是 `system/orchestrator@1`
   的普通 `AgentDefinition`，不建 `orchestrator-agent` 服务。
   `SingleAttemptOrchestrator` 是 Harness 的单 Attempt 协调器，与本
   决策的 Orchestrator Agent 无关，保留在 harness（是否改名
   `SingleAttemptRunner` 另行决定）。

## 责任边界

| 包 | 拥有 | 禁止拥有 |
|---|---|---|
| `agent-orchestration` | Plan/Replan 合同、Budget、DAG 校验与调度、Child Task 物化协调、取消/恢复、Completion Gate、worktree 合并环、Orchestrator 工具表面与 `system/orchestrator@1` Definition | 直接写数据库、Worker 分配、模型/工具执行、Host 业务逻辑 |
| `agent-control-plane` | Task admission、authority、capability/task binding、command/query/replay、usage、Host registry | DAG 调度、模型规划、Worker、SQL、HTTP、反向导入 orchestration |
| `agent-core` | 通用 Task、Session、Event、Authority、Port、基础值对象、Focused Subagent | 具体 Orchestrator Definition、调度实现、导入任何其他 agent 包 |
| `agent-storage` | Orchestration PostgreSQL adapter | 编排决策 |
| `agent-integrations` | AG-UI 投影、Host adapter | 编排状态机 |
| `apps/*` | 依赖装配和进程入口 | 领域逻辑 |

## 后果

- `agent-core → agent-tools` 反向依赖关闭且受门保护；workspace 依赖图
  保持无环（`test_package_dependencies.py`）。
- orchestration 域可在不动 core 的情况下独立演化（Replan、Agent Team
  等后续卡落在 `agent-orchestration`）。
- 进行中分支若触及被移文件，rebase 成本为导入路径调整，无语义冲突。
- `AGENT_TASKS.md` 中历史 ORCH-* 卡记录的旧路径为当时事实，保留不改；
  后续编排卡一律落在 `packages/agent-orchestration/`。

---
title: "Codex-like 工程 Agent 平台：任务拆解与阶段验收标准"
subtitle: "适用于使用 Codex 进行 Vibe Coding 的分阶段执行计划"
author: "Project Architecture Office"
date: "2026-06-18"
---

> Status: Historical reference only.
> Active execution has moved to `实施任务拆解与阶段验收.md`, `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`, and `AGENT_TASKS.md`.
> If this file conflicts with the active execution set, follow the newer documents.

# 目录

1. 文档说明
2. 执行摘要
3. 适配 Codex Vibe Coding 的任务设计规则
4. 全局准入与完成定义
5. Phase 0：架构验证
6. Phase 1：本地 Durable Agent Kernel
7. Phase 2：团队协作与 IDE
8. Phase 3：私有云与多租户
9. Phase 4：平台生态
10. 跨阶段非功能验收矩阵
11. Go / No-Go 决策规则
12. Codex 执行提示词模板
13. 建议的第一批执行顺序
14. 参考依据

# 文档说明

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 架构基线 | 《Codex-like 工程 Agent 平台最终架构设计 v1.0》 |
| 适用对象 | 产品负责人、技术负责人、开发工程师、测试/安全/运维人员，以及使用 Codex 执行任务的成员 |
| 目标 | 将架构方案转化为可排期、可分配、可自动验证、可阶段退出的实施 Backlog |
| 计划假设 | Phase 0-1 推荐 5 人核心团队；Phase 2 起扩展至 6-8 人；周期为规划基线而非承诺日期 |

本计划坚持三个原则：第一，**任务必须以可验证结果定义，而不是以“写了多少代码”定义**；第二，**任何阶段只有通过 Gate 才能进入下一阶段**；第三，**Codex 是执行加速器，不是责任主体，任务始终由明确的人类 Owner 负责**。

# 1. 执行摘要

项目按五个阶段推进：

| 阶段 | 目标 | 基线周期 | 主要范围 | 退出结果 |
|---|---|---:|---|---|
| Phase 0 | 架构验证 | 1-2 周 | 纵切链路、可恢复、Worktree + Rootless Docker | 证明架构关键假设成立 |
| Phase 1 | 本地 Durable Agent Kernel | 6-8 周 | CLI、Event Store、Harness、Context、Tools、Policy、Docker、Eval | 发布 v0.1.0 本地 MVP |
| Phase 2 | 团队协作与 IDE | 6-8 周 | PostgreSQL、多 Worker、Web/ACP、Broker、Repo Map、Snapshot | 发布可供团队使用的 v0.5 |
| Phase 3 | 私有云与多租户部署 | 8-12 周 | K8s、强隔离、Kubernetes RBAC、外部 authority、Vault、Temporal、SLO/DR | 私有云 GA |
| Phase 4 | 平台生态 | 持续演进 | Skills/MCP/Memory/多 Agent/模型路由/在线 Eval | 形成平台与生态 |

Phase 0 和 Phase 1 是当前唯一应进入详细排期的范围。Phase 2 以后保留架构接口和 Backlog，但不得提前微服务化或引入 Kubernetes、Temporal、复杂多 Agent 等平台能力。

# 2. 适配 Codex Vibe Coding 的任务设计规则

## 2.1 一个 Codex 任务必须满足的粒度

一个可执行任务应满足：

1. 只有一个主要目标和一个人类 Owner；
2. 通常可在 0.5-2 个工作日内产生可审查增量；超过 3 天必须拆分；
3. 明确允许修改的目录和禁止修改的目录；
4. 明确前置依赖、输入合同和交付文件；
5. 至少有一个自动验证命令；
6. 明确停止条件，例如合同不清、需要真实凭证、预期改动超过 1,000 行或需要跨越两个以上核心边界；
7. 任务完成时必须留下测试证据、Diff 说明和未解决风险。

WBS 中的“大项”是人类排期单元；进入 Codex 前应按 `AGENT_TASKS.md` 或任务卡模板再拆为原子任务。

## 2.2 仓库内唯一事实来源

项目根目录应长期维护：

```text
AGENTS.md        # 团队规范、命令、限制、完成定义
PLANS.md         # 长任务执行计划模板
REQUIREMENTS.md  # 当前发布范围与非目标
TEST.md          # 阶段 Gate、验收命令、测试矩阵
AGENT_TASKS.md   # 可由人或 Codex 执行的原子任务
```

聊天记录、即时消息和 Codex 线程不能成为唯一事实来源。任何合同、范围或验收变更必须回写上述文件或 ADR。

## 2.3 推荐任务卡

```markdown
# <TASK-ID> <标题>

Owner: <人类负责人>
Reviewer: <主审人>
Status: Ready | In Progress | Review | Blocked | Done
Depends on: <TASK-ID>
Owned paths: <允许修改路径>

## Goal
一个可观察的目标。

## Context
必须先读的架构、合同、ADR、代码和错误证据。

## Scope
本任务必须完成的内容。

## Out of scope
明确禁止顺手实现的内容。

## Acceptance
- [ ] 自动化命令与期望结果
- [ ] 安全/恢复/兼容性要求
- [ ] 文档和证据要求

## Stop conditions
遇到何种情况必须停止并交还人类决策。
```

# 3. 全局准入与完成定义

## 3.1 Definition of Ready（DoR）

任务进入 `Ready` 前必须具备：目标、范围、非目标、Owner、Reviewer、依赖、允许修改路径、合同版本、验收命令、安全等级和回滚方式。任意一项缺失，Codex 只能做只读分析，不得直接实现。

## 3.2 Definition of Done（DoD）

任务标记 `Done` 必须同时满足：

- 实现与任务范围一致，没有未经批准的扩展；
- 新增/修改的行为有测试，且相关 lint、typecheck、unit、integration 通过；
- Diff 已由人类审查，核心、安全、契约变更获得 CODEOWNER 审批；
- 事件、工具和 API 合同保持兼容，破坏性变更有版本升级和迁移；
- 没有真实凭证、敏感数据、调试后门或绕过 Policy 的路径；
- PR 描述包含验证命令、结果、风险、回滚和 Codex 使用说明；
- 任务证据可从 commit/PR 追溯到 task ID、trace、测试报告和 Artifact。

## 3.3 缺陷等级

| 等级 | 定义 | 发布处理 |
|---|---|---|
| P0 | 数据/凭证泄漏、Sandbox 逃逸、跨 namespace 访问、不可恢复的数据破坏 | 立即停止，禁止发布 |
| P1 | 关键流程不可用、重复副作用、恢复失败、权限绕过 | 禁止阶段退出 |
| P2 | 有规避方案的功能缺陷、明显性能退化、重要可观测性缺口 | 必须有 Owner、期限和风险接受 |
| P3 | 体验、文档、低风险优化 | 可进入后续迭代 |

## 3.4 每个阶段必须生成的验收证据包

```text
docs/releases/<phase>/
  acceptance-report.md
  test-report.xml / test-summary.md
  security-report.md
  resilience-report.md
  eval-report.json
  trace-samples/
  migration-or-rollback-report.md
  known-risks.md
  release-notes.md
```

# 4. Phase 0：架构验证（1-2 周）

目标不是写出完整产品，而是用最小纵切证明：**事件是事实来源、Harness 可替换、Runtime 受控、Patch 可恰好一次、任务可恢复。**

| ID | 任务与交付物 | 依赖 | 估算 | 任务级验收 |
|---|---|---|---:|---|
| `P0-GOV-01` | **仓库与工程治理骨架**<br>建立可被多人和 Codex 稳定操作的 Monorepo 基线。<br>交付：根目录 pyproject.toml、uv.lock、Makefile、AGENTS.md、PLANS.md、CI 骨架、CODEOWNERS 模板。 | 无 | 2-3 人日 | `uv sync`、`make check` 可执行；依赖边界检查进入 CI；主分支保护策略有文档。 |
| `P0-CON-01` | **V1 事件与调用契约**<br>固定 SessionEvent、ToolCall、ToolResult、PolicyDecision 的最小字段和版本策略。<br>交付：`contracts/events/v1`、`contracts/tools/v1`、`contracts/policy/v1`；JSON Schema/Pydantic 模型；兼容性测试。 | P0-GOV-01 | 3-4 人日 | 所有示例通过 Schema 校验；未知字段策略明确；破坏性变更测试能失败。 |
| `P0-STO-01` | **SQLite Append-only Event Store 原型**<br>验证顺序追加、唯一序号、幂等键和事务边界。<br>交付：SQLite 表结构、append/read API、并发写测试、唯一约束。 | P0-CON-01 | 3-4 人日 | 同一 idempotency_key 重试只产生一条事件；同一 session 的 sequence 连续且唯一。 |
| `P0-STO-02` | **Projection 与重放原型**<br>证明任务状态可完全由事件重建，而不是依赖进程内状态。<br>交付：TaskProjection、ProjectionBuilder、rebuild 命令、状态对比测试。 | P0-STO-01 | 3-4 人日 | 清空 projection 后重放得到相同状态；重放重复执行不改变最终结果。 |
| `P0-RT-01` | **Git Worktree 生命周期原型**<br>验证每个写任务独立分支和工作区。<br>交付：create/list/cleanup worktree API；脏仓库、同名分支、清理失败处理。 | P0-GOV-01 | 2-3 人日 | 源工作区零改动；异常结束后可重复清理；任务分支可生成 diff。 |
| `P0-RT-02` | **Rootless Docker Runtime 原型**<br>验证无 root、只挂载 worktree、默认禁网、资源限制和超时。<br>交付：Dockerfile、RuntimeSpec、exec/kill/cleanup API、network none 验证脚本。 | P0-RT-01 | 3-4 人日 | 容器内 UID 非 root；无法读取 Home；无法联网；超时进程及子进程被终止。 |
| `P0-SEC-01` | **最小 Policy 执行链**<br>在 Runtime 前强制执行 allow/ask/deny，并记录决策。<br>交付：PolicyPort、规则加载、路径/命令基础规则、Approval 占位、Policy 事件。 | P0-CON-01 | 3-4 人日 | 被 deny 的动作不会触达 Runtime；ask 会挂起；每个决策可关联 tool_call_id。 |
| `P0-HAR-01` | **端到端纵切链路**<br>用 MockModel 串起 Session -> ToolCall -> Policy -> Runtime -> Event。<br>交付：最小 Stateless Harness、MockProvider、一个 read 工具和一个 patch 工具、CLI demo。 | P0-STO-02, P0-RT-02, P0-SEC-01 | 4-5 人日 | 单条命令产生完整事件链、diff 和结构化结果；Harness 重启后可继续。 |
| `P0-RES-01` | **崩溃注入与 Exactly-once Patch**<br>验证模型返回、Policy、工具启动、Patch 落盘、事件提交等边界的恢复语义。<br>交付：故障注入点、幂等执行表、Patch 哈希、恢复测试。 | P0-HAR-01 | 4-5 人日 | 至少 8 个故障点各重复 5 次，恢复后 Patch 恰好应用一次。 |
| `P0-GATE-01` | **Phase 0 验收脚本与报告**<br>把 PoC 结论固化为可重复 Gate。<br>交付：`scripts/accept_phase0.sh`、验收报告模板、trace 样例、风险清单。 | 全部 P0 任务 | 2-3 人日 | 一条命令执行全部 Gate；失败返回非零；报告记录 commit、环境和证据路径。 |

## 4.1 Phase 0 退出 Gate

| Gate ID | 硬性标准 | 验证方式 | 证据 |
|---|---|---|---|
| G0-ARCH-01 | 一条 MockModel ToolCall 能完整经过 Policy、Runtime、Event Store 和 Projection | `scripts/accept_phase0.sh` | trace + event dump |
| G0-DUR-01 | 至少 8 个故障点各 5 次恢复成功，Patch 恰好一次 | failure-injection suite | recovery report |
| G0-ISO-01 | 源工作区、用户 Home 零写入；Sandbox 默认无网络 | security smoke tests | container inspect + test logs |
| G0-CON-01 | 事件、工具、Policy 契约有 V1 Schema 和兼容性测试 | contract tests | schema report |
| G0-DEC-01 | 如任一硬 Gate 不通过，不进入 Phase 1；需修改架构或 ADR | Gate review | 签字记录 |

# 5. Phase 1：本地 Durable Agent Kernel（6-8 周）

Phase 1 交付 v0.1.0。本阶段完成可在可信开发机上使用的本地 Agent Kernel，重点是正确性、安全性、恢复能力和评测闭环，而不是 UI 丰富度。

| ID | 任务与交付物 | 依赖 | 估算 | 任务级验收 |
|---|---|---|---:|---|
| `P1-GOV-01` | **正式 Monorepo 与包依赖规则**<br>落地 apps/packages/services/contracts/tests/evals 目录和单向依赖。<br>交付：uv workspace、各包 pyproject、import-linter 规则、开发命令。 | P0-GATE-01 | 3-4 人日 | 所有包可独立安装；agent-core 不依赖基础设施；CI 能阻止反向 import。 |
| `P1-GOV-02` | **配置系统与 Schema**<br>统一应用、模型、权限、Runtime 配置，支持 local/test profile。<br>交付：config loader、JSON Schema、示例配置、敏感值检查。 | P1-GOV-01 | 3-4 人日 | 非法配置启动失败且错误可定位；配置中真实 secret 被 pre-commit 拦截。 |
| `P1-CON-01` | **Event Contract V1 定版**<br>补齐因果链、关联 ID、版本、Actor、Artifact 引用和迁移规则。<br>交付：V1 事件目录、upcaster 接口、Golden fixtures、Schema 兼容测试。 | P1-GOV-01 | 4-5 人日 | 旧 fixtures 可读取；相同事件序列在不同进程生成一致 projection。 |
| `P1-CON-02` | **Tool/Policy/Runtime Contract V1**<br>定义 Typed Tool 参数、ToolResult、PolicyContext、RuntimeSpec。<br>交付：Schema、Python 类型、序列化测试、错误码字典。 | P1-CON-01 | 4-5 人日 | 所有内置工具仅通过合同调用；错误不依赖自由文本解析。 |
| `P1-CORE-01` | **Session 领域模型与状态机**<br>实现创建、运行、等待审批、挂起、恢复、完成、失败、取消状态。<br>交付：Session aggregate、状态迁移、非法迁移错误、单元测试。 | P1-CON-01 | 4-5 人日 | 状态表覆盖 100%；非法迁移均被拒绝并记录事件。 |
| `P1-STO-01` | **SQLite Event Store 正式实现**<br>加入事务、并发、分页、快照指针、迁移与备份。<br>交付：生产实现、Alembic/迁移脚本、仓储测试。 | P1-CON-01 | 4-5 人日 | 并发追加无丢失；故障回滚无半条事件；可从备份恢复。 |
| `P1-STO-02` | **Projection 与幂等执行记录**<br>实现任务、审批、费用、工具执行视图和幂等表。<br>交付：Projection handlers、rebuild、幂等仓储、查询 API。 | P1-STO-01, P1-CORE-01 | 4-5 人日 | 在线投影与离线重放一致；重复消息不产生重复副作用。 |
| `P1-SCH-01` | **DB Lease Scheduler**<br>实现单机多进程可恢复的租约、心跳、超时和重试。<br>交付：SchedulerPort、SQLite lease、worker consumer、故障测试。 | P1-STO-02 | 5-6 人日 | 同一 session 同时仅一个有效 lease；worker 被杀后超时接管。 |
| `P1-RES-01` | **Durable Resume 与副作用抑制**<br>将恢复策略覆盖模型调用、审批、命令和 Patch。<br>交付：recovery service、execution journal、idempotency policy、故障注入。 | P1-SCH-01 | 5-6 人日 | 12 个关键检查点恢复成功率 100%；不可重放动作会进入人工决策。 |
| `P1-RT-01` | **RuntimePort 与 Fake/Local Adapter**<br>形成可测试的 provision/exec/stream/destroy 接口。<br>交付：RuntimePort、FakeRuntime、受限 LocalRuntime、契约测试。 | P1-CON-02 | 3-4 人日 | 同一契约测试可运行于 Fake、Local、Docker；核心不 import Docker SDK。 |
| `P1-RT-02` | **Docker Runtime 硬化**<br>实现 rootless、只读根文件系统、资源/PID/网络限制、完整清理。<br>交付：Docker adapter、SandboxSpec、seccomp、超时与日志截断。 | P1-RT-01 | 6-8 人日 | 安全套件无法越界；容器/网络/卷无泄漏；资源限制可观测。 |
| `P1-RT-03` | **Repository/Worktree Manager**<br>管理 branch、worktree、基线 SHA、diff、cleanup 和冲突。<br>交付：RepositoryPort、WorktreeManager、Git 错误模型、测试。 | P1-RT-01 | 4-5 人日 | 并行 10 个任务不互相污染；源目录保持 clean；异常可回收。 |
| `P1-ART-01` | **本地内容寻址 Artifact Store**<br>保存 stdout/stderr、patch、报告和大结果，事件只存引用。<br>交付：ArtifactPort、local CAS、哈希校验、GC 策略。 | P1-STO-02 | 3-4 人日 | 相同内容去重；篡改可检测；事件可解析回 Artifact。 |
| `P1-TOOL-01` | **Tool Registry 与统一执行器**<br>注册版本化工具、校验输入、生成结构化结果并发事件。<br>交付：registry、executor、contracts adapter、测试。 | P1-CON-02, P1-RT-01 | 3-4 人日 | 未知工具/非法参数在 Runtime 前拒绝；所有结果包含 duration/exit/status。 |
| `P1-TOOL-02` | **只读文件、搜索与 Git 上下文工具**<br>实现 read/list/search/repo-tree/git-status/git-diff。<br>交付：Typed tools、输出限额、二进制文件策略、测试。 | P1-TOOL-01, P1-RT-03 | 4-5 人日 | 路径越界被拒；超长输出落 Artifact；结果可复现。 |
| `P1-TOOL-03` | **Patch 与受控文件修改工具**<br>实现 unified diff、create/delete、原子写、冲突检测和 Patch 哈希。<br>交付：apply_patch、precondition、rollback、changed-files 结果。 | P1-TOOL-01, P1-SEC-02 | 5-6 人日 | Patch 基线不匹配时拒绝；失败不留下半写文件；重复调用不重复应用。 |
| `P1-TOOL-04` | **Typed Command/Test/Git 工具**<br>以 executable+argv 代替默认 shell 字符串，支持测试和受控 Git。<br>交付：command、test、git tools；timeout；stream；exit 规范。 | P1-TOOL-01, P1-RT-02, P1-SEC-03 | 5-6 人日 | 不经 shell 解析执行；timeout 杀死进程树；commit/push 需要明确策略。 |
| `P1-SEC-01` | **权限 Profiles 与 Policy Engine**<br>实现 read-only/workspace-write/test-runner/setup/full-access。<br>交付：PDP、profiles、规则组合、decision reason、测试。 | P1-CON-02 | 5-6 人日 | 同一请求在固定 profile 下决策确定；默认 profile 最小权限。 |
| `P1-SEC-02` | **文件系统与 Secret 防护**<br>防路径穿越、symlink 逃逸、Home/凭证读取和敏感输出。<br>交付：canonical path 校验、deny patterns、secret redaction、security tests。 | P1-SEC-01 | 4-5 人日 | 攻击 fixtures 全部被阻断；日志和 Artifact 不泄漏测试 token。 |
| `P1-SEC-03` | **命令、网络与审批**<br>实现命令结构校验、默认禁网、审批挂起/恢复和风险摘要。<br>交付：command/network rules、approval service、CLI approval。 | P1-SEC-01, P1-TOOL-04 | 5-6 人日 | 网络测试在 agent phase 失败；ask 不执行；批准后只执行原始哈希匹配请求。 |
| `P1-SEC-04` | **审计关联与日志脱敏**<br>建立 session/event/tool/policy/approval/artifact 的完整关联链。<br>交付：Audit record、correlation middleware、redaction、查询。 | P1-SEC-02, P1-SEC-03 | 3-4 人日 | 任一 tool_call_id 可追溯到模型响应、决策、执行和 Artifact。 |
| `P1-MDL-01` | **Model Gateway 与 Mock Provider**<br>统一 message/tool call/usage/error/retry 接口，核心不依赖厂商。<br>交付：ModelGateway、MockProvider、record/replay fixtures。 | P1-CON-02 | 4-5 人日 | Harness 可仅靠 MockProvider 运行完整测试；响应可序列化为事件。 |
| `P1-MDL-02` | **OpenAI Provider 与使用量治理**<br>接入当前模型 API，处理 tool calls、流式、重试、费用和限额。<br>交付：OpenAI adapter、usage mapper、retry/backoff、契约测试。 | P1-MDL-01 | 4-5 人日 | 网络/限流/超时映射为稳定错误；费用与 token 进入 projection。 |
| `P1-CTX-01` | **Project Guidance 与仓库扫描**<br>加载 AGENTS.md/README/构建配置，使用 git ls-files 与 rg。<br>交付：loader、scanner、文件过滤、基础 Repo Tree。 | P1-GOV-01 | 4-5 人日 | 分层 AGENTS.md 优先级正确；忽略规则可配置；大文件不误读。 |
| `P1-CTX-02` | **Context Compiler 与 Token Budget**<br>按来源、信任、相关性、成本编译稳定前缀和动态尾部。<br>交付：ContextItem、ranker、budget、prompt layout、provenance。 | P1-CTX-01, P1-MDL-01 | 5-6 人日 | 相同输入产生稳定 cache key；不可信内容显式标记；超预算可预测裁剪。 |
| `P1-CTX-03` | **工具输出压缩与会话 Compaction**<br>压缩长日志和历史事件，保留事实、未决事项和证据引用。<br>交付：compactor、checkpoint summary、Artifact 引用、回归测试。 | P1-CTX-02, P1-ART-01 | 5-6 人日 | 压缩前后任务状态一致；关键失败证据和未执行事项不丢失。 |
| `P1-HAR-01` | **Stateless Harness Loop**<br>实现模型调用、工具提议、Policy、执行、事件追加和恢复。<br>交付：loop、state projection、tool routing、stream callbacks。 | P1-RES-01, P1-TOOL-03, P1-TOOL-04, P1-MDL-02, P1-CTX-02 | 6-8 人日 | Harness 进程无权威状态；任意 worker 可从 Event Store 继续。 |
| `P1-HAR-02` | **预算、停止、Verifier 与最终总结**<br>控制 step/token/cost/time，运行验证并输出未解决风险。<br>交付：budget policy、stopping、verifier、final report schema。 | P1-HAR-01, P1-CTX-03 | 5-6 人日 | 达到任一预算会安全停止；最终报告始终包含 diff/test/risk/cost。 |
| `P1-CLI-01` | **CLI 任务生命周期**<br>提供 run/inspect/resume/approve/cancel/events/artifacts 命令。<br>交付：Typer/Rich CLI、非交互模式、JSON 输出。 | P1-HAR-02, P1-SCH-01 | 5-6 人日 | 核心场景可只用 CLI 完成；退出码稳定；自动化可消费 JSON。 |
| `P1-API-01` | **本地控制 API 最小集**<br>为未来 Web/IDE 提供 session/message/approval/artifact 接口。<br>交付：FastAPI routes、SSE 基础、OpenAPI、auth=local。 | P1-HAR-02 | 4-5 人日 | OpenAPI 合同测试通过；CLI 与 API 读取同一 projection。 |
| `P1-OBS-01` | **Trace、Metrics 与成本**<br>记录模型、工具、Policy、Runtime 时延和费用，支持 replay 链接。<br>交付：structured logging、trace span、metrics、cost report。 | P1-SEC-04, P1-MDL-02 | 4-5 人日 | 每个 session 有完整 trace；敏感值脱敏；可导出 JSONL。 |
| `P1-EVAL-01` | **确定性 Fixture Repositories**<br>构造 Python/TypeScript/Go 故障仓库与恶意仓库。<br>交付：fixtures、golden patch、测试脚本、版本锁定。 | P1-GOV-01 | 5-6 人日 | fixture 可离线复现；基线失败、golden 修复后通过。 |
| `P1-EVAL-02` | **Agent Eval Runner 与 30-50 用例**<br>实现 runner、grader、基线、三次运行聚合和回归门禁。<br>交付：eval cases、graders、report、baseline comparison。 | P1-EVAL-01, P1-HAR-02 | 6-8 人日 | 一键运行；结果含成功、diff 质量、违规、成本；回归超阈值阻断。 |
| `P1-E2E-01` | **修复测试失败端到端闭环**<br>完成用户命令、计划、Patch、测试、二次修复、总结和恢复。<br>交付：3 类语言 demo、golden traces、操作手册。 | 全部 P1 核心任务 | 5-6 人日 | Python/TS/Go 至少各 3 个固定用例通过；中断恢复无重复修改。 |
| `P1-GATE-01` | **MVP 发布 Gate 与 v0.1.0**<br>执行功能、耐久、安全、评测、文档、SBOM 和版本发布。<br>交付：acceptance report、release notes、known issues、tag。 | P1-E2E-01, P1-EVAL-02 | 4-5 人日 | 所有硬 Gate 通过；0 个 P0/P1 缺陷；架构偏差有 ADR。 |

## 5.1 Phase 1 退出 Gate

| Gate ID | 硬性标准 | 目标/阈值 | 证据 |
|---|---|---:|---|
| G1-FUN-01 | `agent "修复当前仓库测试失败"` 完成 plan -> patch -> test -> retry -> diff -> summary | Python/TS/Go 各至少 3 个固定用例通过 | E2E report + golden traces |
| G1-DUR-01 | 关键检查点恢复且无重复副作用 | 12 个故障点 × 5 次，100% 成功 | resilience report |
| G1-ISO-01 | 源工作区和用户 Home 不被读写；Agent Phase 默认无网络 | 安全用例 100% 通过 | security report |
| G1-CRED-01 | Sandbox 内不存在平台原始 Token/Key | 0 次泄漏 | secret scan report |
| G1-AUD-01 | ModelResponse、ToolCall、Policy、Approval、Execution、Artifact 全链关联 | 100% tool call 可追溯 | audit consistency report |
| G1-EVAL-01 | 评测可一键运行并比较版本 | 30-50 个 cases；三次运行中位 pass@1 >= 70%；相对基线下降不得超过 5 个百分点 | eval report |
| G1-QUAL-01 | 确定性测试、类型、lint、依赖边界通过 | 核心包覆盖率 >= 85%，其他关键包 >= 75% | CI report |
| G1-DEF-01 | 无未关闭的阻断缺陷 | 0 个 P0/P1；P2 必须有 owner 和计划 | defect report |
| G1-DEL-01 | 交付包含 diff、测试、风险、费用、审批与 Artifact | 100% 完整 | acceptance bundle |

# 6. Phase 2：团队协作与 IDE（6-8 周）

Phase 2 将单机 Kernel 升级为多人共享的控制平面，并把原始凭证移出 Sandbox。所有服务拆分必须由明确的安全、权限或独立扩缩需求驱动。

| ID | 任务与交付物 | 依赖 | 估算 | 任务级验收 |
|---|---|---|---:|---|
| `P2-STO-01` | **PostgreSQL Event/Projection Store**<br>迁移事件、projection、幂等和 lease，支持双写/回滚。<br>交付：Postgres adapter、migration、backfill、兼容测试。 | P1-GATE-01 | 6-8 人日 | SQLite 数据可迁移；并发追加和租约测试通过；可回滚。 |
| `P2-SCH-01` | **多 Worker 调度与重试**<br>支持多节点 claim、心跳、退避、死信和公平性。<br>交付：queue/lease scheduler、worker autosafe shutdown、dashboard metrics。 | P2-STO-01 | 6-8 人日 | 3 worker 下 20 个并发 session 无重复所有权；kill 后自动接管。 |
| `P2-ART-01` | **对象存储 Artifact Adapter**<br>接入 S3/MinIO、签名访问、生命周期和完整性校验。<br>交付：S3 adapter、presigned access、retention、迁移工具。 | P2-STO-01 | 4-5 人日 | 大 Artifact 不进 DB；权限隔离；校验失败可检测。 |
| `P2-API-01` | **团队 Control Plane API**<br>增加外部身份验证、Agent authority、repo、session、审批、审计和技术 limits 接口。<br>交付：API v1、auth middleware、OpenAPI SDK。 | P2-STO-01, P2-SCH-01 | 6-8 人日 | 权限测试覆盖；API 版本化；错误格式统一。 |
| `P2-API-02` | **SSE/WebSocket 可靠流式**<br>支持断线重连、last-event-id、背压和事件补发。<br>交付：stream gateway、cursor、客户端测试。 | P2-API-01 | 4-5 人日 | 断线 60 秒后恢复无事件丢失/重复展示；慢客户端不拖垮 worker。 |
| `P2-WEB-01` | **Web 会话、Trace、Diff 与 Artifact**<br>提供任务提交、时间线、diff、日志和技术 usage/cost evidence 页面。<br>交付：React app、API client、核心页面、e2e tests。 | P2-API-02 | 8-10 人日 | 操作者可完成查看/恢复/下载证据；主要流程可自动化测试。 |
| `P2-WEB-02` | **审批中心与风险展示**<br>展示命令、路径、网络、理由、哈希和审批有效期。<br>交付：approval UI、bulk policy guard、audit link。 | P2-WEB-01, P2-SEC-01 | 4-5 人日 | 审批对象与执行对象哈希一致；过期审批不可用。 |
| `P2-ACP-01` | **ACP Adapter**<br>让 IDE 通过标准会话、消息、工具进度接口连接。<br>交付：ACP adapter、capability negotiation、integration tests。 | P2-API-02 | 6-8 人日 | 至少一个支持客户端完成 run/resume/approve；断线可恢复。 |
| `P2-SEC-01` | **Credential Broker**<br>原始 Git/LLM/MCP 凭证保存在 Sandbox 外，签发短时能力。<br>交付：broker service、scope model、audit、revocation。 | P2-API-01 | 8-10 人日 | Sandbox 环境和文件系统扫描不到原始凭证；能力超期失效。 |
| `P2-SEC-02` | **Egress Proxy**<br>按 session/域名/方法/目的地实施网络策略并审计。<br>交付：proxy service、allowlist、DNS/IP 防绕过、logs。 | P2-SEC-01 | 8-10 人日 | SSRF、DNS rebinding、直连 IP 测试被阻断；所有请求可追溯。 |
| `P2-SCM-01` | **GitHub/GitLab App**<br>实现 clone/push/PR、最小 scope、分支限制和 webhook。<br>交付：SCM adapters、webhook handlers、PR workflow。 | P2-SEC-01, P2-API-01 | 6-8 人日 | 仅能访问授权 repo/branch；push/PR 全程审计。 |
| `P2-CTX-01` | **Tree-sitter Repo Map**<br>生成符号、定义、引用、import 图和相关文件排序。<br>交付：indexer、language packs、repo map artifact。 | P1-CTX-01 | 8-10 人日 | Python/TS/Go fixture 的定义/引用准确率达基线；增量更新可验证。 |
| `P2-CTX-02` | **LSP 与增量索引**<br>接入 LSP、变更监听、索引版本和回退。<br>交付：LSP adapter、index cache、freshness metrics。 | P2-CTX-01 | 6-8 人日 | 文件变更后索引在目标时限内一致；LSP 不可用时回退 tree-sitter。 |
| `P2-RT-01` | **Snapshot/Suspend/Resume**<br>保存依赖、缓存和运行环境，支持释放计算后恢复。<br>交付：snapshot API、adapter、retention、compat checks。 | P2-SCH-01 | 8-10 人日 | 挂起 30 分钟后恢复并继续测试；代码、事件、环境版本一致。 |
| `P2-SUB-01` | **Research Subagent**<br>提供只读代码探索与证据化返回。<br>交付：spawn/join/cancel primitives、read-only profile、result schema。 | P1-HAR-02, P2-CTX-01 | 5-6 人日 | 不能写文件/执行高风险命令；返回包含来源和置信度。 |
| `P2-SUB-02` | **Reviewer Subagent**<br>对 diff 做安全、正确性、可维护性和测试覆盖审查。<br>交付：review agent config、findings schema、dedupe。 | P2-SUB-01 | 5-6 人日 | findings 可定位文件/行；不直接修改代码；误报基线可追踪。 |
| `P2-OBS-01` | **OpenTelemetry 与运营面板**<br>统一 API/worker/sandbox/broker trace、指标和告警。<br>交付：OTel、Prometheus/Grafana、SLO dashboards。 | P2-SCH-01, P2-SEC-02 | 5-6 人日 | 跨服务 trace 连续；关键错误/延迟/成本有告警。 |
| `P2-EVAL-01` | **协作、重连与凭证安全评测**<br>覆盖并发、worker crash、stream reconnect、credential/egress。<br>交付：new eval suites、chaos scripts、report。 | 全部 P2 核心任务 | 6-8 人日 | 20 并发与故障场景达 Gate；0 个凭证泄漏。 |
| `P2-E2E-01` | **团队版端到端发布流**<br>从 Web/IDE 提交到 PR、审批、恢复、审计。<br>交付：demo repo、runbook、golden trace、video/script。 | P2-EVAL-01 | 5-6 人日 | 两个外部 subject/Agent permission profile 完成完整流程；权限、PR、审计证据一致。 |
| `P2-GATE-01` | **Phase 2 发布 Gate**<br>完成团队功能、安全、容量和升级验收。<br>交付：acceptance report、migration report、release tag。 | P2-E2E-01 | 4-5 人日 | 所有 Phase 2 硬 Gate 通过；升级/回滚演练完成。 |

## 6.1 Phase 2 退出 Gate

| Gate ID | 硬性标准 | 目标/阈值 | 证据 |
|---|---|---:|---|
| G2-CON-01 | 多 Worker 对 Session 维持单一有效所有权 | 3 Worker、20 并发 Session，无重复执行 | concurrency report |
| G2-STR-01 | SSE/WebSocket 断线重连不丢事件 | 断线 60 秒后恢复，UI 无缺口 | reconnect tests |
| G2-CRED-01 | 原始凭证永不进入 Sandbox | 0 次扫描命中；短时 Capability 可撤销/过期 | broker security report |
| G2-NET-01 | 外联只经 Egress Proxy，SSRF/直连 IP/DNS 绕过被阻断 | 安全套件 100% 通过 | egress report |
| G2-SNP-01 | Sandbox 可挂起、释放、恢复 | 30 分钟后恢复并继续任务，环境哈希一致 | snapshot report |
| G2-UX-01 | Web/IDE 可完成提交、审批、恢复、审查 Diff 和下载 Artifact | 两个角色完整 E2E | usability/e2e report |
| G2-UPG-01 | SQLite -> PostgreSQL、Local Artifact -> S3 升级可回滚 | 迁移和回滚演练成功 | migration report |
| G2-DEF-01 | 无未关闭 P0/P1；关键依赖完成安全审查 | 0 个 P0/P1 | release report |

# 7. Phase 3：私有云与多租户（8-12 周）

Phase 3 的核心不是“部署到 Kubernetes”，而是证明外部 namespace 隔离、外部
authority 验证、凭证治理、跨节点恢复、容量和运维准备度。Zebra 不开发用户、组织、
成员、业务 RBAC、订阅、计费或业务配额；这些由调用 Zebra 的业务系统负责。

| ID | 任务与交付物 | 依赖 | 估算 | 任务级验收 |
|---|---|---|---:|---|
| `P3-RT-01` | **Kubernetes Sandbox Manager**<br>创建、观察、回收 Agent Sandbox/Pod 和工作卷。<br>交付：K8s adapter、CRD/manifest、controller integration。 | P2-GATE-01 | 10-12 人日 | 100 个 sandbox 生命周期测试无孤儿资源；失败可回收。 |
| `P3-RT-02` | **gVisor/Kata/Firecracker 分级隔离**<br>按信任等级选择运行时并验证兼容性。<br>交付：runtime classes、capability matrix、benchmark。 | P3-RT-01 | 10-15 人日 | 不可信 profile 使用独立内核级隔离；兼容/性能数据可审计。 |
| `P3-TEN-01` | **外部 Namespace 数据隔离**<br>在 Agent 实体、查询、对象路径和 cache key 中落实 opaque namespace，不建立 Tenant Domain。<br>交付：namespace contract、row/object policy、migration。 | P3-RT-01 | 8-10 人日 | 跨 namespace 读取/写入测试 100% 阻断；无默认 namespace 回退。 |
| `P3-IAM-01` | **外部身份与 Authority 接入**<br>使用 Authelia OIDC 认证并验证业务系统签发的短时 Agent authority；不实现用户、成员或业务 RBAC。<br>交付：OIDC adapter、authority verifier、scope matrix。 | P3-TEN-01 | 6-8 人日 | issuer/audience/expiry/scope 验证 fail closed；Zebra Policy 不得扩权。 |
| `P3-SEC-01` | **Agent Policy 与 Authority 快照**<br>支持 Agent Policy 收紧、模拟、签名和审计，并持久化 Attempt 生效权限摘要。<br>交付：policy registry、authority snapshot、dry-run、rollout。 | P3-IAM-01 | 8-10 人日 | 策略变更可预演；历史任务可解析当时 authority 与 Policy 版本。 |
| `P3-SEC-02` | **Vault/KMS 与短时 Capability**<br>集中密钥、轮换、短时令牌、撤销和最小 scope。<br>交付：Vault/KMS adapters、issuer、rotation runbook。 | P3-SEC-01 | 8-10 人日 | 轮换不中断现有安全会话；撤销在 SLO 内生效。 |
| `P3-NET-01` | **集群级网络隔离与私网连接**<br>实现 namespace/network policy、egress、企业私网 connector。<br>交付：NetworkPolicy、proxy scale-out、private connector。 | P3-RT-01, P3-SEC-02 | 10-12 人日 | 默认 deny；跨 namespace 和未授权外联被阻断；审计完整。 |
| `P3-SCALE-01` | **Warm Pool 与自动伸缩**<br>降低启动延迟并按队列、资源和技术限制扩缩。<br>交付：pool controller、autoscaling、capacity model。 | P3-RT-01 | 8-10 人日 | 目标负载下 p95 调度时延达 SLO；无 namespace 资源串用。 |
| `P3-COST-01` | **技术限制与 Usage Evidence**<br>执行外部提供的并发、Token、Runtime、存储和网络上限，并输出业务无关的技术用量事件；不实现套餐或账单。<br>交付：limit enforcement、usage schema、capacity dashboard。 | P3-TEN-01, P3-SCALE-01 | 6-8 人日 | 超出技术上限的任务按策略停止；usage 可关联外部 request、namespace 和 session。 |
| `P3-WF-01` | **Temporal Adapter 与长任务编排**<br>将 lease/workflow 抽象映射到可持久工作流。<br>交付：Temporal adapter、activity idempotency、migration path。 | P3-SCALE-01 | 10-12 人日 | 跨节点重启/升级不丢任务；活动重复不产生副作用。 |
| `P3-DR-01` | **备份、跨节点恢复与灾难演练**<br>定义 DB/Object/Event/Secrets 的 RPO/RTO 和恢复步骤。<br>交付：backup jobs、restore scripts、DR runbook、演练报告。 | P3-WF-01, P3-SEC-02 | 8-10 人日 | 在隔离环境完成恢复；达到 RPO<=5 分钟、RTO<=30 分钟基线。 |
| `P3-OBS-01` | **生产 SLO、告警与审计保留**<br>建立可用性、调度、恢复、隔离、成本和留存 SLO。<br>交付：SLO docs、alerts、retention jobs、audit export。 | P3-COST-01, P3-DR-01 | 6-8 人日 | 关键 SLO 有可执行告警；审计保留和删除策略可验证。 |
| `P3-SEC-03` | **跨 Namespace 攻击与渗透测试**<br>系统化测试逃逸、SSRF、凭证、越权、供应链和 prompt injection。<br>交付：threat model 更新、attack suite、修复报告。 | 全部 P3 安全任务 | 10-15 人日 | 0 个未接受的 Critical/High；所有发现有复测证据。 |
| `P3-EVAL-01` | **100 并发与混沌评测**<br>模拟 worker/sandbox/DB/proxy 故障和扩缩。<br>交付：load/chaos suite、capacity report、baseline。 | P3-WF-01, P3-OBS-01 | 8-10 人日 | 100 活跃 session 下无数据错配；恢复和延迟满足 Gate。 |
| `P3-GATE-01` | **私有云 GA Gate**<br>完成隔离、容量、DR、运维、安全和合规证据。<br>交付：GA checklist、runbooks、SBOM、release notes。 | P3-SEC-03, P3-EVAL-01 | 5-6 人日 | 所有硬 Gate 通过；值班和回滚演练完成；风险正式接受。 |

## 7.1 Phase 3 退出 Gate

| Gate ID | 硬性标准 | 目标/阈值 | 证据 |
|---|---|---:|---|
| G3-TEN-01 | 跨 namespace 数据、Artifact、Cache、Sandbox、凭证隔离 | 攻击/越权测试 100% 阻断 | isolation report |
| G3-SCL-01 | 私有云容量基线达标 | 100 活跃 Session；无错配；p95 调度等待 <= 30 秒（Warm Pool 基线） | load report |
| G3-DUR-01 | 跨节点恢复和工作流幂等 | Worker/Node/DB 短故障后任务恢复，无重复副作用 | chaos report |
| G3-DR-01 | 灾难恢复达到基线 | RPO <= 5 分钟，RTO <= 30 分钟 | DR exercise report |
| G3-SEC-01 | 跨 namespace 渗透测试无未接受 Critical/High | 0 个未接受 Critical/High | penetration report |
| G3-IAM-01 | Authelia OIDC、外部 authority、Agent Policy、Capability、撤销与轮换可验证 | Agent scope 矩阵 100% 通过 | identity/authority report |
| G3-OPS-01 | SLO、告警、runbook、值班、审计保留和删除齐备 | 演练全部通过 | operations readiness review |
| G3-GA-01 | 升级、回滚、SBOM、发布说明和风险接受完成 | 技术与业务双签 | GA bundle |

# 8. Phase 4：平台生态（持续演进）

Phase 4 以 Epic 管理。每个 Epic 进入开发前都必须有独立需求、威胁模型、评测集和商业价值指标。

| ID | 任务与交付物 | 依赖 | 估算 | 任务级验收 |
|---|---|---|---:|---|
| `P4-SKILL-01` | **Skill Registry 与版本治理**<br>团队发布、发现、签名、依赖和回滚 Skills。<br>交付：registry、manifest、review pipeline。 | P3-GATE-01 | Epic | 技能安装可审计、可锁版本、可撤销。 |
| `P4-MCP-01` | **MCP Marketplace 与可信分级**<br>管理 MCP server、OAuth scope、签名、风险和运行状况。<br>交付：catalog、trust policy、health/audit。 | P3-GATE-01 | Epic | 未批准 MCP 不可调用；scope 最小化可验证。 |
| `P4-MEM-01` | **团队共享记忆与治理**<br>支持来源、有效期、ACL、矛盾和删除。<br>交付：memory governance、UI、evaluation。 | P3-TEN-01 | Epic | 跨团队不可越权；陈旧/冲突记忆有自动降权。 |
| `P4-MA-01` | **多 Agent Worktree Merge Coordinator**<br>并行写 Agent 的分支、冲突、测试和合并。<br>交付：coordinator、merge policy、conflict UI。 | P3-WF-01 | Epic | 并行写不共享 workspace；冲突可确定性重放和人工接管。 |
| `P4-A2A-01` | **A2A/跨平台委派**<br>在明确业务需求下支持跨系统任务委派。<br>交付：adapter、trust/capability、audit。 | P3-SEC-01 | Epic | 远端 Agent 权限和结果均可验证、撤销和追溯。 |
| `P4-MDL-01` | **自动模型路由**<br>按任务、风险、延迟、成本和效果选择模型。<br>交付：router、policy、offline/online eval。 | P3-COST-01 | Epic | 任何路由变更先经评测；可回退固定模型。 |
| `P4-EVAL-01` | **线上 Eval、灰度与回归归因**<br>从 trace 生成 eval，做 shadow、canary 和版本比较。<br>交付：improvement loop、release gates、dashboards。 | P3-OBS-01 | Epic | 模型/Harness/Skill 变更有统计显著的对比和回滚。 |
| `P4-POL-01` | **Policy Simulator 与策略分析**<br>在不执行动作时模拟策略影响和历史回放。<br>交付：simulator、diff、impact report。 | P3-SEC-01 | Epic | 策略发布前可对历史流量回放，无实际副作用。 |

# 9. 跨阶段非功能验收矩阵

| 维度 | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Durability | 单机/多进程恢复，副作用幂等 | 多 Worker、流重连、Snapshot | 跨节点、Temporal、DR |
| Security | Worktree、Rootless Docker、默认禁网、敏感路径 | Credential Broker、Egress Proxy、外部身份 | 强隔离、Namespace、Vault/KMS、外部 Authority |
| Evaluation | 30-50 本地 cases、版本对比 | 并发、协作、凭证与 UI E2E | 负载、混沌、跨 namespace 攻击、SLO |
| Observability | JSONL/Trace/Cost/Audit | OTel 跨服务、运营面板 | SLO、告警、审计保留、合规导出 |
| Compatibility | V1 Contract + upcaster | API/DB/Artifact 升级与回滚 | 工作流、K8s、Policy 和数据迁移 |
| Performance | 工具层开销可测，不阻塞本地使用 | 20 并发基线 | 100 并发、Warm Pool 与容量模型 |

# 10. Go / No-Go 决策规则

阶段评审只允许三种结果：

- **Go**：全部硬 Gate 通过，P2 风险已接受，进入下一阶段；
- **Conditional Go**：仅文档、体验或非关键 P2 存在，指定 Owner 和截止日期；
- **No-Go**：任一安全、耐久、数据一致性、契约兼容或 P0/P1 Gate 未通过。

不得以“Codex 已经写完”“Demo 能跑”代替 Gate 证据。

# 11. Codex 执行提示词模板

```text
你负责执行任务 <TASK-ID>。先读取 AGENTS.md、REQUIREMENTS.md、TEST.md、
AGENT_TASKS.md 中对应任务，以及列出的合同和 ADR。

目标：<Goal>
允许修改：<Owned paths>
禁止修改：<Out of scope paths>
依赖：<Dependencies>
完成标准：<Acceptance checklist>
验证命令：<Commands>

先输出不超过 8 步的实现计划并核对依赖；随后只在任务范围内实现。
每完成一个可验证增量就运行局部测试。结束前运行全部验收命令、检查 git diff、
说明风险和未完成项。若合同含糊、需要真实凭证、改动预计超过 1000 行、
或必须修改未授权路径，立即停止并报告，不要自行扩大范围。
```

# 12. 建议的第一批执行顺序

```text
Wave 1: P0-GOV-01
Wave 2: P0-CON-01 || P0-RT-01
Wave 3: P0-STO-01 || P0-RT-02 || P0-SEC-01
Wave 4: P0-STO-02
Wave 5: P0-HAR-01
Wave 6: P0-RES-01
Wave 7: P0-GATE-01
```

Phase 0 通过后，再将 Phase 1 按四条并行泳道推进：

```text
A 控制平面：Contracts -> Session -> Event Store -> Scheduler -> Recovery -> Harness
B 执行安全：Runtime -> Worktree -> Policy -> Tools -> Approvals
C 智能能力：Model Gateway -> Guidance -> Context Compiler -> Compaction
D 产品质量：CLI/API -> Trace -> Fixtures -> Eval -> E2E -> Release Gate
```

# 13. 参考依据

本计划基于项目最终架构文档，并吸收当前 Codex 官方实践：复杂任务先计划；使用 `AGENTS.md` 固化仓库规则与完成定义；每个目标应明确不应修改的范围、验证方式和停止条件；多人/多 Agent 协作应由项目经理式角色生成 `REQUIREMENTS.md`、`TEST.md`、`AGENT_TASKS.md`，以文件和 Gate 管理交接；独立工作使用 Worktree 隔离。

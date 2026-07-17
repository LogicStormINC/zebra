# Issue #129 架构整改与延期实施计划

## 1. 文档状态

- GitHub Issue：`#129 Architecture follow-up: hard sandbox, ACP adapter, and optional code intelligence`
- 决策：整改项进入仓库任务计划，当前只完成规划，不进入实现
- 当前实施状态：三个工作流均为 `Locked`
- 启动条件：维护者明确要求启动，并按依赖顺序将对应任务改为 `Ready`
- 任务注册表：`docs/AGENT_TASKS.md` 的 `Issue #129 Deferred Architecture Plan`

本文件是 Issue #129 后续实施的持久化依据。它不声明 hard sandbox、
ACP 或代码智能已经实现，也不改变当前产品的安全能力说明。

## 2. 背景与整改原因

Zebra Agent 已具备 durable session event store、无状态 Harness、Typed Tool
Gateway、Policy/HITL、恢复机制和通用上下文编译能力，但仍存在三个目标架构
差距：

1. 本地命令执行仍不等同于内核或容器强制的安全边界；
2. ACP 仍是目标入口协议，尚无适配器；
3. 上下文编译已有确定性文件扫描与检索，但没有可选的语义代码导航。

这些差距不阻塞当前本地优先产品继续迭代，因此采用“先形成可执行计划、后按需
启动”的策略。任何后续实现都必须复用现有 durable Session/Event、Policy、
Tool Gateway、RuntimePort 和 Context Compiler 边界，不能另建状态权威或绕过
审批路径。

## 3. 整改目标

- 将三个架构差距拆成独立任务、分支、Owned paths、验收和验证命令；
- 固定依赖顺序，避免同时修改 runtime、入口协议和 context 造成边界冲突；
- 明确当前延后状态与启动门槛，避免路线图条目被误读为现有能力；
- 保留 Zebra Agent 的通用执行型产品定位，代码能力始终为可选能力；
- 让 GitHub Issue 可以在计划落入主线后关闭，后续执行状态以任务注册表为准。

## 4. 总体依赖顺序

```text
ARCH-129-PLAN-01
  -> ARCH-129-RT-01   Hard-Enforced Local Runtime
       -> ARCH-129-ACP-01  ACP Entry Adapter
       -> ARCH-129-CTX-01  Optional Code Intelligence
```

顺序约束：

- hard runtime 先建立真实执行边界，避免 ACP 扩大未隔离的执行入口；
- ACP 复用已经稳定的 Session/Event、Policy 和 Tool Gateway；
- ACP 与 code intelligence 在 hard runtime 合入后可分别排期；code intelligence
  不依赖 ACP，但其 language-server 子进程必须服从新的 runtime 边界；
- code intelligence 先用 eval 证明收益，再考虑扩大语言或索引范围；
- 三项不得合并到同一分支或 PR；
- 当前均不占用任何活跃 phase 或任务，不能在没有显式启动决定时自行解锁。

## 5. 工作流一：Hard-Enforced Local Runtime

### 5.1 目标

在 `RuntimePort` 后增加 OS sandbox 或 rootless container 实现，使显式请求的
限制配置由操作系统或容器边界强制执行；无法建立边界时必须 fail closed。

### 5.2 预定范围

- 保留现有 Event Store、Tool Gateway、Policy、审批、凭证和网络契约；
- 持久化有效 sandbox profile 与可恢复 runtime handle；
- 恢复时禁止静默扩大文件、进程、网络或凭证权限；
- 凭证留在 sandbox 外，只通过受限能力暴露；
- 明确 macOS 与 Linux 的执行和限制差异。

### 5.3 验收标准

- 越界读写由内核或容器拒绝，而非仅靠 Python 路径检查；
- 子进程不能继承未授权的文件描述符、环境、凭证或权限，也不能通过 shell
  逃逸扩大权限；
- 显式请求 sandbox 但平台无法执行时，任务在运行前失败；
- timeout、cancel、snapshot、restore 保持确定性；
- resume 使用不宽于原会话的有效 profile；
- 网络默认拒绝，并有可重复的允许/拒绝测试。

### 5.4 验证要求

- 聚焦 runtime/security 测试；
- Linux rootless-container 或 OS sandbox 集成测试；
- macOS 能力矩阵和 fail-closed 测试；
- `make test`、`make check`、eval gate、file-size gate；
- 更新架构文档第 18 节安全威胁模型、operator runbook 和架构状态说明。

### 5.5 非目标

- Kubernetes sandbox orchestration、warm pool 或多租户调度；
- 新凭证系统、远程执行服务或任意网络代理；
- 通过字符串黑名单把宿主机 subprocess 宣称为 hard sandbox。

## 6. 工作流二：ACP Entry Adapter

### 6.1 目标

把 ACP 会话生命周期和流式交互映射到现有 Zebra Session API 与事件流，提供
IDE/客户端入口，但不引入第二套会话状态机或授权路径。

### 6.2 预定范围

- 映射 session create/attach、stream、tool progress、approval、clarification、
  cancel、suspend 和 resume；
- 使用 durable sequence checkpoint 支持 reconnect 与 replay；
- 所有动作继续经过现有 Policy、Tool Gateway、MCP allowlist 和材料来源校验；
- ACP 协议类型只存在于 composition/integration 层。

### 6.3 验收标准

- 客户端断开后能从持久 sequence 恢复且不重复执行已完成工具；
- approval、clarification 和 cancellation 与 API/CLI 行为一致；
- ACP 无法调用未注册、未授权或未批准的工具；
- append-only Session Event Store 仍是唯一 durable authority；
- adapter 重启不丢失可恢复会话状态。

### 6.4 验证要求

- protocol mapping 和 replay/resume 合同测试；
- approval/clarification/cancel 的端到端测试；
- 未授权工具与 MCP capability 的拒绝测试；
- `make test`、`make check`、eval gate、file-size gate；
- 对适用客户端做至少一条真实连接验收。

### 6.5 非目标

- 把 ACP 变成授权系统或 durable transcript authority；
- 在 `agent-core` 引入协议 SDK 类型；
- 同时建设新的 IDE、远程 Agent 协议或 A2A 系统。

## 7. 工作流三：Optional Code Intelligence

### 7.1 目标

为 coding profile 增加受限、可选的 Tree-sitter/LSP 语义导航适配器，用于
definitions、references、symbols 和 diagnostics；非 coding 任务不依赖该能力。

### 7.2 预定范围

- 首版只支持少量明确列出的语言；
- 所有结果携带 provenance、trust、文件范围和截断信息；
- 设置文件数、字节数、时间、结果数和并发上限；
- 不可用或超限时退回现有确定性文件 list/search/read 路径；
- 索引只作为派生数据，不成为项目状态权威。

### 7.3 验收标准

- definitions、references、symbols、diagnostics 返回稳定且有来源的结果；
- 超时、取消、过大仓库、损坏索引和语言服务失败均有确定性降级；
- `agent-core` 不依赖 Tree-sitter、LSP SDK 或索引实现；
- general profile 与固定 Research child 不被隐式扩权；
- 代表性仓库 eval 相比 lexical baseline 有可量化改善，否则不扩大范围。

### 7.4 验证要求

- 小型多语言 fixture 的确定性合同测试；
- bounds、cancel、failure 和 fallback 测试；
- lexical 与 semantic context selection 对照 eval；
- `make test`、`make check`、eval gate、file-size gate；
- 更新 Context Compiler 文档和 operator 能力说明。

### 7.5 非目标

- 默认全仓库常驻索引或向量数据库；
- 未测量收益前引入 embedding、reranker 或多仓库图；
- 让 code index 直接修改代码、授予工具权限或成为 durable state。

## 8. 激活与延期规则

三个实施任务当前统一遵守以下规则：

1. `Status` 保持 `Locked`，`Owner` 保持 `Unassigned`；
2. 维护者明确选择该架构工作后，由维护者指定的拟认领人提交独立 planning
   PR，将一个任务改为 `Ready`，并由 TL 与 Security/RUNTIME 相关 reviewer
   审核；
3. 启动前重新核对最新 `main`、平台能力、依赖版本和安全威胁模型；
4. planning PR 必须补充实际 owner、branch、精确 Owned paths、实现选型、支持
   矩阵、fixture/eval 位置、量化阈值和可直接执行的验证命令；
5. 前置任务未合并到 `main` 时，后续任务不得开始；
6. 若产品优先级变化，可继续延期，不需要创建占位实现或伪能力开关。

## 9. 交付与关闭策略

- 本规划通过独立文档 PR 合入后，Issue #129 的“规划与分诊”职责完成；
- GitHub Issue 可关闭，关闭评论必须说明三项实现尚未完成且已转入任务注册表；
- 未来进度以 `docs/AGENT_TASKS.md` 中 RT、ACP、CTX 三个实施任务为准；
- 只有各任务自己的验收全部勾选并分别合入 PR，才可在产品文档中把目标能力
  标记为已实现；
- `PROGRESS.md` 只记录本次“计划已建立、实现已延期”，不得记录功能完成。

## 10. 重新评审触发条件

出现以下任一情况时，应重新评审并考虑解锁：

- 宿主机执行风险阻塞生产或更高信任等级使用场景；
- 明确的 IDE/ACP 客户端接入需求进入近期里程碑；
- lexical context 在代表性 coding eval 中成为可测量的主要失败原因；
- 平台、依赖或安全要求变化使原验收矩阵需要更新；
- 维护者主动提升 Issue #129 相关工作的优先级。

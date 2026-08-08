# ADR-015：FinOS Personal Investment OS Runtime Integration Boundary

- 状态：Accepted / Next-stage contract
- 日期：2026-08-08
- 适用分支：`codex/finos-runtime-next`
- 对应 FinOS：`codex/finos-next`
- 决策范围：Zebra Runtime 如何支撑 Personal Investment OS，不扩大 Zebra 业务边界

## 1. 背景

FinOS 将 Zebra 作为 Agent Runtime 使用。下一阶段目标从“让 Agent 能完成一次金融任务”转向“持续积累用户金融世界并改善后续判断”。

这要求明确区分：

- Zebra Runtime Memory；
- FinOS Investor Knowledge；
- FinOS Core Truth；
- User Configuration。

这些对象都会影响未来 Agent 使用体验，但它们不是同一种数据，也不能共享生命周期。

## 2. 决策

Zebra 继续保持 Agent Runtime 定位：

```text
Zebra = Agent execution runtime
FinOS = Financial domain environment
```

Zebra 负责：

- Task / Conversation / Session / Attempt / Event 生命周期；
- reasoning runtime；
- context management；
- tool selection and execution boundary；
- runtime memory；
- Artifact runtime contract；
- streaming、resume、audit 和 usage evidence。

FinOS 负责：

- 金融事实；
- owner/account 业务模型；
- Journal、Core、Review、Thesis、Decision、Investor Knowledge；
- business authorization；
- Controlled Ingestion；
- 用户确认后的业务写入。

Zebra 不成为金融数据库，也不成为投资知识库。

## 3. Memory Boundary

### 3.1 Zebra Runtime Memory

Zebra memory 只能表达 Agent runtime 需要的信息，例如：

- 对话连续性；
- Task history；
- runtime context；
- 工具执行经验；
- 通用 Agent 行为记忆。

它不能代表：

- 用户拥有多少股票；
- 用户投资理念；
- 用户长期风险偏好；
- 用户认可的交易规则；
- 某次分析后的长期结论。

### 3.2 FinOS Investor Knowledge

金融领域长期知识由 FinOS 管理：

- Investment Thesis；
- Decision Record；
- confirmed correction；
- user-confirmed investment rule；
- Review feedback。

Zebra 可以读取 FinOS 提供的 typed capability，但不能把 runtime memory 自动同步为 Investor Knowledge。

### 3.3 Core Truth

Core 保存金融事实：

- account；
- cash；
- transaction；
- position；
- snapshot。

Core 只能通过 FinOS Controlled Ingestion 写入。

Zebra 的回答、Skill 输出、Review Artifact 和 Memory 都不能直接改变 Core。

## 4. Runtime Integration Contract

FinOS -> Zebra：

- stable Task creation；
- owner-scoped authority；
- namespace；
- approved tool/Skill grants；
- immutable attachments/resources；
- typed read capability；
- domain contract。

Zebra -> FinOS：

- durable Task/Event state；
- final message identity；
- Artifact output contract；
- runtime usage evidence；
- clarification/approval lifecycle。

禁止：

- FinOS 解析 Zebra final 文本决定业务写入；
- Zebra 直接访问 FinOS database；
- Zebra memory 写入 Core 或 Investor Knowledge；
- FinOS 维护第二套 conversation/task memory。

## 5. Skill 使用边界

Financial Skill 是 capability provider，不是 workflow controller。

Skill 可以声明：

- domain knowledge；
- input/output schema；
- required capability；
- evaluation requirement。

Skill 不可以：

- 获得 Core write authority；
- 强制 Zebra 推理步骤；
- 把模型推断自动升级为用户长期知识；
- 绕过 typed command 和 approval。

## 6. Artifact 与长期知识

Zebra 产生的 Artifact 是分析产物，不自动成为事实。

例如：

```text
Review Artifact
      |
      | user confirmation
      v
Investor Knowledge
```

而不是：

```text
Zebra output
      |
      v
automatic memory/Core write
```

任何业务对象生命周期由 FinOS 管理。

## 7. 下一阶段支持重点

Zebra Runtime 需要优先保证：

1. durable Task 稳定；
2. typed artifact contract 稳定；
3. context/resource access 边界稳定；
4. runtime memory 与业务知识隔离；
5. usage/audit evidence 完整。

不进入 Zebra：

- 金融对象模型；
- 投资知识生命周期；
- 账户同步；
- Review 产品流程；
- 用户登录体系；
- 订阅和商业化。

## 8. Read Path Principle

业务系统列表性能问题不得通过让 Zebra replay 全部历史解决。

Zebra Event Store 是 runtime 事实源，但：

- durable projection 优先服务常规读取；
- event replay 用于恢复、审计和修复；
- 详情页可以触发惰性补偿；
- 列表页不能为了少量异常记录扫描所有历史。

该原则与 FinOS projection/reconciliation 设计保持一致。

## 9. 架构不变量

1. Zebra 是 Agent Runtime，不是 Financial OS。
2. FinOS 是金融领域环境，不是 Agent Brain。
3. Runtime Memory、Investor Knowledge、Core Truth、Configuration 四层隔离。
4. Agent 输出不是业务事实，必须经过明确 typed boundary。
5. 用户确认是长期金融知识形成的必要条件。
6. Skill 增加能力，不增加权限。
7. Event Store 是 Runtime 事实源，但不是业务数据库。
8. 下一阶段扩展保持 API、Event、Authority 和 Artifact contract 可版本化。

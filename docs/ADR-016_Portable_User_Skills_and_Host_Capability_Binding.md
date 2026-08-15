# ADR-016：Portable User Skills 与 Host Capability Binding

- 状态：Accepted / Next-stage contract
- 日期：2026-08-08
- 适用分支：`codex/finos-runtime-next`
- 上游：`ADR-014_扩展体系架构.md`
- FinOS 配套：`docs/finos-zebra-typed-capability-and-portable-skill-contract-2026-08-08.md`

## 1. 背景

Zebra 已经把 Skill 定义为扩展组件，并具有 Available → Installed → Enabled → Granted → Approved 的控制面模型。

下一阶段需要补充一个此前未明确写死的不变量：

> Skill 必须是 runtime extension，而不是某个业务宿主的私有 workflow package。

这尤其影响 FinOS Review Skill v4 和未来 user-provided Skill。FinOS 可以提供很强的金融数据/Artifact/Knowledge 能力，但这些能力不能成为 Skill package 自身的唯一运行条件。

## 2. 决策

Zebra 正式采用三层模型：

```text
Portable Skill Core
        |
        v
Host Capability Binding
        |
        v
Granted concrete tools/resources
```

业务持久化另走宿主自己的 typed boundary：

```text
Skill output
   -> Zebra final / Artifact candidate
   -> explicit host action
   -> host persistence adapter
```

Skill 不拥有宿主数据库、业务对象或写入权限。

## 3. Skill 来源不是 Skill 类型

下列来源都属于同一种 Zebra Skill component：

- bundled/system；
- user-provided/private；
- repo-installed；
- operator-installed；
- future registry/marketplace。

来源只影响 provenance、信任策略、默认 enablement 和管理权限，不改变 runtime contract。

禁止引入：

```text
FinOSSkill
UserSkillLite
SystemSkillPrivileged
```

这类通过类型本身获得不同业务 authority 的特殊执行路径。

## 4. 五层状态机保持一致

ADR-014 的状态机对全部 Skill 来源统一适用：

```text
Available -> Installed -> Enabled -> Granted -> Approved
```

### Available

来源可不同，但 metadata/provenance 必须可识别。

### Installed

固定 version/digest。运行中 Task 不追“最新版”。

### Enabled

user/repo/namespace 的选择只是可用状态，不代表 Task 有权限。

### Granted

TaskPreparedPayload 或后续等价 durable grant 保存精确 component identity。只有 Granted Skill 对当前 Task 可见。

### Approved

有副作用动作仍走 Policy / Approval / HITL。Skill 来源不能跳过。

## 5. Portable Skill Core

Portable Skill Core 只包含：

- procedural/domain guidance；
- input/output semantics；
- domain validation rules；
- missing-data behavior；
- optional capability needs；
- eval fixtures/references。

它不能以宿主实现细节作为专业方法的一部分。

硬性禁止：

- require a concrete host database；
- require private host module import；
- require fixed host HTTP path；
- require host filesystem layout；
- require host secret/env；
- assume host user/tenant identifiers from prompt；
- call host persistence directly；
- treat host-specific tool names as universal Skill API。

## 6. Host Capability Binding

Skill 可以表达它需要的语义输入/能力，例如：

```text
portfolio_positions
transaction_history
trade_journal
market_data
previous_reviews
```

这些只是 **semantic roles**。

Host Binding 负责把 role 映射到当前 Task 已经拥有的 concrete tool/resource/attachment。

例如：

```text
portfolio_positions
   -> provider A resource
```

或：

```text
portfolio_positions
   -> FinOS typed read
```

或：

```text
portfolio_positions
   -> uploaded CSV attachment
```

核心 Skill 不需要知道 provider 品牌。

## 7. Binding 不赋权

这是最重要的安全约束之一：

```text
Skill requirement != authority
Binding != authority
```

真实上界仍是：

```text
external caller authority
   ∩ Zebra service/policy limits
   ∩ Task granted concrete components/tools/resources
```

Host Binding 只能从这个集合中做语义映射，不能凭 Skill metadata/body 增加新能力。

如果 role 没有可用 binding：

- 返回 unavailable/missing；
- 允许 Skill 使用已经提供的等价 attachment；
- 允许 Agent 询问用户；
- 不自动扩大工具集合。

## 8. Binding 的 durable 语义

在需要可复算/审计的 Task 中，最终实际使用的 concrete input 必须能通过 Event/Artifact/input manifest 追溯。

不要求 Event Store 把所有业务数据复制进 Zebra；保存：

- stable component identity；
- granted capability/tool/resource identity；
- opaque host refs/digests；
- runtime event lineage。

业务对象的具体版本与内容仍由 host 负责。

## 9. System Skill 与 User Skill 的权限一致性

系统 Skill 不能因为“官方内置”而自动获得：

- unrestricted tools；
- Core write；
- hidden credentials；
- background persistence；
- cross-namespace read。

用户 Skill 也不必被实现成只能处理纯文本的二等组件。

如果当前 Task 明确 Granted 某个只读金融能力，一个 user Skill 可以在同样 Policy 下使用；如果没有 Grant，system Skill 也不能使用。

## 10. Host Persistence Boundary

Zebra Skill output 可以成为：

- natural-language final；
- generic Artifact；
- typed output contract payload。

但业务持久化属于宿主：

```text
Zebra Skill output
      |
      v
host validates user intent / business authority
      |
      v
host typed persistence command
```

Zebra 不因为某个 Skill 名称是 `review`、`journal` 或其它业务名字，就调用外部数据库。

## 11. FinOS Review Skill v4 作为验收案例

Review Skill v4 必须是本 ADR 的参考验收 Skill，而不是例外。

正确分层：

```text
portable stock review core
        +
optional market profiles
        +
portable evidence/output contract
```

FinOS 只提供：

```text
FinOS host binding
FinOS business save adapter
```

因此：

- 没有 FinOS API 时，Review 核心仍能处理用户提供的交易日志/持仓/成交数据；
- A 股规则属于 market profile，不属于 FinOS binding；
- `investment_review` 属于 FinOS business artifact mapping，不是 portable Skill 的 runtime identity；
- user-provided Review Skill 可以在同一 Task/Artifact 安全边界中工作。

## 12. Market Profile 与 Host Adapter 的区别

两者不可混淆。

### Market Profile

描述业务/市场事实，例如：

- A 股 T+1；
- 最小交易单位；
- 涨跌停；
- 印花税/交易费用假设；
- 港股/美股不同制度。

它可以随 Skill 一起分发，因为这是专业知识。

### Host Adapter/Binding

描述：

- 这个 host 的什么 resource/tool 提供 positions；
- 什么 output 可以由 host 保存为什么业务对象；
- 当前 owner/namespace 被授权哪些数据。

它不属于 Skill 专业核心。

## 13. User-provided Skill 是一等架构能力

未来用户可以引入自己的 Skill，Zebra runtime 必须支持它作为正常 component，而不是特殊兼容模式。

最低要求：

- immutable version/digest；
- provenance；
- enable/disable；
- Task grant；
- requested vs granted capability 可检查；
- Policy/Approval；
- revocation；
- audit；
- no implicit privilege elevation。

User Skill 的内容仍是不可信 procedural input；被用户安装不意味着内容安全或有权访问所有数据。

## 14. FinOS 当前 UserSkillStore 的解释

FinOS 目前存在自己的 user-skill persistence 与 FinOS-specific capability vocabulary。该实现可以在迁移期继续工作，但从本 ADR 起不能被解释为 Zebra 的跨宿主 Skill 标准。

目标 source of truth：

- Zebra：Skill Installed / Enabled / Granted runtime state；
- Host（如 FinOS）：业务 principal、entitlement、domain capability 上界；
- Task：两者交集后的 durable runtime grant。

FinOS 可以提供 Skill 管理 UI/projection，但不能建立第二个与 Zebra 状态冲突的 runtime lifecycle。

## 15. Capability metadata 的演进原则

未来如果需要把 semantic role 形式化为 metadata/schema：

- 字段必须 optional / backward-compatible；
- role 不等于 tool name；
- role 不产生 authority；
- runtime 不因为 role 自动发现/调用未经 grant 的工具；
- existing Skill v1/v2 package 仍可运行；
- concrete host binding 不能成为 portable package 的 mandatory identity。

在没有正式 schema 之前，可以先通过 Skill body/reference 声明 input roles，避免为了 v4 立即引入新的 runtime EventType/Registry schema。

## 16. Provenance

Task/Artifact 至少应能追溯：

```text
skill source/publisher
skill name
version
digest
Task grant identity
```

`system/user/third_party` 只用于 provenance/trust UI，不能决定业务事实等级。

## 17. 可移植性测试

一个声明 portable 的 Skill 至少通过：

### Test A — No-host-private dependency

静态检查核心 Skill/reference 不要求私有 host DB/module/API/path。

### Test B — Attachment-only

不给任何 host-specific tool，仅给等价的 user attachments，核心任务仍可在数据覆盖范围内执行。

### Test C — Alternate host

换一个 host binding，核心 Skill 不修改即可执行。

### Test D — Capability denial

一个 role 没有对应 grant 时，Skill 正确降级/说明缺失，不能绕过。

### Test E — User/system parity

同样 Task grant 下，system Skill 与 user Skill 的 tool visibility/policy 规则一致。

### Test F — Persistence isolation

Skill 能输出 Artifact candidate，但没有 host typed command 时不能产生业务持久化副作用。

## 18. 非目标

本 ADR 不立即要求：

- 公共 Marketplace；
- 远程 Skill registry；
- 通用行业 capability ontology；
- 自动把所有旧 FinOS user skills 迁移到 Zebra；
- 删除当前兼容表；
- 为 v4 新建 Plugin system；
- 让 Skill 自己管理 OAuth/credential。

这些都可以后续增量实现，不影响本次可移植性边界成立。

## 19. 架构不变量

1. Skill 是 Zebra runtime extension，不是 FinOS 私有 workflow。
2. System/User/Third-party Skill 使用同一 runtime component model。
3. Skill package 来源只影响 provenance/trust，不直接赋权。
4. Portable Skill Core 不依赖 concrete host persistence/API/DB。
5. Host Capability Binding 只映射已 Granted 能力，不创造 authority。
6. Host business write 必须经 host typed boundary 与用户业务意图。
7. FinOS 可以深度集成 Skill，但不能成为 Skill 标准的唯一宿主。
8. Review Skill v4 必须能在非 FinOS 环境用等价输入运行核心 Review。
9. Market-specific rules 属于 domain profile，不等于 host adapter。
10. User-provided Skill 是一等能力，但仍是不可信内容并受相同 Policy 约束。
11. Event Store 记录 runtime lineage，不复制宿主业务数据库。
12. 当前兼容实现不得阻止未来统一到 Zebra extension state。

## 20. 实施门槛

Review Skill v4 或新的 portable Skill 开始编码前：

- FinOS 与 Zebra 两边都引用本 ADR/配套合同；
- 写 portability red tests；
- 明确 portable core 与 FinOS binding 的文件/模块边界；
- 不先用更多 FinOS-specific capability 字段扩展 Skill package；
- 不修改稳定部署分支。
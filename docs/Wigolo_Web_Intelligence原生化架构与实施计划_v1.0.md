# Wigolo Web Intelligence 原生化架构与实施计划 v1.0

## 1. 文档状态

- 规划任务：`WEB-INT-PLAN-01`
- 上游项目：`KnockOutEZ/wigolo`
- 审计基线：`main@bc229d1f9060590cb8e3a119b2651277e46f3ae5`
- 上游版本：`v0.2.0`，公开 Beta
- 当前决策：方案进入 Zebra 任务计划，实施任务保持 `Locked`
- 启动条件：维护者显式选择一个 `Locked` 任务，将其改为 `Ready`，指定
  owner、reviewer、branch、worktree 和最终 Owned paths

本文是将 wigolo Web Intelligence 能力转化为 Zebra Agent 原生能力的持久化
设计依据。本文合入只代表架构、边界、任务和验收已建立，不代表任何新增 Web
能力已经实现、部署或对模型开放。

## 2. 背景与结论

wigolo 不只是十个 MCP Tool。其上游实现同时包含多搜索引擎聚合、HTTP 与
Playwright 分级抓取、爬虫、结构化抽取、本地全文和向量缓存、研究编排、变更
监控、Webhook、插件、健康检查、CLI、REST、SDK 和 MCP 入口。

Zebra 已有 `web.search`、`web.fetch`、MCP stdio、Typed Tool Gateway、Policy/
HITL、Network Profile、Credential 边界、Artifact、durable Tool Run、Harness、
Worker 和 Model Gateway。最小且边界正确的方案不是复制 wigolo，也不是让模型
长期调用 `mcp.wigolo.*`，而是：

1. Zebra 定义稳定的 `web.*` 原生 Tool 和 Workflow 合同；
2. 首期把未修改、固定版本的 wigolo 进程作为可替换执行 Provider；
3. Zebra 继续拥有 Policy、凭证、事件、Artifact、模型调用和持久调度；
4. 只有经过真实使用和 Eval 证明有必要的底层能力，才考虑 clean-room 替换；
5. wigolo 不成为 Session、Task、Agent Memory、安全或授权的事实源。

### 2.1 “原生能力”的判定

满足以下全部条件才可称为 Zebra 原生能力：

- 模型发现的是稳定的 `web.*` 合同，而不是 `mcp.wigolo.*`；
- 工具名、参数、结果、错误和 Artifact 合同由 Zebra 版本化；
- 每次执行经过 Zebra Policy、审批、Egress、预算和审计；
- Provider 可以替换，替换后模型侧合同和 durable state 不变化；
- 完整结果进入 Zebra Artifact，模型只看到有界、可验证的投影；
- 研究综合只经过 Zebra Model Gateway；
- Watch 由 Zebra durable scheduler 执行，不依赖前台工具调用触发。

仅把 wigolo 配入现有 MCP allowlist 可以立即使用能力，但属于外部 MCP 能力，
不满足以上原生化口径。

## 3. 上游能力审计

审计资料固定到以下上游引用，后续激活任务时必须重新核验：

- 仓库：<https://github.com/KnockOutEZ/wigolo>
- 工具合同：<https://github.com/KnockOutEZ/wigolo/blob/bc229d1f9060590cb8e3a119b2651277e46f3ae5/docs/tools.md>
- 安全说明：<https://github.com/KnockOutEZ/wigolo/blob/bc229d1f9060590cb8e3a119b2651277e46f3ae5/docs/privacy-security.md>
- Watch 实现：<https://github.com/KnockOutEZ/wigolo/blob/bc229d1f9060590cb8e3a119b2651277e46f3ae5/src/watch/scheduler.ts>
- 许可证：<https://github.com/KnockOutEZ/wigolo/blob/bc229d1f9060590cb8e3a119b2651277e46f3ae5/LICENSE>

### 3.1 十项 Tool 能力

| wigolo Tool | 主要能力 | Zebra 原生目标 |
|---|---|---|
| `search` | 多查询、多引擎、时间/域名过滤、rerank、引用和新鲜度 | 扩展 `web.search` |
| `fetch` | HTTP/浏览器分级、SPA、PDF、section、截图和 actions | 扩展 `web.fetch`，交互动作单独分类 |
| `crawl` | BFS/DFS/sitemap/map、robots、限速和去重 | 新增 `web.crawl` |
| `extract` | selector、table、metadata、JSON-LD、named/custom schema | 新增 `web.extract` |
| `cache` | FTS/向量检索、统计、清理和变化复查 | 拆分 `web.cache.*` 原子工具 |
| `find_similar` | 关键词、向量和实时 Web 融合 | 新增 `web.find_similar` |
| `research` | 问题分解、检索、抓取、综合和引用 | Zebra `web.research` Workflow |
| `agent` | 自主 plan/search/fetch/extract/synthesize | Zebra `web.gather` 高层 Workflow Tool |
| `diff` | 文本或缓存页面差异 | 新增 `web.diff` |
| `watch` | 创建、检查、暂停、恢复、删除和 Webhook | Zebra Durable Watch 子系统 |

### 3.2 非 Tool 能力

- MCP Resource 使用说明转化为 Zebra 自有 Skill/Operator 文档，不复制上游文案；
- `doctor`、`warmup`、`tune` 转化为 operator/CLI 能力，不暴露给模型；
- 浏览器、模型和 native module 下载必须进入 Zebra Setup Phase，固定版本并校验
  摘要，不允许首次 Tool Call 隐式安装；
- CLI、REST、SDK 和 MCP 是 wigolo 的入口面，不在 Zebra 内重复建设；
- 任意代码插件首期禁用，未来只允许经过 Zebra Provider Registry、完整性校验和
  operator 显式安装的扩展。

## 4. 目标架构

```text
Model / Harness
  -> Zebra native web.* Tool contracts
  -> Policy / HITL / Network Profile / Egress
  -> Web Intelligence Gateway
       -> pinned wigolo provider process
       -> future alternate or clean-room provider
  -> Artifact / provenance projection
  -> Event Store / Tool Run / Context

Zebra web.research / web.gather workflow
  -> the same native web.* tools
  -> Zebra Model Gateway

Zebra Durable Watch worker
  -> the same native web.fetch / web.diff capabilities
  -> durable delivery audit
```

### 4.1 分层职责

| 层 | 负责 | 不负责 |
|---|---|---|
| `agent-core` | 必需的稳定领域类型、Watch 状态和 Ports | wigolo、Node、Playwright 或 MCP SDK 类型 |
| `agent-tools` | `web.*` Tool 合同、参数验证、结果规范化和 Provider-neutral transport Protocol | 进程生命周期、持久化和网络实现 |
| `agent-runtime` | Provider transport、sidecar 生命周期、取消和超时 | durable Watch 状态和授权决策 |
| `agent-security` | Policy、Egress、SSRF、动作风险和凭证能力 | 页面解析、搜索排序和结果综合 |
| `agent-storage` | Watch、快照、投递和必要派生索引 | 把 Web cache 变成 Session 权威 |
| `agent-integrations` | 可选 Provider/Model/通知集成 | Tool 业务合同和 Policy 决策 |
| `apps/*` | 配置、依赖组合、API/CLI/Worker 入口 | 核心规则和 Provider 专属领域逻辑 |

### 4.2 Provider 运行方式

首期优先使用受控常驻进程，而不是每次调用重新启动 stdio MCP：

- 固定 wigolo 版本、命令路径和制品 SHA-256；
- 只绑定 loopback，并使用进程级随机 token 或受控 stdio 长连接；
- 独立 data directory，不能读取 Zebra workspace、Session DB 或凭证目录；
- 禁用上游 LLM、telemetry、任意插件、私网访问和自动安装；
- 暴露 health、version、ready、shutdown 和容量信号；
- sidecar 失败返回 Provider failure，不得静默切换到越权实现；
- Provider 输出始终视为不可信外部数据。

`WEB-INT-ADP-01` 只接受 operator 显式提供、版本和摘要已核对的预安装测试制品；
它不负责下载或面向产品的 Setup。`WEB-INT-OPS-01` 在 Adapter 合同稳定后再把
安装、warmup、升级、清理和 SBOM 产品化。两阶段之间不得以首次调用自动下载
填补空白。

现有通用 MCP transport 默认 30 秒调用超时和 32 KiB 输出上限，适合有界 MCP
工具，不足以直接承载 crawl、综合研究和大型证据结果。原生 Provider adapter
必须支持每工具预算、取消、长输出 Artifact 化和健康恢复，不能简单放宽全局 MCP
上限。

## 5. 原生合同设计

### 5.1 Tool 命名

保留已有 `web.search` 和 `web.fetch`，新增：

- `web.crawl`
- `web.extract`
- `web.find_similar`
- `web.diff`
- `web.cache.search`
- `web.cache.stats`
- `web.cache.clear`
- `web.cache.refresh`
- `web.research`
- `web.gather`
- `web.watch.create`
- `web.watch.list`
- `web.watch.check`
- `web.watch.pause`
- `web.watch.resume`
- `web.watch.delete`

不采用单个 `cache(action=...)` 或 `watch(action=...)` 合同。拆分原子工具可以让
只读、删除、联网刷新、调度变更和外部投递分别接受 Policy、审批和 tool profile
控制。

### 5.2 兼容与版本策略

已有 `web.search` 和 `web.fetch` 保持工具名、必需参数和当前文本输出兼容。
首个原生化合同版本只增加可选参数和 `ToolResult.metadata` 中的结构化 Web
信封；调用方不提供新参数时保持当前行为。完整结构化结果进入 Artifact，后续
如需改变必需字段、默认值或输出语义，必须发布新的 `capability_version`、迁移
说明和双版本合同测试，不能原地改变旧调用。

### 5.3 统一结果信封

Web 结果至少包含：

- `provider`、`provider_version`、`capability_version`；
- `fetched_at`、规范化 URL、内容哈希和 MIME type；
- `citations`、source span、freshness 和证据评分（适用时）；
- `truncated`、`degraded`、失败 backend 和预算使用；
- `artifact_uri`、完整输出校验和与模型投影大小；
- `untrusted_external_content=true`；
- 稳定 error code、失败 stage 和可操作但不泄露秘密的 detail。

wigolo 专有诊断字段可以保存在 Provider metadata 中，但不能成为跨 Provider 的
必需模型合同。

### 5.4 Web cache 边界

Web cache 是可删除、可重建的派生证据存储：

- 不替代 Event Store、Artifact、Task、Session 或 Agent Memory；
- 缓存命中必须返回抓取时间、内容哈希、TTL/stale 状态和来源；
- `clear` 是破坏性操作，`refresh` 是外部网络操作；
- 私有或认证内容不得进入跨 namespace 共享缓存；
- Provider 自有数据库的迁移和删除不能影响 Zebra durable execution 恢复。

## 6. 安全与权限边界

### 6.1 Egress 与 SSRF

- Policy 必须按实际 Tool 和目标分类，不能只审批“启动 wigolo”；
- URL 在输入、DNS 解析、连接和每次重定向后重新验证；
- 默认拒绝 localhost、IP literal、私网/链路本地地址、userinfo、非常规端口；
- Search engine、页面目标、代理、Webhook 和模型 Provider 使用不同 capability；
- sidecar 只能通过 Zebra 允许的 Egress 路径联网，不能获得宿主任意网络；
- robots、每域速率、并发、页面数、字节、Token 和时间预算不可由模型放宽。

### 6.2 Browser actions

`web.fetch` 的普通读取、scroll、wait 和 screenshot 可按只读动作评估。`click`、
`type`、认证 profile、下载或任何可能提交状态的动作必须进入独立 Browser
Action 风险分类。无法证明只读时要求审批；交易、发信、发布、删除等外部副作用
不属于本计划默认范围。

### 6.3 凭证与模型

- 首期关闭 wigolo `use_auth`、浏览器 profile 和自有 key store；
- 后续认证抓取只能使用 Zebra Credential Broker 签发的短时、窄 audience、窄
  scope capability；
- 原始 secret 不进入 Tool 参数、日志、Event、Artifact 或 Provider data directory；
- wigolo 内置 `research`、`agent` 和 `search format=answer` 的外部 LLM 路径关闭；
- 所有综合和结构化模型调用经过 Zebra Model Gateway、预算、Trace 和 Eval。

## 7. Research、Gather 与 Watch

### 7.1 Research 与 Gather

wigolo 的检索算法和证据生成可作为 Provider 能力，但其 Agent loop 不能成为
第二套 Harness：

- `web.research` 由 Zebra 分解问题、并行检索、抓取、去重、校验和综合；
- `web.gather` 是模型可调用的高层 Workflow Tool：合同和模型披露位于
  `agent-tools`，编排位于 Zebra Harness/Runtime；可选 Skill 只能指导使用，
  不能定义另一套执行语义；
- 两者复用原生 `web.*`，支持取消、恢复、Artifact 和 durable event；
- 模型切换、重试和停止条件仍由 Zebra 决定；
- Provider 返回的 raw brief 可以作为不可信证据，不能覆盖系统指令或 Policy。

### 7.2 Durable Watch

上游 Watch 当前是进程内 best-effort：其他 Tool Call 才触发 overdue 检查，
Webhook 没有 durable retry/queue，selector 也尚未真正参与 diff。Zebra 不能把该
实现包装成生产级原生 Watch。

Zebra Watch 必须具备：

- durable `WatchJob`、`WatchCheck`、`ChangeSnapshot` 和 `DeliveryAttempt`；
- Worker lease、幂等键、重试、退避、暂停、恢复和删除状态；
- 无前台请求时仍能按计划执行；
- 每次执行重新做 Policy、SSRF、网络 profile 和 capability 校验；
- 保存前后内容哈希、完整快照或可验证引用，以及 Diff Artifact；
- Webhook 目标审批、签名、redirect 拒绝、SSRF 防护和 delivery audit；
- Worker/Provider/API 重启不丢任务、不重复检查、不重复投递。

## 8. 许可证与供应链

wigolo 使用 AGPL-3.0。本计划不是法律意见；实施或分发前必须完成项目适用的
许可证审查。默认工程规则：

- 不复制、翻译或机械移植 wigolo 源码到 Zebra；
- 首期只调用未修改、独立分发的上游进程；
- 保留上游许可证、NOTICE、版本、制品来源和校验和；
- 若修改 wigolo、分发组合制品或提供网络服务，先停止并重新评审义务；
- clean-room 实现只依据公开行为合同和 Zebra 自有测试，不参考性复制源码；
- 自动升级关闭，升级通过独立任务、合同矩阵和安全回归。

供应链验收还包括 Node/runtime、Playwright/browser、native modules、本地模型和
可选 sidecar 的版本固定、摘要验证、SBOM、离线安装与清理说明。

## 9. 任务拆解与依赖

```text
WEB-INT-PLAN-01
  -> WEB-INT-CON-01
       -> WEB-INT-ADP-01
       -> WEB-INT-SEC-01
            -> WEB-INT-TOOLS-01
                 -> WEB-INT-CACHE-01
                 -> WEB-INT-BROWSER-01
                 -> WEB-INT-ORCH-01
                 -> WEB-INT-OPS-01
                 -> WEB-WATCH-CORE-01
                      -> WEB-WATCH-STO-01
                           -> WEB-WATCH-WRK-01
                                -> WEB-WATCH-SURF-01
  -> WEB-INT-E2E-01
     (等待 Cache、Browser、Orch、Ops、Watch Surface 全部合入)
```

任务状态、owner、branch 和 Owned paths 以 `docs/AGENT_TASKS.md` 为唯一执行
依据。本文中的依赖图不能自行解锁任务。依赖图表达能力依赖，不等于允许共享
路径并行开发；共享 `agent-tools`、`agent-runtime` 或 `agent-security` 的 sibling
卡不得同时进入 `In Progress`。激活后一张卡前必须先合入前一张共享路径卡，或
在 planning PR 中进一步缩窄 Owned paths。

### 9.1 阶段交付

| 任务 | 交付边界 | 初始状态 |
|---|---|---|
| `WEB-INT-PLAN-01` | 本文、任务卡、进度和 docs 索引 | `Review` |
| `WEB-INT-CON-01` | 原生合同、结果信封和 Provider Protocol | `Locked` |
| `WEB-INT-ADP-01` | 固定版本 sidecar、transport、health、cancel | `Locked` |
| `WEB-INT-SEC-01` | Policy/Egress/SSRF/action/credential 边界 | `Locked` |
| `WEB-INT-TOOLS-01` | 只读检索、抓取、爬取、抽取、相似、diff、cache | `Locked` |
| `WEB-INT-CACHE-01` | cache clear/refresh、保留和 namespace 边界 | `Locked` |
| `WEB-INT-BROWSER-01` | 受控 actions、截图和认证浏览 capability | `Locked` |
| `WEB-INT-ORCH-01` | Zebra-native research/gather | `Locked` |
| `WEB-INT-OPS-01` | Setup、health、warmup、tune、升级和清理 | `Locked` |
| `WEB-WATCH-CORE-01` | Watch 领域状态和 Ports | `Locked` |
| `WEB-WATCH-STO-01` | SQLite durable stores 与 migration | `Locked` |
| `WEB-WATCH-WRK-01` | 调度、lease、幂等、重试和投递 | `Locked` |
| `WEB-WATCH-SURF-01` | API/CLI/Desktop/operator parity | `Locked` |
| `WEB-INT-E2E-01` | 合同矩阵、真实 sidecar、安全和产品 E2E | `Locked` |

## 10. 验收标准

### 10.1 Contract 与功能

- 十项上游用户能力都有 Zebra Tool 或 Workflow 映射；
- 模型侧不需要了解 wigolo 名称、MCP server 或 Provider 配置；
- 全部输入有大小、数量、格式和互斥字段校验；
- 大输出保留完整 Artifact，模型投影可验证且明确标记截断；
- Provider failure、degraded、cache stale 和 partial result 不伪装成成功空结果；
- 更换 test double 或 alternate Provider 时原生合同测试保持通过。

### 10.2 Security 与 Recovery

- SSRF fixture 覆盖 redirect、DNS rebinding、IP、localhost、private range、
  userinfo、port 和 Webhook；
- 未审批 Browser action、cache clear、Watch mutation 和外部投递被拒绝；
- secret scan 证明凭证不进入事件、日志、Artifact、SQLite 和 Provider 目录；
- timeout、cancel、sidecar crash、Worker restart 和数据库重开行为确定；
- Watch 不重复检查或投递，失败有 durable retry 和最终状态；
- Provider 不能修改 Policy、tool profile、Session state 或系统指令。

### 10.3 Eval 与发布

- 固定 HTML、PDF、SPA、robots、sitemap、redirect 和 challenge fixture；
- search/research Eval 记录正确性、引用覆盖、来源质量、耗时、Tool/Model 次数；
- 至少一条真实 wigolo sidecar smoke 和一条完全离线 deterministic suite；
- API、CLI、Worker、Desktop 对相同 durable state 给出一致结果；
- `make test`、`make check`、file-size gate 和适用真实浏览器 E2E 通过；
- 文档、SBOM、安装、升级、备份、清理和 rollback 说明齐全。

## 11. 非目标

- 本规划任务不修改代码、不安装 wigolo、不下载浏览器或模型；
- 不把 wigolo 仓库 vendoring 到 Zebra；
- 不为追求参数一比一兼容而保留不安全的多动作 Tool；
- 不建立第二套 Harness、Session、Model Router、Credential Store 或 Memory；
- 认证网站和 Browser actions 必须等 `WEB-INT-BROWSER-01` 独立激活；任意
  插件、私网爬取和会产生外部副作用的浏览器自动化不在本计划范围；
- 不把 Watch best-effort 包装宣称为 durable scheduler；
- 不因本文合入而改变 ACP、代码智能或私有云任务状态。

## 12. 激活与完成规则

1. 当前只有 `WEB-INT-PLAN-01` 进入 `Review`；所有实现任务保持 `Locked`；
2. 每次只解锁一个满足依赖的任务，并补齐 owner、reviewer、worktree 和精确路径；
3. 任务需要扩大权限、引入真实凭证、修改上游或突破 Owned paths 时停止评审；
4. 每个任务单独分支、worktree 和 PR，不把 Tools、Security、Watch、UI 合并；
5. 只有 `WEB-INT-E2E-01` 的全部验收合入后，`PROGRESS.md` 才能声明完整原生化；
6. 在此之前只能准确报告已完成的规划、合同、Provider 或单项能力，不能报告
   “wigolo 所有能力已成为 Zebra 原生能力”。

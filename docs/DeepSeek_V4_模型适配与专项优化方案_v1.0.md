# Zebra Agent DeepSeek V4 模型适配与专项优化方案 v1.0

## 1. 文档状态

| 字段 | 值 |
|---|---|
| 状态 | DS-P0 至 DS-P4 全部实现，PR `#146` |
| 调研基线 | 2026-07-17 |
| 适用范围 | DeepSeek API 上的 `deepseek-v4-flash` 与 `deepseek-v4-pro` |
| 目标读者 | Model Gateway、Harness、Context、Observability、Eval 维护者 |
| 上位约束 | 最终架构、实施基线、RACI、任务登记、PROGRESS |
| 实现状态 | 稳定能力默认启用；Beta 能力独立、显式 opt-in；合并前不代表进入主线 |

本文档细化最终架构文档中的“模型路由”“Prompt Cache 稳定性”和
“可观测性、回放与 Eval”，不改变以下平台不变量：

- 模型只能提出动作，Policy 和 Tool Gateway 决定动作能否执行；
- Session Event Store 仍是耐久状态源；
- Harness Worker 保持无状态和可恢复；
- Provider 差异由 Integration Adapter 吸收，不反向污染 `agent-core`；
- 模型、Prompt、Tool Schema、压缩和路由变化必须经过 Eval。

## 2. 目标与非目标

### 2.1 目标

1. 消除 DeepSeek V4 思考模式与 Zebra 多轮工具调用之间的协议风险。
2. 在不保存或公开私有推理内容的前提下使用 DeepSeek 的推理能力。
3. 让 Flash 与 Pro 按任务角色分工，而不是用一个全局模型覆盖所有调用。
4. 利用 DeepSeek 前缀缓存降低输入成本和重复上下文延迟。
5. 建立可扩展的 Model Profile，使后续模型适配不依赖散落的供应商判断。
6. 用真实任务 Eval 决定模型、模式和路由，而不是依赖静态经验。

### 2.2 非目标

- 本任务不改变当前产品姿态和 `ARCH-129-*` 锁定状态。
- 不把 DeepSeek 私有 `reasoning_content` 写入公开事件、日志、Artifact 或长期存储。
- 不承诺完整使用 1M 上下文；上下文预算仍由任务收益、延迟和成本决定。
- Beta strict tools、FIM 与 Chat Prefix Completion 不进入默认 Profile。
- 不为 DeepSeek 绕过 Policy、审批、网络出口或 Credential Broker。
- 不假设 OpenAI-compatible 等价于行为、错误和流协议完全兼容。

## 3. 当前实现基线

### 3.1 已具备能力

- `OpenAICompatibleModelGateway` 已支持非流式和 SSE 流式 Chat Completions。
- 流解析可重组碎片化文本和多段 Tool Call 参数。
- Provider 工具名被规范化，并校验返回工具是否来自当前工具清单。
- Tool Call 参数会经过 JSON 解析和 Zebra 侧输入校验。
- Harness 已具备耐久事件、审批、澄清、暂停、恢复和工具预算。
- Context Compiler 已把上下文分为稳定、半稳定和动态区域。
- 当前默认 DeepSeek 模型为 `deepseek-v4-flash`。

### 3.2 当前缺口

| 区域 | 当前状态 | 风险 |
|---|---|---|
| 思考模式 | 请求未显式设置 `thinking` | V4 默认开启，行为受供应商默认值变化影响 |
| 工具续传 | 流解析忽略 `reasoning_content` | 思考模式工具轮后续请求可能返回 400 |
| 调用策略 | 只有 provider/base URL/model | 无法按 planner/executor/reviewer 分级 |
| 流 Usage | 未显式请求 `include_usage` | 流式 token、缓存和推理成本不完整 |
| 完成状态 | 未规范化 `finish_reason` | 截断、内容过滤和资源不足可能被误判成功 |
| 缓存观测 | 只有布尔 `cache_hit` 槽位 | 无法计算缓存命中 token 与真实节省 |
| 延迟 | 只记录总延迟 | 无法区分排队、首字和生成耗时 |
| 超时 | 单一 30 秒超时 | DeepSeek 长排队或长推理容易被客户端提前终止 |
| 错误 | 依赖通用 HTTP 异常 | 无法安全区分重试、配置错误和余额问题 |
| Schema | 仅通用 JSON Schema | 不能直接安全启用 DeepSeek strict Beta |

## 4. P0 协议兼容决策

### 4.1 已确认的供应商行为

DeepSeek V4 的 OpenAI 格式通过以下参数控制思考：

```json
{
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
```

官方文档说明：

- V4 默认开启思考模式；
- effort 支持 `high` 和 `max`；
- 思考模式下 temperature、top_p 和 penalty 参数不会生效；
- 无工具的历史推理内容不必进入下一轮；
- 如果一次思考响应包含工具调用，完整 `reasoning_content` 必须在后续请求中回传；
- 未正确回传时，API 会返回 HTTP 400。

来源：[DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)

### 4.2 Zebra 决策

第一阶段不实现“思考模式中的多轮工具调用”。调用策略固定为：

```text
本次调用包含可用工具 -> thinking=disabled
本次调用不包含工具   -> 可按 Model Profile 开启 thinking
```

原因：

1. Zebra 当前消息模型和流适配器不会保存 `reasoning_content`。
2. 为支持审批恢复而持久化原始私有推理，会扩大隐私、审计和数据治理范围。
3. 仅在内存中保留推理无法覆盖进程重启、审批暂停和会话恢复。
4. 显式关闭工具轮思考是最小、确定且可测试的兼容策略。

### 4.3 复杂 Agent 任务的替代流程

```mermaid
flowchart LR
    U["用户任务"] --> P["Pro thinking/max\n无工具生成显式计划"]
    P --> D["计划作为普通内容\n进入耐久事件"]
    D --> E["Flash/Pro non-thinking\n执行工具循环"]
    E --> V["Pro thinking/high|max\n无工具复核与总结"]
    V --> F["公开最终答案"]
```

显式计划是可以展示、审核和持久化的产品内容；私有推理内容不是项目状态。

### 4.4 后续重新评估条件

只有满足以下任一条件，才重新评估思考模式工具轮：

- DeepSeek 提供不暴露私有推理的 opaque continuation token；
- 项目通过单独 ADR 批准受控的 Provider Continuation State；
- 数据分类、加密、保留、删除、审计和恢复语义完成评审；
- Eval 证明其收益足以承担新增治理复杂度。

## 5. DeepSeek 调用矩阵

| Profile | 任务角色 | 模型 | Thinking | Effort | Tools | 默认用途 |
|---|---|---|---|---|---|---|
| `deepseek-flash-executor` | executor | V4 Flash | disabled | - | auto | 文件、命令、搜索、普通工具循环 |
| `deepseek-flash-fast` | classifier/summarizer | V4 Flash | disabled | - | none | 分类、压缩、轻量摘要、参数修复 |
| `deepseek-flash-reasoning` | analyst | V4 Flash | enabled | high | none | 中等复杂度无工具分析 |
| `deepseek-pro-planner` | planner | V4 Pro | enabled | max | none | 架构、复杂调试、跨文件计划 |
| `deepseek-pro-reviewer` | reviewer | V4 Pro | enabled | high/max | none | Diff、安全和最终结果复核 |
| `deepseek-pro-executor` | executor | V4 Pro | disabled | - | auto | Eval 证明 Flash 工具质量不足时的升级路径 |

初始路由原则：

- 简单 Agent 工具任务优先 Flash；
- 复杂推理优先 Pro，但保持无工具；
- 工具执行前后用显式计划或复核内容连接，不传递私有思维链；
- 只有 Eval 证明收益时才从 Flash 升级到 Pro；
- 图片输入路由到已声明 vision 能力的模型；其描述作为带来源的不可信数据
  再交给 DeepSeek，不伪装成 DeepSeek 原生视觉能力；
- 不在已经产生公开流内容或副作用之后静默切换模型重放。

DeepSeek 官方将 Flash 定位为快速、经济、简单 Agent 任务接近 Pro，将 Pro
定位为复杂推理和 Agentic Coding；其 Claude Code 示例也采用 Pro 主模型、
Flash 子任务模型和 max effort。来源：
[DeepSeek V4 Release](https://api-docs.deepseek.com/news/news260424/)、
[DeepSeek Claude Code Integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)。
其 Copilot 集成也明确通过其他模型代理图片描述，而不是把 V4 声明为视觉模型：
[DeepSeek GitHub Copilot Integration](https://api-docs.deepseek.com/quick_start/agent_integrations/github_copilot)

## 6. 通用 Model Profile 设计

### 6.1 分层原则

```text
Harness / Use Case
    -> ModelInvocationPolicy（本次任务意图）
    -> ModelRouter（选择 Profile）
    -> ModelProfile（能力与默认值）
    -> Provider Adapter（供应商协议映射）
    -> Provider API
```

- `agent-core` 只表达中立调用意图和标准结果。
- `agent-integrations` 保存 DeepSeek 参数、错误、usage 和 SSE 映射。
- `apps/*` 负责配置加载和依赖组合。
- Policy 权限不属于 Model Profile；模型能力不能扩大动作权限。

### 6.2 Model Profile 建议字段

```yaml
id: deepseek-v4-flash-executor-v1
provider: deepseek
model: deepseek-v4-flash
version_observed_at: 2026-07-17

roles:
  - executor
  - summarizer

capabilities:
  tools: true
  thinking: true
  thinking_with_tools_requires_continuation: true
  json_output: true
  strict_tools: beta
  fim: beta_non_thinking
  vision: false

limits:
  context_tokens: 1000000
  max_output_tokens: 393216
  max_tools: 128

defaults:
  thinking: disabled
  tool_choice: auto
  stream_usage: true
  timeout_profile: deepseek_interactive

fallback:
  before_first_delta: deepseek-v4-pro-executor-v1
  after_first_delta: none
```

`version_observed_at` 必须进入 Trace。供应商能力会变化，不能只根据模型名称
永久推断能力。

### 6.3 Model Invocation Policy 建议字段

```text
role
thinking_mode
reasoning_effort
tool_choice
max_output_tokens
response_format
timeout_profile
fallback_policy
privacy_scope
```

调用级策略优先于 Profile 默认值，但必须通过 Profile 能力校验。非法组合在请求
离开 Zebra 之前失败，例如：

- executor + tools + thinking enabled 在第一阶段被拒绝；
- JSON Output 未同时提供 JSON 输出提示时被拒绝；
- strict tools 使用不兼容 Schema 时被拒绝；
- FIM 与 thinking enabled 组合被拒绝。

## 7. 流式协议与完成语义

### 7.1 请求要求

所有 DeepSeek 流式请求显式设置：

```json
{
  "stream": true,
  "stream_options": {"include_usage": true}
}
```

根据调用角色显式设置 `thinking`、`reasoning_effort`、`tool_choice` 和
`max_tokens`，不依赖供应商默认值。

### 7.2 响应规范化

需要采集和规范化：

- provider request/model call ID；
- 实际返回模型和 `system_fingerprint`；
- `finish_reason`；
- input、output、reasoning token；
- prompt cache hit/miss token；
- 首事件、首公开文本、首 Tool Call 和总延迟；
- retry count 与规范化错误类别。

`finish_reason` 处理：

| 值 | Zebra 行为 |
|---|---|
| `stop` | 正常完成 |
| `tool_calls` | 进入工具处理，不视为最终答案 |
| `length` | 标记截断；禁止把不完整 JSON 或答案判定为成功 |
| `content_filter` | 记录受限完成并向上层返回受控错误 |
| `insufficient_system_resource` | 可重试错误，受重试策略约束 |

JSON Output 必须同时在 Prompt 中明确要求 JSON，并处理 `length` 截断。
来源：[DeepSeek Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion/)

### 7.3 私有推理处理

- `reasoning_content` 不投递为 Assistant Delta。
- 不写入 Session Event、Artifact、普通日志或错误消息。
- 只记录 `reasoning_tokens`、模式和 effort 等非内容元数据。
- 如果 Provider 在禁用思考时仍返回私有推理字段，丢弃内容并记录协议告警。

## 8. Prompt 与缓存优化

DeepSeek Context Caching 默认开启，并依赖完全一致的重叠前缀。
来源：[DeepSeek Context Caching](https://api-docs.deepseek.com/guides/kv_cache/)

建议固定顺序：

```text
1. 系统身份、平台规则和安全边界
2. 稳定排序的工具名称、描述和 Schema
3. 仓库永久规则与确认记忆
4. Repo Map 等半稳定上下文
5. 会话摘要和最近工具结果
6. 当前任务、预算和动态事件尾部
```

要求：

- 工具及 Schema 属性确定性排序；
- 相同 Profile 使用相同系统 Prompt 版本；
- 稳定前缀禁止包含时间戳、随机 ID、Session ID 或动态预算；
- Prompt 版本、工具清单哈希、Profile ID 进入 Trace；
- `prompt_cache_hit_tokens` 与 `prompt_cache_miss_tokens` 是权威指标；
- Zebra 本地 Cache Key 只用于版本追踪，不能证明供应商缓存命中；
- 缓存属于性能优化，正确性不得依赖缓存存在或持久时间。

官方在调研日公布的 Flash/Pro 上下文均为 1M，最大输出为 384K；价格和并发
属于时效配置，上线前必须重新读取官方页面，不应固化进代码常量。
来源：[DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)

## 9. Tool Schema 与结构化输出

### 9.1 常规工具模式

第一阶段保留 Zebra 当前本地校验：

1. Provider 返回的工具名必须在本次工具清单中；
2. arguments 必须是合法 JSON object；
3. Tool Gateway 执行前做完整 Schema 和权限校验；
4. 模型生成结果永远不直接等价于执行授权。

`tool_choice` 使用原则：

- 普通执行轮：`auto`；
- 无工具规划与复核：`none`；
- 只有流程已经确定必须调用某工具时使用 `required` 或指定工具；
- 禁止为了“提高工具使用率”在开放式任务中全局设为 `required`。

### 9.2 Strict Mode Beta

DeepSeek strict tools 当前需要 `/beta` endpoint，全部函数设置 `strict=true`，
并使用受限 JSON Schema 方言。所有 object 属性必须 required，且
`additionalProperties=false`。
来源：[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)

因此 strict mode 只能作为独立实验 Profile：

- 增加 Schema compatibility checker；
- 不修改原始领域 Tool Definition；
- 对兼容 Schema 生成 Provider 版本；
- 对不兼容 Schema 显式降级到普通模式；
- Beta endpoint 与稳定 endpoint 分开配置和观测；
- 经工具参数有效率 Eval 后再决定是否扩大范围。

## 10. 超时、重试与降级

DeepSeek 可能通过空行或 SSE `: keep-alive` 保持连接；官方说明未开始推理的
请求最长可能在十分钟后由服务端关闭。
来源：[DeepSeek Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit/)

建议初始超时 Profile：

| 参数 | 建议初值 | 说明 |
|---|---:|---|
| connect timeout | 10 秒 | 建连失败快速暴露 |
| first-response timeout | 120 秒 | 覆盖常规排队与复杂推理 |
| stream idle timeout | 90 秒 | keep-alive 可刷新，但不无限等待 |
| overall deadline | 5 分钟 | 交互默认值；任务可缩短或放宽 |

这些值是 Zebra 初始策略，不是 DeepSeek SLA，必须通过生产 Trace 调整。用户取消
始终优先于 deadline。

错误策略：

| HTTP/错误 | 分类 | 自动重试 |
|---|---|---|
| 400 | 协议或请求格式 | 否 |
| 401 | 认证失败 | 否 |
| 402 | 余额不足 | 否 |
| 422 | 参数非法 | 否 |
| 429 | 限流 | 是，退避并尊重 Retry-After |
| 500 | 服务错误 | 是，有限次数 |
| 503 | 服务过载 | 是，有限次数 |

来源：[DeepSeek Error Codes](https://api-docs.deepseek.com/quick_start/error_codes/)

重试边界：

- 首个公开 delta 之前，模型请求可按策略透明重试；
- 首个公开 delta 之后，不透明重放，避免 UI 重复内容；
- Tool Call 已进入审批或执行后，依靠耐久事件恢复，不重新生成后直接执行；
- 有副作用工具完成后不得因模型失败而重放工具；
- 降级模型必须创建新的 model call correlation，并记录原失败原因。

## 11. user_id 与隔离

DeepSeek `user_id` 可用于内容安全、KV Cache 和调度隔离，且禁止包含隐私信息。
建议使用稳定的不可逆应用级标识：

```text
base32(HMAC(application_secret, tenant_id + ":" + internal_user_id))
```

- 不发送邮箱、用户名或原始数据库 ID；
- 同一用户保持稳定以获得合理缓存复用；
- 不按每个 Session 随机生成；
- HMAC secret 由 Credential Broker 或应用 Secret 配置管理；
- 本地单用户模式使用固定的非个人标识。

来源：[DeepSeek Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit/)

## 12. 可观测性与 Eval

### 12.1 Model Call Trace

每次调用至少记录：

```text
profile_id
profile_version_observed_at
provider
requested_model
resolved_model
role
thinking_mode
reasoning_effort
tool_choice
tool_count
tool_schema_bytes
prompt_version
prompt_cache_hit_tokens
prompt_cache_miss_tokens
input_tokens
output_tokens
reasoning_tokens
time_to_first_event_ms
time_to_first_public_text_ms
latency_ms
finish_reason
retry_count
normalized_error
system_fingerprint
cost_usd
```

不得记录私有推理正文、API Key、原始用户身份或未脱敏 Secret。

### 12.2 DeepSeek Provider Contract Tests

- thinking enabled/disabled 请求映射；
- tools 存在时强制禁用思考；
- `stream_options.include_usage`；
- SSE keep-alive、空 choices usage chunk 和 `[DONE]`；
- fragmented content/tool calls；
- `finish_reason` 全分支；
- cache hit/miss 与 reasoning token 映射；
- 400/401/402/422/429/500/503 分类；
- 取消、首 delta 前重试和首 delta 后失败；
- 私有推理内容不进入事件和日志。

### 12.3 任务 Eval 矩阵

| 维度 | 最小用例 |
|---|---|
| 工具 | 单工具、多工具、并行工具、未知工具、无效参数 |
| 恢复 | 审批暂停、澄清暂停、进程重启、流中断 |
| 上下文 | 短任务、跨文件、长日志、重复前缀、压缩后恢复 |
| 质量 | 中文需求、代码修复、架构计划、Diff Review、安全审查 |
| 安全 | Prompt Injection、Secret 诱导、越权工具建议 |
| 完成 | stop、tool_calls、length、content_filter、资源不足 |
| 路由 | Flash/Pro、thinking on/off、high/max 对照 |

决策指标：

- 任务成功率和测试通过率；
- Tool Call 参数有效率；
- 审批/恢复成功率与重复副作用数；
- P50/P95 首字和总延迟；
- 输入、输出、推理、缓存命中 token；
- 单任务成本；
- Reviewer 接受率和无关 Diff 数量。

不预先写死“Pro 必须胜过 Flash”的结论。路由升级以同一 Eval 集上的显著收益为准。

## 13. 分阶段实施包

`DS-OPT-01` 已按任务卡、独立分支和 Owned Paths 实施 DS-P0 至 DS-P3 的首期范围。

### DS-P0：协议安全调用

范围：DeepSeek adapter、调用参数、流 Usage、finish reason、错误和超时。

验收：

- [x] 所有带工具请求显式发送 `thinking=disabled`。
- [x] 无工具请求可以显式选择 high/max 思考。
- [x] 流式调用完整采集 Usage 和完成原因。
- [x] 私有推理正文不进入公开流或耐久存储。
- [x] 多轮真实工具 smoke 可执行；有凭据运行，无凭据明确 skip。
- [x] Provider contract tests 通过，真实 smoke 不记录或输出凭据。

### DS-P1：Model Profile 与角色路由

范围：中立调用策略、版本化 Profile、Flash/Pro 显式路由。

验收：

- [x] Harness 不包含散落的 DeepSeek provider 判断。
- [x] 非法能力组合在发起 HTTP 前失败。
- [x] planner/executor/reviewer/summarizer 可独立配置。
- [x] 旧单模型配置存在明确兼容和迁移路径。

### DS-P2：缓存与可观测性

范围：稳定前缀、缓存 token、TTFT、fingerprint、成本和 Trace。

验收：

- [x] 工具确定性排序，Prompt/schema 版本与稳定前缀哈希进入 Trace。
- [x] 可区分供应商缓存 hit/miss token。
- [x] 可按 Profile 查询成功率、延迟、成本和完成原因。
- [x] 缓存只影响遥测和性能，失效不参与正确性路径。

### DS-P3：评测驱动路由与降级

范围：Eval 矩阵、Profile 对照、受控 fallback 和发布门禁。

验收：

- [x] 路由选择有 Provider Eval、Profile ID 和版本记录。
- [x] fallback/retry 不跨越公开流或工具副作用边界。
- [x] Profile 指标支持离线回放及 Flash/Pro 灰度对照汇总。
- [x] Provider contract tests 与 release eval gate 自动阻止退化。

### DS-P4：Beta 能力实验

范围：strict tools、FIM、Chat Prefix Completion 等独立实验。

验收：

- [x] Beta endpoint 与稳定 endpoint 隔离，配置默认关闭。
- [x] Schema compatibility checker 有确定性测试，非法方言在 HTTP 前拒绝。
- [x] Beta 能力只在无公开 delta、无工具副作用时回退稳定路径并记录原因。
- [x] 三个版本化 Beta Profile 均为 opt-in，Provider Eval 不会改变默认路由。

## 14. 发布与回滚

1. 先以 Profile ID 灰度，不直接替换全局模型配置。
2. DS-P0 只改变 DeepSeek 请求正确性，不同时上线自动路由。
3. DS-P1 初期采用显式角色映射，自动路由在 DS-P3 后启用。
4. 每次 Profile 变更保留旧版本，Session Trace 记录解析后的实际版本。
5. 回滚通过切回旧 Profile 完成，不修改耐久事件语义。
6. 真实凭证测试只作为受控 smoke test，API Key 不进入 CI 日志或 Fixture。

## 15. 外部经验与采用边界

- Continue 按 chat、autocomplete、edit、apply、embed、rerank 等角色配置模型，
  支持“按角色选择模型”而非单全局模型。Zebra 采用角色概念，但保留自己的
  Harness、Policy 和耐久事件边界。
  来源：[Continue Model Roles](https://docs.continue.dev/customize/model-roles/intro)
- OpenCode 支持为不同 Agent 配置模型、Prompt、参数和权限。Zebra 只借鉴模型
  与 Prompt 的 Profile 化；权限仍由独立 Policy 体系负责，不能由 Agent Profile
  自行扩大。
  来源：[OpenCode Agents](https://opencode.ai/docs/agents)
- 第三方集成文档可能滞后于供应商模型更新。因此 DeepSeek 官方 API 文档和真实
  Provider Contract Test 优先于框架中的静态能力声明。

## 16. DS-OPT-01 实施证据

- 基线：`CTX-LC-01` commit `6d85f42`，保留 ContextCapsule 合同与事件字段；
- 聚焦验证：127 passed、2 个显式 provider smoke 默认 skipped；
- 全量验证：1391 passed、2 个显式 provider smoke 与 1 个平台限定 gVisor skipped；
- Provider Eval：6 个稳定协议、隐私、重试、路由与 Beta 能力用例可加载；
- Real provider smoke：稳定多轮工具与 Beta strict-tools、FIM、Chat Prefix 均通过；
- 工程门禁：819 文件上限、Ruff、379 个源文件严格 Mypy、8 个 release eval 通过。

## 17. 来源与时效说明

本方案优先使用 DeepSeek 官方 API 文档，并以 2026-07-17 可见内容为基线。
模型名称、价格、并发、上下文、Beta 功能和参数语义都可能变化。每次实施和发布前
必须重新核对：

- [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Context Caching](https://api-docs.deepseek.com/guides/kv_cache/)
- [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
- [FIM Completion](https://api-docs.deepseek.com/guides/fim_completion/)
- [Chat Prefix Completion](https://api-docs.deepseek.com/guides/chat_prefix_completion/)
- [Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit/)
- [Error Codes](https://api-docs.deepseek.com/quick_start/error_codes/)

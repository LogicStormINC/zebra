# CTX-LC-01 上下文生命周期与混合压缩架构验收记录

## 结论

`CTX-LC-01` 的 provider-neutral 范围已完全实施，状态进入 `Review`。
Zebra 现在以同一 Durable Session 内的渐进式压缩继续为主路径，以
Artifact、透明 Capsule 和可选 provider continuation 组成混合架构；
上下文高水位不会自动创建后台会话或子代理。

## 验收矩阵

| 层级 | 验收结论 | 关键不变量 |
|---|---|---|
| L0 Context Window Planner | 通过 | 所有请求共享 hard gate；reserve 后超限请求不会到达 provider |
| L1 输出增长治理 | 通过 | 完整输出先持久化；模型仅见有界 head/tail 与可验证引用 |
| L2 Micro-compaction | 通过 | 已完成旧结果 typed tombstone 化；未完成调用和近期精确尾部不丢失 |
| L3 Projection Folding | 通过 | 用户约束进入 Protected Ledger；重水合受预算、Policy、provenance 限制 |
| L4 Context Capsule | 通过 | Capsule、事件与 active pointer 原子提交；worker 可确定性恢复 |
| L5 Provider continuation | 通过 | provider/model/version/TTL 隔离；无效状态自动 Capsule fallback |
| L6 控制与观测 | 通过 | API/CLI 支持 inspect、focus、preview、through-sequence、历史恢复和 hooks |

## 安全与恢复证明

- Event Store 仍是权威历史，压缩不删除原始事件。
- Capsule 不替代 Policy、approval、tool idempotency 或 Runtime authority。
- assistant tool call 与 tool result 成对保留或成对投影。
- prompt injection 类型的工具输出不会进入 Protected Instruction Ledger。
- Capsule Artifact、`ContextCompacted`、`ContextCapsuleCreated` 与 active
  pointer 在同一 SQLite 事务内推进。
- provider continuation 缺失、过期、不兼容、删除或跨 provider 时，恢复
  使用透明 Capsule，不依赖 opaque 私有状态。
- 操作者选择 `through-sequence` 时，worker 会按事件引用恢复近期精确尾部。

## 验证证据

```text
make test
1379 passed, 1 skipped in 27.10s

make check
file size gate: passed=True checked=810 violations=0
All checks passed!
Success: no issues found in 379 source files
eval release gate: passed=True pass_rate=1.00 average_score=1.00 cases=8
```

唯一跳过项是当前 macOS 环境无法执行的 Linux gVisor smoke，不属于本任务
行为范围。Context、Core、Storage、Tools、Runtime、Worker、API、CLI 和跨包
契约测试均已执行。

## Provider 专项边界

核心已完成 tokenizer/count-token Port、模型窗口 profile、native continuation
capability、持久化与 fallback 契约。OpenAI、Anthropic、DeepSeek 各自真实
API 的协议字段、版本化模型参数、流式 usage 和线上 Eval 必须在对应
`agent-integrations` 专项任务中完成。当前 `DS-OPT-01` 保持独立 owned paths，
不属于 `CTX-LC-01` 的未完成项。

# CA-P3-03A 原业务效果收据协调

## 问题与边界

同一 Task 的 EffectLedger 按业务动作、参数与授权归属去重。新 Run 复用相同业务效果时，旧缓存记录只有调度确认，包含旧 Run 的 `client_effect_deferred`；它不是执行结果。把该确认直接交给新 Worker 会等待已经属于旧 Run 的 Effect。

保留业务键和所有旧记录。共享 Guard 在 legacy/fenced 的缓存返回路径调用只读协调，Worker 提供当前绑定和原收据读取，Control Plane 的确定性函数验证身份并解释结果。Core 仅定义窄读取 Port，PostgreSQL 按 namespace/effect 查询，独立只读事务受 task-I/O 超时约束。无 schema 或依赖变更。

| 原记录状态 | 当前 ToolCall 的结果 | 新派发 |
| --- | --- | --- |
| 匹配且 succeeded 的原收据 | 历史成功，current_ui_performed=false | 禁止 |
| 匹配且 failed/declined/unavailable/stale_ui_state 的终态收据 | 原报告失败；不证明未提交 | 禁止 |
| 缺失、pending、篡改、不匹配、读取异常 | unknown，要求原操作对账；不返回旧 deferred | 禁止 |
| 同一 Segment、ToolCall、Run、绑定且仍 pending/delivered | 保留原 deferred，恢复原等待 | 不新增 |

校验 Task、动作、参数、当前允许的动作合同摘要、原 Effect/ToolCall/Run/绑定/请求摘要及收据 Effect/请求摘要。返回结果绑定当前 ToolCall ID，并保留 original receipt/effect/run 标识。读取之后再次检查 Worker 所有权；租约失效不可被 unknown 捕获掩盖。

## 显式业务意图

新 Run、随机 UUID、UI 修订及客户端重连都不代表新的业务执行授权。同一业务意图只协调原操作；历史成功不证明当前 UI 被执行，也不证明当前外部状态。结果 unknown 不自动重发、不重新领取 Controller，不清空账本或改写收据。

需要再次执行同一业务动作时，必须另行设计受信、不可变且经过权限校验的业务意图合同；本批不提供该入口，也不把自然语言 follow-up 或新的 Run 偷换成新意图。Task follow-up 响应 unknown 仍中止，不能假装已有公开原请求 GET 合同。

## 兼容与发布边界

普通非 deferred 结果保持原样；原操作的合法 pending 恢复保留。历史事件、快照、账本、Coverage、原收据和数据库保持不变。修复位于实际 Worker 路径，依赖所有承担该工作的 Worker 升级；只更新 API 副本或混用旧 Worker 不在验证范围。没有部署、生产迁移或真实业务副作用重放。

## 验证

先以 legacy/fenced 两个定向用例证明旧代码错误，再修复共享路径。覆盖五种终态、跨 Task/参数/合同/摘要不匹配、缺失/读取失败/不确定结果、所有权丢失和原 pending 恢复。真实 PostgreSQL 验证 namespace 隔离、读取不改写原收据/事件。

运行 `make test`、`make check`；TypeScript SDK 运行 check/test。固定发布源码的 Chromium/WebKit 相同 item 跨 Run 验收由 Overdoze OD-P3-01Z 单独记录，同时保留不同 item 的第二轮 UI 执行和旧消费者兼容验收。隔离 IdP/模型/业务 UI 均为测试夹具，不声称生产 IdP、厂商模型、生产高可用或外部取消已验收。

结果见 [验证记录](evidence/ca-p3-03a/validation.json)。

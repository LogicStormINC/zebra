# AG-UI 协议兼容性验证记录

| 字段 | 值 |
|---|---|
| Task | `EMB-AGUI-SPIKE-01` |
| 日期 | 2026-07-23 |
| 状态 | Review；focused validation passed；baseline blockers reproduced |
| Python | 3.12.9 |
| SDK | `ag-ui-protocol==0.1.19` |
| Pydantic | 2.13.4 |
| Production wiring | 无 |

## 1. 目的与边界

本 Spike 在 Zebra 定义生产 AG-UI Adapter 前，用官方 Python SDK 固定并验证
wire model、SSE encoder、interrupt/resume 和 forward-compatibility 行为。

它只修改 development dependency、隔离测试和本记录，不修改：

- Zebra Domain Event、Task、Segment、Approval 或 Worker；
- API route、SSE production handler 或 dependency injection；
- HostSessionGrant、Trench Tool、CopilotKit 或前端代码；
- 最终 `EMB-AGUI-CON-01` 契约。

官方参考：

- [PyPI ag-ui-protocol](https://pypi.org/project/ag-ui-protocol/)
- [Python core events](https://docs.ag-ui.com/sdk/python/core/events)
- [Python EventEncoder](https://docs.ag-ui.com/sdk/python/encoder/overview)
- [AG-UI interrupts](https://docs.ag-ui.com/concepts/interrupts)

## 2. 文件结构

```text
tests/spikes/ag_ui/
├── README.md
├── fixtures.py
├── sse_decoder.py
├── test_event_stream.py
├── test_interrupt_resume.py
└── test_forward_compatibility.py
```

目录故意不包含 `__init__.py`。若把它声明为顶层 `ag_ui` 测试包，会遮蔽官方
SDK 的同名 import，这是首轮 collection 实际发现并修正的边界。

## 3. 已验证事件流

canonical success stream 覆盖并保持以下顺序：

```text
RUN_STARTED
TEXT_MESSAGE_START
TEXT_MESSAGE_CONTENT
TEXT_MESSAGE_END
TOOL_CALL_START
TOOL_CALL_ARGS
TOOL_CALL_END
TOOL_CALL_RESULT
STATE_SNAPSHOT
STATE_DELTA
MESSAGES_SNAPSHOT
RUN_FINISHED
```

测试同时验证：

- `EventEncoder.get_content_type()` 为 `text/event-stream`；
- encoder 输出 `data: <camelCase JSON>\n\n`；
- UTF-8 多字节内容被任意 byte chunk 切分后仍可重组；
- independent decoder 不 import AG-UI SDK，并限制 stream/event bytes 和数量；
- official `TypeAdapter(Event)` 可重新验证每个解码 payload；
- thread、run、message、tool-call 标识 round-trip 不变；
- truncated、oversized 和 event-count overflow 均确定性失败。

## 4. SDK 0.1.19 的兼容性行为

### 4.1 Event discriminator

- `Event` 是按 `type` 判别的 union。
- 未知 `type`（例如 `FUTURE_EVENT`）产生 `union_tag_invalid`，不会静默变成
  某个已知事件。
- `CUSTOM` 和 `RAW` 是显式 forward-compatibility 出口。
- 已知事件的额外字段会保留；缺少 `threadId` 等 required core field 会失败。

生产决策：

- Zebra 不把未知 Domain Event 自动投影为任意 AG-UI wire event；
- 只有版本化、allowlisted extension 才能使用 `CUSTOM`；
- `RAW` 只保留受限 provider/host-native evidence，不能绕过 Policy 或信任分级；
- 版本升级必须显式更新 EventType snapshot 和 golden fixtures。

### 4.2 Reviewed EventType snapshot

0.1.19 暴露 33 个 EventType，不再只是早期文档常见的“16 个核心事件”。除
text/tool/state/run 外，还包括 thinking、reasoning、activity、chunk、raw 和
custom families。测试保存完整 snapshot，依赖升级时任何增删都会显式失败。

生产决策：首个 `EMB-AGUI-CON-01` 只映射目标架构列出的最小 allowlist；存在于
SDK 不等于 Zebra 自动支持。

## 5. Interrupt / resume 结论

官方 interrupt 协议要求：

1. `RUN_FINISHED` interrupt outcome 前发送恢复所需的 State 和 Messages snapshot；
2. resume 使用相同 `threadId`；
3. `resume[]` 覆盖该 Run 的全部 open interrupts；
4. 相同 interrupt response 重放必须幂等；
5. payload 应按 `responseSchema` 校验，并拒绝过期 interrupt。

Spike 使用两个 open interrupts，避免“单元素数组恰好完整”的假阳性，并验证：

- snapshot-before-finish ordering；
- same-thread、new-run resume fixture；
- full interrupt ID set coverage；
- 对 resume entry 排序不敏感、对 payload 敏感的确定性 SHA-256 identity。

### 5.1 SDK 不提供的安全保证

0.1.19 的 Pydantic model 只执行结构校验。它会接受：

- 少于 open interrupt 数量的 `resume[]`；
- 与原 Run 不同的 `threadId`；
- 不符合 `responseSchema` 的 payload；
- 不能解析为 RFC 3339 的 `expiresAt`。

它会拒绝不在 `resolved | cancelled` 内的 resume status。

因此后续生产 Adapter 必须从 Zebra durable state 加载 open interrupts，并自行
校验 thread、coverage、expiry、schema、authority 和 replay identity。不能把
SDK model validation 当作 Approval/Policy validation。

## 6. 对后续任务的约束

### EMB-AGUI-CON-01

- 在 `agent-integrations` 固定 production SDK version，不泄漏到 `agent-core`；
- Domain Event → AG-UI 是纯投影；unknown mapping fail closed；
- golden fixtures 同时记录 SDK class 和 uppercase wire value；
- 生产 decoder/transport 不能复用本 Spike 的测试 decoder；
- interrupt validator 依赖 durable Approval/Clarification state，而非前端状态。

### TRN-CPK-SPIKE-01

- 使用同一 AG-UI version matrix 验证 Copilot Runtime/HttpAgent；
- 验证 `CUSTOM`/`RAW` 的 Trench 渲染与默认拒绝行为；
- 验证两个 simultaneous interrupts 和完整 `resume[]`；
- 不使用 `agents__unsafe_dev_only` 作为生产连接结论。

## 7. 验证记录

本任务验证通过：

```text
uv run pytest tests/spikes/ag_ui -q
11 passed

uv run ruff check tests/spikes/ag_ui
passed

uv run ruff format --check tests/spikes/ag_ui
5 files already formatted

uv lock --check
passed

git diff --check
passed
```

额外检查确认：

- Spike 文件均在仓库长度限制内；
- `packages/` 与 `apps/` 不存在 `ag_ui` / `ag-ui-protocol` production import；
- release Eval gate 通过：10/10 cases，pass rate 和 average score 均为 1.00。

仓库级门禁已运行，但当前基线不是全绿：

- `make test` 收集 1,763 个测试并出现 9 个失败；相同 9 个 node ID 在不含
  SDK pin 和 Spike 文件的架构基线 worktree 上逐项复现，未发现本任务回归；
- `make check` 在文件长度门禁停止：两个未修改文件分别为 561/500 和
  505/500 行；
- 单独运行后续 Ruff 门禁得到 13 个既有问题，在基线输出完全一致；
- 单独运行 Mypy 得到 4 个既有问题，在基线输出完全一致。

9 个基线测试失败分为四组：DeepSeek 异常包装断言、OpenAI-compatible
fixture 未声明 `files.read`、5 个过期 credential binding API 用例，以及一个
Worker cancellation race。它们均不位于本任务 Owned paths。

结论：`EMB-AGUI-SPIKE-01` 的目标与验收证据完整，可进入 Review；仓库基线问题
不在本卡修复范围，且不得通过扩大 Owned paths 混入本分支。

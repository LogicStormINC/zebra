# Progress Log

## 2026-06-19

- 将会与 `PROGRESS.md` 冲突的旧 `progress.md` 会话日志文件重命名为 `WORKLOG.md`
- 执行 `P2-TOOL-01 Tool Contracts And Execution Results`
- 新增 `agent-tools` 执行层骨架：
  - `contracts.py`
  - `errors.py`
  - `registry.py`
  - `executor.py`
  - `gateway.py`
- 新增测试：
  - `tests/agent_tools/test_executor.py`
- 为 `agent-core` 和 `agent-tools` 增加 `py.typed`，消除 workspace 类型导入噪音
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools tests/agent_tools tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-tools/src/agent_tools tests/agent_tools` 通过

## 2026-06-19 Governance Alignment

- 恢复真正的 `PROGRESS.md` 项目状态文件
- 把文档中的会话日志引用统一从 `progress.md` 改为 `WORKLOG.md`
- 更新 `README.md`，将仓库状态从 bootstrap 调整为 `Phase 2 - Runtime And Tooling Spine`

## 2026-06-19 Runtime Workspace Baseline

- 执行 `P2-RT-02 - Workspace And Worktree Abstractions`
- 新增 `agent-runtime.workspace` 模块：
  - `errors.py`
  - `models.py`
  - `local.py`
- 新增 `LocalWorkspace` 和 `LocalWorktree`
- 增加 workspace root 绝对路径校验、相对路径归一化、越界路径拒绝、worktree 创建与销毁生命周期
- 新增测试：
  - `tests/agent_runtime/test_workspace.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_runtime/test_workspace.py tests/agent_runtime/test_local_runtime.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-runtime/src/agent_runtime tests/agent_runtime` 通过

## 2026-06-19 Builtin File Read Path

- 执行 `P2-TOOL-02 - Builtin File Read Path`
- 新增 `agent_tools.builtin.files`
- 实现 `files.read`：
  - 通过 `LocalWorkspace` 做相对路径归一化
  - 拒绝越界读取
  - 对大文件返回截断结果和结构化 metadata
- 为 `agent-tools` 增加对 `agent-runtime` 的 workspace 依赖声明
- 新增测试：
  - `tests/agent_tools/test_file_read_tool.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools/test_file_read_tool.py tests/agent_tools/test_executor.py tests/agent_runtime/test_workspace.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/smoke/test_workspace_bootstrap.py` 通过
  - `make check` 通过

## 2026-06-19 Builtin Command Execution Path

- 执行 `P2-TOOL-03 - Builtin Command Execution Path`
- 新增 `agent_tools.builtin.command`
- 实现 `command.run`：
  - `command` 必须是 typed argv，不接受自由 shell 字符串
  - 默认在 workspace 根目录执行
  - `cwd` 如果提供，必须仍然位于 workspace 内
  - `timeout_seconds` 透传到 `RuntimePort`
  - 返回结构化执行结果：`stdout` 作为输出，`exit_code`、`stderr`、`timed_out` 写入 metadata
- 新增测试：
  - `tests/agent_tools/test_command_run_tool.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools/test_command_run_tool.py tests/agent_tools/test_file_read_tool.py tests/agent_tools/test_executor.py tests/agent_runtime/test_workspace.py tests/agent_runtime/test_local_runtime.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools` 通过
  - `uv run mypy packages/agent-tools/src/agent_tools tests/agent_tools` 通过
  - `make check` 通过

## 2026-06-19 Builtin Patch And Validation Path

- 执行 `P2-TOOL-04 - Builtin Patch Apply Path`
- 新增 `agent_tools.builtin.patch`
- 实现 `patch.apply`：
  - 输入为 unified diff 字符串
  - 先校验 patch 头中的路径，拒绝越界到 workspace 外
  - 通过 typed `patch` 命令映射到 `RuntimePort`
  - 非零退出和 stderr 作为结构化结果返回
- 新增测试：
  - `tests/agent_tools/test_patch_apply_tool.py`

- 执行 `P2-TOOL-05 - Builtin Validation Commands`
- 新增 `agent_tools.builtin.tests`
- 实现 `tests.run`：
  - 使用 preset 映射，不接受任意自由 shell 文本
  - 支持 `cwd` 与 `timeout_seconds`
  - 返回结构化执行结果
- 新增测试：
  - `tests/agent_tools/test_tests_run_tool.py`

- 执行 `P2-IT-01 - Local Toolchain Integration Flow`
- 新增集成测试：
  - `tests/integration/test_local_toolchain_flow.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/agent_runtime tests/integration tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/integration` 通过
  - `make check` 通过

## 2026-06-19 Readonly Git Inspection Path

- 执行 `P2-GIT-01 - Readonly Git Inspection Tools`
- 新增 `agent_tools.builtin.git`
- 实现 `git.status`：
  - 只执行 readonly `git status --short --branch`
  - `cwd` 如果提供，必须仍然位于 workspace 内
  - 返回结构化结果，不引入写操作
- 新增测试：
  - `tests/agent_tools/test_git_status_tool.py`
- 补齐 `Phase 2` 最小本地工具闭环：
  - `files.read`
  - `patch.apply`
  - `command.run`
  - `tests.run`
  - `git.status`
  - `tests/integration/test_local_toolchain_flow.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/agent_runtime tests/integration tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/integration` 通过
  - `make check` 通过

## 2026-06-19 Harness Loop Skeleton

- 执行 `P3-HAR-01 - Harness Loop Skeleton`
- 新增 `agent_core.harness`
- 实现最小 loop 骨架：
  - `HarnessTask`
  - `HarnessAttempt`
  - `HarnessContext`
  - `HarnessAttemptResult`
  - `HarnessLoop`
- 新增 `HARNESS_ATTEMPT_STARTED` 事件，并接入 session projection
- 当前 loop 只协调一次注入式 `attempt_runner`，不提前耦合真实模型或真实工具执行
- 新增测试：
  - `tests/agent_core/test_harness_loop.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过

## 2026-06-19 Mock Model Gateway

- 执行 `P3-MOD-01 - Mock Model Gateway`
- 新增 `agent_core.domain.modeling.ModelCompletion`
- 调整 `ModelGatewayPort`，从返回单条消息升级为返回 `ModelCompletion`
- 新增 `agent_core.application.mock_model`：
  - `ScriptedModelGateway`
  - `ScriptedModelResponse`
- 新增 `HarnessModelStep`，用于构造初始用户消息并请求一次模型完成
- 新增测试：
  - `tests/agent_core/test_mock_model_gateway.py`
- 覆盖场景：
  - deterministic mock completion
  - tool call planning path
  - script exhaustion failure
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Single Attempt Tool Orchestration

- 执行 `P3-HAR-02 - Single Attempt Tool Orchestration`
- 新增 `SingleAttemptOrchestrator`
- 在单次 attempt 中串起：
  - model completion
  - tool call proposal
  - policy evaluation
  - tool execution
  - structured attempt result
- 为 harness 增加 `HarnessEventDraft` 机制，使 attempt 内部步骤能稳定写回事件流
- 新增测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
- 覆盖场景：
  - model -> policy -> tool success
  - tool execution failed path
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Structured Run Output And Retry Skeleton

- 执行 `P3-HAR-03 - Structured Run Output And Retry Skeleton`
- 新增：
  - `HarnessRunResult`
  - `HarnessStopReason`
  - `HarnessStoppingPolicy`
- `HarnessLoopResult` 现在包含结构化 `run_result`
- 当前 loop 仍然只执行单次 attempt，但已经能稳定给出：
  - 最终 outcome
  - stop reason
  - attempts used
  - max attempts
  - can retry
- 新增测试：
  - `tests/agent_core/test_harness_stopping.py`
- 覆盖场景：
  - failed but retryable
  - retry exhausted
  - loop 暴露结构化 run result
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Multi-Attempt Loop Driver

- 执行 `P3-HAR-04 - Multi-Attempt Loop Driver`
- `HarnessLoop` 从单次 attempt 升级为 bounded multi-attempt driver
- 当前行为：
  - 如果失败且 `can_retry=true`，继续下一次 attempt
  - 成功后立即停止
  - 达到重试预算后终止并返回 `retry_exhausted`
- `HarnessLoopResult` 现在保留 `attempt_results`
- 新增测试：
  - `tests/agent_core/test_harness_multi_attempt.py`
- 覆盖场景：
  - 第一次失败，第二次成功
  - 重试预算耗尽后失败终止
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Assistant And Tool Trace Projection

- 执行 `P3-HAR-05 - Assistant Message And Tool Trace Projection`
- 新增：
  - `HarnessToolTrace`
  - `HarnessAttemptTrace`
  - `HarnessRunTrace`
  - `HarnessTraceProjector`
- `SingleAttemptOrchestrator` 现在在 emitted events 中显式携带 `attempt_number`
- 当前 projection 可以把 assistant message、tool proposal、policy decision、tool result 投影为紧凑 run-facing trace
- 新增测试：
  - `tests/agent_core/test_harness_trace_projection.py`
- 覆盖场景：
  - successful tool trace
  - failed tool trace
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Attempt Event Timestamp Refinement

- 执行 `P3-HAR-06 - Attempt Event Timestamp Refinement`
- 新增：
  - `SystemClock`
  - `StepClock`
- `HarnessLoop` 现在通过 `ClockPort` 驱动事件时间，不再把整次 run 的所有事件压成同一个 `created_at`
- 当前行为：
  - 初始化事件按时钟顺序推进
  - 每次 attempt 有独立 `started_at`
  - emitted events 和 terminal events 继续沿时钟推进
- 新增测试：
  - `tests/agent_core/test_harness_multi_attempt.py` 中的时间顺序断言
- 覆盖场景：
  - 多 attempt 事件时间递增
  - 同一 run 内时间顺序稳定可预测
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Planner And Verifier Hooks

- 执行 `P3-HAR-07 - Planner And Verifier Hooks`
- 新增：
  - `PlannerHook`
  - `VerifierHook`
  - `PlannerResult`
  - `VerifierResult`
  - `NoopPlanner`
  - `NoopVerifier`
- `SingleAttemptOrchestrator` 现在有显式 planner / verifier hook 点：
  - planner 在 tool call proposal 前参与
  - verifier 在 tool result 后参与
- emitted events 里新增：
  - `PLAN_PROPOSED`
  - `TESTS_COMPLETED` 作为最小 verifier 完成事件
- 新增测试：
  - `tests/agent_core/test_harness_hooks.py`
- 覆盖场景：
  - planner 和 verifier 在一次 run 中被调用
  - 结构化 metadata 回写到 attempt result
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Session Event Builder Cleanup

- 执行 `P3-HAR-08 - Session Event Builder Cleanup`
- 新增 `HarnessEventRecorder`
- 统一收拢：
  - `SessionEvent.create`
  - sequence 递增
  - append 到事件流
  - `apply_event` 投影回 session
  - clock 驱动的 `created_at`
- `HarnessLoop` 改为通过 recorder 记录初始化、attempt、draft 和 terminal 事件
- 新增测试：
  - `tests/agent_core/test_harness_recorder.py`
- 覆盖场景：
  - recorder 正常记录事件
  - sequence 递增
  - session projection 行为保持不变
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_recorder.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Tool Call Selection Strategy

- 执行 `P3-HAR-09 - Tool Call Selection Strategy`
- 新增：
  - `ToolCallSelection`
  - `ToolCallSelectionStrategy`
  - `FirstToolCallSelectionStrategy`
- `SingleAttemptOrchestrator` 现在通过显式 selector 选择 tool call，不再内联硬编码 `completion.tool_calls[0]`
- 当前行为：
  - 默认策略仍然稳定选择第一个 tool call
  - selection summary 和 metadata 会进入 proposal event 与 attempt metadata
- 新增测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
- 覆盖场景：
  - 默认选择策略的确定性
  - multi-tool completion 下 orchestrator 只执行选中的 tool call
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Explicit Harness Budgets

- 执行 `P3-HAR-10 - Explicit Harness Budgets`
- 新增：
  - `HarnessTask.max_model_calls`
  - `HarnessTask.max_tool_calls`
  - `HarnessRunResult` 的 budget usage / limit 字段
  - `MODEL_CALL_BUDGET_EXHAUSTED`
  - `TOOL_CALL_BUDGET_EXHAUSTED`
- `HarnessLoop` 现在会把 task budget 写入 `TASK_PREPARED` event，并累计每次 attempt 的 model/tool usage
- `SingleAttemptOrchestrator` 现在会在 attempt metadata 中显式回传：
  - `model_calls_used`
  - `tool_calls_executed`
- `HarnessStoppingPolicy` 现在会在 retry 判断前先检查 model/tool budget 是否已经耗尽
- 新增测试：
  - `tests/agent_core/test_harness_stopping.py`
  - `tests/smoke/test_mock_harness_loop.py`
- 覆盖场景：
  - tool call budget exhausted
  - model call budget exhausted
  - loop 因 tool budget 耗尽而停止重试
  - mock harness loop 端到端 smoke 闭环
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/smoke/test_mock_harness_loop.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core tests/smoke` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

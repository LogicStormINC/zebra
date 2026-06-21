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

## 2026-06-22 Model Call Index

- 执行 `P4-STO-05 - Model Call Index`
- 为核心模型调用补齐 durable 索引闭环：
  - `agent_core.domain.model_calls.ModelCallRecord`
  - `agent_core.ports.model_call_store.ModelCallStorePort`
  - `agent_core.domain.modeling` 中的 `ModelCallMetadata` 与 `ModelUsage`
- `SingleAttemptOrchestrator` 现在会把以下字段写入 `MODEL_RESPONSE_RECEIVED` 事件：
  - `provider`
  - `model_name`
  - `input_tokens`
  - `output_tokens`
  - `total_tokens`
  - `latency_ms`
  - `cache_hit`
  - `cost_usd`
- 新增 `agent_storage.model_calls.SQLiteModelCallStore`
- 新增 `zebra_agent_worker.model_call_index.ModelCallIndexer`
- 新增测试：
  - `tests/agent_storage/test_sqlite_model_calls.py`
  - `tests/worker/test_model_call_index.py`
  - `tests/agent_core/test_single_attempt_orchestrator.py` 中的模型响应元数据断言
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py tests/agent_core/test_single_attempt_orchestrator.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage apps/worker/src/zebra_agent_worker tests/agent_core/test_single_attempt_orchestrator.py tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage apps/worker/src/zebra_agent_worker tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py` 通过
  - `make check` 通过

## 2026-06-22 Context Compiler Bootstrap

- 执行 `P5-CTX-01 - Context Compiler Bootstrap`
- 将 `agent-context` 从占位返回值升级为最小可用的 deterministic compiler：
  - `ContextItemKind`
  - `ContextProvenance`
  - `ContextItem`
  - `ContextBudget`
  - `ContextCompileRequest`
  - `CompiledContext`
- `compile_context` 现在支持：
  - workspace 扫描
  - root/doc 文件优先
  - 基于任务词和路径的基础打分
  - repo map 引导项
  - token budget 裁剪与 `truncated` 标记
- 新增测试：
  - `tests/agent_context/test_compiler.py`
  - `tests/smoke/test_workspace_bootstrap.py` 中的真实编译路径断言
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Related Files Recall And Ranking Split

- 执行 `P5-CTX-02 - Related Files Recall And Ranking Split`
- 将 `agent-context` 进一步拆分为更清晰的职责边界：
  - `scanner.py`
  - `ranking.py`
  - `related.py`
  - `compiler.py`
- 新增 `ContextItemKind.RELATED_FILE`
- `compile_context` 现在除了主排序文件外，还会基于本地 Python import 关系补充 related file context items
- 新增测试：
  - `tests/agent_context/test_compiler.py` 中的 related-file recall 场景
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Conversation And Tool Output Compaction

- 执行 `P5-CTX-03 - Conversation And Tool Output Compaction`
- 新增 `agent_context.compaction`：
  - `ConversationCompactionRequest`
  - `ToolOutputCompactionRequest`
  - `ToolOutputEvidence`
  - `compact_conversation`
  - `compact_tool_outputs`
- 新增 `ContextItemKind`：
  - `CONVERSATION_SUMMARY`
  - `TOOL_OUTPUT_SUMMARY`
- 当前 compaction 行为：
  - 保留用户目标、验收、约束、计划、修改文件、失败尝试、未解决测试、审批、artifact 等关键 section
  - 对工具输出做结构化单行压缩
  - 在 token budget 下做 deterministic truncation
- 新增测试：
  - `tests/agent_context/test_compaction.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Prompt Layout And Cache Key Rules

- 执行 `P5-CTX-04 - Prompt Layout And Cache Key Rules`
- 新增 `agent_context.prompt_layout`：
  - `PromptSectionKind`
  - `PromptSection`
  - `PromptLayout`
  - `PromptCacheKeyRequest`
  - `build_prompt_layout`
  - `build_prompt_cache_key`
- 当前 prompt-layout 行为：
  - `AGENTS.md` / `README.md` 等稳定项目指导进入 stable section
  - `Repo Map`、代码片段、related files 进入 semi-stable section
  - conversation/tool-output compaction items 进入 dynamic section
- 当前 cache-key 行为会显式纳入：
  - `task_input`
  - `workspace_root`
  - `model_profile`
  - `policy_summary`
  - `tool_manifest`
  - 各 section 的序列化 context items
- 新增测试：
  - `tests/agent_context/test_prompt_layout.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Trust Marking And Prompt-Injection Baseline

- 执行 `P5-CTX-05 - Trust Marking And Prompt-Injection Baseline`
- 新增 `agent_context.trust`：
  - `trust_level_for_item`
  - `prompt_injection_metadata`
- `ContextItem` 现在补充：
  - `trust_level`
  - `metadata`
- 当前 trust baseline：
  - `Repo Map` 标记为 `system`
  - `AGENTS.md` / `README.md` / `pyproject.toml` / `Makefile` 标记为 `trusted`
  - conversation/tool-output summaries 标记为 `user`
  - 代码文件默认标记为 `untrusted`
- 当前 injection baseline：
  - 仅做 suspicious pattern metadata 标记
  - 不做自动拒绝或策略联动
- 新增测试：
  - `tests/agent_context/test_compiler.py` 中的 suspicious-content 标记断言
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
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

## 2026-06-20 SQLite Event Store And Session Projection

- 执行 `P4-STO-01 - SQLite Event Store And Session Projection`
- 新增 `agent-storage` workspace package
- 新增：
  - `SQLiteEventStore`
  - `SQLiteProjectionStore`
  - SQLite 连接与 event row 映射辅助模块
- 当前行为：
  - session events 可按 `session_id + sequence` 顺序持久化和读取
  - 同一 session 的重复 sequence 会被 SQLite 唯一约束拒绝
  - 读取出的 event stream 可以直接喂给 `rebuild_session`
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
  - `tests/agent_storage/test_sqlite_projection_store.py`
- 覆盖场景：
  - append/list session events
  - duplicate sequence rejection
  - replay into session projection
  - save/get session projection
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-storage/src/agent_storage tests/agent_storage tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-20 Event Idempotency Protection

- 执行 `P4-STO-02 - Event Idempotency Protection`
- `SQLiteEventStore` 现在会为 `session_id + idempotency_key` 建立唯一索引
- 当前行为：
  - 同一 session 下，带相同 `idempotency_key` 的重试写入不会产生第二条事件
  - `append()` 在幂等重试时会返回已存在的 durable event
  - 原有 `session_id + sequence` 冲突保护保持不变
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
- 覆盖场景：
  - idempotent retry returns existing event
  - duplicate sequence rejection still works
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py` 通过
  - `uv run ruff check packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `uv run mypy packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-20 Worker Recovery Entry

- 执行 `P4-WKR-01 - Worker Recovery Entry`
- `apps/worker` 新增：
  - `SessionRecoveryService`
  - `RecoveredSession`
  - `SessionRecoveryError`
- 当前行为：
  - worker 可以从 event store 读取一个 session 的完整事件流
  - 通过 `rebuild_session` 重建 durable session 视图
  - recovery 后会把最新 projection 写回 projection store
  - 缺失 session 会以确定性错误失败
- 新增测试：
  - `tests/worker/test_recovery.py`
- 覆盖场景：
  - interrupted running session recovery
  - terminal session recovery
  - missing session failure
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/worker/test_recovery.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-21 SQLite Worker Leases

- 执行 `P4-SCH-01 - SQLite Worker Leases`
- `agent-core` 新增：
  - `WorkerLease`
  - `LeaseStorePort`
- `agent-storage` 新增：
  - `SQLiteLeaseStore`
  - `LeaseConflictError`
- 当前行为：
  - worker 可以为某个 session 申请 lease
  - 未过期 lease 不允许被其他 worker 抢占
  - 过期 lease 可以被后续 worker 重新获取
  - 已持有 worker 可以 heartbeat 更新 checkpoint 和 expiry
  - release 后 lease 会被删除
- 新增测试：
  - `tests/agent_storage/test_sqlite_leases.py`
- 覆盖场景：
  - acquire and read active lease
  - reject other worker before expiry
  - allow reacquire after expiry
  - heartbeat owned lease
  - release owned lease
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_leases.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_storage tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-21 Worker Claim And Resume Flow

- 执行 `P4-WKR-02 - Worker Claim And Resume Flow`
- `apps/worker` 新增：
  - `SessionClaimService`
  - `ClaimedSession`
- 当前行为：
  - worker 可以先恢复 session，再申请 lease 完成 claim
  - claim 结果同时包含 recovery state 和 lease state
  - 已 claim session 可以 heartbeat 续租并推进 checkpoint
  - 可以显式 release claim
- 新增测试：
  - `tests/worker/test_claims.py`
- 覆盖场景：
  - claim running session
  - block concurrent claim before expiry
  - allow takeover after expiry
  - heartbeat and release claim
- 本轮验证结果：
  - `uv run pytest tests/worker/test_claims.py tests/worker/test_recovery.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-21 Core Event Schema Drafts

- 执行 `P4-GOV-01 - Core Event Schema Drafts`
- `agent-core` 新增：
  - `agent_core.contracts`
  - `event_payload_schema_for`
  - `validate_event_payload`
  - `EventPayloadValidationError`
- 当前行为：
  - `SessionCreated`、`UserMessageReceived`、`ToolExecutionCompleted` 已有 machine-checkable payload schema
  - covered payload 默认拒绝未知字段
  - 可以直接生成 JSON Schema dict，供后续 API / storage / docs 复用
- 新增测试：
  - `tests/agent_core/test_event_contracts.py`
- 覆盖场景：
  - schema generation
  - valid payload acceptance
  - unknown field rejection
  - unknown event schema lookup failure
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_event_contracts.py tests/agent_core/test_events.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/contracts tests/agent_core/test_event_contracts.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/contracts tests/agent_core/test_event_contracts.py` 通过
  - `make check` 通过

## 2026-06-21 Event Schema Enforcement

- 执行 `P4-GOV-02 - Event Schema Enforcement`
- `SessionEvent.create()` 现在会对已覆盖的 event payload 执行 schema 校验
- 当前行为：
  - covered event 在创建时即拒绝非法 payload
  - 未覆盖 event 暂时保持 passthrough，避免阻塞后续 schema 逐步补齐
- 新增测试：
  - `tests/agent_core/test_events.py`
- 覆盖场景：
  - invalid covered-event payload rejection
  - uncovered event payload passthrough
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py tests/agent_storage/test_sqlite_event_store.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/domain/events.py tests/agent_core/test_events.py tests/agent_storage/test_sqlite_event_store.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/domain/events.py tests/agent_core/test_events.py` 通过
  - `make check` 通过

## 2026-06-22 Incremental Event Replay

- 执行 `P4-STO-03 - Incremental Event Replay`
- `EventStorePort` 新增 `read_since(session_id, sequence)`
- `SQLiteEventStore` 现在支持按 sequence 增量读取 session 事件
- `SessionRecoveryService` 现在会优先读取已有 projection，并只回放其后的增量事件
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
  - `tests/worker/test_recovery.py`
- 覆盖场景：
  - event-store delta reads
  - projection-based resume with newer events
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/ports/event_store.py packages/agent-storage/src/agent_storage/sqlite.py apps/worker/src/zebra_agent_worker/recovery.py tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/ports/event_store.py packages/agent-storage/src/agent_storage/sqlite.py apps/worker/src/zebra_agent_worker/recovery.py tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `make check` 通过

## 2026-06-22 Explicit Resume Entry

- 执行 `P4-WKR-03 - Explicit Resume Entry`
- `apps/worker` 新增：
  - `SessionResumeService`
  - `ResumedSession`
  - `SessionResumeError`
- 当前行为：
  - worker 可以通过单个 resume entry 完成 claim + recovery
  - terminal session 会被明确拒绝
  - terminal resume 失败后不会遗留 lease
- 新增测试：
  - `tests/worker/test_resume.py`
- 覆盖场景：
  - resume running session
  - reject terminal session without dangling lease
- 本轮验证结果：
  - `uv run pytest tests/worker/test_resume.py tests/worker/test_claims.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-22 Tool Run Index

- 执行 `P4-STO-04 - Tool Run Index`
- `agent-core` 新增：
  - `ToolRunRecord`
  - `ToolRunStorePort`
- `agent-storage` 新增：
  - `SQLiteToolRunStore`
- `apps/worker` 新增：
  - `ToolRunIndexer`
- 当前行为：
  - tool execution event 可以被映射为 durable tool-run record
  - control plane 可以按 session 查询 tool run 索引，而不是每次直接扫描原始 event payload
- 新增测试：
  - `tests/agent_storage/test_sqlite_tool_runs.py`
  - `tests/worker/test_tool_run_index.py`
- 覆盖场景：
  - tool-run upsert and query
  - event-to-tool-run indexing
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/domain/tool_runs.py packages/agent-core/src/agent_core/ports/tool_run_store.py packages/agent-storage/src/agent_storage/tool_runs.py apps/worker/src/zebra_agent_worker/tool_run_index.py tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/domain/tool_runs.py packages/agent-core/src/agent_core/ports/tool_run_store.py packages/agent-storage/src/agent_storage/tool_runs.py apps/worker/src/zebra_agent_worker/tool_run_index.py tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py` 通过
  - `make check` 通过

## 2026-06-22 Runtime Evidence Context Injection

- 执行 `P5-CTX-07 - Runtime Evidence Context Injection`
- `ContextCompileRequest` 新增：
  - `runtime_evidence_items`
- 当前行为：
  - 允许把 `CONVERSATION_SUMMARY` 与 `TOOL_OUTPUT_SUMMARY` 作为 runtime evidence 注入编译输入
  - 这些 items 和普通 context items 一样参与统一 token budget
  - prompt layout 会把它们路由到 dynamic section
- 新增测试：
  - `tests/agent_context/test_runtime_evidence.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Attempt Evidence Feedback Loop

- 执行 `P5-CTX-08 - Attempt Evidence Feedback Loop`
- `agent-core` 新增：
  - `RuntimeEvidenceInput`
- `HarnessLoop` 现在支持：
  - 从 prior attempt result 提取 conversation summary evidence
  - 从 prior attempt result 提取 tool-output evidence
  - 在 retry attempt 前把 evidence 填回 `HarnessTask.runtime_evidence`
- `LocalContextCompiler` 现在支持：
  - 接收抽象 runtime-evidence inputs
  - 把它们压缩成 dynamic context items
- 新增测试：
  - `tests/agent_core/test_harness_runtime_evidence.py`
  - `tests/agent_context/test_adapter.py` 中的 runtime-evidence 渲染场景
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Context-Aware Retry Plan Hint

- 执行 `P5-CTX-10 - Context-Aware Retry Plan Hint`
- `agent-core` 新增：
  - `RetryPlanHint`
  - `build_retry_plan_hint`
- 默认 `NoopPlanner` 现在支持：
  - 在 retry attempt 存在 runtime evidence 时生成 deterministic retry summary
  - 在 planner metadata 中暴露 retry focus、retry blockers、accepted constraints、prior tool outputs
- 当前行为：
  - `planner_summary` 会成为 retry focus
  - failed `verifier_summary` 与 failed `tool_status` 会成为 retry blockers
  - passed `verifier_summary` 会成为 accepted constraints
- 新增测试：
  - `tests/agent_core/test_harness_retry_plan.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `make check` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Harness Context Input Wiring

- 执行 `P5-CTX-06 - Harness Context Input Wiring`
- `agent-core` 新增：
  - `ContextCompilerPort`
  - `HarnessTask.workspace_root`
  - `HarnessTask.context_token_budget`
- `HarnessModelStep` 现在支持：
  - 通过抽象 `ContextCompilerPort` 生成 system message
  - 在 user message 前注入 compiled context prompt
- `agent-context` 新增：
  - `LocalContextCompiler`
- 新增测试：
  - `tests/agent_core/test_harness_model_step.py`
  - `tests/agent_context/test_adapter.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Structured Planner And Verifier Evidence

- 执行 `P5-CTX-09 - Structured Planner And Verifier Evidence`
- `RuntimeEvidenceInput` 新增：
  - `metadata`
- `HarnessLoop` 现在支持：
  - 把 prior attempt 的 planner summary 提取为 `planner_summary`
  - 把 prior attempt 的 verifier result 提取为带 pass/fail metadata 的 `verifier_summary`
  - 把 tool status 与 tool output 分别保留为结构化 evidence
- `LocalContextCompiler` 现在支持：
  - 把 planner summaries 合并进 conversation compaction 的 current plan
  - 把 failed verifier summaries 合并进 unresolved tests
  - 把 passed verifier summaries 合并进 acceptance criteria
- 更新测试：
  - `tests/agent_core/test_harness_runtime_evidence.py`
  - `tests/agent_context/test_adapter.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

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

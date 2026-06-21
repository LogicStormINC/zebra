# Phase 5 Context Compiler 验收记录

## 验收记录

- 阶段：`Phase 5 - Context Compiler`
- 日期：2026-06-22
- 负责人：Codex
- 目标是否完成：完成本地 MVP 验收范围
- 代码入口：
  - `packages/agent-context/src/agent_context/compiler.py`
  - `packages/agent-context/src/agent_context/models.py`
  - `packages/agent-context/src/agent_context/compaction.py`
  - `packages/agent-context/src/agent_context/prompt_layout.py`
  - `packages/agent-context/src/agent_context/trust.py`
  - `packages/agent-context/src/agent_context/adapter.py`
  - `packages/agent-core/src/agent_core/ports/context_compiler.py`
  - `packages/agent-core/src/agent_core/harness/model_step.py`
  - `packages/agent-core/src/agent_core/harness/loop.py`
  - `packages/agent-core/src/agent_core/harness/retry_plan.py`
- 测试命令：
  - `uv run pytest tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py`
  - `uv run ruff check packages/agent-context/src/agent_context packages/agent-core/src/agent_core/ports/context_compiler.py packages/agent-core/src/agent_core/harness/model_step.py packages/agent-core/src/agent_core/harness/loop.py packages/agent-core/src/agent_core/harness/retry_plan.py tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py`
  - `uv run mypy packages/agent-context/src/agent_context packages/agent-core/src/agent_core/ports/context_compiler.py packages/agent-core/src/agent_core/harness/model_step.py packages/agent-core/src/agent_core/harness/loop.py packages/agent-core/src/agent_core/harness/retry_plan.py tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py`
  - `make check`
- 测试结果：通过
- 未完成项：
  - Git commit diff context is still represented by repository file recall, not a dedicated git-context provider.
  - Cache key is deterministic in prompt layout, but no durable cache store has been introduced.
  - Context compaction is local deterministic logic; durable `ContextCompacted` events are deferred until storage or observability follow-up.
- 风险与下一步：
  - Phase 6 should harden policy and approvals around tool execution before expanding context sources.
  - Future context work should add git-aware retrieval and eval-backed ranking after policy boundaries are explicit.

## Phase 5 Acceptance Mapping

- 稳定排序上下文项：`compile_context` scans workspace files, ranks them with `rank_files`, adds repo map and related files, then sorts by priority and locator.
- 来源信息：`ContextItem` requires `ContextProvenance`; scanner, compaction, and repo-map builders all populate provenance.
- Token budget 裁剪：`ContextBudget` and `_apply_budget` enforce total token limits and expose the `truncated` flag.
- 压缩测试覆盖：conversation compaction, tool-output compaction, runtime evidence injection, and prompt layout have deterministic tests.
- Prompt injection baseline：trust metadata marks suspicious file content as untrusted data.
- Harness integration：`ContextCompilerPort`, `HarnessModelStep`, runtime evidence feedback, and retry-plan hints connect compiled context back into multi-attempt execution.

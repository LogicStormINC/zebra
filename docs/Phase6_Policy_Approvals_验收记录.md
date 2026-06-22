# Phase 6 Policy And Approvals Hardening 验收记录

## 验收记录

- 阶段：`Phase 6 - Policy And Approvals Hardening`
- 日期：2026-06-22
- 负责人：Codex
- 目标是否完成：完成本地 MVP 验收范围
- 代码入口：
  - `packages/agent-security/src/agent_security/policy.py`
  - `packages/agent-core/src/agent_core/application/approvals.py`
  - `packages/agent-core/src/agent_core/harness/orchestrator.py`
  - `packages/agent-core/src/agent_core/application/session_projection.py`
  - `packages/agent-core/src/agent_core/domain/sessions.py`
- 测试命令：
  - `uv run pytest tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py`
  - `uv run ruff check packages/agent-security/src/agent_security packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/harness/orchestrator.py packages/agent-core/src/agent_core/domain/sessions.py tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py`
  - `uv run mypy packages/agent-security/src/agent_security packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/harness/orchestrator.py packages/agent-core/src/agent_core/domain/sessions.py tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py`
  - `uv run pytest`
  - `make check`
- 测试结果：通过
- 未完成项：
  - MCP-specific policy rules are deferred until MCP adapter contracts exist.
  - Network egress broker and credential broker are deferred until external integration boundaries exist.
  - Approval API endpoints are deferred to productization or API adapter work; Phase 6 added the reusable application service entry.
- 风险与下一步：
  - Phase 7 should add audit/tracing and replay coverage for policy decisions, approval requests, and approval decisions.
  - Future policy work should move from heuristic local command checks to adapter-aware policy modules when tool surface expands.

## Phase 6 Acceptance Mapping

- 高风险操作拒绝或审批：command shell risk, path traversal, and sensitive-output risks are denied or require approval by `LocalPolicyEngine`.
- 单元测试覆盖：`tests/agent_security/test_policy_profiles.py` covers profiles, command risk, path traversal, sensitive output, and approval request projection.
- 集成路径覆盖：`tests/agent_core/test_single_attempt_orchestrator.py` covers policy approval wiring through the harness event stream.
- 路径越权：`files.read`, `command.run` cwd, `git.status` cwd, and `patch.apply` patch headers have policy-level traversal checks.
- Shell injection：shell interpreters and shell metacharacters in `command.run` require approval.
- 敏感信息泄露：`.env`, private key, secret/token/credential markers and network transfer commands require approval.
- Approval service：`ApprovalDecisionService` builds grant/reject events with sequence and status validation.

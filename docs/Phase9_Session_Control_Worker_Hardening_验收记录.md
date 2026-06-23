# Phase 9 Session Control And Worker Hardening 验收记录

## 验收记录

- 阶段：`Phase 9 - Session Control And Worker Hardening`
- 日期：2026-06-23
- 负责人：Codex
- 目标是否完成：完成本地 session control API 与 worker daemon 语义加固
- 代码入口：
  - `apps/api/src/zebra_agent_api/app.py`
  - `apps/api/src/zebra_agent_api/routes.py`
  - `apps/api/src/zebra_agent_api/session_payloads.py`
  - `apps/worker/src/zebra_agent_worker/loop.py`
  - `apps/worker/src/zebra_agent_worker/main.py`
  - `packages/agent-core/src/agent_core/application/session_messages.py`
  - `packages/agent-core/src/agent_core/application/session_controls.py`
  - `packages/agent-core/src/agent_core/application/approvals.py`
- 测试命令：
  - `uv run pytest tests/api/test_approval_api_app.py tests/api/test_approval_routes.py tests/api/test_http_approvals.py tests/cli/test_cli_commands.py`
  - `uv run pytest tests/worker/test_loop.py tests/worker/test_execution.py tests/worker/test_claims.py tests/worker/test_resume.py`
  - `make check`
- 测试结果：通过
- 未完成项：
  - `GET /sessions/{id}/diff` 仍未开放，operator 还不能通过 API 查看当前工作区差异。
  - `GET /sessions/{id}/artifacts` 仍未开放，tool/model 产物还没有统一查询面。
  - `POST /sessions/{id}/commit` 仍未开放，代码交付动作还没有受控 API 入口。
  - `POST /sessions/{id}/pull-request` 仍未开放，PR 创建仍未进入受控交付面。
- 风险与下一步：
  - 下一阶段应优先补代码交付面，而不是扩散新的 session lifecycle 状态。
  - `diff` 和 `artifacts` 是只读入口，可先落地以支撑 operator review。
  - `commit` 和 `pull-request` 是有副作用入口，需要沿用 policy/approval 思路设计 fail-closed 行为。

## Phase 9 Acceptance Mapping

- 现有 session 可以追加用户消息：
  - `POST /sessions/{id}/messages` 已完成；
  - 相关覆盖在 `tests/api/test_routes.py`、`tests/api/test_http_app.py` 与 `tests/agent_core/test_session_messages.py`。
- 控制面状态可以通过 API 进入取消或挂起：
  - `POST /sessions/{id}/cancel` 与 `POST /sessions/{id}/suspend` 已完成；
  - invalid transition 会返回 deterministic conflict。
- 审批决策可以通过 HTTP 记录：
  - `POST /approvals/{id}/approve` 与 `POST /approvals/{id}/reject` 已完成；
  - HTTP 入口复用 `ApprovalDecisionService`，保持 CLI 与 API 语义一致。
- worker loop 具备 daemon-friendly 运行语义：
  - omitted `--max-cycles` 进入连续 polling；
  - bounded run 输出 `stop_reason`；
  - 多轮 idle polling 不会在最后一轮额外 sleep；
  - 单轮 `--max-cycles 1 --stop-when-idle` 行为继续可用。
- operator 文档已同步：
  - `docs/operator_runbook.md` 覆盖短运行 worker、长运行 worker、session message、cancel/suspend 与 approval HTTP path。

# Phase 10 Code Delivery Surface 验收记录

## 验收记录

- 阶段：`Phase 10 - Code Delivery Surface`
- 日期：2026-06-23
- 负责人：Codex
- 目标是否完成：完成本地代码交付面的只读 review、artifact 查询、local commit 与 PR dry-run planning
- 代码入口：
  - `apps/api/src/zebra_agent_api/app.py`
  - `apps/api/src/zebra_agent_api/routes.py`
  - `apps/api/src/zebra_agent_api/session_commit.py`
  - `apps/api/src/zebra_agent_api/session_context.py`
  - `apps/api/src/zebra_agent_api/session_pull_request.py`
  - `apps/api/src/zebra_agent_api/session_payloads.py`
  - `packages/agent-runtime/src/agent_runtime/git_diff.py`
  - `packages/agent-runtime/src/agent_runtime/git_commit.py`
  - `packages/agent-storage/src/agent_storage/artifacts.py`
  - `packages/agent-security/src/agent_security/delivery.py`
  - `packages/agent-integrations/src/agent_integrations/scm.py`
- 测试命令：
  - `uv run pytest tests/agent_runtime/test_git_diff.py tests/api/test_session_diff.py`
  - `uv run pytest tests/agent_storage/test_artifacts.py tests/api/test_session_artifacts.py`
  - `uv run pytest tests/agent_runtime/test_git_commit.py tests/agent_security/test_delivery_policy.py tests/api/test_session_commit.py`
  - `uv run pytest tests/agent_integrations/test_scm.py tests/agent_security/test_delivery_policy.py tests/api/test_session_pull_request.py`
  - `make check`
- 测试结果：通过
- 未完成项：
  - PR 仍是 local-only dry-run plan，不执行真实 GitHub/SCM 网络调用。
  - side-effect POST 还没有统一 `Idempotency-Key` 处理。
  - commit 与 PR 动作还没有专门的 durable delivery event 或 audit projection。
  - artifact projection 目前组合 model/tool indexes，还不是独立 artifact table。
- 风险与下一步：
  - 下一阶段应先补 side-effect 幂等性与 delivery audit，再接真实远端 PR provider。
  - 真实 PR provider 必须保持 policy/approval gated，不能绕过当前 local-only fail-closed 行为。
  - artifact table 可以在 audit/event 链路稳定后升级，避免过早复制 event payload。

## Phase 10 Acceptance Mapping

- read-only diff review：
  - `GET /sessions/{id}/diff` 已完成；
  - 相关覆盖在 `tests/agent_runtime/test_git_diff.py` 与 `tests/api/test_session_diff.py`。
- artifact review：
  - `GET /sessions/{id}/artifacts` 已完成；
  - 相关覆盖在 `tests/agent_storage/test_artifacts.py` 与 `tests/api/test_session_artifacts.py`。
- local commit：
  - `POST /sessions/{id}/commit` 已完成；
  - commit 需要 `full_access` session policy；
  - 相关覆盖在 `tests/agent_runtime/test_git_commit.py`、`tests/agent_security/test_delivery_policy.py` 与 `tests/api/test_session_commit.py`。
- pull request planning：
  - `POST /sessions/{id}/pull-request` 已完成 local-only dry-run；
  - `dry_run=false` 返回 deterministic unavailable conflict；
  - 相关覆盖在 `tests/agent_integrations/test_scm.py`、`tests/agent_security/test_delivery_policy.py` 与 `tests/api/test_session_pull_request.py`。
- operator 文档已同步：
  - `docs/operator_runbook.md` 覆盖 diff、artifacts、commit 与 pull-request dry-run。

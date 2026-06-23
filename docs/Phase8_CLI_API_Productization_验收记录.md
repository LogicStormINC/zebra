# Phase 8 CLI/API Productization 验收记录

## 验收记录

- 阶段：`Phase 8 - CLI/API Productization`
- 日期：2026-06-23
- 负责人：Codex
- 目标是否完成：完成本地 MVP 的 CLI/API/worker operator 闭环
- 代码入口：
  - `apps/cli/src/zebra_agent_cli/cli.py`
  - `apps/cli/src/zebra_agent_cli/execution.py`
  - `apps/api/src/zebra_agent_api/app.py`
  - `apps/api/src/zebra_agent_api/routes.py`
  - `apps/api/src/zebra_agent_api/http.py`
  - `apps/api/src/zebra_agent_api/responses.py`
  - `apps/api/src/zebra_agent_api/session_payloads.py`
  - `apps/api/src/zebra_agent_api/serialization.py`
  - `apps/worker/src/zebra_agent_worker/execution.py`
  - `apps/worker/src/zebra_agent_worker/loop.py`
  - `apps/worker/src/zebra_agent_worker/main.py`
  - `packages/agent-storage/src/agent_storage/projections.py`
- 测试命令：
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_http_app.py tests/api/test_routes.py tests/agent_storage/test_sqlite_projection_store.py tests/worker/test_loop.py`
  - `make check`
- 测试结果：通过
- 未完成项：
  - `POST /sessions/{id}/messages` 仍未开放，现有 session 还不能通过 API 追加下一轮用户输入。
  - `POST /sessions/{id}/cancel`、`POST /sessions/{id}/suspend` 仍未开放，控制面状态流转还不完整。
  - `POST /approvals/{id}/approve`、`POST /approvals/{id}/reject` 仍未开放，审批 HTTP 入口缺失。
  - `POST /sessions/{id}/commit`、`POST /sessions/{id}/pull-request` 仍未开放，代码交付面还停留在本地 operator 阶段。
  - `zebra-agent-worker` 已具备 polling loop，但还不是偏 daemon 语义的持续运行形态。
- 风险与下一步：
  - 下一阶段应优先补 session control API，而不是继续扩散新的 operator 入口种类。
  - `apps/api/` 的后续工作应按 message -> cancel/suspend -> approval 的顺序推进，避免同路径并行冲突。
  - `apps/worker/` 可以并行推进 continuous loop hardening，但应避免与 `apps/api/` 共用同一任务分支。

## Phase 8 Acceptance Mapping

- CLI 可以创建、恢复、查看任务：
  - `zebra-agent run`、`inspect`、`resume`、`approve` 已完成；
  - `run --execute` 与 `resume --execute` 已接入 durable execution；
  - 相关覆盖在 `tests/cli/test_cli_commands.py`。
- API 可以暴露基础会话和健康检查接口：
  - `GET /health`、`GET /sessions/{id}`、`GET /sessions/{id}/stream`、`POST /sessions`、`POST /sessions/{id}/resume` 已完成；
  - 相关覆盖在 `tests/api/test_http_app.py` 与 `tests/api/test_routes.py`。
- 主要操作有清晰的 operator 使用方式：
  - `docs/operator_runbook.md` 已覆盖 CLI durable run、CLI/API resume、worker loop、API serve 与 SSE readback；
  - `README.md` 已同步当前 operator surface。
- queued session 可被后续 worker 恢复：
  - create-only session 会持久化 bootstrap events 并进入 `ready`；
  - worker 可以通过 `SessionExecutionService` 与 `WorkerLoopService` 恢复并执行 ready session。
- Phase 8 主线已对齐：
  - `P8-CLI-06`、`P8-API-07`、`P8-WKR-05` 已通过 `P8-INT-01` 合流到 `main`。

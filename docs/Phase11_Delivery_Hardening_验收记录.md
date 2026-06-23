# Phase 11 Delivery Hardening 验收记录

## 范围

Phase 11 聚焦交付面加固，不把真实远程 SCM side effect 作为默认行为。

已完成任务：

- `P11-API-01 - Side Effect Idempotency Keys`
- `P11-OBS-01 - Delivery Audit Events`
- `P11-INT-01 - GitHub Pull Request Provider Skeleton`

## 验收结果

### Side Effect Idempotency

- `POST /sessions/{id}/commit` 支持 `Idempotency-Key`。
- `POST /sessions/{id}/pull-request` 支持 `Idempotency-Key`。
- 同 key 同 payload 重放首次响应。
- 同 key 不同 payload 返回确定性 `idempotency_conflict`。
- 缺失 idempotency key 时响应显式包含 `idempotency_key=null`。

### Delivery Audit

- commit 成功、policy blocked、unavailable 均写入 delivery audit。
- pull-request dry-run、policy blocked、unavailable 均写入 delivery audit。
- audit 记录包含 session、action、status、HTTP 状态、policy profile、idempotency key 和结果 metadata。
- 幂等重放不会重复写入 delivery audit。

### GitHub Provider Skeleton

- `LocalOnlyPullRequestGateway` 仍是 API 默认行为。
- `GitHubPullRequestGateway` 可以生成 dry-run request payload。
- GitHub non-dry-run 缺 token 时在网络调用前失败。
- GitHub non-dry-run 即使有 token 也仍 fail-closed，因为真实执行尚未实现。
- request payload 的 token header 只输出 `Bearer <redacted>`。

## 验证命令

```bash
uv run pytest tests/agent_storage/test_idempotency.py tests/agent_storage/test_delivery_audit.py tests/api/test_session_commit.py tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py
make check
make test
```

最近验证结果：

- `make check`: passed
- `make test`: `327 passed`

## 风险与下一步

- 真实 GitHub PR 创建尚未接入 API，下一阶段必须先补 SCM 配置和 provider selection，再考虑 network execution。
- GitHub token 只能通过显式配置和 future credential boundary 接入，不能硬编码到代码或文档。
- delivery audit 目前是存储能力和测试覆盖，尚未暴露 read API；如果运营需要 UI/CLI 查询，应拆为独立任务。
- Phase 12 应保持 local-only 默认值，远程 SCM 执行必须显式 opt-in。

# Phase 12 Remote SCM Configuration 验收记录

## 范围

Phase 12 聚焦远程 SCM 前置配置、provider selection 和只读审计查询，不启用真实 GitHub side effect。

已完成任务：

- `P12-CONFIG-01 - SCM Provider Settings`
- `P12-INT-01 - Pull Request Gateway Selection`
- `P12-API-01 - Delivery Audit Read API`

## 验收结果

### SCM Provider Settings

- 默认 SCM provider 为 `local-only`。
- GitHub provider 必须显式配置 owner、repo 和 token env name。
- 配置只保存 token 环境变量名，不保存 token 值。
- `configs/default.env` 和 `.env.example` 已包含安全默认值。

### Pull Request Gateway Selection

- API 默认仍使用 local-only PR gateway。
- 显式 GitHub settings 可选择 GitHub dry-run gateway。
- GitHub dry-run 返回可审查 request payload。
- GitHub non-dry-run 仍 fail-closed，真实远程执行尚未实现。
- delivery audit 记录所选 provider 的结果 metadata。

### Delivery Audit Read API

- `GET /sessions/{id}/delivery-audit` 可查询单个 session 的 delivery audit。
- 无记录时返回显式空列表。
- 响应包含 action、status、status code、policy profile、idempotency key、metadata 和 timestamp。
- 读取接口不触发任何 side effect。

## 验证命令

```bash
uv run pytest tests/config/test_settings.py tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_session_delivery_audit.py
make check
make test
```

最近验证结果：

- `make check`: passed
- `make test`: `338 passed`

## 风险与下一步

- `apps/api/src/zebra_agent_api/app.py` 当前 489 行，后续新增 API 前必须先拆分 composition。
- GitHub live PR execution 仍未实现，必须在 credential boundary、policy 和 audit 全部明确后再启用。
- 下一阶段应先处理 API composition split，再定义 remote SCM execution 的最小安全切片。

# Phase 13 API Composition And Guarded SCM Execution 验收记录

## 范围

Phase 13 聚焦两个目标：

- 先拆分 API composition，避免继续突破单文件长度限制。
- 在 credential boundary 之后加入第一条 guarded GitHub PR execution 路径。

已完成任务：

- `P13-API-01 - API Composition Split`
- `P13-SEC-01 - SCM Credential Boundary Draft`
- `P13-INT-01 - Guarded GitHub Pull Request Execution`

## 验收结果

### API Composition Split

- `apps/api/src/zebra_agent_api/app.py` 从 489 行降到 384 行。
- read-only session API 已移动到 `session_read.py`。
- route 和 HTTP 行为保持不变。
- 后续 API 扩展有明确模块边界。

### SCM Credential Boundary

- token env name 和 token value 明确分离。
- settings snapshot 只包含 token env name，不包含 token value。
- credential redaction 固定输出 `<redacted>`。
- local-only 不产生 token capability。

### Guarded GitHub PR Execution

- local-only 仍是默认 provider。
- GitHub execution 需要显式 provider、`ZEBRA_SCM_PULL_REQUEST_DRY_RUN=false`、token 可用和 `full_access` policy。
- 缺 token 时在网络调用前失败。
- 测试使用 fake transport，不依赖 live GitHub。
- 默认 HTTP transport 已拆到 `agent_integrations/github.py`，`scm.py` 保持在目标行数内。

## 验证命令

```bash
uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py tests/api/test_session_diff.py tests/api/test_session_artifacts.py tests/api/test_session_delivery_audit.py
uv run pytest tests/agent_security/test_credentials.py tests/config/test_settings.py
uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py
make check
make test
```

最近验证结果：

- `make check`: passed
- `make test`: `345 passed`

## 风险与下一步

- 真实 GitHub execution 已存在 guarded path，但仍应优先补失败分类、审计明细和 operator safety checks。
- 继续扩展 GitHub 行为前，应保持 local-only 默认，并避免在测试中依赖 live GitHub。
- Phase 14 应聚焦 post-execution hardening，而不是增加更多远程 side effect。

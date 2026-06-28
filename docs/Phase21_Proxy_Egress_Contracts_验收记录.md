# Phase 21 Proxy Egress Contracts 验收记录

## Scope

Phase 21 turned the earlier egress-policy foundation into explicit proxy-oriented contracts for both SCM and MCP-style tool paths.

The phase did not broaden default execution permissions. Instead, it introduced the minimal transport, routing, and operator contracts needed before proxy-backed remote execution can become a first-class runtime path.

## Completed Tasks

### P21-INT-01 - SCM Proxy Transport Contract

Implemented behavior:

- Added `ScmProxyRequest`, `ScmProxyResponse`, and `ScmProxyTransport`.
- Added deterministic serialization helpers for proxy request and response payloads.
- Added `build_github_pull_request_proxy_request(...)` as the first SCM-specific proxy request builder.
- Kept the proxy contract separate from the direct GitHub HTTP transport path.

Validation:

- `poetry run pytest tests/agent_integrations/test_scm_proxy.py tests/agent_integrations/test_scm.py`
- `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations`
- `uv run mypy packages/agent-integrations/src/agent_integrations/scm_proxy.py tests/agent_integrations/test_scm_proxy.py`
- `make check`

### P21-INT-02 - GitHub Proxy Pull Request Adapter

Implemented behavior:

- Added `GitHubProxyPullRequestTransport`.
- Added `ScmHttpProxyTransport` as the first HTTP-backed proxy transport adapter.
- Added environment-driven transport selection through:
  - `ZEBRA_SCM_GITHUB_TRANSPORT`
  - `ZEBRA_SCM_PROXY_ENDPOINT`
- Preserved existing credential and egress-policy classification while allowing GitHub PR execution to route through the proxy-backed adapter.
- Kept the direct transport path explicit and backwards compatible.

Validation:

- `poetry run pytest tests/agent_integrations/test_scm_proxy.py tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
- `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations tests/api/test_session_pull_request.py`
- `make check`

### P21-TOOL-01 - MCP Proxy Egress Starter Contract

Implemented behavior:

- Added `McpToolTarget`, `McpProxyRequest`, `McpProxyResponse`, and `McpProxyTransport`.
- Defined `mcp.<server>.<tool>` as the initial MCP tool naming contract.
- Added `build_mcp_proxy_request(...)` and `parse_mcp_tool_name(...)`.
- Added policy-facing egress metadata through:
  - `ToolEgressRoute`
  - `ToolEgressMetadata`
  - `classify_tool_egress(...)`
- Distinguished:
  - builtin/local tool paths as `route=local`
  - proxy-routable MCP calls as `route=mcp_proxy`
  - blocked MCP calls under non-proxy profiles as `route=blocked`
- Refactored `agent_tools.__init__` to lazy exports so the new starter contracts do not reintroduce the package initialization cycle.

Validation:

- `poetry run pytest tests/agent_tools/test_mcp_proxy.py tests/agent_security/test_mcp_proxy_policy.py tests/agent_tools/test_executor.py`
- `uv run ruff check packages/agent-tools/src/agent_tools packages/agent-security/src/agent_security tests/agent_tools tests/agent_security`
- `uv run mypy packages/agent-tools/src/agent_tools/__init__.py packages/agent-tools/src/agent_tools/mcp_proxy.py packages/agent-security/src/agent_security/mcp_proxy_policy.py tests/agent_tools/test_mcp_proxy.py tests/agent_security/test_mcp_proxy_policy.py`
- `make check`

### P21-DOC-01 - Proxy Egress Operator Docs

Implemented behavior:

- Updated `docs/operator_runbook.md` with:
  - proxy-backed SCM transport configuration
  - transport-selection guidance for direct versus proxy execution
  - proxy failure remediation and rollback guidance
  - MCP proxy starter routing guidance
- Updated `README.md` and `PROGRESS.md` so repository state reflects the new proxy-oriented egress model.

Validation:

- `make check`

## Acceptance Summary

- SCM now has both a standalone proxy transport contract and a proxy-backed GitHub PR adapter.
- MCP now has a starter proxy contract and policy-facing egress metadata without broadening the default local execution posture.
- Operator docs explain how to choose direct versus proxy-backed SCM execution and how MCP proxy starter routing behaves.
- Default local posture remains fail-closed until future phases wire actual proxy-backed execution paths more broadly.

## Validation Notes

- Targeted Phase 21 regression suites passed.
- `make check` passed.
- Full `make test` was not rerun in this closeout slice because the repo still carries the known unrelated worker lease test blocker recorded in earlier progress notes.

## Known Deferrals

- No end-to-end MCP gateway execution path exists yet.
- SCM proxy execution currently focuses on the GitHub PR adapter only.
- Proxy-side audit normalization and broader gateway health semantics remain future work.

## Next Phase

Phase 22 should turn the current proxy contracts into runtime gateway execution paths:

- execute MCP proxy requests through the tool gateway
- normalize proxy-backed audit metadata across SCM and MCP paths
- wire proxy route policy decisions deeper into execution flow
- extend operator documentation and acceptance evidence for gateway-backed proxy execution

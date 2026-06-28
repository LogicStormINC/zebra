# Phase 22 Proxy Execution And Gateway Wiring 验收记录

## Scope

Phase 22 turned the Phase 21 proxy-oriented contracts into concrete runtime and
operator paths.

The phase did not broaden default execution permissions. Instead, it made proxy
execution observable, policy-aware, and operationally reviewable while keeping
`network_profile=none` as the fail-closed default.

## Completed Tasks

### P22-TOOL-01 - MCP Proxy Gateway Execution Path

Implemented behavior:

- Added `McpProxyToolGateway` as the concrete execution path for
  `mcp.<server>.<tool>` calls.
- Updated `ToolExecutor` so unknown MCP-named tools can execute through the proxy
  gateway when that gateway is explicitly wired in.
- Preserved builtin local tool execution behavior.
- Kept failed MCP proxy execution deterministic through tool-result metadata.

Validation:

- `poetry run pytest tests/agent_tools/test_executor.py tests/agent_tools/test_mcp_proxy.py tests/agent_security/test_mcp_proxy_policy.py`
- `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/agent_security`
- `uv run mypy packages/agent-tools/src/agent_tools/__init__.py packages/agent-tools/src/agent_tools/executor.py packages/agent-tools/src/agent_tools/mcp_gateway.py packages/agent-tools/src/agent_tools/mcp_proxy.py tests/agent_tools/test_executor.py tests/agent_tools/test_mcp_proxy.py`
- `make check`

### P22-OBS-01 - Proxy Audit Metadata Normalization

Implemented behavior:

- Normalized proxy-backed SCM and MCP execution metadata around:
  - `route`
  - `proxy_target`
  - `proxy_transport`
- Preserved deterministic failure classification for proxy transport failures.
- Updated API pull-request responses and delivery-audit records to carry the same
  proxy metadata shape as runtime MCP execution.

Validation:

- `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_session_delivery_audit.py tests/agent_tools/test_executor.py`
- `uv run ruff check packages/agent-integrations/src/agent_integrations packages/agent-tools/src/agent_tools apps/api/src/zebra_agent_api tests/agent_integrations tests/api tests/agent_tools`
- `make check`

### P22-SEC-01 - Proxy Route Policy Integration

Implemented behavior:

- Extended `LocalPolicyEngine` to classify MCP tools against the current
  `network_profile` before execution.
- Distinguished deterministic policy outputs for:
  - local builtin tool paths
  - proxy-routed MCP approval paths
  - fail-closed blocked MCP routes
- Extended `ApprovalRequest` so approval-facing scope can include:
  - `route`
  - `target`
  - `network_profile`
- Preserved the fail-closed default under `network_profile=none`.

Validation:

- `poetry run pytest tests/agent_security/test_policy_profiles.py tests/agent_security/test_mcp_proxy_policy.py`
- `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
- `uv run mypy packages/agent-security/src/agent_security/policy.py tests/agent_security/test_policy_profiles.py tests/agent_security/test_mcp_proxy_policy.py`
- `make check`

### P22-DOC-01 - Proxy Gateway Operator Docs

Implemented behavior:

- Added `docs/proxy_gateway_operator_runbook.md` for proxy-backed SCM and MCP
  operator guidance.
- Split proxy-specific content out of `docs/operator_runbook.md` so the main
  runbook returns below the markdown file-size limit.
- Documented:
  - the difference between Phase 21 starter contracts and Phase 22 concrete gateway execution
  - audit and trace interpretation for SCM and MCP proxy flows
  - rollback steps that restore fail-closed defaults

Validation:

- `make check`

## Acceptance Summary

- MCP proxy requests now have a concrete tool-gateway execution path.
- SCM proxy-backed pull-request execution and MCP proxy execution share stable
  metadata fields for route and transport interpretation.
- Policy and approval outputs now distinguish local, proxy-routed, and blocked
  MCP tool paths deterministically.
- Operator runbooks now explain how to inspect proxy-backed SCM and MCP flows
  and how to roll back to safe defaults.

## Validation Notes

- Targeted Phase 22 regression suites passed for tool execution, policy, API, and
  SCM integration surfaces.
- `make check` passed after each major slice and in the documentation closeout.
- Full `make test` was not rerun in this closeout slice because the touched areas
  were already covered by targeted regression suites plus the repository release gate.

## Known Deferrals

- Proxy-aware approval metadata is not yet projected through all core event,
  approval, and session readback surfaces.
- MCP proxy execution currently relies on runtime and tool metadata rather than a
  dedicated operator read API.
- SCM proxy execution remains focused on the GitHub pull-request path.

## Next Phase

Phase 23 should project proxy-aware approval and policy metadata through durable
readback surfaces:

- persist proxy-aware policy and approval metadata into harness events
- expose proxy approval context through operator-facing session and approval reads
- keep proxy execution evidence coherent across policy, trace, and API surfaces

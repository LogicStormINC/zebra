# Proxy Gateway Operator Runbook

## Purpose

This runbook documents the current operator model for proxy-backed SCM and MCP
execution paths in Phase 22.

Use this document when you need to:

- review proxy-backed SCM pull-request execution
- understand how MCP proxy gateway execution differs from the starter-contract phase
- inspect audit or tool metadata for proxy-routed paths
- roll the system back to fail-closed local defaults after testing or incidents

## Phase 22 Delta

Phase 21 established contracts only:

- SCM proxy request and response models
- GitHub proxy transport selection
- MCP proxy request and response models
- policy-facing MCP egress classification

Phase 22 adds concrete gateway behavior:

- `ToolExecutor` can execute `mcp.<server>.<tool>` through `McpProxyToolGateway`
- SCM proxy-backed pull-request execution and MCP proxy execution share stable
  `route`, `proxy_target`, and `proxy_transport` metadata
- local policy evaluation and approval requests now distinguish:
  - local builtin tool paths
  - proxy-routed MCP tool paths
  - fail-closed blocked MCP routes

This means the proxy path is no longer only a planned contract. Operators can
now inspect deterministic runtime evidence for both SCM and MCP proxy flows.

## Default Safety Posture

Start from the safe baseline unless the current task explicitly requires remote
or proxy-backed execution:

```bash
export ZEBRA_SCM_PROVIDER=local-only
export ZEBRA_SCM_PULL_REQUEST_DRY_RUN=true
export ZEBRA_SCM_NETWORK_PROFILE=none
unset ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST
export ZEBRA_SCM_GITHUB_TRANSPORT=direct
unset ZEBRA_SCM_PROXY_ENDPOINT
```

For MCP-related work, the same fail-closed posture applies:

- keep `network_profile=none` unless MCP proxy execution is intentionally required
- use `network_profile=mcp-proxy-only` when MCP tools must egress only through the proxy
- do not treat `mcp-proxy-only` as permission for direct SCM or direct HTTP execution

## SCM Proxy Configuration

Current SCM settings surface:

```bash
ZEBRA_SCM_PROVIDER=local-only
ZEBRA_GITHUB_OWNER=
ZEBRA_GITHUB_REPO=
ZEBRA_GITHUB_TOKEN_ENV=
ZEBRA_GITHUB_API_BASE_URL=https://api.github.com
ZEBRA_SCM_PULL_REQUEST_DRY_RUN=true
ZEBRA_SCM_NETWORK_PROFILE=none
ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST=
ZEBRA_SCM_GITHUB_TRANSPORT=direct
ZEBRA_SCM_PROXY_ENDPOINT=
```

Rules:

- `local-only` remains the default SCM provider
- `github` must be selected explicitly with `ZEBRA_SCM_PROVIDER=github`
- `ZEBRA_GITHUB_TOKEN_ENV` stores only the env var name, never the token value
- `ZEBRA_SCM_GITHUB_TRANSPORT=proxy` requires `ZEBRA_SCM_PROXY_ENDPOINT`
- `ZEBRA_SCM_NETWORK_PROFILE=none` remains the default fail-closed posture
- direct SCM execution is allowed only when the network profile and transport
  explicitly permit it

## MCP Proxy Configuration

Current MCP proxy routing requires:

- MCP tool names in the form `mcp.<server>.<tool>`
- a wired `McpProxyToolGateway`
- a policy path whose `network_profile` allows MCP proxy routing

Current route behavior:

- local builtin tools stay on `route=local`
- MCP tools under `mcp-proxy-only` or `full-trusted-local` become proxy-routed approval paths
- MCP tools under other profiles are blocked before execution

Approval requests for MCP tools now include:

- `route`
- `target`
- `network_profile`

This is the key difference from the starter-contract phase: operators no longer
see only classification helpers, they now get approval-facing scope data that
matches the actual gateway route.

## SCM Proxy Execution Flow

1. Keep `dry_run=true` and confirm payload shape first.
2. Switch to `ZEBRA_SCM_PROVIDER=github` only when the repository target is intentional.
3. Keep `ZEBRA_SCM_NETWORK_PROFILE=none` and verify that live execution is still blocked.
4. Only then widen the network profile or transport configuration.
5. Review audit metadata immediately after each request.

Example dry-run path:

```bash
export ZEBRA_SCM_PROVIDER=github
export ZEBRA_GITHUB_OWNER=<owner>
export ZEBRA_GITHUB_REPO=<repo>
export ZEBRA_GITHUB_TOKEN_ENV=ZEBRA_GITHUB_TOKEN
export ZEBRA_SCM_PULL_REQUEST_DRY_RUN=true
export ZEBRA_SCM_NETWORK_PROFILE=none
unset ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/pull-request \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pr-github-dry-run-1" \
  -d '{"title":"GitHub dry run PR","body":"Review payload only.","head_branch":"feature/zebra","dry_run":true}'
```

Expected result:

- `provider=github`
- `status=dry_run`
- no network mutation
- delivery audit records `dry_run=true`

Example live proxy-backed path:

```bash
export ZEBRA_GITHUB_TOKEN=<token>
export ZEBRA_SCM_PULL_REQUEST_DRY_RUN=false
export ZEBRA_SCM_NETWORK_PROFILE=domain-allowlist
export ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST=api.github.com
export ZEBRA_SCM_GITHUB_TRANSPORT=proxy
export ZEBRA_SCM_PROXY_ENDPOINT=http://127.0.0.1:9000/scm
```

Required preconditions:

- the session was created with `policy_profile=full_access`
- the reviewed dry-run payload is acceptable
- the token value exists only in the API process environment
- the default broker can issue `pull_request:create` for `repo:<owner>/<repo>`
- the proxy endpoint is intentionally selected and reachable

## MCP Proxy Execution Flow

Current MCP proxy execution evidence is runtime-level rather than HTTP-level.
Operators should inspect:

- policy decision reason
- approval request scope
- tool result metadata
- trace or audit records that persist those metadata fields

Proxy-routed MCP policy example:

- tool name: `mcp.github.create_pull_request`
- network profile: `mcp-proxy-only`
- decision: `require_approval`
- reason: proxy-routed external tool execution
- approval scope includes:
  - `tool:mcp.github.create_pull_request`
  - `route:mcp_proxy`
  - `network_profile:mcp-proxy-only`
  - `target:github.create_pull_request`

Blocked MCP policy example:

- tool name: `mcp.github.create_pull_request`
- network profile: `none`
- decision: `deny`
- reason: network profile does not allow MCP proxy egress

Successful MCP proxy execution metadata currently includes:

- `route=proxy`
- `proxy_target=<server>.<tool>`
- `proxy_transport=mcp_proxy`
- `server_name`
- `tool_name`

This is the runtime evidence that proves the gateway path, rather than only the
starter-contract classification.

## Audit And Trace Interpretation

For SCM proxy-backed pull-request paths, inspect:

- `route`
- `proxy_target`
- `proxy_transport`
- `provider`
- `status`
- `failure_class`
- `credential_source`
- `credential_backend`

Interpretation guidance:

- `route=proxy` with `proxy_transport=scm_http_proxy` means the local process
  sent the request through the SCM proxy adapter
- `failure_class=transport_failure` with proxy transport means inspect the proxy
  endpoint, proxy response shape, and proxy upstream connectivity first
- `failure_class=egress_policy` means the network profile blocked execution
  before credential or transport side effects

For MCP proxy-backed tool execution, inspect:

- policy decision reason
- approval request `route`, `target`, and `network_profile`
- tool result `route`, `proxy_target`, and `proxy_transport`

Interpretation guidance:

- policy `route:mcp_proxy` plus tool result `route=proxy` means the call was
  both approved for proxy routing and executed through the proxy gateway
- policy `route:mcp_proxy` without execution means the flow is waiting for
  approval or was halted before tool execution
- policy denial under `network_profile=none` confirms fail-closed behavior is intact

## Failure Handling

SCM proxy-backed failures:

- If `reason=ZEBRA_SCM_PROXY_ENDPOINT is required when ZEBRA_SCM_GITHUB_TRANSPORT=proxy`,
  the operator selected proxy mode without wiring the endpoint.
- If `failure_class=transport_failure`, inspect proxy availability before retrying.
- If `failure_class=credential_missing`, confirm the configured token env var exists
  and is non-empty in the credential backend.
- If `failure_class=credential_denied`, confirm the broker grants
  `pull_request:create` for the requested repository audience.

MCP proxy-backed failures:

- If policy denies the tool under `network_profile=none`, do not bypass the block;
  widen the profile only when MCP proxy egress is intentional.
- If policy approves proxy routing but no execution metadata is produced, inspect
  approval handling or gateway wiring before retrying.
- If tool execution returns proxy transport failures, inspect the proxy service and
  upstream target availability before changing policy.

## Rollback

After any proxy-backed test or incident, return to safe defaults:

```bash
export ZEBRA_SCM_PROVIDER=local-only
export ZEBRA_SCM_PULL_REQUEST_DRY_RUN=true
export ZEBRA_SCM_NETWORK_PROFILE=none
unset ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST
export ZEBRA_SCM_GITHUB_TRANSPORT=direct
unset ZEBRA_SCM_PROXY_ENDPOINT
```

Rollback checklist:

- stop using proxy-backed SCM transport unless the incident review explicitly keeps it enabled
- restore `network_profile=none` for fail-closed defaulting
- confirm MCP tools again produce blocked policy outputs under the default profile
- record the incident window and affected session ids in operator notes or worklog

## Validation Commands

Use repository validation before or after proxy-configuration changes:

```bash
make test
make check
```

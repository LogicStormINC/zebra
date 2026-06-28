# Phase 20 Egress Control Foundations 验收记录

## Scope

Phase 20 completed the first explicit egress-control foundation for Zebra Agent.

The phase turned the earlier credential-first SCM execution path into a fail-closed network-aware flow by:

- defining deterministic network-profile contracts
- guarding remote GitHub PR execution against those profiles before credential lookup or transport side effects
- documenting operator remediation and rollback procedures

This phase still does not introduce proxy-backed remote transport. Direct GitHub execution remains intentionally narrow.

## Completed Tasks

### P20-SEC-01 - Network Profile Contract

Implemented behavior:

- Added `NetworkProfileName` with the supported profiles:
  - `none`
  - `setup-only`
  - `domain-allowlist`
  - `mcp-proxy-only`
  - `git-proxy-only`
  - `full-trusted-local`
- Added `NetworkProfile` and `parse_network_profile(...)` with deterministic validation.
- Preserved `DEFAULT_NETWORK_PROFILE=none` as the fail-closed local default.
- Rejected ambiguous configurations such as blank profile names, invalid profile names, invalid allowlist entries, and allowlists attached to non-allowlist profiles.

Validation:

- `poetry run pytest tests/agent_security/test_network_profile.py tests/agent_security/test_secret_store.py tests/agent_security/test_policy_profiles.py`
- `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
- `uv run mypy packages/agent-security/src/agent_security tests/agent_security`
- `make check`

### P20-INT-01 - SCM Transport Egress Guard

Implemented behavior:

- Added network-profile loading for SCM execution through:
  - `ZEBRA_SCM_NETWORK_PROFILE`
  - `ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST`
- Added a pre-transport egress gate to GitHub PR execution.
- Ensured the gate runs before credential lookup and before remote transport side effects.
- Added deterministic blocked-execution metadata:
  - `failure_class=egress_policy`
  - `network_profile=<profile>`
  - `target_host=<host>`
- Preserved dry-run and local-only behavior without widening the default operator path.
- Preserved existing credential and transport failure classification when egress is explicitly allowed.

Current direct GitHub transport policy:

- allowed:
  - `full-trusted-local`
  - `domain-allowlist` when the configured GitHub API host is present in the allowlist
- blocked:
  - `none`
  - `setup-only`
  - `mcp-proxy-only`
  - `git-proxy-only`

Validation:

- `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
- `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations tests/api/test_session_pull_request.py`
- `make check`

### P20-DOC-01 - Egress Control Operator Docs

Implemented behavior:

- Updated `docs/operator_runbook.md` with:
  - explicit network-profile environment variables
  - default-blocked live-execution example
  - remediation guidance for `egress_policy`
  - guidance that distinguishes egress failures from credential and transport failures
  - rollback steps that restore `network_profile=none`
- Updated `README.md` and `PROGRESS.md` so the repository state reflects the new egress model.

Validation:

- `make check`

## Acceptance Summary

- Network profiles are now explicit, deterministic, and fail-closed by default.
- Remote SCM execution is blocked unless the current operator environment explicitly allows the configured GitHub API host or opts into `full-trusted-local`.
- Delivery audit now distinguishes egress-policy failures from credential and transport failures.
- Operator docs preserve the safe default posture and explain how to broaden access intentionally and narrowly.

## Validation Notes

- Targeted Phase 20 regression suites passed.
- `make check` passed.
- Full `make test` was not rerun in this closeout slice because the repo still carries the known unrelated worker lease test blocker recorded in earlier progress notes.

## Known Deferrals

- No proxy-backed SCM transport exists yet.
- `git-proxy-only` and `mcp-proxy-only` remain policy states without corresponding runtime adapters.
- Egress rules are currently environment-driven for the local operator path; no broader multi-tenant control plane exists yet.

## Next Phase

Phase 21 should turn the current direct-gate foundation into proxy-capable transport paths:

- define a proxy transport contract for SCM execution
- add a proxy-backed GitHub PR adapter
- define MCP proxy egress starter contracts
- extend operator docs and acceptance evidence for proxy-backed flows

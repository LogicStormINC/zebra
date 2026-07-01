# Phase 19 Secret Store And Broker Credentials 验收记录

## Scope

Phase 19 completed the local secret-store and provider-backed credential foundation needed before broader networked execution paths are expanded.

The phase introduced a secret-store Port, a local secret-store backend, and a guarded GitHub App credential adapter skeleton without widening the default operator execution path.

## Completed Tasks

### P19-SEC-01 - Secret Store Port And Redaction Contract

Implemented behavior:

- Added `SecretStore` as the Port for secret retrieval by handle.
- Added `SecretMaterial` with redacted snapshots and hidden runtime values in `repr`.
- Added deterministic `SecretMissingError` and `SecretUnavailableError` semantics.
- Added `InMemorySecretStore` as a deterministic fake for tests.
- Updated credential broker foundation docs to anchor future non-environment backends to the new Port.

Validation:

- `poetry run pytest tests/agent_security/test_secret_store.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py tests/agent_security/test_environment_broker.py`
- `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
- `uv run mypy packages/agent-security/src/agent_security tests/agent_security`

### P19-SEC-02 - Local Secret Store Backend

Implemented behavior:

- Added `LocalSecretStore` backed by per-handle JSON secret documents under a local root directory.
- Added `get_secret_value(...)` as the broker-facing helper for retrieving raw secret material through the Port.
- Enforced traversal rejection and handle validation for local secret lookup.
- Preserved separation between missing-secret and unavailable-backend failures.

Validation:

- `poetry run pytest tests/agent_security/test_secret_store.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py tests/agent_security/test_environment_broker.py`
- `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
- `uv run mypy packages/agent-security/src/agent_security tests/agent_security`
- `make check`

### P19-INT-01 - GitHub App Credential Adapter Skeleton

Implemented behavior:

- Added `GitHubAppCredentialBroker`, `GitHubAppCredentialBinding`, `GitHubAppInstallationToken`, and `GitHubAppTokenTransport`.
- GitHub App credential exchange now reads private-key material through `SecretStore` rather than environment variables.
- Existing SCM credential lookup path now preserves broker backend metadata, including `credential_backend=github_app`.
- Provider-backed missing, denied, unavailable, and transport failures remain classifiable in SCM delivery-audit metadata.
- Operator documentation identifies the GitHub App adapter as a guarded future execution path rather than the default operator path.

Validation:

- `poetry run pytest tests/agent_integrations/test_github_app.py tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
- `uv run ruff check packages/agent-integrations/src/agent_integrations packages/agent-security/src/agent_security tests/agent_integrations tests/api/test_session_pull_request.py`
- `uv run mypy packages/agent-integrations/src/agent_integrations packages/agent-security/src/agent_security tests/agent_integrations`
- `make check`

## Acceptance Summary

- Secret retrieval is now abstracted behind a redacted Port and local backend.
- Provider-backed GitHub App credential exchange can be injected through the broker boundary without leaking secret material into API responses or audit metadata.
- Existing SCM audit classification remains intact across provider-backed missing, denied, unavailable, and transport failure paths.
- Default operator behavior remains broker-first with local environment-backed credentials; GitHub App flow is still guarded and non-default.

## Validation Notes

- Targeted Phase 19 regression suites passed.
- `make check` passed.
- Full `make test` was not rerun in this closeout slice because the repo still carries the known unrelated worker lease test blocker recorded in Phase 18 closeout.

## Known Deferrals

- No production GitHub App transport is wired into default API composition.
- No OS keychain, Vault, KMS, or cloud secret manager backend exists yet.
- Network egress policy is still broader architecture work beyond the current credential foundation slice.

## Next Phase

Phase 20 should turn the current credential foundation into explicit egress control:

- define network profile contracts and deterministic validation
- enforce SCM and external transport behavior against those profiles
- document operator expectations for guarded egress paths

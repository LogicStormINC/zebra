# Phase 16 Local Credential Backend And API Wiring 验收记录

## Scope

Phase 16 added the first concrete local credential backend and wired API pull-request composition through the broker boundary.

The phase preserved local-only and GitHub dry-run defaults. It did not add durable secret storage.

## Completed Tasks

### P16-SEC-01 - Local Environment Credential Broker

Implemented behavior:

- Added `EnvironmentCredentialBinding`.
- Added `EnvironmentCredentialBroker`.
- Broker issues `CredentialCapability` values from configured environment variable names.
- Missing environment values raise `CredentialMissingError`.
- Unsupported provider or requested scopes raise `CredentialDeniedError`.
- Raw token values are excluded from broker repr, capability repr, and redacted snapshots.

Validation:

- `uv run pytest tests/agent_security/test_environment_broker.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py`
- `make check`
- `make test`

### P16-APP-01 - API Credential Broker Composition

Implemented behavior:

- `ZebraAgentApi` can receive a credential broker dependency.
- `create_app` and `create_http_app` support optional broker and GitHub transport injection.
- GitHub non-dry-run API tests can use a broker-issued test capability.
- Missing broker credentials fail before network execution and record delivery audit metadata.
- Default local-only and GitHub dry-run behavior remains unchanged.

Validation:

- `uv run pytest tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py tests/agent_security/test_environment_broker.py`
- `make check`
- `make test`

## Acceptance Summary

- Local environment-backed credentials are available behind the broker Port.
- API composition can use broker-issued credentials without spreading env reads into API handlers.
- Missing credential failures are auditable.
- Direct env-token fallback still exists in integration construction for compatibility, but is no longer the only path.

## Known Deferrals

- Default API composition does not yet construct an environment broker from settings automatically.
- Direct env-token fallback in `build_pull_request_gateway` remains for compatibility.
- No OS keychain, Vault, KMS, cloud secret manager, or GitHub App token backend exists yet.
- Operator runbook does not yet describe default broker composition.

## Next Phase

Phase 17 should harden credential backend composition:

- add a default environment broker factory for API composition
- narrow or explicitly deprecate direct SCM env fallback
- document the operator path for broker-backed SCM execution

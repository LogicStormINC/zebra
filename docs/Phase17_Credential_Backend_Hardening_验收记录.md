# Phase 17 Credential Backend Hardening 验收记录

## Scope

Phase 17 hardened credential backend composition for guarded SCM execution.

The phase made API composition broker-first, narrowed direct SCM env fallback, and updated operator documentation for broker-backed execution.

## Completed Tasks

### P17-APP-01 - API Default Environment Broker Factory

Implemented behavior:

- Added `build_default_credential_broker`.
- API composition builds a default `EnvironmentCredentialBroker` from GitHub SCM settings when no explicit broker is supplied.
- Local-only API behavior remains unchanged.
- GitHub dry-run does not require a broker credential.
- GitHub non-dry-run can use the default broker in tests.
- Missing default broker env values record delivery audit metadata.

Validation:

- `uv run pytest tests/api/test_credential_broker.py tests/api/test_session_pull_request.py tests/agent_security/test_environment_broker.py`
- `make check`
- `make test`

### P17-INT-01 - SCM Env Fallback Boundary

Implemented behavior:

- Direct SCM env fallback is disabled by default.
- Retained env fallback requires explicit `allow_env_token_fallback=True`.
- Broker-backed path is preferred in integration tests.
- Local-only and GitHub dry-run behavior remains unchanged.

Validation:

- `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_credential_broker.py`
- `make check`
- `make test`

### P17-DOC-01 - Broker-Backed SCM Operator Docs

Implemented behavior:

- Operator runbook describes broker-backed GitHub PR execution.
- Token handling rules remain visible before execution steps.
- Audit inspection remains part of the live execution flow.
- Direct env fallback is documented as an explicit integration compatibility boundary, not the operator path.

Validation:

- `make check`
- `make test`

## Acceptance Summary

- API composition is broker-first for GitHub credentials.
- Direct SCM env fallback is explicit and disabled by default.
- Operator documentation matches the broker-backed execution model.
- Local-only and dry-run safety defaults remain unchanged.

## Known Deferrals

- Delivery audit metadata records SCM outcome but not the credential source.
- Broker issuance itself is not yet surfaced in observability traces.
- No OS keychain, Vault, KMS, cloud secret manager, or GitHub App token backend exists yet.

## Next Phase

Phase 18 should improve observability for broker-backed SCM delivery:

- record credential source metadata without token values
- distinguish credential missing, denied, unavailable, and transport failures in operator-facing audit
- add tests proving audit metadata stays redacted

# Phase 15 Credential Broker Foundation 验收记录

## Scope

Phase 15 introduced the credential broker foundation needed before concrete secret backends or GitHub App token flows.

The phase kept local-only and dry-run defaults unchanged. It did not add durable token storage.

## Completed Tasks

### P15-SEC-01 - Credential Capability Domain Model

Implemented behavior:

- Added `CredentialCapability` with provider, audience, scopes, expiry, and runtime token value.
- Runtime token values are excluded from `repr`.
- Redacted serialization emits `<redacted>` instead of raw token values.
- Expiry checks require timezone-aware datetimes.

Validation:

- `uv run pytest tests/agent_security/test_capabilities.py tests/agent_security/test_credentials.py`
- `make check`
- `make test`

### P15-SEC-02 - Credential Broker Port

Implemented behavior:

- Added `CredentialBroker` Port for SCM credential requests.
- Added `InMemoryCredentialBroker` test fake.
- Added `CredentialMissingError`, `CredentialDeniedError`, and `CredentialUnavailableError`.
- Documented local-only MVP limits in `docs/Credential_Broker_Foundation.md`.

Validation:

- `uv run pytest tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py`
- `make check`
- `make test`

### P15-INT-01 - SCM Broker Lookup Adapter

Implemented behavior:

- `build_pull_request_gateway` accepts an optional credential broker.
- GitHub dry-run does not request broker credentials.
- GitHub non-dry-run can use a broker-issued capability.
- Missing broker credentials fail before network execution.
- Existing env-token fallback remains when no broker is supplied.

Validation:

- `uv run pytest tests/agent_integrations/test_scm.py tests/agent_security/test_broker.py`
- `make check`
- `make test`

## Acceptance Summary

- Credential capabilities can be modeled and redacted without durable token storage.
- Broker error semantics distinguish missing, denied, and unavailable credentials.
- SCM gateway construction can use broker-issued credentials while preserving local-only and dry-run defaults.
- Existing API composition remains compatible through the current env-token fallback.

## Known Deferrals

- No concrete local secret backend exists yet.
- No OS keychain, Vault, KMS, or cloud secret manager backend exists yet.
- No GitHub App installation token flow exists yet.
- API composition does not yet own or inject a broker instance.
- Env-token fallback still exists for compatibility.

## Next Phase

Phase 16 should add a local credential backend and wire API composition through the broker boundary:

- local in-process or environment-backed broker implementation
- API settings and composition injection for broker-backed SCM execution
- regression tests proving API-created pull requests can use broker-issued credentials
- explicit deprecation boundary for direct env-token fallback

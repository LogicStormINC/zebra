# Credential Broker Foundation

## Purpose

The credential broker boundary lets runtime adapters request short-lived capabilities without coupling domain logic to environment variables, keychains, Vault, KMS, or GitHub App token flows.

Phase 15 starts with local contracts only. It does not add a concrete secret backend.

## Current Local MVP

- `CredentialCapability` models provider, audience, scopes, expiry, and runtime token value.
- Runtime token values are excluded from `repr`.
- `redacted()` snapshots emit `<redacted>` instead of raw token values.
- `CredentialBroker` is a Port for requesting SCM credentials.
- `InMemoryCredentialBroker` is a deterministic test fake.
- `EnvironmentCredentialBroker` can issue local capabilities from configured environment variable names.
- `EnvironmentCredentialBinding` maps provider, audience, scopes, token env name, and expiry.
- API composition can inject a credential broker into pull-request gateway construction.
- API composition now builds a default `EnvironmentCredentialBroker` from GitHub SCM settings when no explicit broker is supplied.

## Error Semantics

- `CredentialMissingError`: no matching credential exists or the matching credential is expired.
- `CredentialDeniedError`: the request is explicitly denied or asks for scopes not granted by the capability.
- `CredentialUnavailableError`: the broker cannot serve requests.

These errors intentionally distinguish operator remediation paths:

- missing: configure or issue a credential
- denied: narrow the request or update policy
- unavailable: retry after broker recovery

## Non-Goals

- No durable token storage.
- No OS keychain integration.
- No Vault, KMS, or cloud secret manager integration.
- No GitHub App installation token flow.
- No durable or external secret backend yet.

## SCM Adapter Status

`P15-INT-01` routes optional SCM token lookup through this broker boundary while preserving:

- local-only default behavior
- GitHub dry-run without credential lookup
- fail-closed non-dry-run behavior when the broker cannot issue a capability

For compatibility, SCM gateway construction retains direct environment token fallback only when `allow_env_token_fallback=True` is passed explicitly. API composition should use the default environment broker instead of relying on direct adapter env reads.

When a broker is supplied, GitHub non-dry-run execution requests credentials during pull-request planning. Missing broker credentials fail before network execution and are recorded in delivery audit metadata.

When no broker is supplied to API composition, the default environment broker uses `ZEBRA_GITHUB_TOKEN_ENV` as the token variable name. The token value itself remains outside settings and durable state.

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

## Secret-Store Direction

Phase 19 introduces the local contract that future non-environment broker backends should depend on:

- `SecretStore` is the Port for retrieving secret material by handle.
- `SecretMaterial` carries `handle`, `backend`, optional `version`, and runtime `value`.
- `SecretMaterial.redacted()` must replace raw values with `<redacted>`.
- `SecretMissingError` means the requested handle does not exist.
- `SecretUnavailableError` means the backing store cannot currently serve reads.
- `LocalSecretStore` is the first local backend, backed by per-handle JSON documents under a local root directory.
- `get_secret_value(...)` is the broker-facing helper for retrieving raw secret material through the Port.

This contract exists so future broker backends can consume secret material without:

- reading raw secret storage directly from API composition
- leaking secret values into repr, durable metadata, or operator-facing audit state
- coupling integrations to a specific storage backend such as OS keychain, Vault, or KMS

## SCM Adapter Status

`P15-INT-01` routes optional SCM token lookup through this broker boundary while preserving:

- local-only default behavior
- GitHub dry-run without credential lookup
- fail-closed non-dry-run behavior when the broker cannot issue a capability

For compatibility, SCM gateway construction retains direct environment token fallback only when `allow_env_token_fallback=True` is passed explicitly. API composition should use the default environment broker instead of relying on direct adapter env reads.

When a broker is supplied, GitHub non-dry-run execution requests credentials during pull-request planning. Missing broker credentials fail before network execution and are recorded in delivery audit metadata.

When no broker is supplied to API composition, the default environment broker uses `ZEBRA_GITHUB_TOKEN_ENV` as the token variable name. The token value itself remains outside settings and durable state.

Delivery audit metadata may include non-secret credential observability fields:

- `credential_source=broker` when the GitHub credential came through the broker boundary
- `credential_source=env_fallback` only when explicit adapter fallback is enabled with `allow_env_token_fallback=True`
- `credential_backend=environment` for the current local backend implementation

These fields are intended for operator diagnosis only. They must never contain raw token material.

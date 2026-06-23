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
- No API-owned broker composition yet.

## SCM Adapter Status

`P15-INT-01` routes optional SCM token lookup through this broker boundary while preserving:

- local-only default behavior
- GitHub dry-run without credential lookup
- fail-closed non-dry-run behavior when the broker cannot issue a capability

For compatibility, the current API composition path can still use the existing environment token fallback when no broker is supplied. Future secret backend work should replace that fallback with a concrete broker implementation rather than spreading environment reads into additional adapters.

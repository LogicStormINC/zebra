# Phase 18 SCM Audit Observability 验收记录

## Scope

Phase 18 completed the SCM delivery-audit observability slice for guarded GitHub pull-request execution.

The phase added non-secret credential source metadata, classified operator-facing credential and transport failure families, and documented remediation guidance without exposing token values.

## Completed Tasks

### P18-OBS-01 - SCM Credential Source Audit Metadata

Implemented behavior:

- Added non-secret `credential_source` metadata for broker-backed and explicit env-fallback execution paths.
- Added `credential_backend` metadata for the current local environment-backed backend.
- API pull-request responses and delivery-audit records now expose the same non-secret source metadata.
- Missing broker credentials remain auditable before network execution.
- Token values remain excluded from API responses, delivery-audit metadata, and serialized request payloads.

Validation:

- `poetry run pytest tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py`
- `make check`

### P18-OBS-02 - Credential Failure Audit Classification

Implemented behavior:

- Added stable `failure_class` metadata values:
  - `credential_missing`
  - `credential_denied`
  - `credential_unavailable`
  - `transport_failure`
- Broker-backed credential failures now preserve distinct audit classification for missing, denied, and unavailable cases.
- GitHub transport failures are now distinguishable from broker unavailability.
- Transport failures keep `credential_source` and `credential_backend` metadata so operators can see which credential path was active.
- Operator runbook now maps each failure class to remediation guidance.

Validation:

- `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py`
- `make check`

## Acceptance Summary

- SCM delivery audit records now capture credential source and backend metadata without exposing raw token values.
- Credential missing, denied, unavailable, and transport failure paths are distinguishable in operator-facing audit metadata.
- Operator documentation now provides remediation guidance keyed to the failure classification.
- Local-only and dry-run safety defaults remain unchanged.

## Validation Notes

- Targeted Phase 18 regression suites passed.
- `make check` passed.
- `make test` is currently blocked by `tests/worker/test_loop.py::test_worker_loop_skips_already_leased_ready_session`.
- The failing worker test uses a fixed lease timestamp (`2026-06-23T09:00:00Z`) and is outside the owned paths for Phase 18 SCM audit work.

## Known Deferrals

- No OS keychain, Vault, KMS, cloud secret manager, or GitHub App credential backend exists yet.
- Broker issuance is still local-process only and not yet backed by a durable secret-store abstraction.
- Network egress control remains broader architecture work beyond the current SCM audit slice.

## Next Phase

Phase 19 should move from audit observability into broker-backed secret handling:

- define a secret-store Port and redaction contract
- add a local secret-store backend aligned with the architecture's local secure storage path
- start a GitHub App credential adapter skeleton on top of the broker and secret-store boundaries

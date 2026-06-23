# Phase 14 SCM Execution Hardening 验收记录

## Scope

Phase 14 hardened the guarded SCM execution path that was introduced in Phase 13.

The phase did not broaden default remote side effects. Local-only and dry-run behavior remain the safe defaults.

## Completed Tasks

### P14-OBS-01 - SCM Execution Audit Hardening

Implemented behavior:

- Pull-request delivery audit records normalized provider, status, commit SHA, dry-run flag, URL, and failure reason when available.
- Created GitHub PR attempts can be distinguished from dry-run, policy-blocked, and unavailable attempts.
- Delivery audit read API returns the normalized metadata without token values.
- Existing local-only audit behavior remains unchanged.

Validation:

- `uv run pytest tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py tests/api/test_session_pull_request.py tests/agent_storage/test_delivery_audit.py`
- `make check`
- `make test`

### P14-SEC-01 - SCM Token Redaction Regression Gate

Implemented behavior:

- GitHub PR plans expose redacted authorization headers only.
- API pull-request responses do not expose raw SCM token values.
- Delivery audit result metadata does not expose raw SCM token values.
- Credential redacted snapshots and settings snapshots do not expose raw token values.

Validation:

- `uv run pytest tests/agent_security/test_credentials.py tests/agent_integrations/test_scm.py tests/api/test_scm_token_redaction.py tests/api/test_session_pull_request.py tests/api/test_delivery_audit_metadata.py`
- `make check`
- `make test`

### P14-DOC-01 - Remote SCM Operator Safety Runbook

Implemented behavior:

- Operator runbook starts with local-only and dry-run defaults.
- GitHub live execution instructions require explicit opt-in.
- Token handling rules are visible before execution steps.
- Delivery audit inspection is part of the live operator flow.
- Rollback and failure handling are documented for accidental PRs, policy blocks, and transport failures.

Validation:

- `make check`
- `make test`

## Acceptance Summary

- Local-only remains the default SCM provider.
- GitHub execution remains opt-in through provider, dry-run disablement, token availability, and `full_access` policy.
- Auditors can distinguish dry-run, created, blocked, and unavailable PR attempts.
- Token values are covered by regression tests across plan, API response, audit, and settings paths.
- Operators have a dry-run-first remote SCM checklist.

## Known Deferrals

- No durable credential broker exists yet; Phase 14 still uses a process environment token as the runtime source.
- No GitHub App installation token flow exists yet.
- No GitLab provider exists yet.
- No egress broker or network allowlist is implemented yet.

## Next Phase

Phase 15 should start the credential broker foundation:

- model short-lived credential capabilities without storing raw token values in domain state
- define a broker Port before adding concrete secret backends
- wire SCM token lookup through the broker boundary behind tests
- preserve local-only and dry-run defaults while the broker matures

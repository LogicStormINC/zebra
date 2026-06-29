# Phase 23 Proxy Approval Projection And Operator Readback 验收记录

## Scope

Phase 23 extended the proxy-execution work from Phase 22 into durable approval
and operator readback surfaces.

The phase did not broaden execution permissions. Instead, it made proxy-aware
approval metadata visible across harness events, session and approval API
responses, and trace outputs while preserving fail-closed defaults.

## Completed Tasks

### P23-HAR-01 - Proxy Approval Event Projection

Implemented behavior:

- Extended `PolicyDecision` so policy outcomes can optionally carry:
  - `route`
  - `target`
  - `network_profile`
  - `scope`
- Updated `SingleAttemptOrchestrator` so `policy_decision_made` and
  `approval_requested` events persist proxy-aware policy metadata when present.
- Preserved the previous event payload shape for local-only policy paths.

Validation:

- `poetry run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/smoke/test_mock_harness_loop.py`
- `uv run ruff check packages/agent-core/src/agent_core tests/agent_core tests/smoke`
- `uv run mypy packages/agent-core/src/agent_core/domain/policies.py packages/agent-core/src/agent_core/harness/orchestrator.py tests/agent_core/test_single_attempt_orchestrator.py`

### P23-API-01 - Proxy Approval Readback Surface

Implemented behavior:

- Added `zebra_agent_api.approval_context.latest_approval_context(...)`.
- Updated `GET /sessions/{id}` to expose `approval_context` when the latest
  `approval_requested` event carries proxy-aware fields.
- Updated approval approve/reject responses to echo the same safe
  `approval_context` shape.
- Limited readback to non-secret fields:
  - `tool_name`
  - `reason`
  - `policy_profile`
  - `route`
  - `target`
  - `network_profile`
  - `scope`

Validation:

- `poetry run pytest tests/api/test_approval_api_app.py tests/api/test_http_app.py tests/api/test_approval_routes.py tests/api/test_http_approvals.py`
- `uv run ruff check apps/api/src/zebra_agent_api tests/api`
- `make check`

### P23-OBS-01 - Proxy Approval Trace Normalization

Implemented behavior:

- Extended `HarnessToolTrace` with:
  - `policy_route`
  - `policy_target`
  - `policy_network_profile`
  - `policy_scope`
- Updated `HarnessTraceProjector` to normalize proxy-aware policy metadata from
  `policy_decision_made` events into tool traces.
- Updated API trace payloads and `serialize_trace_events(...)` to use the same
  proxy approval vocabulary as policy and execution layers.
- Preserved backwards-compatible `None` / empty values for local-only paths.

Validation:

- `poetry run pytest tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_single_attempt_orchestrator.py tests/api/test_api_app.py tests/api/test_http_app.py`
- `uv run ruff check packages/agent-core/src/agent_core apps/api/src/zebra_agent_api tests/agent_core tests/api`
- `make check`

## Acceptance Summary

- Proxy-aware approval metadata is now durable in harness events.
- Operator-facing session and approval responses expose safe proxy approval
  context without exposing secrets or raw credential material.
- Trace outputs now reuse the same proxy route vocabulary as policy and tool
  execution metadata.
- Existing local-only policy, approval, and trace outputs remain backwards
  compatible.

## Validation Notes

- Targeted Phase 23 regression suites passed for harness, API, and trace
  surfaces.
- `make check` passed for the closeout line.
- Full `make test` was not rerun in the closeout slice because the modified
  areas were already covered by targeted regression suites plus the repository
  release gate.

## Known Deferrals

- `approval_context` is still reconstructed from session events instead of a
  dedicated durable approval projection.
- There is no dedicated approval queue or approval detail read API yet.
- Approval-oriented operator reads still rely on session-scoped queries rather
  than projection-backed approval indexes.

## Next Phase

Phase 24 should move proxy-aware approval state from replay-only readback into
durable projections and operator queue surfaces:

- persist approval context into durable projection models
- expose approval-focused read APIs and queue views
- keep approval projections and API surfaces aligned with proxy-aware event and trace metadata

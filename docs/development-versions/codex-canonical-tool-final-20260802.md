# Zebra Development Version: Canonical Tool Final

## Identity and ancestry

- Repository: `https://github.com/vinson1101/zebra.git`
- Owner / task: `vinson1101` / `CANONICAL-TOOL-FINAL-20260802`
- Base branch / commit: `codex/finos-runtime-alignment` /
  `873de973fb6db922e16f17c72b0183f8b68fb4bb`
- Source branch / commit: `codex/finos-runtime-alignment` /
  `873de973fb6db922e16f17c72b0183f8b68fb4bb`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-canonical-tool-final`
- Implementation branch: `codex/canonical-tool-final-20260802`
- Fixed deployment branch / merge target: `codex/finos-runtime-alignment`
- Status: `Review`; not pushed, merged, deployed, or deployable

## Real staging evidence

On the fixed staging base, a native Qwen image task produced a complete first
model response with a tool call. After the tool failures, the model returned a
short no-tool message that incorrectly claimed success. The current sequential
loop records that message as `response_stage=final`, so public conversation and
artifacts can hide the complete earlier response while exposing the false short
status. The repair must stay in Zebra Harness; FinOS must not parse or select
natural-language messages.

## Contract slice and owned paths

After at least one tool has executed and tools remain available, a no-tool model
candidate is provisional: it is emitted as `tool_loop` and receives exactly one
existing `allow_tools=False` terminal synthesis using the same conversation,
tool results, and context recovery path. Ordinary no-tool conversations and
already tool-disabled finite-budget terminal paths remain unchanged. The
existing final-answer instruction is strengthened to require a complete,
self-contained answer that directly answers the original request and truthfully
reports succeeded/failed visible tool results.

Existing public projection already excludes `response_stage=tool_loop`; no
production `public_conversation.py` change is planned.

Owned paths:

- `packages/agent-core/src/agent_core/harness/sequential_loop.py`
- `packages/agent-core/src/agent_core/harness/context_recovery.py`
- `tests/agent_core/test_concurrent_tool_batches.py`
- `tests/agent_core/test_harness_convergence.py`
- `tests/agent_core/test_harness_trace_projection.py`
- `tests/agent_core/test_policy_deny_recovery.py`
- `tests/agent_core/test_public_conversation_multiturn.py`
- `tests/agent_core/test_sequential_tool_loop.py`
- `tests/agent_core/test_session_plans.py`
- `tests/agent_core/test_single_attempt_orchestrator.py`
- `tests/agent_core/test_tool_call_batches.py`
- `tests/agent_core/test_tool_failure_recovery.py`
- `tests/agent_runtime/test_harness_runner.py`
- `tests/api/test_api_app.py`
- `tests/integration/test_readonly_research_delegation.py`
- `tests/worker/execution/test_core_execution.py`
- `tests/worker/execution/test_memory_lifecycle.py`
- `tests/worker/execution/worker_execution_support.py`
- `tests/worker/test_approved_batch_continuation.py`
- `tests/worker/test_approved_continuation.py`
- `tests/worker/test_web_pipeline_v2_authority.py`
- `docs/development-versions/codex-canonical-tool-final-20260802.md`

No FinOS, ToolExecutor, model profile, MCP, workflow, API, Worker composition,
deployment, or public projection production code changes are permitted.

## Validation record

- Baseline command: `make sync` with CPython 3.12.13, followed by the narrow
  Harness/sequential/convergence/public projection suite — `38 passed`.
- New red tests: the new success/failure canonical-final command returned
  `2 failed, 12 passed`; both failed because the no-tool candidate was still
  emitted as `final` without a third, tools-disabled synthesis call.
- Green focused tests: `14 passed`; related Harness/convergence/trace/public
  tests: `49 passed`; full `tests/agent_core`: `260 passed`.
- The expanded consumer set covering the 27 new red tests is now `27 passed`.
- The affected runtime/API/integration/worker files are `81 passed, 1 failed,
  1 warning`; the only failure is the pre-existing durable-cancellation thread
  race. Worker/API narrow is `64 passed, 1 failed, 1 warning`, with the same
  cancellation failure.
- The new success case has one provisional `tool_loop` followed by one
  canonical `final`; the failure case verifies the failed tool observation and
  final-answer instruction reach the tools-disabled request and the final does
  not claim success. Ordinary no-tool conversation remains one model call.
- Full suite: `1925 passed, 10 failed, 9 skipped, 1 warning`, matching the
  fixed-base inherited failure count. The remaining exact failures are:
  - `tests/agent_integrations/test_deepseek_specialization.py::test_deepseek_thinking_tool_response_requires_valid_reasoning_content`
  - `tests/agent_integrations/test_openai_compatible.py::test_openai_compatible_gateway_parses_tool_calls`
  - `tests/api/http_app/test_session_reads.py::test_http_app_serves_health`
  - `tests/api/session_pull_request/test_broker_credentials.py::test_api_pull_request_uses_broker_credential_for_github_execution`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_missing_broker_credential_records_audit`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_transport_failure_records_audit`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_uses_proxy_transport_for_github_execution`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_proxy_transport_failure_records_audit`
  - `tests/test_file_size_limits.py::test_repository_file_size_gate_passes`
  - `tests/worker/execution/test_core_execution.py::test_worker_streaming_stops_cleanly_after_durable_cancellation`
- The canonical-final consumer failures are gone; no provider, HTTP, file-size,
  or cancellation test was changed. `tests/worker/test_approved_continuation.py`
  remains at the 700-line test limit.
- Owned Ruff: passed. Python 3.12 compileall: passed. `git diff --check`:
  passed.
- Implementation head: `93e422b` (`fix(harness): canonicalize post-tool final responses`).
- Consumer test commit: `7a85405` (`test(harness): align consumers with canonical finals`).
- Record closure: follow-up local documentation commit; no production deployment.
- Merge commit: not applicable.
